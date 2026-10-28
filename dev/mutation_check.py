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

Round 5 (R9, WHA-F-304..308): M5's anchor follows the rewritten warning
scan (F-305/F-306 abstract evaluation walk), M8 = F-298 OR True-dominance
pin; and the verdict itself got honest (F-308): a mutant counts CAUGHT
only when its run exits non-zero AND the output carries the expected
fragment — a non-zero exit without the fragment is INVALID, and both
runners are baseline-checked green before the first mutation.
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
        "                    if (cid, side, group) in self._empty_branch_warned:",
        "                    if False:",
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
    (
        "M8 F-298: OR loses its provably-true dominance again",
        CC / "schema.py",
        "                elif ctype == COND_OR:\n"
        "                    verdict = (\n"
        "                        True\n"
        "                        if any(v is True for v in verdicts)\n"
        "                        else None if any(v is None for v in verdicts)"
        " else False\n"
        "                    )",
        "                elif ctype == COND_OR:\n"
        "                    verdict = (\n"
        "                        None\n"
        "                        if any(v is None for v in verdicts)\n"
        "                        else False\n"
        "                    )",
        "smoke",
        [],
        "OR with a provably-true member must be rejected",
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
    # Baseline self-check (审查 R9-5): every verdict below compares a
    # mutant run against a green suite — a broken environment (import
    # error, missing dependency, collection error) would otherwise fail
    # every mutant run and fake a full CAUGHT scoreboard.
    base_rc, base_out = run_smoke()
    if base_rc != 0:
        print("[BASELINE] smoke failed before any mutation; aborting")
        for line in base_out.strip().splitlines()[-10:]:
            print(f"         {line}")
        return 1
    print("[BASELINE] smoke green (exit 0)")
    base_rc, base_out = run_pytest([str(TESTS)])
    if base_rc != 0:
        print("[BASELINE] pytest failed before any mutation; aborting")
        for line in base_out.strip().splitlines()[-10:]:
            print(f"         {line}")
        return 1
    print("[BASELINE] pytest green (exit 0)")
    caught, survived, invalid = [], [], []
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
            detail = ""
            if out.strip():
                tail = out.strip().splitlines()[-3:]
                detail = " | ".join(t.strip() for t in tail)[:220]
            # The pin must FAIL (non-zero exit) AND fail through the pinned
            # assertion (expected fragment present): a non-zero exit without
            # the fragment is some global breakage, not a caught mutant
            # (审查 R9-5).
            if rc == 0:
                survived.append((name, detail))
            elif frag and frag not in out:
                invalid.append(
                    (name, "failed without expected fragment; last: " + detail)
                )
            else:
                caught.append((name, detail))
        finally:
            shutil.copy2(backup, path)
            backup.unlink()
    print("=== MUTATION DISCRIMINATION (round 5, R9) ===")
    for name, detail in caught:
        print(f"[CAUGHT] {name}")
        if detail:
            print(f"         {detail}")
    for name, detail in invalid:
        print(f"[INVALID] {name} — {detail}")
    for name, detail in survived:
        print(f"[SURVIVED] {name} — {detail}")
    print(f"caught {len(caught)}/{len(MUTATIONS)}")
    return 0 if not survived and not invalid else 1


if __name__ == "__main__":
    sys.exit(main())
