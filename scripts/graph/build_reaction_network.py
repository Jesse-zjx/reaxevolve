#!/usr/bin/env python3
"""Build Graph Memory: the only writer of the canonical reaction network.

Merges:
  - seed nodes (glucose starts + the three human-set product targets)
  - hypotheses written by scripts/graph/add_hypothesis.py (template and LLM Explore)
  - **/strict_cache.json under runs/ and graph/caches/

Edge status comes only from recorded verdicts; this script never adjudicates and
never injects a pre-validated chain.
"""
from __future__ import annotations

import glob
import json
import os
import sys
import time

_PKG = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_PKG, "scripts", "lib"))
import chem_paths as CP  # noqa: E402

CP.bootstrap()

try:
    from rdkit import Chem
    from rdkit.Chem import rdMolDescriptors as desc
except ImportError:
    Chem = None
    desc = None

try:
    import networkx as nx
except ImportError:
    nx = None

OUT = CP.GRAPH
# Human-set product targets (policy/targets_and_budget.md). HAA and FF are
# C-C-cleavage products, so a route to them changes carbon count — nothing here
# assumes a carbon-preserving dehydration ladder.
TARGETS = {
    "HMF": "O=Cc1ccc(CO)o1",
    "HAA": "O=CCO",
    "FF": "O=Cc1ccco1",
}
GLUCOSE = "OCC1OC(O)C(O)C(O)C1O"
GLUCOSE_OPEN = "O=CC(O)C(O)C(O)C(O)CO"

STATUS_RANK = {
    "STRICT": 4,
    "evidence_ok": 3,
    "validated": 3,
    "qm_real": 2,
    # QM-seen unresolved/rejected outrank mere Explore proposals
    "rejected": 1,
    "unresolved": 1,
    "proposed": 0,
    "failed": -1,
}


def canon(s):
    if not s or Chem is None:
        return s
    m = Chem.MolFromSmiles(s)
    if m is None:
        return None
    Chem.RemoveStereochemistry(m)
    return Chem.MolToSmiles(m)


def nid(smi):
    import hashlib

    return "N_" + hashlib.sha1(smi.encode()).hexdigest()[:12]


def eid(r, p):
    import hashlib

    return "E_" + hashlib.sha1(f"{r}>>{p}".encode()).hexdigest()[:12]


def load_json(path, default):
    if os.path.isfile(path):
        try:
            return json.load(open(path))
        except json.JSONDecodeError:
            return default
    return default


def collect_caches():
    patterns = [
        os.path.join(CP.RUNS, "**", "strict_cache.json"),
        os.path.join(CP.GRAPH_ROOT, "caches", "**", "strict_cache.json"),
        os.path.join(OUT, "strict_cache.json"),
    ]
    out = {}
    for pat in patterns:
        for path in glob.glob(pat, recursive=True):
            try:
                data = json.load(open(path))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            for k, v in data.items():
                if not isinstance(v, dict):
                    continue
                prev = out.get(k)
                if prev is None or STATUS_RANK.get(v.get("status"), -9) >= STATUS_RANK.get(
                    prev.get("status"), -9
                ):
                    vv = dict(v)
                    vv["_cache_path"] = path
                    out[k] = vv
    return out


def ensure_seed(net):
    meta = net.setdefault("meta", {})
    meta["target_names"] = sorted(TARGETS)
    meta["start_smiles"] = [canon(GLUCOSE), canon(GLUCOSE_OPEN)]
    meta["target_smiles"] = [canon(s) for s in TARGETS.values() if canon(s)]
    nodes = net.setdefault("nodes", {})
    seeds = [("glucose_cyclic", GLUCOSE, "seed_start"), ("glucose_open", GLUCOSE_OPEN, "seed_start")]
    seeds += [(name.lower(), smi, "seed_target") for name, smi in sorted(TARGETS.items())]
    for name, smi, role in seeds:
        c = canon(smi)
        if not c:
            continue
        i = nid(c)
        nodes.setdefault(
            i,
            {"id": i, "name": name, "smiles": c, "role": role, "source": "seed"},
        )
    return net


def _strict_graph(net):
    if nx is None:
        return None
    g = nx.DiGraph()
    for e in net.get("edges", {}).values():
        if e.get("status") != "STRICT":
            continue
        g.add_edge(e["reactant"], e["product"])
    return g


def reachable_strict(net) -> dict:
    """Per-target: is there a STRICT-only path from either glucose seed?"""
    out = {name: False for name in TARGETS}
    g = _strict_graph(net)
    if g is None:
        return out
    starts = [s for s in (canon(GLUCOSE), canon(GLUCOSE_OPEN)) if s]
    for name, smi in TARGETS.items():
        t = canon(smi)
        if not t or t not in g:
            continue
        out[name] = any(s in g and nx.has_path(g, s, t) for s in starts)
    return out


def strict_distance_to_targets(net) -> dict:
    """Shortest STRICT-only hop count from a glucose seed to each target.

    Target-agnostic progress signal: it replaces the HMF-specific stoichiometric
    ladder, which assumed carbon was conserved and therefore discarded every HAA /
    FF intermediate.
    """
    out = {name: None for name in TARGETS}
    g = _strict_graph(net)
    if g is None:
        return out
    starts = [s for s in (canon(GLUCOSE), canon(GLUCOSE_OPEN)) if s and s in g]
    for name, smi in TARGETS.items():
        t = canon(smi)
        if not t or t not in g:
            continue
        best = None
        for s in starts:
            try:
                d = nx.shortest_path_length(g, s, t)
            except Exception:
                continue
            best = d if best is None else min(best, d)
        out[name] = best
    return out


def main():
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--network",
        default=os.path.join(OUT, "reaction_network.json"),
        help="network file to read and rewrite (override to avoid touching Graph Memory)",
    )
    ap.add_argument(
        "--out",
        default=None,
        help="write the rebuilt network here instead of in place (read-only rebuild)",
    )
    a = ap.parse_args()

    path = a.network
    net = load_json(path, {"version": "reaxevolve-v1", "nodes": {}, "edges": {}, "hypotheses": {}, "meta": {}})
    net = ensure_seed(net)
    caches = collect_caches()

    edges = net.setdefault("edges", {})
    for key, rec in caches.items():
        if ">>" not in key:
            r, p = rec.get("reactant"), rec.get("product")
        else:
            r, p = key.split(">>", 1)
        r, p = canon(r), canon(p)
        if not r or not p:
            continue
        i = eid(r, p)
        st = rec.get("status") or "unresolved"
        prev = edges.get(i)
        if prev and STATUS_RANK.get(prev.get("status"), -9) > STATUS_RANK.get(st, -9):
            continue
        edges[i] = {
            "id": i,
            "reactant": r,
            "product": p,
            "reactant_id": nid(r),
            "product_id": nid(p),
            "coproduct": rec.get("coproduct"),
            "kind": rec.get("kind") or (prev or {}).get("kind") or "unknown",
            "status": st,
            "detail": rec.get("detail"),
            "ts_imag_cm-1": rec.get("ts_imag_cm-1"),
            "source": "strict_cache",
            "cache_path": rec.get("_cache_path"),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        net.setdefault("nodes", {}).setdefault(
            nid(r), {"id": nid(r), "smiles": r, "role": "intermediate", "source": "cache"}
        )
        net.setdefault("nodes", {}).setdefault(
            nid(p), {"id": nid(p), "smiles": p, "role": "intermediate", "source": "cache"}
        )

    # Drop still-unattempted edges whose hypothesis was retracted. An edge that has
    # QM evidence (any status other than "proposed") is kept regardless — evidence is
    # never deleted by a rebuild.
    live_hyp_edges = {h.get("edge_id") for h in net.get("hypotheses", {}).values()}
    for i in list(edges):
        if edges[i].get("status") == "proposed" and i not in live_hyp_edges:
            edges.pop(i)

    # Pull pending hypotheses that have no edge yet
    for h in net.get("hypotheses", {}).values():
        r, p = canon(h.get("reactant")), canon(h.get("product"))
        if not r or not p:
            continue
        i = eid(r, p)
        if i not in edges:
            edges[i] = {
                "id": i,
                "reactant": r,
                "product": p,
                "reactant_id": nid(r),
                "product_id": nid(p),
                "coproduct": h.get("coproduct"),
                "kind": h.get("kind") or "unknown",
                "status": "proposed",
                "source": "hypothesis",
                "hypothesis_id": h.get("id"),
            }

    net["meta"]["built_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    net["meta"]["n_nodes"] = len(net.get("nodes", {}))
    net["meta"]["n_edges"] = len(edges)
    net["meta"]["n_strict"] = sum(1 for e in edges.values() if e.get("status") == "STRICT")
    reach = reachable_strict(net)
    net["meta"]["targets_reachable_strict"] = reach
    net["meta"]["n_targets_reachable_strict"] = sum(1 for v in reach.values() if v)
    net["meta"]["strict_distance_to_targets"] = strict_distance_to_targets(net)
    # Kept so older readers do not silently see None; it means "at least one target".
    net["meta"]["target_reachable_strict_from_glucose"] = any(reach.values())
    net["meta"]["expander"] = "tools/expand/templates_expand.py"

    dest = a.out or path
    json.dump(net, open(dest, "w"), indent=2, ensure_ascii=False)
    open(dest, "a").write("\n")

    summary = {
        "network": dest,
        "n_nodes": net["meta"]["n_nodes"],
        "n_edges": net["meta"]["n_edges"],
        "n_strict": net["meta"]["n_strict"],
        "targets_reachable_strict": net["meta"]["targets_reachable_strict"],
        "n_targets_reachable_strict": net["meta"]["n_targets_reachable_strict"],
        "strict_distance_to_targets": net["meta"]["strict_distance_to_targets"],
        "caches_merged": len(caches),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
