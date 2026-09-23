#!/usr/bin/env python3
"""Derive an arm's task file from the locked preregistration.

The two protocols and the runner do not speak the same shape. The comparison route is stored in
`preregistration/panel.json` as pairs — `["reactant", "product"]` — while the runner reads
`step["reactant"]`, and the replay's instances are nested per failure mode under `repair` and
`transfer` rather than being a flat list of steps.

Adapting that by hand would put a hand-written file between the locked protocol and the calculation,
which is the one place a task must not be able to drift. So the task is derived, every time, from the
preregistration, and carries a `source` naming exactly where each step came from. `arm_runner.py`
refuses a task whose steps are not present in the preregistration.

  python scripts/eval/make_task.py --c2
  python scripts/eval/make_task.py --c1 --mode no_dominant_mode --kind repair
  python scripts/eval/make_task.py --list
"""
from __future__ import annotations

import argparse
import json
import os

PKG = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PANEL = os.path.join(PKG, "preregistration", "panel.json")
SELECTION = os.path.join(PKG, "preregistration", "c1_selection.json")
TASKS = os.path.join(PKG, "runs", "tasks")


def c2_task() -> dict:
    blob = json.load(open(PANEL))
    route = blob.get("c2_task_route") or {}
    steps = []
    for pair in route.get("steps") or []:
        if not (isinstance(pair, (list, tuple)) and len(pair) >= 2):
            raise SystemExit(f"unexpected step shape in panel.json: {pair!r}")
        steps.append({
            "reactant": pair[0],
            "product": pair[1],
            # The route as locked carries no coproduct; a step that needs one would have to be
            # recorded in the preregistration rather than added here.
            "coproduct": pair[2] if len(pair) > 2 else None,
        })
    return {
        "task": "c2_fixed_asset_comparison",
        "source": "preregistration/panel.json#c2_task_route.steps",
        "protocol": "preregistration/c2_protocol.md",
        "note": route.get("note"),
        "steps": steps,
    }


def c1_task(mode: str, kind: str) -> dict:
    blob = json.load(open(SELECTION))
    sel = blob.get("selection") or {}
    if mode not in sel:
        raise SystemExit(f"mode {mode!r} is not in the selection; have: {sorted(sel)}")
    if kind not in ("repair", "transfer"):
        raise SystemExit("--kind must be repair or transfer")
    rev = sel[mode]["revision"]
    steps = [
        {"reactant": i["reactant"], "product": i["product"], "coproduct": i.get("coproduct"),
         "instance": i["name"], "recorded_status": i.get("status")}
        for i in sel[mode][kind]
    ]
    return {
        "task": f"c1_{kind}",
        "source": f"preregistration/c1_selection.json#selection.{mode}.{kind}",
        "protocol": "preregistration/c1_protocol.md",
        "failure_mode": mode,
        "revision": {
            "seq": rev["seq"],
            "asset_id": rev["asset_id"],
            "snapshot": rev["snapshot"],
            "asset_version_before": rev.get("asset_version_before"),
            "asset_version_after": rev.get("asset_version_after"),
        },
        "steps": steps,
    }


def preregistered_steps() -> set[tuple]:
    """Every (reactant, product) a task is allowed to contain, from the locked files.

    Used by arm_runner to refuse a task that is not derivable from the preregistration — the check
    that makes deriving the task worth anything.
    """
    out: set[tuple] = set()
    if os.path.isfile(PANEL):
        blob = json.load(open(PANEL))
        for pair in (blob.get("c2_task_route") or {}).get("steps") or []:
            if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                out.add((pair[0], pair[1]))
        for cls in (blob.get("classes") or {}).values():
            for e in cls.get("edges") or []:
                out.add((e["reactant"], e["product"]))
    if os.path.isfile(SELECTION):
        for blob2 in (json.load(open(SELECTION)).get("selection") or {}).values():
            for kind in ("repair", "transfer"):
                for i in blob2.get(kind) or []:
                    out.add((i["reactant"], i["product"]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--c2", action="store_true")
    ap.add_argument("--c1", action="store_true")
    ap.add_argument("--mode", help="failure mode, for --c1")
    ap.add_argument("--kind", choices=("repair", "transfer"), help="for --c1")
    ap.add_argument("--list", action="store_true", help="what can be derived")
    ap.add_argument("-o", "--out", help="where to write (default: runs/tasks/<name>.json)")
    a = ap.parse_args()

    if a.list:
        blob = json.load(open(PANEL))
        n = len((blob.get("c2_task_route") or {}).get("steps") or [])
        print(f"--c2                       {n} step(s) from panel.json#c2_task_route")
        if os.path.isfile(SELECTION):
            sel = json.load(open(SELECTION)).get("selection") or {}
            for mode, b in sel.items():
                for kind in ("repair", "transfer"):
                    print(f"--c1 --mode {mode:<20} --kind {kind:<9} "
                          f"{len(b.get(kind) or [])} instance(s)")
        return 0

    if a.c2 and a.c1:
        print("pick one of --c2 / --c1")
        return 2
    if a.c2:
        task, name = c2_task(), "c2_route"
    elif a.c1:
        if not (a.mode and a.kind):
            print("--c1 needs --mode and --kind")
            return 2
        task, name = c1_task(a.mode, a.kind), f"c1_{a.mode}_{a.kind}"
    else:
        print("pick --c2 or --c1 (or --list)")
        return 2

    out = a.out or os.path.join(TASKS, f"{name}.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(task, open(out, "w"), indent=2)
    print(f"{task['task']}: {len(task['steps'])} step(s)")
    print(f"  from {task['source']}")
    for s in task["steps"]:
        extra = f"  (+{s['coproduct']})" if s.get("coproduct") else ""
        print(f"  {s['reactant'][:34]:<34} -> {s['product'][:34]}{extra}")
    print(f"[wrote] {os.path.relpath(out, PKG)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
