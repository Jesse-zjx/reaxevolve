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


def is_eval_arm_cache(path: str) -> bool:
    return CP.is_eval_arm_cache(path)


def collect_caches():
    patterns = [
        os.path.join(CP.RUNS, "**", "strict_cache.json"),
        os.path.join(CP.GRAPH_ROOT, "caches", "**", "strict_cache.json"),
        os.path.join(OUT, "strict_cache.json"),
    ]
    out = {}
    for pat in patterns:
        for path in glob.glob(pat, recursive=True):
            if is_eval_arm_cache(path):
                continue
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


def _has_attempt_identity(rec: dict) -> bool:
    """Live evidence that can be told apart from a geometry-less record."""
    fp = rec.get("input_fingerprint")
    if isinstance(fp, dict) and fp:
        return True
    if isinstance(fp, str) and fp:
        return True
    return bool(rec.get("invocation_id"))


def cache_identity_fields(rec: dict) -> dict:
    """Fields a cache row must keep on the graph edge for later readjudication."""
    return {
        "input_fingerprint": rec.get("input_fingerprint"),
        "attempt_time": rec.get("time"),
        "invocation_id": rec.get("invocation_id"),
        "name": rec.get("name"),
    }


_BINDS_PATH = os.path.join(_PKG, "evidence", "audit", "provisional_binds.json")
_PROVISIONAL_BINDS = None


def load_provisional_binds(path=None) -> dict:
    """Map `reactant>>product` to the cache attempt a provisional row judged."""
    raw = load_json(path or _BINDS_PATH, {})
    rows = raw.get("binds") if isinstance(raw, dict) else None
    if rows is None and isinstance(raw, dict):
        rows = [v for k, v in raw.items() if isinstance(v, dict) and k != "purpose"]
    out = {}
    for v in rows or []:
        if not isinstance(v, dict):
            continue
        r, p = canon(v.get("reactant")), canon(v.get("product"))
        if not r or not p:
            continue
        out[f"{r}>>{p}"] = v
    return out


def provisional_binds() -> dict:
    global _PROVISIONAL_BINDS
    if _PROVISIONAL_BINDS is None:
        _PROVISIONAL_BINDS = load_provisional_binds()
    return _PROVISIONAL_BINDS


def _cache_paths_match(a, b) -> bool:
    """True when two cache paths name the same artifact, including isolated clones."""
    if not a or not b:
        return False
    na = os.path.normpath(str(a)).replace("\\", "/")
    nb = os.path.normpath(str(b)).replace("\\", "/")
    if na == nb:
        return True
    if os.path.realpath(na) == os.path.realpath(nb):
        return True
    def tail(s: str) -> str:
        for marker in ("/graph/caches/", "/graph/strict_caches/"):
            i = s.find(marker)
            if i >= 0:
                return s[i + 1 :]
        return s.lstrip("./")
    ta, tb = tail(na), tail(nb)
    if ta == tb:
        return True
    return na.endswith(nb) or nb.endswith(na)


def _bound_attempt(rec: dict) -> dict:
    """The attempt a pair-level judgement actually covered."""
    bound = {
        "cache_path": rec.get("cache") or rec.get("cache_path"),
        "time": str(rec.get("time") or rec.get("demoted_at") or ""),
        "invocation_id": rec.get("invocation_id"),
        "input_fingerprint": rec.get("input_fingerprint"),
        "name": rec.get("name"),
    }
    if bound["cache_path"] or bound["time"] or bound["invocation_id"] or bound["input_fingerprint"]:
        return bound
    r, p = canon(rec.get("reactant")), canon(rec.get("product"))
    if not r or not p:
        return bound
    extra = provisional_binds().get(f"{r}>>{p}") or {}
    return {
        "cache_path": extra.get("cache_path"),
        "time": str(extra.get("time") or ""),
        "invocation_id": extra.get("invocation_id"),
        "input_fingerprint": extra.get("input_fingerprint"),
        "name": extra.get("name"),
    }


def _same_bound_attempt(edge: dict, bound: dict) -> bool:
    """True when the live row is still the attempt the judgement named.

    A reusable workdir and task name are not attempt identity. The writer
    keeps prior rows under ``attempts`` and writes a later retry as the
    latest row in the same cache; that retry has a new time (and usually a
    new fingerprint / invocation id). Path+name without that original time
    is not the bound attempt.
    """
    if bound.get("invocation_id") and edge.get("invocation_id"):
        return str(edge["invocation_id"]) == str(bound["invocation_id"])
    if bound.get("input_fingerprint") and edge.get("input_fingerprint"):
        return edge.get("input_fingerprint") == bound.get("input_fingerprint")
    path_match = _cache_paths_match(edge.get("cache_path"), bound.get("cache_path"))
    time_match = bool(bound.get("time") and str(edge.get("attempt_time") or "") == str(bound["time"]))
    name_match = bool(bound.get("name") and edge.get("name") == bound["name"])
    if path_match and time_match:
        return True
    if time_match and name_match:
        return True
    if path_match and not bound.get("time") and not str(edge.get("attempt_time") or ""):
        return True
    return False


def _supersedes_bound(edge: dict, bound: dict) -> bool:
    """True when the live row is a different attempt than the one judged.

    Presence of an invocation id, or a similar imaginary frequency, is not
    enough. The live row must be another cache file, a fingerprint the
    bound attempt did not have, or a later launch in the same file (new
    time plus an identity the bound row never had). An explicit
    ``supersedes`` pointer also names the replaced evidence.
    """
    if _same_bound_attempt(edge, bound):
        return False
    if edge.get("supersedes") and bound.get("cache_path"):
        if _cache_paths_match(edge.get("supersedes"), bound["cache_path"]):
            return True
        if bound.get("name") and edge.get("supersedes") == bound["name"]:
            return True
    edge_cache = edge.get("cache_path")
    bound_cache = bound.get("cache_path")
    if edge_cache and bound_cache and not _cache_paths_match(edge_cache, bound_cache):
        return True
    edge_fp = edge.get("input_fingerprint")
    has_fp = (isinstance(edge_fp, dict) and bool(edge_fp)) or (isinstance(edge_fp, str) and bool(edge_fp))
    bound_fp = bound.get("input_fingerprint")
    if has_fp and (not bound_fp or edge_fp != bound_fp):
        return True
    edge_time = str(edge.get("attempt_time") or "")
    if bound.get("time") and edge_time and edge_time != str(bound["time"]):
        if edge.get("invocation_id") and edge.get("invocation_id") != bound.get("invocation_id"):
            return True
    return False


def _newer_qualifying_attempt(edge: dict, rec: dict, ledger_path: str) -> bool:
    """True when the live cache is a later successful attempt than this demotion.

    Historical demotions key only on the reaction pair, so a later STRICT
    repair of the same pair used to inherit the old reject. Geometry-less
    provisional rows are bound to one cache attempt; they still demote that
    attempt, including after identity fields are pasted onto it. A later
    retry in the same cache (new time plus fingerprint or invocation) is a
    different attempt, as is another cache file. Invocation id or imaginary
    frequency alone is not attempt identity.
    """
    before = edge.get("status")
    if rank(before) < rank("STRICT"):
        return False
    rec_fp = rec.get("input_fingerprint")
    rec_cache = rec.get("cache") or rec.get("cache_path")
    rec_time = str(rec.get("time") or rec.get("demoted_at") or "")
    if rec.get("provisional") and not (rec_fp or rec_cache or rec_time):
        return _supersedes_bound(edge, _bound_attempt(rec))
    edge_fp = edge.get("input_fingerprint")
    if rec_fp and edge_fp and rec_fp != edge_fp:
        return True
    edge_cache = edge.get("cache_path")
    if rec_cache and edge_cache and not _cache_paths_match(edge_cache, rec_cache):
        return True
    edge_time = str(edge.get("attempt_time") or "")
    if rec_time and edge_time and edge_time > rec_time:
        return True
    return False


def apply_readjudication(net, ledgers=None) -> dict:
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
      evidence/audit/provisional_binds.json      which attempt a provisional row judged
    """
    if ledgers is None:
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
            # A geometry-less provisional audit is not an accepted edge.
            if rec.get("provisional") and new_status == "STRICT":
                new_status = "unresolved"
            i = eid(r, p)
            e = edges.get(i)
            if e is None:
                unmatched.append({"ledger": kind, "edge": f"{r}>>{p}"})
                continue
            before = e.get("status")
            # Pair-level ledger rows, including a geometry-less provisional, must
            # not cover a later independent qualifying attempt on the same pair.
            if rank(new_status) < rank(before) and _newer_qualifying_attempt(e, rec, path):
                continue
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
            **cache_identity_fields(rec),
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
