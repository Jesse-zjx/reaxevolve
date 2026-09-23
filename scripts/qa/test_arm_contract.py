#!/usr/bin/env python3
"""The seams an evaluation arm only reaches on a real run.

Every check here covers something the dry run cannot see, because it stops before any QM. That is how
two defects survived: `arm_runner` passed `--reactant` / `--product` while `skill_runner` expects
`--reactant-smiles` / `--product-smiles`, so a real arm would have died on an argparse error after
materialising; and `CHEM_REFLECT_CLOSED` was set by the runner and read by nothing, so "Reflect is
closed" rested entirely on the arm never happening to call Reflect.

  1. every flag the runner passes is one the step runner accepts
  2. the reflect-closed guard actually refuses a bump
  3. a task must be derivable from the preregistration
  4. the asset digest notices an asset changing, which the ledger digest cannot
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile

PKG = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PKG, "scripts", "eval"))
PY = sys.executable

FAILS: list[str] = []


def ok(m):
    print(f"  OK  {m}")


def fail(m):
    print(f" FAIL {m}")
    FAILS.append(m)


def main() -> int:
    print("== 1. the runner passes only flags the step runner accepts ==")
    src = open(os.path.join(PKG, "scripts", "eval", "arm_runner.py")).read()
    m = re.search(r"cmd = \[(.*?)\]\n", src, re.S)
    if not m:
        fail("could not find the step-runner invocation in arm_runner.py")
    else:
        passed = set(re.findall(r'"(--[a-z-]+)"', m.group(1)))
        h = subprocess.run(
            [PY, os.path.join(PKG, "loop", "skill_runner.py"), "--help"],
            capture_output=True, text=True,
        ).stdout
        accepted = set(re.findall(r"(--[a-z-]+)", h))
        unknown = sorted(passed - accepted)
        if unknown:
            fail(f"skill_runner does not accept {unknown}: a real arm would fail after materialising")
        elif not passed:
            fail("no flags found in the invocation; the check is not looking at anything")
        else:
            ok(f"{len(passed)} flag(s) all accepted")
        # The guess budget must be pinned, not defaulted, or the arms can differ in more than assets.
        if "--max-rounds" not in passed:
            fail("--max-rounds is not pinned: arms could run different guess budgets")
        else:
            ok("--max-rounds pinned explicitly")

    print("\n== 2. the reflect-closed guard refuses a bump ==")
    env = dict(os.environ, CHEM_REFLECT_CLOSED="1")
    r = subprocess.run(
        [PY, os.path.join(PKG, "scripts", "reflect", "asset_snapshot.py"), "--bump",
         "--asset-id", "tools/screen/diversity.py", "--path", "tools/screen/diversity.py",
         "--revision-class", "plumbing", "--failure-mode", "stale_path_reference",
         "--trigger-evidence", "contract test", "--intended-effect", "none", "--scope", "none"],
        capture_output=True, text=True, cwd=PKG, env=env,
    )
    out = (r.stdout or "") + (r.stderr or "")
    if "refusing to bump" not in out:
        fail("asset_snapshot bumped while CHEM_REFLECT_CLOSED was set")
    else:
        ok("bump refused while an arm is running")
    # And the refusal must not have written anything.
    ledger = os.path.join(PKG, "evolution", "EVOLUTION_LOG.jsonl")
    n = sum(1 for line in open(ledger) if line.strip())
    g = subprocess.run(["git", "diff", "--name-only", "--", "evolution", "tools/VERSIONS.json"],
                       capture_output=True, text=True, cwd=PKG).stdout.split()
    if g:
        fail(f"the refused bump still modified {g}")
    else:
        ok(f"nothing written; ledger still {n} revisions")

    print("\n== 3. a task must be derivable from the preregistration ==")
    import make_task as MT

    allowed = MT.preregistered_steps()
    if len(allowed) < 10:
        fail(f"only {len(allowed)} preregistered step(s) found; the allowlist looks empty")
    else:
        ok(f"{len(allowed)} preregistered step(s)")
    with tempfile.TemporaryDirectory() as td:
        bad = os.path.join(td, "tampered.json")
        json.dump({"task": "t", "source": "hand-written",
                   "steps": [{"reactant": "CCO", "product": "CC=O"}]}, open(bad, "w"))
        r = subprocess.run(
            [PY, os.path.join(PKG, "scripts", "eval", "arm_runner.py"),
             "--set", "final", "--task", bad, "--workdir", os.path.join(td, "arm")],
            capture_output=True, text=True, cwd=PKG,
        )
        if "not in the preregistration" not in (r.stdout + r.stderr):
            fail("the runner accepted a task step that is in no protocol")
        else:
            ok("a step outside the preregistration is refused")

    print("\n== 4. the asset digest notices what the ledger digest cannot ==")
    import arm_runner as AR

    with tempfile.TemporaryDirectory() as td:
        dest = os.path.join(td, "arm")
        AR.materialise("final", dest)
        n0, d0 = AR.asset_digest(dest)
        skill = os.path.join(dest, ".skills", "ts-validation-strategy", "SKILL.md")
        with open(skill, "a") as fh:
            fh.write("\n<!-- an arm editing its own skill mid-run -->\n")
        n1, d1 = AR.asset_digest(dest)
        if d0 == d1:
            fail("editing a skill inside the arm did not change the asset digest")
        else:
            ok(f"a mid-arm skill edit changes the digest ({d0} -> {d1}, {n0} files)")

    print("\n==== SUMMARY ====")
    if FAILS:
        print(f"{len(FAILS)} failure(s):")
        for f in FAILS:
            print(" -", f)
        return 1
    print("ARM CONTRACT HOLDS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
