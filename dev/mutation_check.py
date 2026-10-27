# -*- coding: utf-8 -*-
"""Mutation discrimination for the WHA review-fix rounds (in-repo copy,
审查 R7-7: the reviewer sandbox could not read the previous round's
out-of-repo copy under temp\\wha-fix-r7-src\\).

Each mutation reverts ONE fix to its pre-fix (buggy) shape in-memory on
disk, runs the pin that must catch it, restores the file from backup, and
reports PASS-CAUGHT / MUTANT-SURVIVED. Exit 0 = every mutant caught.

Round 4 (R7, WHA-F-297..302): M1-M3 = F-298 Kleene dominance, M4 = F-297
None-payload guard, M5 = F-299 empty-branch warning, M6 = F-300 repair
KeyError contract, M7 = F-302 inner-value filter.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CC = ROOT / "custom_components" / "sensor_switch_controller"
TESTS = ROOT / "tests"

WEB = TESTS / "test_web.py"
SMOKE = TESTS / "smoke.py"

# (name, file, old, new, runner("smoke"|"pytest"), pytest targets, fragment)
MUTATIONS = [
    (
        "M1 F-298: AND loses its dead-member dominance again",
        CC / "schema.py",
        "False\n                        if any(v is False for v in verdicts)",
        "False\n                        if False and any(v is False for v in verdicts)",
        "smoke",
        [],
        "AND mixing a cooldown must be rejected",
    ),
    (
        "M2 F-298: NOT falls back to any-unknown short-circuit again",
        CC / "schema.py",
        "                else:  # not: passes only when NO member is true (engine :500)\n"
        "                    verdict = (\n"
        "                        False\n"
        "                        if any(v is True for v in verdicts)\n"
        "                        else None if any(v is None for v in verdicts) else True\n"
        "                    )",
        "                else:  # not\n"
        "                    verdict = (\n"
        "                        None\n"
        "                        if any(v is None for v in verdicts)\n"
        "                        else not any(v is True for v in verdicts)\n"
        "                    )",
        "smoke",
        [],
        "NOT with a provably-true member must be rejected",
    ),
    (
        "M3 F-298: duration ignores a provably-satisfied abort again",
        CC / "schema.py",
        "            verdict = False if start_v is False or abort_v is True else None",
        "            verdict = False if start_v is False else None",
        "smoke",
        [],
        "duration with a provably-satisfied abort must be rejected",
    ),
    (
        "M4 F-297: None payload wipes populated memory again",
        CC / "hub.py",
        "        if data is None and (self.controllers or self.invalid):",
        "        if False and (self.controllers or self.invalid):",
        "smoke",
        [],
        "None payload must keep the last-known-good memory",
    ),
    (
        "M5 F-299: empty-branch warning suppressed again",
        CC / "condition_engine.py",
        "                        and (cid, side, member) not in self._empty_branch_warned",
        "                        and False",
        "smoke",
        [],
        "empty-group flag branch warns once",
    ),
    (
        "M6 F-300: repair_controller resurrects vanished keys again",
        CC / "hub.py",
        "        if cid not in self.invalid:\n            raise KeyError(cid)",
        "        if False:\n            raise KeyError(cid)",
        "pytest",
        [str(WEB) + "::test_repair_controller_raises_on_vanished_key"],
        "DID NOT RAISE",
    ),
    (
        "M7 F-302: non-boolean flag latch values trusted again",
        CC / "hub.py",
        "                clean = {\n"
        "                    k: v\n"
        "                    for k, v in value.items()\n"
        "                    if isinstance(k, str) and isinstance(v, bool)\n"
        "                }",
        "                clean = dict(value)",
        "smoke",
        [],
        "store/flag load guards hold on corrupt payloads",
    ),
]


def run_smoke() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(SMOKE)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=300,
    )
    return proc.returncode, proc.stdout + proc.stderr


def run_pytest(targets: list[str]) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *targets],
        cwd=str(ROOT), capture_output=True, text=True, timeout=300,
    )
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    caught, survived = [], []
    for name, path, old, new, runner, targets, frag in MUTATIONS:
        backup = path.with_suffix(path.suffix + ".mutbak")
        shutil.copy2(path, backup)
        try:
            src = path.read_text(encoding="utf-8")
            if old not in src:
                survived.append((name, "mutation anchor not found — check offsets"))
                continue
            path.write_text(src.replace(old, new, 1), encoding="utf-8", newline="")
            if runner == "smoke":
                rc, out = run_smoke()
            else:
                rc, out = run_pytest(targets)
            # the pin must FAIL (non-zero exit) under the mutant
            failed = rc != 0
            detail = ""
            if failed:
                tail = out.strip().splitlines()[-3:]
                detail = " | ".join(t.strip() for t in tail)[:220]
                if frag and frag not in out:
                    detail = "failed without expected fragment; last: " + detail
            (caught if failed else survived).append((name, detail))
        finally:
            shutil.copy2(backup, path)
            backup.unlink()
    print("=== MUTATION DISCRIMINATION (round 4, R7) ===")
    for name, detail in caught:
        print(f"[CAUGHT] {name}")
        if detail:
            print(f"         {detail}")
    for name, detail in survived:
        print(f"[SURVIVED] {name} — {detail}")
    print(f"caught {len(caught)}/{len(MUTATIONS)}")
    return 0 if not survived else 1


if __name__ == "__main__":
    sys.exit(main())
