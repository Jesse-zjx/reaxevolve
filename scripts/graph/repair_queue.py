#!/usr/bin/env python3
"""Build / apply the post-v5 repair queue for pinned edges that failed re-adjudication.

Default: write evidence/audit/REPAIR_QUEUE.md + repair_queue.jsonl from READJUDICATION.
With --apply-demote: demote irreparable edges from pin + network STRICT projection
(keep attempt provenance; never overwrite without note).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

PKG = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PKG, "scripts", "lib"))
import chem_paths as CP  # noqa: E402

READJ = os.path.join(PKG, "evidence", "audit", "readjudication.jsonl")
OUT_JL = os.path.join(PKG, "evidence", "audit", "repair_queue.jsonl")
OUT_MD = os.path.join(PKG, "evidence", "audit", "REPAIR_QUEUE.md")
PIN = os.path.join(CP.GRAPH_ROOT, "canonical", "audited_strict_edges.json")
NET = os.path.join(CP.GRAPH_ROOT, "canonical", "reaction_network.json")


def load_rows():
    return [json.loads(l) for l in open(READJ) if l.strip()]


def classify(r):
    if r.get("pass") is True and not r.get("provisional"):
        return None
    if r.get("pass") is True and r.get("provisional"):
        return {
            "action": "verify_geometry",
            "reason": "provisional keep from record; locate final .out/.xyz",
        }
    if r.get("single_imag") is False:
        return {
            "action": "soft_mode_cleanup_or_reopt",
            "reason": f"multi-imag {r.get('imag')}",
        }
    if r.get("endpoints_ok") is False:
        return {
            "action": "reguess_optts_irc",
            "reason": "endpoint mismatch under v5",
        }
    if r.get("water_ok") is False:
        return {
            "action": "demote_rejected",
            "reason": f"spectator water: {r.get('water_detail')}",
        }
    if r.get("pass") is None:
        return {
            "action": "locate_artifacts_or_reopt",
            "reason": "missing final geometry for hard re-adjudication",
        }
    return {"action": "investigate", "reason": "; ".join(r.get("notes") or [])}


def build():
    rows = load_rows()
    queue = []
    for r in rows:
        c = classify(r)
        if not c:
            continue
        queue.append(
            {
                "edge": r.get("edge"),
                "reactant": r.get("reactant"),
                "product": r.get("product"),
                "in_chain": r.get("in_chain"),
                "prior_new_status": r.get("new_status"),
                "imag": r.get("imag"),
                "judgement_source": r.get("judgement_source"),
                **c,
            }
        )
    with open(OUT_JL, "w") as f:
        for q in queue:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")
    lines = [
        "# REPAIR_QUEUE (post STRICT v5 readjudication)",
        "",
        f"Items: **{len(queue)}**",
        "",
        "| edge | action | reason |",
        "|---|---|---|",
    ]
    for q in queue:
        lines.append(
            f"| `{(q.get('edge') or '')[:70]}` | {q['action']} | {q.get('reason','')[:90]} |"
        )
    lines += [
        "",
        "## Policy",
        "- Try soft-mode cleanup / re-guess OptTS+NumFreq+IRC before demotion.",
        "- If irreparable: demote from STRICT pin + network projection to "
        "`evidence_ok` or `rejected`; keep attempt provenance.",
        "- Do not overwrite attempt records without a provenance note.",
        "",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]
    open(OUT_MD, "w").write("\n".join(lines))
    print(f"wrote {OUT_MD} ({len(queue)} items)")
    return queue


def demote(queue, dry_run=True):
    """Demote edges marked demote_rejected or still failing after repair attempts.

    This pass only demotes water_ok=False / explicit demote_rejected actions.
    Other actions stay on the queue for human/agent repair.
    """
    pin = json.load(open(PIN))
    edges = pin.get("edges") or []
    demote_keys = {
        q["edge"]
        for q in queue
        if q.get("action") == "demote_rejected" and q.get("edge")
    }
    if not demote_keys:
        print("no demote_rejected items")
        return
    kept = []
    removed = []
    for e in edges:
        key = e.get("edge") or f"{e.get('reactant')}>>{e.get('product')}"
        if key in demote_keys:
            removed.append(key)
        else:
            kept.append(e)
    print(f"demote candidates: {len(removed)}")
    for k in removed:
        print(" ", k)
    if dry_run:
        print("dry-run: pin not modified")
        return
    pin["edges"] = kept
    pin["n_strict"] = len(kept)
    pin["pinned_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    pin["demoted_v5"] = removed
    json.dump(pin, open(PIN, "w"), indent=2)
    # Network status demotion
    if os.path.isfile(NET):
        net = json.load(open(NET))
        for e in net.get("edges") or []:
            key = e.get("id") or e.get("edge") or f"{e.get('reactant')}>>{e.get('product')}"
            if key in demote_keys and (e.get("status") == "STRICT" or str(e.get("status","")).startswith("STRICT")):
                e["status"] = "rejected"
                e["detail"] = "demoted after STRICT(v5) spectator-water fail"
                e["strict_version"] = "v5"
        json.dump(net, open(NET, "w"), indent=2)
    open(os.path.join(PKG, "evidence", "audit", "DEMOTE_LOG.md"), "w").write(
        "# Demotions under STRICT(v5)\n\n" + "\n".join(f"- `{k}`" for k in removed) + "\n"
    )
    print("pin + network updated")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply-demote", action="store_true")
    ap.add_argument("--force", action="store_true", help="with --apply-demote, actually write")
    a = ap.parse_args()
    queue = build()
    if a.apply_demote:
        demote(queue, dry_run=not a.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
