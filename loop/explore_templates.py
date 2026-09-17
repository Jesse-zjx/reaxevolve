#!/usr/bin/env python3
"""Explore path A — reaction-template enumeration.

Expands the confirmed frontier (STRICT ∪ evidence_ok, plus the human-set seeds) with
`tools/expand/templates_expand.py`, then lands every surviving candidate through
`scripts/graph/add_hypothesis.py`, the single write entry for hypotheses.

Why it runs first: it is cheap, deterministic, and conserves atoms by construction,
so it fills the queue broadly before any model tokens are spent. What it cannot do is
propose a step its SMARTS cannot express — that gap is what path B (LLM Explore) is
asked to cover, using the coverage summary this stage returns.

The expander and its scoring function are evolvable assets (`tools/expand/`,
`tools/screen/`); this wrapper is loop plumbing and is not.

Usage:
  python loop/explore_templates.py [--top 24] [--dry-run] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PKG, "scripts", "lib"))
sys.path.insert(0, os.path.join(PKG, "scripts", "reflect"))
sys.path.insert(0, os.path.join(PKG, "tools", "expand"))
sys.path.insert(0, os.path.join(PKG, "tools", "screen"))
import chem_paths as CP  # noqa: E402

CP.bootstrap()

NETWORK = os.path.join(CP.GRAPH, "reaction_network.json")

# Frontier seeds: the human-set starting material plus the pentose entry point the
# furfural branch needs. Seeds only prime the frontier; they are not accepted edges.
SEEDS = [
    "OCC1OC(O)C(O)C(O)C1O",   # glucose, cyclic
    "O=CC(O)C(O)C(O)C(O)CO",  # glucose, open
    "OCC1OC(O)C(O)C1O",       # xylose, cyclic
    "O=CC(O)C(O)C(O)CO",      # xylose, open
]


def _load_net() -> dict:
    if not os.path.isfile(NETWORK):
        return {}
    try:
        return json.load(open(NETWORK))
    except json.JSONDecodeError:
        return {}


def frontier_species(net: dict) -> list[str]:
    """Confirmed species worth expanding from.

    Multi-fragment nodes (retro-aldol product pairs) are dropped: they are not real
    standalone reactants for the intramolecular templates.
    """
    import graph_views as GV  # noqa: WPS433
    import templates_expand as TE  # noqa: WPS433

    seeds = [TE.canon(s) for s in SEEDS]
    seeds = [s for s in seeds if s]
    if not net:
        return seeds
    reached, _ = GV.confirmed_nodes(net, view="working", seeds=seeds)
    return sorted(s for s in reached if s and "." not in s)


def known_pairs(net: dict) -> set:
    out = set()
    for e in (net.get("edges") or {}).values():
        r, p = e.get("reactant"), e.get("product")
        if r and p:
            out.add((r, p))
    return out


def enumerate_candidates(top: int) -> dict:
    import templates_expand as TE  # noqa: WPS433

    net = _load_net()
    frontier = frontier_species(net)
    known = known_pairs(net)
    cands = TE.expand(frontier, known)
    return {
        "n_frontier": len(frontier),
        "n_candidates": len(cands),
        "by_kind": dict(Counter(c["reaction_kind"] for c in cands)),
        "candidates": cands[:top],
        "all_kinds_seen": sorted({c["reaction_kind"] for c in cands}),
    }


def land(c: dict) -> dict:
    """Write one template candidate through the single hypothesis write entry."""
    cmd = [
        CP.PYBIN,
        os.path.join(PKG, "scripts", "graph", "add_hypothesis.py"),
        "--reactant", c["reactant"],
        "--product", c["product"],
        "--kind", c.get("reaction_kind") or "unknown",
        "--source", "explore_template",
        "--priority", str(c.get("score", 0.0)),
    ]
    if c.get("coproduct"):
        cmd += ["--coproduct", c["coproduct"]]
    # Templates carry no mechanism prose; the reaction kind is the whole claim.
    cmd += ["--mechanism", f"template:{c.get('reaction_kind')}"]
    r = subprocess.run(cmd, cwd=PKG, text=True, capture_output=True)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": "unparseable_add_hypothesis", "tail": (r.stdout or r.stderr)[-400:]}


def run(top: int = 24, dry_run: bool = False) -> dict:
    info = enumerate_candidates(top)
    results = []
    if not dry_run:
        for c in info["candidates"]:
            results.append(land(c))
    landed = sum(1 for x in results if x.get("ok"))
    return {
        "path": "template",
        "status": "ok",
        "dry_run": dry_run,
        "n_frontier": info["n_frontier"],
        "n_enumerated": info["n_candidates"],
        "n_offered": len(info["candidates"]),
        "n_landed": landed,
        "by_kind": info["by_kind"],
        "kinds_covered": info["all_kinds_seen"],
        "results": results,
        "offered": [
            {
                "reactant": c["reactant"],
                "product": c["product"],
                "kind": c["reaction_kind"],
                "coproduct": c.get("coproduct"),
                "score": c.get("score"),
            }
            for c in info["candidates"]
        ],
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--top", type=int, default=24)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    out = run(top=a.top, dry_run=a.dry_run)
    if a.json:
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        print(json.dumps({k: v for k, v in out.items() if k not in ("results", "offered")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
