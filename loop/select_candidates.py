#!/usr/bin/env python3
"""Which candidate edges to spend QM on this round (score-first, with retries).

Selection policy
----------------
Candidates are ranked by the score their generator assigned:

  * template Explore  → `tools/expand/templates_expand.py::motif_score` + novelty
  * LLM Explore       → the priority the model reported for its own hypothesis

Both are *ordering* signals only. Nothing here can make an edge acceptable: status is
written solely by `scripts/validate/verdict_writer.py` under
`policy/acceptance/STRICT.md`, so a bad score costs compute and cannot manufacture a
verdict.

Two filters run before ranking:

  1. atom conservation (`loop/mass_balance.py`) — a step that cannot balance has no
     IRC connecting its stated endpoints, so it is never worth QM;
  2. retry budget — a candidate is retired after `--max-attempts` tries.

The retry budget matters for the evolution claim: an earlier campaign selected only
`pending` candidates, so every edge froze at one attempt and revised TS skills never
got a second chance at the step that triggered them. Without retries there is no way
to observe "the same edge passed after the asset changed".
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PKG, "scripts", "lib"))
sys.path.insert(0, os.path.join(PKG, "loop"))
import chem_paths as CP  # noqa: E402

CP.bootstrap()

QUEUE = os.path.join(CP.GRAPH_ROOT, "caches", "candidate_queue.json")
NETWORK = os.path.join(CP.GRAPH, "reaction_network.json")

# Statuses that mean "already settled, do not re-spend".
_SETTLED = frozenset({"STRICT"})


def load_queue(path: str = QUEUE) -> list[dict]:
    if not os.path.isfile(path):
        return []
    try:
        data = json.load(open(path))
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        return data.get("candidates") or data.get("queue") or []
    return data if isinstance(data, list) else []


def _graph_status() -> dict[tuple[str, str], str]:
    if not os.path.isfile(NETWORK):
        return {}
    try:
        net = json.load(open(NETWORK))
    except json.JSONDecodeError:
        return {}
    out = {}
    for e in (net.get("edges") or {}).values():
        r, p = e.get("reactant"), e.get("product")
        if r and p:
            out[(r, p)] = e.get("status") or "proposed"
    return out


def score_of(c: dict) -> float:
    """Generator-assigned ordering score, normalised across the two Explore paths.

    `motif_score` is unbounded and can be negative; LLM priority is 0..1. Both are
    used as-is on purpose — a template candidate the evolved scorer pushed to -4 is
    genuinely meant to rank below anything the model bothered to propose.
    """
    for key in ("score", "priority"):
        v = c.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return 0.0


def analyze(max_attempts: int = 3, queue_path: str = QUEUE) -> dict:
    import mass_balance as MB  # noqa: WPS433

    cands = load_queue(queue_path)
    gstatus = _graph_status()

    eligible, dropped = [], {"unbalanced": [], "settled": [], "exhausted": []}
    for c in cands:
        r, p = c.get("reactant"), c.get("product")
        if not r or not p:
            continue
        pair = (r, p)
        if gstatus.get(pair) in _SETTLED:
            dropped["settled"].append({"reactant": r, "product": p})
            continue
        bal = MB.check(r, p, c.get("coproduct"))
        if not bal["ok"]:
            dropped["unbalanced"].append({"reactant": r, "product": p, "delta": bal["delta"]})
            continue
        attempts = int(c.get("attempts") or 0)
        if attempts >= max_attempts:
            dropped["exhausted"].append({"reactant": r, "product": p, "attempts": attempts})
            continue
        row = dict(c)
        row["coproduct"] = bal.get("coproduct") or c.get("coproduct")
        row["attempts"] = attempts
        row["_score"] = score_of(c)
        row["graph_status"] = gstatus.get(pair)
        eligible.append(row)

    # score first; fewer prior attempts breaks ties so a fresh candidate is not
    # starved by an equally scored one already retried twice.
    eligible.sort(key=lambda c: (-c["_score"], c["attempts"]))
    return {
        "n_queue": len(cands),
        "n_eligible": len(eligible),
        "n_dropped_unbalanced": len(dropped["unbalanced"]),
        "n_dropped_settled": len(dropped["settled"]),
        "n_dropped_exhausted": len(dropped["exhausted"]),
        "dropped": dropped,
        "candidates": eligible,
        "max_attempts": max_attempts,
    }


def select(top: int = 4, max_attempts: int = 3, info: dict | None = None) -> list[dict]:
    info = analyze(max_attempts=max_attempts) if info is None else info
    return (info.get("candidates") or [])[:top]


def writeback(results: list[dict], queue_path: str = QUEUE) -> int:
    """Persist attempt outcomes so a tried candidate is not re-selected forever.

    A candidate can be selected while missing from the queue file (it may exist only
    on the graph), so an unseen key is appended rather than dropped — otherwise its
    attempt count would stay at zero and it would be re-picked every round.
    """
    if not os.path.isfile(queue_path):
        return 0
    try:
        data = json.load(open(queue_path))
    except json.JSONDecodeError:
        return 0
    if isinstance(data, list):
        data = {"candidates": data}

    by_key = {
        f"{x['candidate'].get('reactant')}>>{x['candidate'].get('product')}": x for x in results
    }
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    n = 0
    seen = set()
    for c in data.get("candidates") or []:
        k = f"{c.get('reactant')}>>{c.get('product')}"
        seen.add(k)
        if k in by_key:
            c["status"] = by_key[k]["result"].get("status") or "unresolved"
            c["last_attempt_at"] = now
            c["attempts"] = int(c.get("attempts") or 0) + 1
            n += 1
    for k, x in by_key.items():
        if k in seen:
            continue
        c = {kk: vv for kk, vv in x["candidate"].items() if not kk.startswith("_")}
        c["status"] = x["result"].get("status") or "unresolved"
        c["last_attempt_at"] = now
        c["attempts"] = int(c.get("attempts") or 0) + 1
        data.setdefault("candidates", []).append(c)
        n += 1

    data["updated_at"] = now
    json.dump(data, open(queue_path, "w"), indent=2, ensure_ascii=False)
    open(queue_path, "a").write("\n")
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--max-attempts", type=int, default=3)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    info = analyze(max_attempts=a.max_attempts)
    if a.json:
        print(json.dumps(info, indent=2, ensure_ascii=False))
        return 0
    print(
        f"queue={info['n_queue']} eligible={info['n_eligible']} "
        f"dropped: unbalanced={info['n_dropped_unbalanced']} "
        f"settled={info['n_dropped_settled']} exhausted={info['n_dropped_exhausted']}"
    )
    print(f"\ntop {a.top}:")
    for c in select(top=a.top, info=info):
        print(
            f"  [{c['_score']:+7.2f}] att={c['attempts']} {str(c.get('kind')):16} "
            f"{c['reactant'][:34]} -> {c['product'][:34]}"
            + (" + H2O" if c.get("coproduct") else "")
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
