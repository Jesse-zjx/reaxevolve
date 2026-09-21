#!/usr/bin/env python3
"""The preregistered panel must stay disjoint from the C2 task, and must still be resolvable.

A preregistration is only worth writing down if it cannot quietly stop being true. Three ways
it could:

  1. A panel edge turns out to lie on the C2 route, so the stopping decision fits the
     evaluation set — the one thing D-28 says the panel must not do.
  2. A panel edge is not in the graph, so the panel cannot be measured at all.
  3. An asset-set version hash stops matching the asset set it names, so "the arms were these
     two versions" becomes unverifiable.

None of these would raise on their own, which is why they are checked.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

PKG = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PANEL = os.path.join(PKG, "preregistration", "panel.json")
NETWORK = os.path.join(PKG, "graph", "canonical", "reaction_network.json")

FAILS: list[str] = []


def ok(msg):
    print(f"  OK  {msg}")


def fail(msg):
    print(f" FAIL {msg}")
    FAILS.append(msg)


def vector_hash(path: str) -> str | None:
    if not os.path.isfile(path):
        return None
    v = json.load(open(path))
    blob = json.dumps({k: v[k] for k in ("skills", "tools") if k in v}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def main() -> int:
    pre = json.load(open(PANEL))
    classes = pre.get("classes") or {}
    panel = [(cls, e) for cls, blob in classes.items() for e in (blob.get("edges") or [])]
    route = {tuple(s) for s in ((pre.get("c2_task_route") or {}).get("steps") or [])}
    print(f"panel: {len(panel)} edges in {len(classes)} classes | C2 route: {len(route)} steps")

    print("\n== 1. panel is disjoint from the C2 task route ==")
    overlap = [(cls, e["id"]) for cls, e in panel if (e["reactant"], e["product"]) in route]
    if overlap:
        fail(f"panel edge(s) lie on the C2 route: {overlap}")
    else:
        ok("no panel edge lies on the C2 route")

    print("\n== 2. every panel edge is present in the graph ==")
    if not os.path.isfile(NETWORK):
        fail("graph/canonical/reaction_network.json missing")
    else:
        net = json.load(open(NETWORK))
        pairs = {(e.get("reactant"), e.get("product")) for e in (net.get("edges") or {}).values()}
        missing = [(cls, e["id"]) for cls, e in panel if (e["reactant"], e["product"]) not in pairs]
        if missing:
            fail(f"panel edge(s) not in the graph: {missing}")
        else:
            ok(f"all {len(panel)} panel edges resolve against the graph")
        # Route must resolve too, or the C2 task is not specified.
        route_missing = [s for s in route if tuple(s) not in pairs]
        if route_missing:
            fail(f"C2 route step(s) not in the graph: {route_missing}")
        else:
            ok(f"all {len(route)} C2 route steps resolve")

    print("\n== 3. each class has the preregistered number of edges ==")
    for cls, blob in classes.items():
        n = len(blob.get("edges") or [])
        if n != 3:
            fail(f"{cls} has {n} edges, expected 3")
    if not FAILS:
        ok("three edges per class")

    print("\n== 4. asset-set hashes match the sets they name ==")
    for arm, spec in (pre.get("c2_arms") or {}).items():
        path = os.path.join(PKG, spec["path"], "tools", "VERSIONS.json")
        got = vector_hash(path)
        want = spec.get("vector_sha256_16")
        if got is None:
            fail(f"{arm}: {spec['path']}/tools/VERSIONS.json missing")
        elif got != want:
            fail(f"{arm}: version vector changed since locking (recorded {want}, now {got}). "
                 f"Either the asset set moved, in which case the protocol must be re-locked and "
                 f"the change recorded, or this is an accidental edit.")
        else:
            ok(f"{arm}: vector {got} matches")

    print("\n== 5. stopping rule is fully specified ==")
    rule = pre.get("stopping_rule") or {}
    for key in ("window_rounds", "epsilon_relative_growth", "sufficient_condition"):
        if rule.get(key) in (None, ""):
            fail(f"stopping rule missing {key}")
    if not any("stopping rule missing" in f for f in FAILS):
        ok(f"K={rule.get('window_rounds')}, eps={rule.get('epsilon_relative_growth')}")

    print("\n==== SUMMARY ====")
    if FAILS:
        print(f"{len(FAILS)} failure(s):")
        for f in FAILS:
            print(" -", f)
        return 1
    print("PREREGISTRATION CONSISTENT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
