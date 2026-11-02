"""Decision-log read-side regression: corrupt JSONL lines must warn (R2#5).

The ``bad_lines`` warning branch in ``decision_log._read_day_records_sync``
previously had zero test coverage — deleting the branch or reverting the
counter to a bare ``pass`` left every gate green. These pins assert:

- a torn line warns exactly once AND the good lines still parse;
- a clean file stays silent (the warning must not move into the loop and
  spam one line per record).
"""

from __future__ import annotations

import asyncio
import json
import logging
import types

from custom_components.sensor_switch_controller import decision_log

CTRL_A = "ctrl_" + "a" * 32
CTRL_B = "ctrl_" + "b" * 32
DAY = "2026-11-03"


def _make_hass(config_dir) -> types.SimpleNamespace:
    """Minimal hass stub: config_dir plus the executor hop read_day_records
    awaits (run_in_executor mirrors hass.async_add_executor_job)."""
    hass = types.SimpleNamespace(
        config=types.SimpleNamespace(config_dir=str(config_dir))
    )
    hass.async_add_executor_job = lambda func, *a: (
        asyncio.get_running_loop().run_in_executor(None, lambda: func(*a))
    )
    return hass


def _write_day(config_dir, controller_id: str, lines: list[str]):
    day_dir = config_dir / decision_log.LOG_DIR_NAME / controller_id
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / f"{decision_log.LOG_FILE_PREFIX}{DAY}.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_bad_line_warns_once_and_good_lines_still_parse(tmp_path, caplog):
    good = {"ts": "2026-11-03T00:00:00", "decision": "on", "output": "sw.x"}
    good2 = {"ts": "2026-11-03T00:01:00", "decision": "off", "output": "sw.x"}
    _write_day(
        tmp_path,
        CTRL_A,
        [json.dumps(good), "{broken json", json.dumps(good2), ""],
    )
    with caplog.at_level(
        logging.WARNING, logger=decision_log._LOGGER.name
    ):
        records, truncated = asyncio.run(
            decision_log.read_day_records(
                _make_hass(tmp_path), CTRL_A, DAY, 100, None
            )
        )
    assert records == [good, good2], records
    assert truncated is False
    warns = [
        r
        for r in caplog.records
        if r.levelno >= logging.WARNING and "无法解析" in r.getMessage()
    ]
    assert len(warns) == 1, caplog.records


def test_clean_file_is_silent(tmp_path, caplog):
    good = {"ts": "2026-11-03T00:00:00", "decision": "on"}
    _write_day(tmp_path, CTRL_B, [json.dumps(good)])
    with caplog.at_level(
        logging.WARNING, logger=decision_log._LOGGER.name
    ):
        records, _truncated = asyncio.run(
            decision_log.read_day_records(
                _make_hass(tmp_path), CTRL_B, DAY, 100, None
            )
        )
    assert records == [good], records
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
