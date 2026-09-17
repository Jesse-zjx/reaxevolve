#!/usr/bin/env python3
"""Unique write entry for Explore hypotheses in reaxevolve.

No template expander is provided. Every intermediate the LLM proposes must land
here before Validate can pick it up.

Usage:
  python scripts/graph/add_hypothesis.py \\
    --reactant "OCC1OC(O)C(O)C(O)C1O" \\
    --product "O=CC(O)C(O)C(O)C(O)CO" \\
    --kind ring_opening \\
    --mechanism "pyranose ring open to aldose" \\
    [--coproduct O] [--source explore_llm] [--priority 0.5]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from typing import Any

_PKG = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_PKG, "scripts", "lib"))
import chem_paths as CP  # noqa: E402

CP.bootstrap()

try:
    from rdkit import Chem
except ImportError:  # pragma: no cover
    Chem = None

sys.path.insert(0, os.path.join(_PKG, "loop"))
try:
    import mass_balance as MB
except ImportError:  # pragma: no cover
    MB = None


def canon(smi: str) -> str | None:
    if not smi:
        return None
    if Chem is None:
        return smi
    m = Chem.MolFromSmiles(smi)
    if m is None:
        return None
    Chem.RemoveStereochemistry(m)
    return Chem.MolToSmiles(m)


def node_id(smi: str) -> str:
    return "N_" + hashlib.sha1(smi.encode()).hexdigest()[:12]


def edge_id(r: str, p: str) -> str:
    return "E_" + hashlib.sha1(f"{r}>>{p}".encode()).hexdigest()[:12]


def hyp_id(r: str, p: str, kind: str, mech: str) -> str:
    raw = f"{r}|{p}|{kind}|{mech}"
    return "H_" + hashlib.sha1(raw.encode()).hexdigest()[:12]


def load_net(path: str) -> dict[str, Any]:
    if os.path.isfile(path):
        return json.load(open(path))
    return {
        "version": "reaxevolve-v1",
        "nodes": {},
        "edges": {},
        "hypotheses": {},
        "meta": {},
    }


def ensure_node(net: dict, smi: str, role: str = "intermediate") -> str:
    nid = node_id(smi)
    nodes = net.setdefault("nodes", {})
    if nid not in nodes:
        nodes[nid] = {
            "id": nid,
            "smiles": smi,
            "role": role,
            "source": "hypothesis",
            "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    return nid


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reactant", required=True)
    ap.add_argument("--product", required=True)
    ap.add_argument("--kind", default="unknown")
    ap.add_argument("--mechanism", default="")
    ap.add_argument("--coproduct", default=None)
    ap.add_argument("--source", default="explore_llm")
    ap.add_argument("--priority", type=float, default=0.5)
    ap.add_argument(
        "--network",
        default=os.path.join(CP.GRAPH, "reaction_network.json"),
    )
    ap.add_argument(
        "--queue",
        default=os.path.join(CP.GRAPH_ROOT, "caches", "candidate_queue.json"),
    )
    ap.add_argument(
        "--allow-unbalanced",
        action="store_true",
        help="bypass the atom-conservation gate (diagnostics only)",
    )
    a = ap.parse_args()

    r = canon(a.reactant)
    p = canon(a.product)
    if not r or not p:
        print(json.dumps({"ok": False, "error": "invalid_smiles", "reactant": a.reactant, "product": a.product}))
        return 2
    if r == p:
        print(json.dumps({"ok": False, "error": "identity_edge", "smiles": r}))
        return 2

    # Atom conservation. A step that does not balance cannot have an IRC connecting the
    # stated endpoints, so admitting it only buys wasted QM. Segment-4 lost roughly half
    # its budget this way. The delta is returned so the caller can repair its SMILES.
    coproduct = a.coproduct
    if MB is not None and not a.allow_unbalanced:
        bal = MB.check(r, p, coproduct)
        if not bal["ok"]:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": "mass_unbalanced",
                        "verdict": bal["verdict"],
                        "delta_reactant_minus_products": bal["delta"],
                        "reactant": r,
                        "product": p,
                        "coproduct": coproduct,
                        "hint": "reactant atoms must equal product + coproduct; a single "
                        "dehydration loses exactly one H2O (O-1, H-2)",
                    }
                )
            )
            return 3
        # the model routinely omits the water it just eliminated
        coproduct = bal.get("coproduct") or coproduct

    net = load_net(a.network)
    rid = ensure_node(net, r, role="seed_or_intermediate")
    pid = ensure_node(net, p, role="intermediate")
    eid = edge_id(r, p)
    hid = hyp_id(r, p, a.kind, a.mechanism)

    edges = net.setdefault("edges", {})
    if eid not in edges:
        edges[eid] = {
            "id": eid,
            "reactant": r,
            "product": p,
            "reactant_id": rid,
            "product_id": pid,
            "coproduct": coproduct,
            "kind": a.kind,
            "status": "proposed",
            "source": a.source,
            "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    hyps = net.setdefault("hypotheses", {})
    created = hid not in hyps
    hyps[hid] = {
        "id": hid,
        "edge_id": eid,
        "reactant": r,
        "product": p,
        "coproduct": coproduct,
        "kind": a.kind,
        "mechanism": a.mechanism,
        "source": a.source,
        "priority": a.priority,
        "status": "pending",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    os.makedirs(os.path.dirname(a.network), exist_ok=True)
    json.dump(net, open(a.network, "w"), indent=2, ensure_ascii=False)
    open(a.network, "a").write("\n")

    # Maintain a flat candidate queue for Validate
    os.makedirs(os.path.dirname(a.queue), exist_ok=True)
    queue = []
    if os.path.isfile(a.queue):
        try:
            queue = json.load(open(a.queue))
            if isinstance(queue, dict):
                queue = queue.get("candidates") or queue.get("queue") or []
        except json.JSONDecodeError:
            queue = []
    key = f"{r}>>{p}"
    existing = {f"{c.get('reactant')}>>{c.get('product')}" for c in queue}
    if key not in existing:
        queue.append(
            {
                "reactant": r,
                "product": p,
                "coproduct": coproduct,
                "kind": a.kind,
                "mechanism": a.mechanism,
                "hypothesis_id": hid,
                "edge_id": eid,
                "priority": a.priority,
                "status": "pending",
                "source": a.source,
            }
        )
        queue.sort(key=lambda c: -float(c.get("priority") or 0))
        json.dump({"candidates": queue, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                  open(a.queue, "w"), indent=2, ensure_ascii=False)
        open(a.queue, "a").write("\n")

    # Timeline breadcrumb — only for the canonical network, so smoke tests and
    # scratch runs pointed at a temp --network do not write campaign history.
    canonical_net = os.path.realpath(os.path.join(CP.GRAPH, "reaction_network.json"))
    if os.path.realpath(a.network) != canonical_net:
        print(
            json.dumps(
                {
                    "ok": True,
                    "created": created,
                    "hypothesis_id": hid,
                    "edge_id": eid,
                    "reactant": r,
                    "product": p,
                    "network": a.network,
                    "queue": a.queue,
                    "timeline": "skipped (non-canonical network)",
                },
                indent=2,
            )
        )
        return 0

    tl = os.path.join(_PKG, "evidence", "state", "timeline.jsonl")
    os.makedirs(os.path.dirname(tl), exist_ok=True)
    with open(tl, "a") as f:
        f.write(
            json.dumps(
                {
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "event": "hypothesis_added" if created else "hypothesis_refreshed",
                    "hypothesis_id": hid,
                    "edge_id": eid,
                    "reactant": r,
                    "product": p,
                    "kind": a.kind,
                },
                ensure_ascii=False,
            )
            + "\n"
        )

    print(
        json.dumps(
            {
                "ok": True,
                "created": created,
                "hypothesis_id": hid,
                "edge_id": eid,
                "reactant": r,
                "product": p,
                "network": a.network,
                "queue": a.queue,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
