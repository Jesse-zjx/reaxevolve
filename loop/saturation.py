#!/usr/bin/env python3
"""Preregistered stopping rule: has revising the assets stopped paying?

The loop previously stopped on `--idle-stop`, "N consecutive rounds with no new accepted edge
and no asset revision". That is a reasonable operational brake but it is **not** the rule the
paper commits to, and shipping a repository whose code and protocol disagree about when a run
ends is the kind of gap a reader is entitled to find. The rule here is the one locked in
`preregistration/panel.json`:

    stop when, for each of the last K rounds, d_strict / max(1, n_strict_before) < eps
    or, as a sufficient condition, d_strict == 0 for all K rounds

and it reports **which** of the two fired, because they license different statements: a run that
stopped on zero growth has not shown that growth became small, only that it stopped.

Alongside the decision, the nine preregistered panel edges are re-measured and reported. They
are the diagnostic — pass rate per mechanism class and core-hours per passing edge — and they are
deliberately disjoint from the C2 task so that deciding to stop cannot fit the evaluation set.

  python loop/saturation.py                # report against the recorded metrics
  python loop/saturation.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PKG, "scripts", "lib"))
sys.path.insert(0, os.path.join(PKG, "scripts", "reflect"))
import chem_paths as CP  # noqa: E402

CP.bootstrap()

PANEL = os.path.join(PKG, "preregistration", "panel.json")
METRICS = os.path.join(PKG, "evidence", "state", "loop", "loop_metrics.jsonl")
NETWORK = os.path.join(CP.GRAPH, "reaction_network.json")


def load_rule() -> dict:
    with open(PANEL) as fh:
        pre = json.load(fh)
    rule = pre.get("stopping_rule") or {}
    return {
        "K": int(rule.get("window_rounds") or 3),
        "eps": float(rule.get("epsilon_relative_growth") or 0.05),
        "sufficient_condition": rule.get("sufficient_condition"),
        "panel": pre.get("classes") or {},
    }


def recent_rounds(n: int) -> list[dict]:
    if not os.path.isfile(METRICS):
        return []
    rows = []
    for line in open(METRICS):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("round") is not None and r.get("d_strict") is not None:
            rows.append(r)
    return rows[-n:]


def panel_state(panel: dict) -> dict:
    """Current status of each preregistered panel edge, per mechanism class."""
    if not os.path.isfile(NETWORK):
        return {}
    net = json.load(open(NETWORK))
    status = {
        (e.get("reactant"), e.get("product")): e.get("status")
        for e in (net.get("edges") or {}).values()
    }
    out = {}
    for cls, blob in panel.items():
        rows = []
        for e in blob.get("edges") or []:
            rows.append({
                "id": e["id"],
                "status_at_locking": e.get("status_at_locking"),
                "status_now": status.get((e["reactant"], e["product"])),
            })
        n_pass = sum(1 for r in rows if r["status_now"] == "STRICT")
        out[cls] = {
            "edges": rows,
            "n": len(rows),
            "n_strict": n_pass,
            "pass_rate": round(n_pass / len(rows), 3) if rows else None,
            "limitation": blob.get("limitation"),
        }
    return out


def evaluate() -> dict:
    rule = load_rule()
    K, eps = rule["K"], rule["eps"]
    rows = recent_rounds(K)

    per_round = []
    for r in rows:
        d = int(r.get("d_strict") or 0)
        before = int(r.get("strict") or 0) - d
        rel = d / max(1, before)
        per_round.append({
            "round": r.get("round"),
            "d_strict": d,
            "n_strict_before": before,
            "relative_growth": round(rel, 4),
            "below_eps": rel < eps,
        })

    enough = len(rows) >= K
    zero_growth = enough and all(p["d_strict"] == 0 for p in per_round)
    below_eps = enough and all(p["below_eps"] for p in per_round)
    # Report which fired: stopping on zero growth is a weaker statement than stopping because
    # growth became small, and the two must not be reported interchangeably.
    fired = None
    if zero_growth:
        fired = "zero_growth_for_K_rounds"
    elif below_eps:
        fired = "relative_growth_below_epsilon"

    return {
        "K": K,
        "epsilon": eps,
        "rounds_available": len(rows),
        "enough_rounds": enough,
        "per_round": per_round,
        "saturated": bool(fired),
        "which_fired": fired,
        "sufficient_condition": rule["sufficient_condition"],
        "panel": panel_state(rule["panel"]),
        "note": (
            "Saturation licenses freezing the asset set and starting the fixed-asset comparison. "
            "It is not a claim that the assets are optimal, and the panel pass rate is a "
            "diagnostic rather than a result."
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    st = evaluate()
    if a.json:
        print(json.dumps(st, indent=2, ensure_ascii=False))
        return 0
    print(f"rule: K={st['K']} rounds, eps={st['epsilon']}  "
          f"(rounds available: {st['rounds_available']})")
    if not st["enough_rounds"]:
        print(f"  not enough finished rounds yet — need {st['K']}")
    for p in st["per_round"]:
        print(f"  round {p['round']:>3}  d_strict={p['d_strict']:>3}  "
              f"relative growth {p['relative_growth']:.4f}  "
              f"{'< eps' if p['below_eps'] else '>= eps'}")
    print(f"\nsaturated: {st['saturated']}"
          + (f"  ({st['which_fired']})" if st["which_fired"] else ""))
    if st["panel"]:
        print("\npanel (diagnostic, disjoint from the C2 task):")
        for cls, blob in st["panel"].items():
            print(f"  {cls:<24} {blob['n_strict']}/{blob['n']} STRICT")
            if blob.get("limitation"):
                print(f"    limitation: {blob['limitation']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
