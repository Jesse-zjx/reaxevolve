#!/usr/bin/env python3
"""Diversity helpers for candidate scoring and route enumeration.

What the live path calls:
  - `tools/expand/templates_expand.py` uses `novelty`: one minus the maximum Morgan Tanimoto
    of a product against species already in the network.
  - `scripts/graph/enumerate_routes.py` uses `route_descriptor`, `niche_key`, `is_divergent`
    and `route_diversity_report`. A candidate route is dropped only when it shares at least 60%
    of its edges with an already-kept route AND sits in a niche that route already occupies.
    Either condition on its own is not enough to drop it.

`select_diverse` is a greedy batch picker: normalised quality plus a weight times the minimum
fingerprint distance to what has already been picked. Nothing in this repository calls it, and
it is not a determinantal point process and not a MAP-Elites archive. Those names are not used
here because the code does not implement them.
"""
import math
from rdkit import Chem
from rdkit.Chem import AllChem, rdMolDescriptors as rdd
from rdkit import DataStructs, RDLogger
RDLogger.DisableLog('rdApp.*')

# ---------- fingerprints / similarity ----------
_FP_CACHE = {}
def fp(smi):
    if smi in _FP_CACHE: return _FP_CACHE[smi]
    m = Chem.MolFromSmiles(smi)
    f = AllChem.GetMorganFingerprintAsBitVect(m, 2, nBits=2048) if m else None
    _FP_CACHE[smi] = f; return f

def tanimoto(a, b):
    fa, fb = fp(a), fp(b)
    return DataStructs.TanimotoSimilarity(fa, fb) if (fa and fb) else 0.0

def nC(smi):
    m = Chem.MolFromSmiles(smi)
    return sum(1 for a in m.GetAtoms() if a.GetSymbol() == 'C') if m else 0

# ---------- (1) novelty + diverse selection ----------
def novelty(smi, known):
    """1 - max Tanimoto(smi, known species). 1.0 = maximally novel vs explored set."""
    fa = fp(smi)
    if fa is None or not known: return 1.0
    best = 0.0
    for k in known:
        fk = fp(k)
        if fk: best = max(best, DataStructs.TanimotoSimilarity(fa, fk))
    return 1.0 - best

def select_diverse(cands, n, key_smi, quality_key="score", lam=1.0):
    """Greedy batch pick: argmax of normalised quality plus lam times min fingerprint distance
    to candidates already picked. Not called by the loop. `key_smi(c)` returns a product SMILES."""
    if len(cands) <= n: return list(cands)
    pool = list(cands); picked = []
    # normalise quality to [0,1] so it trades off against distance (also in [0,1])
    qs = [c.get(quality_key, 0.0) for c in pool]
    qlo, qhi = min(qs), max(qs); rng = (qhi - qlo) or 1.0
    def q(c): return (c.get(quality_key, 0.0) - qlo) / rng
    # seed with the highest-quality candidate
    first = max(pool, key=q); picked.append(first); pool.remove(first)
    while len(picked) < n and pool:
        def gain(c):
            d = min(1.0 - tanimoto(key_smi(c), key_smi(p)) for p in picked)
            return q(c) + lam * d
        best = max(pool, key=gain); picked.append(best); pool.remove(best)
    return picked

# ---------- (2) route behavioral descriptor + QD niche ----------
def route_descriptor(nodes, edges):
    """Interpretable behavioral descriptor of a whole route (for QD niching)."""
    carbons = [nC(s) for s in nodes]
    ctraj = tuple(sorted(set(carbons), reverse=True))          # e.g. (6,5) C6->C5 route
    kinds = tuple(sorted(k for k in (e.get("kind") or e.get("reaction_kind") for e in edges) if k))
    has_retro = any(carbons[i] > carbons[i+1] for i in range(len(carbons)-1))
    # does it pass through a ketose (internal C=O, "C(=O)C" not terminal O=C) intermediate?
    def is_ketose(s):
        m = Chem.MolFromSmiles(s); 
        return bool(m and m.HasSubstructMatch(Chem.MolFromSmarts('[#6][CX3](=O)[#6]')))
    ketose = any(is_ketose(s) for s in nodes)
    return {"carbon_traj": ctraj, "n_steps": len(edges), "fragmenting": has_retro,
            "via_ketose": ketose, "kind_multiset": kinds}

def niche_key(desc):
    """Coarse route shape: carbon trajectory, whether it fragments, whether it passes a ketose,
    and the set of reaction kinds. Used by enumerate_routes as a niche label, not as an archive."""
    return (desc["carbon_traj"], desc["fragmenting"], desc["via_ketose"],
            tuple(sorted(set(desc["kind_multiset"]))))

# ---------- (3) route divergence gate ----------
def edgeset(route):
    return frozenset((e["reactant"], e["product"]) for e in route["edges"])

def overlap(routeA, routeB):
    a, b = edgeset(routeA), edgeset(routeB)
    if not a or not b: return 0.0
    return len(a & b) / min(len(a), len(b))

def is_divergent(new_route, existing_routes, max_overlap=0.6):
    """Accept new_route only if it shares < max_overlap edges with EVERY existing route
    to the same target (else it is a near-duplicate, not a novel route)."""
    return all(overlap(new_route, r) < max_overlap for r in existing_routes)

def route_diversity_report(routes):
    """Pairwise mean edge-overlap and niche coverage for a set of routes to one target."""
    n = len(routes)
    if n < 2:
        niches = {niche_key(route_descriptor(r["nodes"], r["edges"])) for r in routes}
        return {"n_routes": n, "mean_pairwise_overlap": 0.0,
                "n_distinct_niches": len(niches)}
    ov = [overlap(routes[i], routes[j]) for i in range(n) for j in range(i+1, n)]
    niches = {niche_key(route_descriptor(r["nodes"], r["edges"])) for r in routes}
    return {"n_routes": n, "mean_pairwise_overlap": round(sum(ov)/len(ov), 3),
            "n_distinct_niches": len(niches)}
