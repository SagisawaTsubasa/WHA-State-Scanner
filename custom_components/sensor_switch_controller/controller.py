"""Controller manager – orchestrates triggers, sensors, conditions, outputs.

Since 0.5.0 evaluation is trigger-driven: the controller's TriggerManager
fires on configured events (state changes / time / sun / HA start), the
controller debounces bursts, runs one level-based evaluation and —
whenever a timer is running — schedules a precise wakeup at the exact
moment a gate can flip on its own.

Since 0.6.0 evaluation is *directed*; since 0.7.0 triggers carry only
``routes.conditions`` (the gates their canvas wires cover) and wake the
outputs those chains reach — outputs are driven purely by condition
chains (routes absent → legacy evaluate-everything; covering no gate →
wakes nothing). Timed wakeups (FOR/duration expiry, debounce quiet
points, cooldown ends, time-range/sun edges) are directed too, via a
precomputed condition→outputs reverse index.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import (
    async_call_later,
    async_track_point_in_time,
)
from homeassistant.util import dt as dt_util

from .condition_engine import ConditionEngine
from .const import (
    CONF_ABORT,
    CONF_CONDITIONS,
    CONF_LOGGING,
    CONF_OUTPUTS,
    CONF_ROUTES,
    CONF_SENSORS,
    CONF_START,
    CONF_TRIGGERS,
    EVAL_DEBOUNCE_SECONDS,
)
from .decision_log import DecisionLogger
from .triggers import TriggerManager

_LOGGER = logging.getLogger(__name__)


class ControllerManager:
    """Manages one controller instance."""

    def __init__(
        self, hass: HomeAssistant, controller_id: str, config: dict
    ) -> None:
        """Initialize."""
        self.hass = hass
        self.controller_id = controller_id
        self.config = config

        self.name = config.get("name", controller_id)
        self.enabled = config.get("enabled", True)
        self.triggers = config.get(CONF_TRIGGERS, [])
        self.sensors = config.get(CONF_SENSORS, [])
        self.conditions = config.get(CONF_CONDITIONS, [])
        self.outputs = config.get(CONF_OUTPUTS, [])
        self.logging_enabled = config.get(CONF_LOGGING, False)

        self.engine = ConditionEngine(hass, self.conditions, manager=self)
        self.logger = DecisionLogger(
            hass, self.name, controller_id, enabled=self.logging_enabled
        )
        self.trigger_manager = TriggerManager(
            hass, self.triggers, self._on_trigger_fire
        )

        # Registered output entities, keyed by the stable internal output id
        # (out_cfg["entity_id"], e.g. "ssc_<hex>") — the same key used for
        # lookups during evaluation.
        self._entities: dict[str, Any] = {}
        self._expected_out_ids = {
            out["entity_id"]
            for out in self.outputs
            if isinstance(out, dict) and out.get("entity_id")
        }
        self._added_out_ids: set[str] = set()
        self._first_eval_pending = True
        self._warned_bad_sensors = False

        # Debounced trigger firings (trigger ids + log descriptions).
        self._debounce_unsub = None
        self._pending_triggers: set[str | None] = set()
        self._pending_descs: set[str] = set()

        # Routing index (rebuilt once per manager; config is immutable here):
        # cond id → outputs whose chains contain it; trigger id → outputs it
        # may wake; ``_legacy_routing`` when any trigger lacks routes.
        self._cond_to_outs: dict[str, set[str]] = {}
        self._trg_targets: dict[str, set[str]] = {}
        self._legacy_routing = False
        self._build_route_index()

        # Serialized evaluation guard (see _async_evaluate).
        self._evaluating = False
        self._rerun_pending = False
        self._rerun_sources: set[str] = set()
        # Backlog of evaluation scope swallowed mid-run. None vs set is a
        # real distinction: ``_rerun_full`` marks a swallowed full sweep
        # (legacy trigger / wakeup without targets), ``_rerun_targets``
        # accumulates directed sets. An empty set is a valid backlog
        # (wired-to-nothing → evaluate nothing).
        self._rerun_full = False
        self._rerun_targets: set[str] = set()
        # Shared by every evaluation entry point (trigger ticks, web trial
        # runs, force_evaluate) so engine state is never mutated concurrently.
        self._eval_lock = asyncio.Lock()

        # Precise FOR-expiry wakeup (cancelled/re-armed after every cycle).
        self._for_wakeup_unsub = None

        # Last applied flip (utc) per output id — feeds cooldown conditions.
        self._last_flip: dict[str, Any] = {}

        # Latest evaluation result per output, served to the web panel.
        self.last_results: dict[str, dict] = {}
        self.last_cycle: str | None = None

    async def async_setup(self) -> None:
        """Register triggers and schedule a one-off old-log cleanup.

        The first evaluation is deferred until the platform entities have
        been registered (see ``async_entity_added``) so it does not idle.
        """
        pool_ids = [
            s.get("entity_id") for s in self.sensors
            if isinstance(s, dict) and s.get("entity_id")
        ]
        self.trigger_manager.async_setup(pool_ids)
        self.hass.async_create_task(self.logger.async_cleanup())

    def async_unload(self) -> None:
        """Stop all triggers, timers and entity references."""
        self.trigger_manager.async_unload()
        if self._debounce_unsub:
            self._debounce_unsub()
            self._debounce_unsub = None
        self._cancel_for_wakeup()
        self._entities.clear()
        self._added_out_ids.clear()
        self._first_eval_pending = False

    def last_flip_at(self, out_id: str):
        """UTC datetime of the last controller-applied flip, or None."""
        return self._last_flip.get(out_id)

    # ------------------------------------------------------------------
    # Entity registration
    # ------------------------------------------------------------------

    def register_entity(self, out_id: str, entity) -> None:
        """Register an output entity under its stable internal id."""
        self._entities[out_id] = entity

    def unregister_entity(self, out_id: str) -> None:
        """Drop an entity reference (called on entity removal)."""
        self._entities.pop(out_id, None)
        self._added_out_ids.discard(out_id)

    def async_entity_added(self, out_id: str) -> None:
        """Notify the manager that an output entity finished adding to hass.

        Once every expected output entity is present, the first evaluation
        is triggered instead of idling for up to one scan interval.
        """
        self._added_out_ids.add(out_id)
        if (
            self._first_eval_pending
            and self._expected_out_ids
            and self._expected_out_ids <= self._added_out_ids
        ):
            self._first_eval_pending = False
            self.hass.async_create_background_task(
                self._async_evaluate(None, ["init"]), f"{self.controller_id}-init"
            )

    @property
    def entities(self) -> dict[str, Any]:
        """Expose registered output entities (read-only view)."""
        return self._entities

    # ------------------------------------------------------------------
    # Routing index
    # ------------------------------------------------------------------

    def _build_route_index(self) -> None:
        """Precompute condition→outputs reachability and trigger targets.

        Reachability follows the graph the wires describe: output chains
        (on/off), group members, and duration start/abort inputs. A trigger
        with ``routes`` wakes the outputs its covered conditions can reach
        (routes carry conditions only — triggers never wire outputs
        directly); a trigger without ``routes`` (legacy config) flips the
        whole controller into evaluate-everything mode.
        """
        cond_by_id = {
            c["id"]: c
            for c in self.conditions
            if isinstance(c, dict) and c.get("id")
        }
        cond_to_outs: dict[str, set[str]] = {}

        def add_chain(out_id: str, cond_ids: list[str]) -> None:
            stack = list(cond_ids)
            seen: set[str] = set()
            while stack:
                cid = stack.pop()
                if cid in seen:
                    continue
                seen.add(cid)
                cond_to_outs.setdefault(cid, set()).add(out_id)
                cond = cond_by_id.get(cid)
                if not cond:
                    continue
                stack.extend(cond.get("conditions") or [])
                if cond.get(CONF_START):
                    stack.append(cond[CONF_START])
                if cond.get(CONF_ABORT):
                    stack.append(cond[CONF_ABORT])

        for out in self.outputs:
            if not isinstance(out, dict) or not out.get("entity_id"):
                continue
            out_id = out["entity_id"]
            add_chain(out_id, out.get("on_conditions") or [])
            add_chain(out_id, out.get("off_conditions") or [])
        self._cond_to_outs = cond_to_outs

        legacy = False
        targets_by_trg: dict[str, set[str]] = {}
        for trg in self.triggers:
            if not isinstance(trg, dict):
                continue
            trg_id = trg.get("id")
            routes = trg.get(CONF_ROUTES)
            if routes is None:
                legacy = True
                continue
            # 0.7.0: signals flow through the condition graph only — a
            # trigger's targets are the outputs its covered conditions can
            # reach (direct output wiring was removed with v4 storage).
            targets = set()
            for cid in routes.get("conditions") or []:
                targets |= cond_to_outs.get(cid) or set()
            if trg_id:
                targets_by_trg[trg_id] = targets
        self._trg_targets = targets_by_trg
        self._legacy_routing = legacy

    # ------------------------------------------------------------------
    # Trigger plumbing
    # ------------------------------------------------------------------

    @callback
    def _on_trigger_fire(self, trg_id: str | None, description: str | None) -> None:
        """A trigger fired: open (or join) a debounced evaluation window.

        The window is opened once and never reset — a chatty pool delays
        evaluation by at most EVAL_DEBOUNCE_SECONDS, never indefinitely.
        """
        self._pending_triggers.add(trg_id)
        if description:
            self._pending_descs.add(description)
        if self._debounce_unsub is None:
            self._debounce_unsub = async_call_later(
                self.hass, EVAL_DEBOUNCE_SECONDS, self._async_debounced_evaluate
            )

    @callback
    def _async_debounced_evaluate(self, _now) -> None:
        self._debounce_unsub = None
        trg_ids = self._pending_triggers
        self._pending_triggers = set()
        sources = sorted(self._pending_descs) or ["unknown"]
        self._pending_descs = set()

        if self._legacy_routing or None in trg_ids:
            targets: set[str] | None = None  # legacy / unknown → full sweep
        else:
            targets = set()
            for tid in trg_ids:
                targets |= self._trg_targets.get(tid, set())
            # empty targets = wired to nothing → wakes nothing (by design)
        self.hass.async_create_background_task(
            self._async_evaluate(None, sources, targets),
            f"{self.controller_id}-evaluate",
        )

    @callback
    def _cancel_for_wakeup(self) -> None:
        if self._for_wakeup_unsub:
            self._for_wakeup_unsub()
            self._for_wakeup_unsub = None

    @callback
    def _rearm_for_wakeup(self) -> None:
        """Wake up at the earliest instant some gate may flip on its own
        (FOR/duration expiry, debounce quiet point, cooldown end, time/sun
        range edge) — and re-evaluate only the outputs it can reach."""
        self._cancel_for_wakeup()
        pending = self.engine.next_wakeup(self._cond_to_outs)
        if pending is None:
            return
        expiry, out_ids = pending

        @callback
        def _woken(_now) -> None:
            self._for_wakeup_unsub = None
            self.hass.async_create_task(
                self._async_evaluate(None, ["wakeup"], set(out_ids))
            )

        self._for_wakeup_unsub = async_track_point_in_time(
            self.hass, _woken, expiry
        )

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def _async_read_sensors(self) -> dict[str, Any]:
        """Collect current states of the configured sensor pool."""
        readings: dict[str, Any] = {}
        for sensor_cfg in self.sensors:
            if not isinstance(sensor_cfg, dict):
                continue
            eid = sensor_cfg.get("entity_id")
            if not eid:
                if not self._warned_bad_sensors:
                    self._warned_bad_sensors = True
                    _LOGGER.warning(
                        "Sensor entry without entity_id is skipped: %r", sensor_cfg
                    )
                continue
            state = self.hass.states.get(eid)
            readings[eid] = state.state if state else None
        return readings

    def _stack_targets(self, targets: set[str] | None) -> None:
        """Accumulate a swallowed run's scope. ``None`` = full sweep and
        absorbs any directed set already stacked; directed sets union."""
        if targets is None:
            self._rerun_full = True
        else:
            self._rerun_targets |= targets

    def _pop_backlog(self) -> tuple[list[str], set[str] | None]:
        """Take the swallowed sources+scope out of the backlog."""
        sources = sorted(self._rerun_sources)
        self._rerun_sources.clear()
        targets = None if self._rerun_full else set(self._rerun_targets)
        self._rerun_full = False
        self._rerun_targets = set()
        return sources, targets

    async def _async_evaluate(
        self,
        _now: Any,
        sources: list[str] | None = None,
        targets: set[str] | None = None,
    ) -> None:
        """Evaluate the outputs in ``targets`` (None = all of them); one
        output failing never blocks the rest.

        Serialized: a trigger arriving mid-run stacks its sources+targets as
        backlog and a drain pass happens afterwards, so overlapping runs
        never interleave their engine state and the backlog keeps exactly
        the scope of the runs that were swallowed (a directed swallow never
        widens into a full sweep — WHA-F-012).
        """
        if sources:
            self._rerun_sources.update(sources)
        self._stack_targets(targets)
        if self._evaluating:
            self._rerun_pending = True
            return
        await self._async_drain()

    async def _async_drain(self) -> None:
        """Run stacked evaluations until no backlog is left."""
        while True:
            self._evaluating = True
            try:
                async with self._eval_lock:
                    sources, targets = self._pop_backlog()
                    await self._async_evaluate_locked(sources, targets)
            finally:
                self._evaluating = False
                self._rearm_for_wakeup()
            if not self._rerun_pending:
                return
            self._rerun_pending = False

    async def _async_evaluate_locked(
        self,
        sources: list[str] | None = None,
        targets: set[str] | None = None,
    ) -> None:
        self._first_eval_pending = False
        readings = self._async_read_sensors()
        source_desc = ", ".join(sources or ["unknown"])

        records: list[dict] = []
        for out_cfg in self.outputs:
            if not isinstance(out_cfg, dict):
                continue
            out_id = out_cfg.get("entity_id")
            if targets is not None and out_id not in targets:
                continue
            try:
                record, _details = await self._async_evaluate_output(out_cfg, readings)
            except Exception:
                _LOGGER.exception(
                    "Error evaluating output '%s'", out_cfg.get("name", "<unknown>")
                )
                continue
            if not record:
                # Output entity not registered yet — nothing evaluated.
                continue
            record["triggered_by"] = source_desc
            records.append(record)

        if self.logging_enabled and records:
            await self.logger.log_cycle(records)

    async def _async_evaluate_output(
        self, out_cfg: dict, readings: dict[str, Any], detailed: bool = False
    ) -> tuple[dict, dict | None]:
        """Evaluate one output and apply its action.

        Returns ``(record, details)``; ``details`` is populated only when
        ``detailed`` is set (web trial-run) and carries per-condition results.
        """
        out_id = out_cfg.get("entity_id")
        if not out_id:
            _LOGGER.warning(
                "Output without entity_id is skipped: %r", out_cfg.get("name")
            )
            return {}, None

        entity = self._entities.get(out_id)
        if entity is None:
            return {}, None
        if getattr(entity, "entity_id", None) is None:
            # Entity object exists but has not been added to hass yet.
            return {}, None

        on_ids = out_cfg.get("on_conditions", [])
        off_ids = out_cfg.get("off_conditions", [])

        on_details: dict[str, bool] | None = None
        off_details: dict[str, bool] | None = None
        if detailed:
            on_met, on_details = await self.engine.evaluate_detailed(on_ids, out_id)
            off_met, off_details = await self.engine.evaluate_detailed(off_ids, out_id)
        else:
            on_met = await self.engine.evaluate_any(on_ids, out_id)
            off_met = await self.engine.evaluate_any(off_ids, out_id)

        decision = "hold"
        applied = False
        overridden = False
        if off_met:
            decision = "off"
            if entity.is_on:
                if await entity.async_controller_turn_off():
                    applied = True
                else:
                    overridden = True
        elif on_met:
            decision = "on"
            if not entity.is_on:
                if await entity.async_controller_turn_on():
                    applied = True
                else:
                    overridden = True

        if applied:
            self._last_flip[out_id] = dt_util.utcnow()

        record = {
            "output": out_cfg.get("name"),
            "decision": decision,
            "on_met": on_met,
            "off_met": off_met,
            "applied": applied,
            "override": overridden,
            "readings": readings,
        }

        self.last_results[out_id] = {
            "entity_id": entity.entity_id,
            "state": "on" if entity.is_on else "off",
            "decision": decision,
            "on_met": on_met,
            "off_met": off_met,
            "applied": applied,
            "override": overridden,
            "evaluated_at": dt_util.now().isoformat(),
        }
        self.last_cycle = dt_util.now().isoformat()

        if not detailed:
            return record, None
        return record, {
            "decision": decision,
            "on_met": on_met,
            "off_met": off_met,
            "on_conditions": on_details or {},
            "off_conditions": off_details or {},
        }

    def runtime_snapshot(self) -> dict:
        """Live view of this controller for the web panel."""
        return {
            "outputs": dict(self.last_results),
            "last_cycle": self.last_cycle,
            "triggers": len(self.triggers),
            "trigger_errors": self.trigger_manager.register_errors,
        }

    async def async_evaluate_with_details(self) -> dict:
        """Run one evaluation cycle now and return per-condition results.

        Semantically identical to a trigger-driven tick (writes are applied,
        the cycle is logged); the extra detail powers the editor trial-run.
        Shares the evaluation lock with trigger ticks so engine state is
        never mutated concurrently.
        """
        async with self._eval_lock:
            return await self._async_evaluate_with_details_locked()

    async def _async_evaluate_with_details_locked(self) -> dict:
        readings = self._async_read_sensors()
        outputs: dict[str, dict] = {}
        conditions: dict[str, bool] = {}
        records: list[dict] = []
        for out_cfg in self.outputs:
            if not isinstance(out_cfg, dict):
                continue
            try:
                record, details = await self._async_evaluate_output(
                    out_cfg, readings, detailed=True
                )
            except Exception:
                _LOGGER.exception(
                    "Error evaluating output '%s'", out_cfg.get("name", "<unknown>")
                )
                continue
            if not record:
                continue
            records.append(record)
            outputs[out_cfg["entity_id"]] = details or {}
            for key in ("on_conditions", "off_conditions"):
                conditions.update((details or {}).get(key) or {})

        if self.logging_enabled and records:
            await self.logger.log_cycle(records)

        self._rearm_for_wakeup()
        return {"readings": readings, "outputs": outputs, "conditions": conditions}

    async def async_evaluate_output(self, out_id: str) -> None:
        """Evaluate only the output identified by its internal id (service API)."""
        out_cfg = next(
            (
                out
                for out in self.outputs
                if isinstance(out, dict) and out.get("entity_id") == out_id
            ),
            None,
        )
        if out_cfg is None:
            _LOGGER.warning("Unknown output id '%s'; nothing to evaluate", out_id)
            return
        readings = self._async_read_sensors()
        async with self._eval_lock:
            try:
                record, _details = await self._async_evaluate_output(out_cfg, readings)
            except Exception:
                _LOGGER.exception(
                    "Error evaluating output '%s'", out_cfg.get("name", out_id)
                )
                return
            if record and self.logging_enabled:
                await self.logger.log_cycle([record])
            self._rearm_for_wakeup()
