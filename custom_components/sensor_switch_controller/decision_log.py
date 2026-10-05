"""Independent file-based decision logging."""

from __future__ import annotations

import json
import logging
import os

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

LOG_DIR_NAME = "sensor_switch_controller_logs"
LOG_FILE_PREFIX = "log_"
LOG_RETENTION_DAYS = 30
READ_LIMIT_MAX = 5000
# Records carry full sensor-pool snapshots; never read more than the tail
# of a day file (records beyond this simply cannot match a sane limit).
_TAIL_MAX_BYTES = 4 * 1024 * 1024


class DecisionLogger:
    """Logs evaluation decisions to one JSONL file per day.

    File name is fixed to ``log_YYYY-MM-DD.jsonl`` inside a per-controller
    directory (keyed by the stable ``ctrl_<hex>`` id), so user-provided
    controller names can never produce invalid file names. All blocking
    file IO runs in the executor.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        controller_name: str,
        controller_id: str,
        enabled: bool,
    ) -> None:
        """Init."""
        self.hass = hass
        self.controller_name = controller_name
        self.controller_id = controller_id
        self.enabled = enabled

        # Log directory: <config>/sensor_switch_controller_logs/<controller_id>/
        self.log_dir = os.path.join(
            hass.config.config_dir, LOG_DIR_NAME, controller_id
        )
        self._dir_ready = False

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def _write_lines(self, records: list[dict]) -> None:
        """Blocking write of one evaluation cycle — runs in the executor."""
        try:
            if not self._dir_ready:
                os.makedirs(self.log_dir, exist_ok=True)
                self._dir_ready = True
            today = dt_util.now().strftime("%Y-%m-%d")
            filepath = os.path.join(
                self.log_dir, f"{LOG_FILE_PREFIX}{today}.jsonl"
            )
            with open(filepath, "a", encoding="utf-8") as fh:
                fh.writelines(json.dumps(record, ensure_ascii=False) + "\n" for record in records)
        except OSError as err:
            _LOGGER.error("Failed to write decision log: %s", err)

    async def log_cycle(self, records: list[dict]) -> None:
        """Append all decision records of one evaluation cycle in one write."""
        if not self.enabled or not records:
            return
        timestamp = dt_util.now().isoformat()
        enriched = [
            {"timestamp": timestamp, "controller": self.controller_name, **record}
            for record in records
        ]
        await self.hass.async_add_executor_job(self._write_lines, enriched)

    # ------------------------------------------------------------------
    # Retention
    # ------------------------------------------------------------------

    def _cleanup_old_logs(self) -> None:
        """Delete log files older than the retention period — executor only."""
        try:
            if not os.path.isdir(self.log_dir):
                return
            cutoff = dt_util.now().timestamp() - LOG_RETENTION_DAYS * 86400
            for filename in os.listdir(self.log_dir):
                if not filename.startswith(LOG_FILE_PREFIX) or not filename.endswith(
                    ".jsonl"
                ):
                    continue
                path = os.path.join(self.log_dir, filename)
                try:
                    if os.path.getmtime(path) < cutoff:
                        os.remove(path)
                except OSError as err:
                    _LOGGER.warning("Could not remove old log %s: %s", path, err)
        except OSError as err:
            _LOGGER.warning("Could not clean up decision logs: %s", err)

    async def async_cleanup(self) -> None:
        """Clean up old log files according to the retention period."""
        if not self.enabled:
            return
        await self.hass.async_add_executor_job(self._cleanup_old_logs)


async def read_day_records(
    hass: HomeAssistant,
    controller_id: str,
    date_str: str,
    limit: int = 500,
    decision: str | None = None,
) -> tuple[list[dict], bool]:
    """Read one day's JSONL records (newest last), optionally filtered.

    Returns ``(records, truncated)``; when truncated, only the most recent
    ``limit`` matching records are returned.
    """
    limit = max(1, min(int(limit), READ_LIMIT_MAX))
    return await hass.async_add_executor_job(
        _read_day_records_sync, hass, controller_id, date_str, limit, decision
    )


def _read_day_records_sync(
    hass: HomeAssistant,
    controller_id: str,
    date_str: str,
    limit: int,
    decision: str | None,
) -> tuple[list[dict], bool]:
    path = os.path.join(
        hass.config.config_dir,
        LOG_DIR_NAME,
        controller_id,
        f"{LOG_FILE_PREFIX}{date_str}.jsonl",
    )
    if not os.path.isfile(path):
        return [], False
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            dropped_head = False
            if size > _TAIL_MAX_BYTES:
                fh.seek(-_TAIL_MAX_BYTES, os.SEEK_END)
                fh.readline()  # discard the partial line at the cut point
                dropped_head = True
            raw = fh.read()
    except OSError as err:
        _LOGGER.error("Failed to read decision log %s: %s", path, err)
        return [], False

    records: list[dict] = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if decision and record.get("decision") != decision:
            continue
        records.append(record)
    truncated = dropped_head or len(records) > limit
    return records[-limit:], truncated
