#!/usr/bin/env python3
"""Extract per-path skill-evolution event timelines (HANDOVER §十).

Fields left null when not recoverable — never invented. Minimal test per path:
whether there exists update → later reuse → later step_accepted.

  python3 scripts/reflect/build_path_evolution.py
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

from rdkit import Chem, RDLogger

RDLogger.DisableLog("rdApp.*")

HERE = Path(__file__).resolve().parent
PKG = HERE.parents[1]
sys.path.insert(0, str(PKG / "tools"))
import chem_paths as CP  # noqa: E402

OUT = PKG / "evidence"

# Capability-demo paths for §4.2 case studies (HAA_R2 is a second HAA route; tracked separately).
PATHS = {
    "HMF": "glucose_hmf_review_v3",
    "HAA": "glucose_haa_review_v1",
    "FF": "glucose_ff_review_v1",
    "HAA_R2": "glucose_haa_review_v2",
}

# Assets most relevant to each path narrative (HANDOVER §十 checklist).
PATH_ASSETS = {
    "HMF": [
        ("cooperative_dehydration_scan", "constrained_scan_guess.py", "update"),
    ],
    "HAA": [
        ("beta_carbonyl_retro_aldol", "retroaldol_ts.py", "update"),
        ("water_relay_predecessor", "water_relay_guess.py", "update"),
    ],
    "FF": [
        ("water_relay_predecessor", "water_relay_guess.py", "update"),
        ("hand_indexed_proton_scan", "proton_scan.py", "update"),
        ("beta_carbonyl_retro_aldol", "retroaldol_ts.py", "update"),
        ("dry_proton_transfer", "dry_proton_guess.py", "update"),
    ],
    "HAA_R2": [
        ("beta_carbonyl_retro_aldol", "retroaldol_ts.py", "reuse"),
        ("hand_indexed_proton_scan", "proton_scan.py", "reuse"),
    ],
}


def canon(s):
    if not s:
        return s
    m = Chem.MolFromSmiles(s)
    return Chem.MolToSmiles(m, isomericSmiles=False) if m else s


def node_smiles(nodes, idx):
    n = nodes[idx]
    return canon(
        n.get("expected_smiles")
        or n.get("canonical_smiles")
        or n.get("smiles")
        or n.get("optimized_smiles")
    )


def imag_of(st):
    im = st.get("imag_cm-1", st.get("imag_cm"))
    if isinstance(im, list):
        im = im[0] if im else None
    return float(im) if im is not None else None


def load_manifest(dep):
    return json.loads((Path(CP.DEPOSITS) / dep / "06_final_chain" / "MANIFEST.json").read_text())


def iter_verdict_records():
    """(provenance, record) for every judgement.

    graph/verdicts.jsonl travels with the package; the per-run strict_cache.json files it was
    built from sit in gitignored ORCA scratch and partly in a historical run tree, so globbing for
    them makes a path's event list depend on machine state. Live caches are the fallback.
    """
    frozen = os.path.join(CP.GRAPH, "verdicts.jsonl")
    if os.path.isfile(frozen):
        with open(frozen) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                yield (rec.get("source") or {}).get("cache") or frozen, rec
        return
    seen = set()
    patterns = [
        os.path.join(CP.GRAPH, "strict_caches", "**", "strict_cache.json"),
        os.path.join(CP.VALIDATION, "**", "strict_cache.json"),
    ]
    for pat in patterns:
        for path in glob.glob(pat, recursive=True):
            real = os.path.realpath(path)
            if not os.path.isfile(path) or real in seen:
                continue
            seen.add(real)
            try:
                blob = json.load(open(path))
            except Exception:
                continue
            if isinstance(blob, dict):
                for rec in blob.values():
                    if isinstance(rec, dict):
                        yield path, rec


def load_verdict_index():
    """pair -> list of (status, time, path, note-ish)."""
    index = defaultdict(list)
    for path, rec in iter_verdict_records():
        r, p = rec.get("reactant"), rec.get("product")
        if not r or not p:
            continue
        index[(canon(r), canon(p))].append(
            {
                "status": str(rec.get("status") or "").strip(),
                "time": rec.get("time"),
                "path": path,
                "n_imag": rec.get("n_imag")
                or (
                    len(rec.get("ts_imag_all") or [])
                    if isinstance(rec.get("ts_imag_all"), list)
                    else None
                ),
                "note": rec.get("note") or rec.get("endpoint_match"),
            }
        )
    return index


def load_timeline_assets():
    assets = {}
    path = OUT / "timeline.jsonl"
    if not path.is_file():
        return assets
    for line in path.open():
        r = json.loads(line)
        if r.get("record") != "asset_event":
            continue
        assets[r["asset"]] = r
    return assets


def load_timeline_deposits():
    deps = {}
    path = OUT / "timeline.jsonl"
    if not path.is_file():
        return deps
    for line in path.open():
        r = json.loads(line)
        if r.get("record") == "deposit":
            deps[r["deposit"]] = r
    return deps


def failure_mode_guess(rec):
    st = rec["status"].upper()
    note = str(rec.get("note") or "").lower()
    if "STRICT" in st and st != "STRICT":
        pass
    if st == "STRICT":
        return None
    n_imag = rec.get("n_imag")
    if n_imag and n_imag > 1:
        return "multiple_imaginary"
    if "mismatch" in st.lower() or "mismatch" in note:
        return "no_match"
    if "zwitter" in note:
        return "zwitterion"
    if "water" in note and "spectator" in note:
        return "spectator_water"
    if "not_clean" in st.lower() or "soft" in note:
        return "no_dominant_mode"
    if "fail" in st.lower() or "irc" in st.lower():
        return "irc_or_opt_failed"
    if st and st.upper() != "STRICT":
        return st.lower()[:40]
    return "unknown"


def build_path(path_id, dep, index, assets, dep_dates):
    man = load_manifest(dep)
    nodes = man["nodes"]
    events = []

    # Bar-change disclosure for HAA
    if path_id == "HAA":
        events.append(
            {
                "path_id": path_id,
                "step_id": "step_4",
                "event_type": "bar_change",
                "date": None,
                "date_kind": "unknown",
                "failure_mode": "spectator_water",
                "what_was_tried": "water-relay tautomerization accepted under protocol v3",
                "asset_touched": "tools/.../water_relay_guess.py",
                "update_or_reuse": "none",
                "outcome": "rejected_by_protocol",
                "evidence_ptr": "evidence/BAR_HISTORY.md",
                "notes": (
                    "Accepted under water-shuttle-permitted bar; current bar rejects new "
                    "spectator-water steps. 05-31 exact-SMILES origin still unverified in transcripts."
                ),
            }
        )

    # Asset birth / revision events for this path
    for asset_key, probe, ure in PATH_ASSETS.get(path_id, []):
        a = assets.get(asset_key)
        if not a or not a.get("first_sighting_date"):
            events.append(
                {
                    "path_id": path_id,
                    "step_id": None,
                    "event_type": "asset_born",
                    "date": None,
                    "date_kind": "unknown",
                    "failure_mode": None,
                    "what_was_tried": None,
                    "asset_touched": probe,
                    "update_or_reuse": ure,
                    "outcome": None,
                    "evidence_ptr": None,
                    "notes": "asset sighting not in timeline.jsonl",
                }
            )
            continue
        events.append(
            {
                "path_id": path_id,
                "step_id": None,
                "event_type": "asset_born",
                "date": a["first_sighting_date"],
                "date_kind": "transcript_sighting",
                "failure_mode": None,
                "what_was_tried": None,
                "asset_touched": probe,
                "update_or_reuse": ure,
                "outcome": None,
                "evidence_ptr": "evidence/timeline.jsonl",
                "notes": f"bracket_turns={a.get('bracket_turns')}; session={a.get('session')}",
            }
        )

    # Per-step fails + accepts
    for st in man["steps"]:
        step_id = st.get("step")
        r = node_smiles(nodes, st["reactant_node"])
        p = node_smiles(nodes, st["product_node"])
        recs = index.get((r, p), [])
        # failures first
        for rec in sorted(recs, key=lambda x: str(x.get("time") or "")):
            if str(rec.get("status") or "").strip().upper() == "STRICT":
                continue
            events.append(
                {
                    "path_id": path_id,
                    "step_id": step_id,
                    "event_type": "attempt_fail",
                    "date": (rec.get("time") or "")[:10] or None,
                    "date_kind": "verdict" if rec.get("time") else "unknown",
                    "failure_mode": failure_mode_guess(rec),
                    "what_was_tried": None,
                    "asset_touched": None,
                    "update_or_reuse": "none",
                    "outcome": "fail",
                    "evidence_ptr": rec.get("path"),
                    "notes": str(rec.get("note") or "")[:200] or None,
                }
            )
        # acceptance
        accepted = [
            rec
            for rec in recs
            if str(rec.get("status") or "").strip().upper() == "STRICT"
        ]
        if accepted:
            accepted.sort(key=lambda x: str(x.get("time") or ""))
            rec = accepted[0]
            events.append(
                {
                    "path_id": path_id,
                    "step_id": step_id,
                    "event_type": "step_accepted",
                    "date": (rec.get("time") or "")[:10] or None,
                    "date_kind": "verdict" if rec.get("time") else "unknown",
                    "failure_mode": None,
                    "what_was_tried": None,
                    "asset_touched": None,
                    "update_or_reuse": "reuse"
                    if any(
                        e.get("update_or_reuse") == "update"
                        and e.get("date")
                        and rec.get("time")
                        and e["date"] <= (rec.get("time") or "")[:10]
                        for e in events
                    )
                    else "none",
                    "outcome": "strict_pass",
                    "evidence_ptr": rec.get("path") or f"deposits/{dep}",
                    "notes": f"imag={imag_of(st)}",
                }
            )
        else:
            # Deposit step with FINAL_STRICT_CHAIN / no cache hit — still accepted in deposit.
            dd = dep_dates.get(dep, {})
            events.append(
                {
                    "path_id": path_id,
                    "step_id": step_id,
                    "event_type": "step_accepted",
                    "date": dd.get("orca_last_run"),
                    "date_kind": "orca_start" if dd.get("orca_last_run") else "unknown",
                    "failure_mode": None,
                    "what_was_tried": None,
                    "asset_touched": None,
                    "update_or_reuse": "none",
                    "outcome": "strict_pass",
                    "evidence_ptr": f"deposits/{dep}/06_final_chain/MANIFEST.json",
                    "notes": "no STRICT cache row for this pair; dated from deposit ORCA window",
                }
            )

    # deposit packaged
    dd = dep_dates.get(dep, {})
    events.append(
        {
            "path_id": path_id,
            "step_id": None,
            "event_type": "deposit_packaged",
            "date": dd.get("orca_last_run"),
            "date_kind": "orca_start" if dd.get("orca_last_run") else "unknown",
            "failure_mode": None,
            "what_was_tried": None,
            "asset_touched": None,
            "update_or_reuse": "none",
            "outcome": None,
            "evidence_ptr": f"deposits/{dep}",
            "notes": dd.get("note"),
        }
    )

    # Mark reuse on steps that follow an update of a path-relevant asset
    update_dates = sorted(
        e["date"]
        for e in events
        if e.get("update_or_reuse") == "update" and e.get("date")
    )
    if update_dates:
        first_update = update_dates[0]
        for e in events:
            if (
                e["event_type"] == "step_accepted"
                and e.get("date")
                and e["date"] >= first_update
                and e.get("update_or_reuse") == "none"
            ):
                # Only mark reuse when a typed asset for this path exists before the step
                e["update_or_reuse"] = "reuse"
                e["notes"] = (
                    (e.get("notes") or "")
                    + f"; reuse_after_asset_update>={first_update}"
                ).strip("; ")

    events.sort(key=lambda e: (e.get("date") or "9999", e.get("event_type") or ""))
    return events


def minimal_check(events):
    """True iff some update is followed later by reuse, then by step_accepted."""
    updates = [e for e in events if e.get("update_or_reuse") == "update" and e.get("date")]
    if not updates:
        return False, "no dated update event"
    for u in updates:
        reuses = [
            e
            for e in events
            if e.get("update_or_reuse") == "reuse"
            and e.get("date")
            and e["date"] >= u["date"]
        ]
        for r in reuses:
            accepts = [
                e
                for e in events
                if e.get("event_type") == "step_accepted"
                and e.get("date")
                and e["date"] >= r["date"]
            ]
            if accepts:
                return True, f"update@{u['date']} → reuse@{r['date']} → accept@{accepts[0]['date']}"
    return False, "no update→reuse→accepted chain"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=OUT)
    a = ap.parse_args()
    a.out_dir.mkdir(parents=True, exist_ok=True)

    index = load_verdict_index()
    assets = load_timeline_assets()
    dep_dates = load_timeline_deposits()

    summary = ["# Path evolution summaries", "", "Generated by `scripts/reflect/build_path_evolution.py`.", ""]
    all_ok = {}

    for path_id, dep in PATHS.items():
        events = build_path(path_id, dep, index, assets, dep_dates)
        out = a.out_dir / f"path_evolution_{path_id.lower()}.jsonl"
        with out.open("w") as f:
            for e in events:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        ok, why = minimal_check(events)
        all_ok[path_id] = (ok, why)
        n_fail = sum(1 for e in events if e["event_type"] == "attempt_fail")
        n_acc = sum(1 for e in events if e["event_type"] == "step_accepted")
        n_asset = sum(1 for e in events if e["event_type"] == "asset_born")
        summary += [
            f"## {path_id} (`{dep}`)",
            "",
            f"- Events: {len(events)} (fails={n_fail}, accepts={n_acc}, asset_born={n_asset})",
            f"- Minimal update→reuse→accepted: **{'PASS' if ok else 'FAIL'}** — {why}",
            f"- File: `{out.name}`",
            "",
        ]
        if not ok:
            summary.append(
                "Per HANDOVER §十 / outline §4.2: this path is capability demonstration only; "
                "do not call it a skill-evolution case study unless more events are recovered.\n"
            )
        print(f"{path_id}: {len(events)} events; minimal_check={'PASS' if ok else 'FAIL'} ({why})")
        print(f"  wrote {out}")

    sum_path = a.out_dir / "PATH_EVOLUTION.md"
    sum_path.write_text("\n".join(summary) + "\n")
    print(f"wrote {sum_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
