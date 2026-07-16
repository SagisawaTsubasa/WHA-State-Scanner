"""Independent file-based decision logging."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)


class DecisionLogger:
    """Logs every evaluation cycle to a dedicated file, not HA system log."""

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
            hass.config.config_dir,
            "sensor_switch_controller_logs",
            entry_id,
        )
        os.makedirs(self.log_dir, exist_ok=True)

        self._current_file = None
        self._current_date = None
        self._fh = None

    def _get_log_file(self) -> str:
        """Return today's log file path."""
        today = dt_util.now().strftime("%Y-%m-%d")
        if today != self._current_date:
            # Rotate
            if self._fh:
                self._fh.close()
                self._fh = None
            self._current_date = today
            self._current_file = os.path.join(
                self.log_dir, f"{self.controller_name}_{today}.jsonl"
            )
        return self._current_file

    async def log(
        self,
        output: str,
        readings: dict,
        on_met: bool,
        off_met: bool,
        decision: str,
    ) -> None:
        """Append a decision record to the log file."""
        if not self.enabled:
            return

        record = {
            "timestamp": dt_util.now().isoformat(),
            "controller": self.controller_name,
            "output": output,
            "decision": decision,
            "on_met": on_met,
            "off_met": off_met,
            "readings": readings,
        }

        filepath = self._get_log_file()
        try:
            with open(filepath, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as err:
            _LOGGER.error("Failed to write decision log: %s", err)

    async def close(self) -> None:
        """Close file handle."""
        if self._fh:
            self._fh.close()
            self._fh = None

    def list_log_files(self) -> list[str]:
        """Return list of log files."""
        try:
            return sorted(
                f for f in os.listdir(self.log_dir) if f.endswith(".jsonl")
            )
        except OSError:
            return []

    def read_log(self, filename: str, tail: int = 100) -> list[dict]:
        """Read last N lines from a log file."""
        filepath = os.path.join(self.log_dir, filename)
        if not os.path.exists(filepath):
            return []
        try:
            with open(filepath, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
            records = []
            for line in lines[-tail:]:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            return records
        except OSError:
            return []
