#!/usr/bin/env python3
"""Both asset sets must be runnable, and the role map must not contradict the rename record.

The loop calls skills by role because the two sets do not share names. That indirection is only
trustworthy if the role map stays consistent with `evolution/ASSET_RENAMES.json` — otherwise the
comparison between asset sets quietly becomes a comparison between two arbitrary skill selections.

The failure this guards against already happened: `loop/skill_runner.py` hardcoded two initial-set
skill names, so it could not run against the final set at all, which is the set the live tree
carries. Nothing caught it because nothing checked that a named skill exists.

Checks:
  1. every set with a role declaration resolves every role to skills that exist
  2. role assignments agree with ASSET_RENAMES: a final-set skill filling a role must be a
     recorded successor of the initial-set skill filling it, and any recorded successor left out
     must be listed in `exclusions` with a reason
  3. skill_runner resolves roles rather than naming skills
"""
from __future__ import annotations

import json
import os
import sys

PKG = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PKG, "loop"))
sys.path.insert(0, os.path.join(PKG, "scripts", "lib"))

FAILS: list[str] = []


def ok(m):
    print(f"  OK  {m}")


def fail(m):
    print(f" FAIL {m}")
    FAILS.append(m)


def successors(renames: dict, initial_id: str) -> list[str]:
    sk = renames.get("skills") or {}
    if initial_id in (sk.get("renamed") or {}):
        return [sk["renamed"][initial_id]]
    if initial_id in (sk.get("merged_into") or {}):
        return list(sk["merged_into"][initial_id])
    if initial_id in (sk.get("unchanged") or []):
        return [initial_id]
    return []


def main() -> int:
    import asset_set as AS

    blob = json.load(open(os.path.join(PKG, "assets", "roles.json")))
    renames = json.load(open(os.path.join(PKG, "evolution", "ASSET_RENAMES.json")))
    declared = blob.get("sets") or {}
    exclusions = blob.get("exclusions") or {}

    print("== 1. every declared role resolves to skills that exist ==")
    for name in sorted(declared):
        for role in sorted(blob["roles"]):
            try:
                dirs = AS.skill_dirs(name, role)
                ok(f"{name}/{role} -> {', '.join(os.path.basename(d) for d in dirs)}")
            except Exception as e:
                fail(f"{name}/{role}: {e}")

    print("\n== 2. role assignments agree with ASSET_RENAMES ==")
    init, fin = declared.get("initial") or {}, declared.get("final") or {}
    for role in sorted(blob["roles"]):
        i_ids, f_ids = init.get(role) or [], fin.get(role) or []
        if not i_ids or not f_ids:
            continue
        expected: set[str] = set()
        for i in i_ids:
            expected |= set(successors(renames, i))
        if not expected:
            fail(f"{role}: ASSET_RENAMES records no successor for {i_ids}")
            continue
        extra = set(f_ids) - expected
        if extra:
            fail(f"{role}: final set uses {sorted(extra)}, which ASSET_RENAMES does not record "
                 f"as a successor of {i_ids}")
        dropped = expected - set(f_ids)
        undeclared = [
            d for d in sorted(dropped)
            if not any(d in k and i in k for k in exclusions for i in i_ids)
        ]
        if undeclared:
            fail(f"{role}: recorded successor(s) {undeclared} left out with no entry in "
                 "`exclusions` explaining why")
        elif dropped:
            ok(f"{role}: {sorted(set(f_ids))} used; {sorted(dropped)} excluded with a stated reason")
        else:
            ok(f"{role}: matches the recorded successors exactly")

    print("\n== 3. skill_runner resolves roles rather than naming skills ==")
    src = open(os.path.join(PKG, "loop", "skill_runner.py")).read()
    for bad in ('".skills" / "generate-ts-guesses"', '".skills" / "diagnose-ts-failures"'):
        if bad in src:
            fail(f"skill_runner still hardcodes {bad}")
    if "skill_dirs(" not in src:
        fail("skill_runner does not call asset_set.skill_dirs")
    if not FAILS:
        ok("skills come from the role map")

    print("\n==== SUMMARY ====")
    if FAILS:
        print(f"{len(FAILS)} failure(s):")
        for f in FAILS:
            print(" -", f)
        return 1
    print("ASSET ROLES CONSISTENT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
