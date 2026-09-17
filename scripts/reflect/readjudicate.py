#!/usr/bin/env python3
"""Re-adjudicate stored QM evidence under STRICT(v5) after a checker fix.

Why this exists: `run_qm_step.py` passed the water coproduct to the informational
endpoint classifier but not to the adjudicator, so `check_step` compared a
dehydration's two-fragment product endpoint (product + H2O) against the organic
product alone and failed clause 3 every time. Every dehydration in the campaign was
rejected on that basis, which is why all four STRICT edges were formula-preserving.

This replays the archived TS output and IRC endpoints — no new QM — and reports what
the corrected adjudicator says. Report-only by default; `--apply` writes verdicts.
It can only promote to STRICT, never demote: a demotion would mean the stored evidence
never supported the edge, which is a separate audit.

  python scripts/reflect/readjudicate.py            # report
  python scripts/reflect/readjudicate.py --apply    # append corrected verdicts
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time

PKG = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PKG, "scripts", "lib"))
sys.path.insert(0, os.path.join(PKG, "policy", "acceptance"))
import chem_paths as CP  # noqa: E402
import check_strict_bar as bar  # noqa: E402

CP.bootstrap()
RUNS = os.path.join(PKG, "runs", "validation")
NET = os.path.join(CP.GRAPH, "reaction_network.json")
QUEUE = os.path.join(PKG, "graph", "caches", "candidate_queue.json")
VERDICTS = os.path.join(CP.GRAPH, "verdicts.jsonl")


def edge_index() -> dict:
    """edge_id -> {reactant, product, coproduct, kind, status}."""
    net = json.load(open(NET))
    out = {}
    for coll in ((net.get("hypotheses") or {}).values(), (net.get("edges") or {}).values()):
        for e in coll:
            eid = e.get("edge_id") or e.get("id")
            if not (eid and e.get("reactant") and e.get("product")):
                continue
            prev = out.get(eid) or {}
            out[eid] = {
                "reactant": e["reactant"],
                "product": e["product"],
                # a hypothesis may carry the coproduct the edge record lacks
                "coproduct": e.get("coproduct") or prev.get("coproduct"),
                "kind": e.get("kind") or e.get("reaction_kind") or prev.get("kind"),
                "status": e.get("status") or prev.get("status"),
            }
    return out


def best_verdict(rundir: str, meta: dict) -> dict | None:
    """Best STRICT outcome across every guess archived for this edge."""
    best = None
    for ts in sorted(glob.glob(os.path.join(rundir, "*_ts.out"))):
        stem = os.path.basename(ts)[: -len("_ts.out")]
        f = os.path.join(rundir, f"{stem}_irc_IRC_F.xyz")
        b = os.path.join(rundir, f"{stem}_irc_IRC_B.xyz")
        if not (os.path.exists(f) and os.path.exists(b)):
            continue
        try:
            r = bar.check_step(
                stem, ts, f, b, meta["reactant"], meta["product"], coproduct=meta.get("coproduct")
            )
        except Exception:
            continue
        r["guess"] = stem
        if r.get("pass"):
            return r
        if best is None:
            best = r
    return best


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    idx = edge_index()
    promotions, unchanged, no_evidence = [], 0, 0
    for eid, meta in sorted(idx.items()):
        rundir = os.path.join(RUNS, eid)
        if not os.path.isdir(rundir):
            no_evidence += 1
            continue
        r = best_verdict(rundir, meta)
        if r is None:
            no_evidence += 1
            continue
        if r.get("pass") and meta.get("status") != "STRICT":
            promotions.append((eid, meta, r))
        else:
            unchanged += 1

    print(f"edges with archived evidence : {len(idx) - no_evidence}")
    print(f"edges without usable evidence: {no_evidence}")
    print(f"unchanged                    : {unchanged}")
    print(f"PROMOTIONS to STRICT         : {len(promotions)}\n")
    for eid, meta, r in promotions:
        print(f"  {eid}  {meta.get('kind')}  guess={r.get('guess')} imag={r.get('imag')}")
        print(f"     {meta['reactant']} -> {meta['product']}  co={meta.get('coproduct')}")

    if not a.apply:
        print("\n(report only; rerun with --apply to write verdicts)")
        return 0

    now = time.strftime("%Y-%m-%d %H:%M")
    provenance = {
        "kind": "readjudication",
        "reason": "coproduct was not passed to check_step; clause 3 compared a "
        "dehydration product endpoint against the organic product alone",
    }

    # The graph is built from strict_cache.json, not from verdicts.jsonl, so the cache
    # entry is what actually promotes an edge. Existing fields are preserved: only the
    # clauses the fixed adjudicator re-decided are overwritten.
    n_cache = 0
    for eid, meta, r in promotions:
        cache_path = os.path.join(RUNS, eid, "strict_cache.json")
        try:
            cache = json.load(open(cache_path)) if os.path.exists(cache_path) else {}
        except json.JSONDecodeError:
            cache = {}
        key = f"{meta['reactant']}>>{meta['product']}"
        entry = dict(cache.get(key) or {})
        entry.update(
            {
                "name": r.get("guess"),
                "reactant": meta["reactant"],
                "product": meta["product"],
                "coproduct": meta.get("coproduct"),
                "status": "STRICT",
                "detail": None,
                "policy_pass": True,
                "ts_imag_all": r.get("imag"),
                "ts_imag_cm-1": (r.get("imag") or [None])[0],
                "water_detail": r.get("water_detail"),
                "strict_version": r.get("strict_version"),
                "readjudicated_at": now,
                "readjudication": provenance,
            }
        )
        cache[key] = entry
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        json.dump(cache, open(cache_path, "w"), indent=2, ensure_ascii=False)
        n_cache += 1

    # verdicts.jsonl is the append-only archive; do not duplicate on a re-run
    already = set()
    if os.path.exists(VERDICTS):
        for line in open(VERDICTS):
            line = line.strip()
            if not line:
                continue
            try:
                v = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (v.get("source") or {}).get("kind") == "readjudication":
                already.add(v.get("edge"))
    n_v = 0
    with open(VERDICTS, "a") as fh:
        for eid, meta, r in promotions:
            edge = f"{meta['reactant']}>>{meta['product']}"
            if edge in already:
                continue
            fh.write(
                json.dumps(
                    {
                        "edge": edge,
                        "name": r.get("guess"),
                        "reactant": meta["reactant"],
                        "product": meta["product"],
                        "coproduct": meta.get("coproduct"),
                        "status": "STRICT",
                        "detail": None,
                        "policy_pass": True,
                        "ts_imag_all": r.get("imag"),
                        "ts_imag_cm-1": (r.get("imag") or [None])[0],
                        "water_detail": r.get("water_detail"),
                        "strict_version": r.get("strict_version"),
                        "time": now,
                        "source": dict(
                            provenance, replayed_from=os.path.join("runs", "validation", eid)
                        ),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            n_v += 1
    print(f"\nupdated {n_cache} strict_cache.json entries; appended {n_v} new verdicts")
    print("run scripts/graph/build_reaction_network.py to fold them into the graph")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
