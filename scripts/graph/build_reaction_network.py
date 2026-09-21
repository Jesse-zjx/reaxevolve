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
import re
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

# Precedence when two attempt records exist for one (reactant, product): the stronger
# judgement wins, which implements the aggregation rule "if any attempt qualified under the
# current acceptance version, the edge is STRICT; else evidence_ok; else rejected; else
# unresolved". Every status a driver can emit is listed, because an unlisted one used to fall
# to a sentinel below `failed` — so a QM-seen negative lost to a bare crash and the graph kept
# the less informative record.
STATUS_RANK = {
    "STRICT": 6,
    # QM-backed positive signal short of delivery grade.
    "evidence_ok": 5,
    "validated": 5,
    "qm_real": 4,
    # Scientific negatives: the calculation ran and said no. More informative than a
    # non-result, so they outrank it.
    "rejected": 3,
    "MISMATCH": 3,
    "PARTIAL_MATCH": 3,
    "pruned_endothermic": 3,
    # Ran, but reached no verdict: incomplete rather than negative.
    "unresolved": 2,
    "NOT_CLEAN_TS": 2,
    "no_strict": 2,
    "TS_FAILED": 2,
    "WALL_TIME": 1,
    # Never produced a usable record.
    "failed": 1,
    # Explore output only; no attempt yet.
    "proposed": 0,
}
_UNKNOWN_STATUS_RANK = 1  # treat like a non-result, not like something below one


def rank(status) -> int:
    """Precedence of a status, with any free text stripped off first.

    Some drivers appended detail to the status (`NOT_CLEAN_TS (imag modes=[...])`), which made
    every such record a distinct unlisted value.
    """
    token, _detail = split_status(status)
    return STATUS_RANK.get(token, _UNKNOWN_STATUS_RANK)


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


_STATUS_WITH_DETAIL = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\((.+)\)\s*$")


def split_status(raw):
    """Separate a status token from free text some drivers appended to it.

    Several older cache entries carry the observed imaginary modes inside the status
    string, e.g. `NOT_CLEAN_TS (imag modes=[-248.0])`. That turns one status into as many
    distinct values as there were runs, so any per-status count becomes unreadable. The
    token and the detail are separated here; the status vocabulary is not remapped and no
    judgement is changed — `graph_views.bucket()` remains the only place that reduces a
    status to the documented four.
    """
    s = (raw or "").strip()
    m = _STATUS_WITH_DETAIL.match(s)
    if not m:
        return s or "unresolved", None
    return m.group(1), m.group(2).strip()


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
                if prev is None or rank(v.get("status")) >= rank(prev.get("status")):
                    vv = dict(v)
                    vv["_cache_path"] = path
                    out[k] = vv
    return out


def apply_readjudication(net) -> dict:
    """Overlay recorded re-adjudications on top of the merged cache evidence.

    A `strict_cache.json` entry is raw evidence: what one driver run observed. A
    re-adjudication is a judgement made later, under a named acceptance version, over
    that evidence. Judgements outrank raw evidence, so they are applied last.

    Without this step the rebuild silently re-promotes every edge a later audit demoted:
    the audit rewrote the network and the pin but not the caches, so merging caches alone
    reports the pre-audit count. The original cache entry is preserved untouched and the
    edge records both what was observed and what was decided.

    Reads (append-only, never rewritten here):
      evidence/audit/readjudication.jsonl        kept   -> new_status
      evidence/audit/demoted_from_pin_v5.jsonl   demoted -> new_status + reason
    """
    ledgers = [
        ("readjudication", os.path.join(_PKG, "evidence", "audit", "readjudication.jsonl")),
        ("demotion", os.path.join(_PKG, "evidence", "audit", "demoted_from_pin_v5.jsonl")),
    ]
    edges = net.get("edges") or {}
    applied, unmatched = [], []
    for kind, path in ledgers:
        if not os.path.isfile(path):
            continue
        for line in open(path):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            new_status = rec.get("new_status")
            r, p = canon(rec.get("reactant")), canon(rec.get("product"))
            if not new_status or not r or not p:
                continue
            i = eid(r, p)
            e = edges.get(i)
            if e is None:
                unmatched.append({"ledger": kind, "edge": f"{r}>>{p}"})
                continue
            before = e.get("status")
            e["status"] = new_status
            e["readjudication"] = {
                "ledger": kind,
                "strict_version": rec.get("strict_version") or "v5",
                "status_from_cache": before,
                "new_status": new_status,
                "judgement_source": rec.get("judgement_source"),
                "reason": rec.get("reason") or rec.get("notes"),
            }
            if before != new_status:
                applied.append({"edge": f"{r}>>{p}", "from": before, "to": new_status})
    return {
        "n_records_applied": len(applied),
        "n_status_changes": len(applied),
        "n_unmatched": len(unmatched),
        "changes": applied,
        "unmatched": unmatched,
    }


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
        st, st_detail = split_status(rec.get("status"))
        prev = edges.get(i)
        if prev and rank(prev.get("status")) > rank(st):
            continue
        detail = rec.get("detail") or st_detail
        edges[i] = {
            "id": i,
            "reactant": r,
            "product": p,
            "reactant_id": nid(r),
            "product_id": nid(p),
            "coproduct": rec.get("coproduct"),
            "kind": rec.get("kind") or (prev or {}).get("kind") or "unknown",
            "status": st,
            "detail": detail,
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

    # Judgements last: raw cache evidence first, then any recorded re-adjudication of it.
    readj = apply_readjudication(net)

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
    net["meta"]["readjudication_applied"] = {
        "status_changes": readj["n_status_changes"],
        "unmatched": readj["n_unmatched"],
        "ledgers": ["evidence/audit/readjudication.jsonl", "evidence/audit/demoted_from_pin_v5.jsonl"],
    }

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
        "readjudication": {
            "status_changes": readj["n_status_changes"],
            "unmatched": readj["n_unmatched"],
        },
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
