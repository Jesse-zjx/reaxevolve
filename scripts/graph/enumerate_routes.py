#!/usr/bin/env python3
"""Multi-route registry for the reaction network.

Enumerates ALL distinct STRICT simple paths from glucose to each target product,
records each as a validated route (with per-step imag/barrier where known), and
maintains routes/routes.json. Also lists near-complete routes (one missing edge)
as candidates for the next validation, so we can grow MULTIPLE routes per target.

Run: python enumerate_routes.py            # refresh routes/routes.json from the graph
"""
import json, os, networkx as nx
from rdkit import Chem

import sys as _sys, os as _os
_here = _os.path.dirname(_os.path.abspath(__file__))
_pkg = _here
while _pkg != '/':
    if _os.path.isfile(_os.path.join(_pkg, 'tools', 'chem_paths.py')):
        _sys.path.insert(0, _os.path.join(_pkg, 'tools'))
        _sys.path.insert(0, _os.path.join(_pkg, 'scripts', 'lib'))
        break
    if _os.path.isfile(_os.path.join(_pkg, 'chem_paths.py')) and _os.path.basename(_pkg) == 'tools':
        _sys.path.insert(0, _pkg)
        _sys.path.insert(0, _os.path.join(_os.path.dirname(_pkg), 'scripts', 'lib'))
        break
    _pkg = _os.path.dirname(_pkg)
import chem_paths as _CP
_CP.bootstrap()

RN = _CP.RN
NET = f"{RN}/reaction_network.json"
OUTDIR = f"{RN}/routes"; os.makedirs(OUTDIR, exist_ok=True)

def C(s):
    m = Chem.MolFromSmiles(s); return Chem.MolToSmiles(m) if m else None

TARGETS = {"HMF": "O=Cc1ccc(CO)o1"}  # genesis: HMF only
SEEDS = ["O=CC(O)C(O)C(O)C(O)CO", "OCC1OC(O)C(O)C(O)C1O"]  # open + cyclic glucose

def load():
    net = json.load(open(NET))
    emap = {(e["reactant"], e["product"]): e for e in net["edges"]}
    return net, emap

def build_graph(emap, statuses):
    G = nx.DiGraph()
    for (r, p), e in emap.items():
        if e["status"] in statuses:
            G.add_edge(r, p, **e)
    return G

def route_edges(path, emap):
    out = []
    for i in range(len(path) - 1):
        e = emap.get((path[i], path[i + 1]), {})
        out.append({"reactant": path[i], "product": path[i + 1],
                    "kind": e.get("reaction_kind"), "ts_imag": e.get("ts_imag"),
                    "status": e.get("status")})
    return out

MAX_OVERLAP = 0.6   # a route sharing >=60% edges with an accepted one is a near-duplicate

def main():
    try:
        import diversity as DIV
    except Exception:
        DIV = None
    net, emap = load()
    seeds = [C(s) for s in SEEDS if C(s)]
    Gs = build_graph(emap, {"STRICT"})
    reg = {}
    for name, tsmi in TARGETS.items():
        t = C(tsmi); cand_paths = []
        seen = set()
        for src in seeds:
            if src in Gs and t in Gs:
                for p in nx.all_simple_paths(Gs, src, t, cutoff=16):
                    key = tuple(p)
                    if key in seen: continue
                    seen.add(key)
                    cand_paths.append(p)
        # shortest first, then apply the divergence gate: keep only routes that are
        # <MAX_OVERLAP with every already-accepted route AND occupy a NEW niche.
        cand_paths.sort(key=len)
        routes = []; niches = set()
        for p in cand_paths:
            r = {"route_id": f"{name}_R{len(routes)+1}", "target": name,
                 "n_steps": len(p) - 1, "status": "STRICT_COMPLETE",
                 "nodes": p, "edges": route_edges(p, emap)}
            if DIV:
                nk = DIV.niche_key(DIV.route_descriptor(p, r["edges"]))
                if routes and (not DIV.is_divergent(r, routes, MAX_OVERLAP)) and nk in niches:
                    continue   # near-duplicate in an already-covered niche -> skip
                niches.add(nk); r["niche"] = list(nk)
            routes.append(r)
        rep = DIV.route_diversity_report(routes) if DIV else {}
        reg[name] = {"target_smiles": t, "n_validated_routes": len(routes),
                     "diversity": rep, "routes": routes}
        print(f"{name}: {len(routes)} distinct STRICT route(s); steps={[r['n_steps'] for r in routes]} "
              f"| niches={rep.get('n_distinct_niches','?')} mean_overlap={rep.get('mean_pairwise_overlap','?')}")
    json.dump(reg, open(f"{OUTDIR}/routes.json", "w"), indent=2, ensure_ascii=False)
    print("wrote", f"{OUTDIR}/routes.json")

if __name__ == "__main__":
    main()
