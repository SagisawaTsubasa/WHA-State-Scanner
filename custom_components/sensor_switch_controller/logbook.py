"""Independent file-based decision logging."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

LOG_DIR_NAME = "sensor_switch_controller_logs"
LOG_FILE_PREFIX = "log_"
LOG_RETENTION_DAYS = 30


class DecisionLogger:
    """Logs evaluation decisions to one JSONL file per day.

    File name is fixed to ``log_YYYY-MM-DD.jsonl`` inside a per-entry
    directory, so user-provided controller names can never produce invalid
    file names. All blocking file IO runs in the executor.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        controller_name: str,
        entry_id: str,
        enabled: bool,
    ) -> None:
        """Init."""
        self.hass = hass
        self.controller_name = controller_name
        self.entry_id = entry_id
        self.enabled = enabled

        # Log directory: <config>/sensor_switch_controller_logs/<entry_id>/
        self.log_dir = os.path.join(
            hass.config.config_dir, LOG_DIR_NAME, entry_id
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
                for record in records:
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")
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
