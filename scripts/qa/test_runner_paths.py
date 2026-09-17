#!/usr/bin/env python3
"""Targeted checks for the skill_runner → run_qm_step seam.

These are the failure modes that silently produced "nothing happened" during the
first round: guesses written into a nested directory, repo-relative paths handed to
a driver that chdir()s, and a killed driver leaving neither verdict nor cleanup.

Runs real ORCA with a deliberately tiny wall clock, so it costs a few core-seconds.

  python scripts/qa/test_runner_paths.py --guess <xyz> --reactant SMI --product SMI
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PKG = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG / "loop"))
sys.path.insert(0, str(PKG / "scripts" / "lib"))

FAILS: list[str] = []


def ok(m):
    print(f"  OK  {m}")


def bad(m):
    print(f" FAIL {m}")
    FAILS.append(m)


def orca_pids() -> set[str]:
    r = subprocess.run(["pgrep", "-f", "orca"], text=True, capture_output=True)
    return {p for p in (r.stdout or "").split() if p.strip()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--guess", required=True, help="an existing TS guess .xyz")
    ap.add_argument("--reactant", required=True)
    ap.add_argument("--product", required=True)
    ap.add_argument("--wall-s", type=int, default=45)
    a = ap.parse_args()

    from skill_runner import list_guess_xyz, validate_guess  # noqa: E402

    guess_src = Path(a.guess).resolve()
    if not guess_src.is_file():
        bad(f"guess not found: {guess_src}")
        return 1

    work = Path(tempfile.mkdtemp(prefix="genesis_seamtest_"))
    try:
        print("== 1. nested guess discovery ==")
        rd = work / "round_0"
        (rd / "guesses").mkdir(parents=True)
        shutil.copy2(guess_src, rd / "guesses" / "g_nested.xyz")
        shutil.copy2(guess_src, rd / "g_flat.xyz")
        found = list_guess_xyz(rd)
        names = sorted(p.name for p in found)
        if names == ["g_flat.xyz", "g_nested.xyz"]:
            ok(f"found both flat and nested guesses: {names}")
        else:
            bad(f"guess discovery returned {names}")

        print("\n== 2. wall-clock kill: verdict written, no orphan ORCA, scratch cleaned ==")
        before = orca_pids()
        t0 = time.time()
        res = validate_guess(
            name="seamtest",
            guess=rd / "guesses" / "g_nested.xyz",
            reactant=a.reactant,
            product=a.product,
            coproduct=None,
            workdir=work,
            nprocs=2,
            wall_s=a.wall_s,
        )
        elapsed = time.time() - t0

        if res.get("status") in {"STRICT", "evidence_ok", "rejected", "unresolved"}:
            ok(f"status={res['status']} detail={res.get('detail')!r} after {elapsed:.0f}s")
        else:
            bad(f"no valid status returned: {res.get('status')!r}")

        if res.get("strict_version"):
            ok(f"stamped strict_version={res['strict_version']}")
        else:
            bad("verdict not stamped by verdict_writer")

        cache = work / "strict_cache.json"
        if cache.is_file():
            blob = json.load(open(cache))
            ok(f"verdict persisted to strict_cache.json ({len(blob)} edge key(s))")
        else:
            bad("no strict_cache.json written")

        # the driver must have actually started ORCA, i.e. paths resolved after chdir
        if (work / "seamtest_ts.inp").is_file():
            ok("driver resolved the guess path and wrote the ORCA input")
        else:
            bad("driver never wrote an ORCA input — path resolution still broken")

        time.sleep(3)
        leaked = orca_pids() - before
        if leaked:
            bad(f"orphan ORCA processes survived the kill: {sorted(leaked)}")
        else:
            ok("no orphan ORCA processes")

        junk = [
            p.name
            for p in work.iterdir()
            if p.suffix in {".tmp", ".gbw", ".densities", ".cpcm"} or ".tmp." in p.name
        ]
        if junk:
            bad(f"scratch not cleaned: {junk[:6]}")
        else:
            ok("scratch cleaned")

        print("\n==== SUMMARY ====")
        if FAILS:
            print(f"{len(FAILS)} failure(s):")
            for f in FAILS:
                print(" -", f)
            return 1
        print("ALL SEAM CHECKS PASSED")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
