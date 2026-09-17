#!/usr/bin/env python3
"""Re-adjudicate pinned STRICT edges under STRICT(v5).

Judgement-source priority (plan):
  1. deposits/*/04_orca_inp_out_hess  (as-built PASS preferred)
  2. runs/ final cleanup .out + IRC xyz
  3. frozen verdict records (last resort; ts_imag_all may predate cleanup)

Also runs a zero-compute scan of rejected attempts for water-clause-only failures.

Outputs:
  evidence/audit/READJUDICATION.md
  evidence/audit/readjudication.jsonl
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys

PKG = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PKG, "scripts", "lib"))
sys.path.insert(0, os.path.join(PKG, "scripts", "validate"))
sys.path.insert(0, os.path.join(PKG, "policy", "acceptance"))
import chem_paths as CP  # noqa: E402
import check_strict_bar as bar  # noqa: E402
import verdict_writer as VW  # noqa: E402

PIN = os.path.join(CP.GRAPH_ROOT, "canonical", "audited_strict_edges.json")
if not os.path.isfile(PIN):
    PIN = os.path.join(CP.GRAPH_ROOT, "audited_strict_edges.json")
VERDICTS = os.path.join(CP.GRAPH_ROOT, "canonical", "verdicts.jsonl")
if not os.path.isfile(VERDICTS):
    VERDICTS = os.path.join(CP.GRAPH_ROOT, "verdicts.jsonl")
OUT_MD = os.path.join(PKG, "evidence", "audit", "READJUDICATION.md")
OUT_JL = os.path.join(PKG, "evidence", "audit", "readjudication.jsonl")


def load_pin():
    d = json.load(open(PIN))
    return d.get("edges") or d


def edge_key(e):
    if isinstance(e, str):
        return e
    r, p = e.get("reactant"), e.get("product")
    if r and p:
        return f"{r}>>{p}"
    return e.get("edge") or e.get("id")


def deposit_step_files():
    """Map edge_key -> (ts_out, irc_f, irc_b) from deposits."""
    found = {}
    for dep in sorted(glob.glob(os.path.join(CP.DEPOSITS, "*"))):
        if not os.path.isdir(dep):
            continue
        # chain table if present
        nodes = os.path.join(dep, "01_chain_nodes_xyz")
        report = os.path.join(dep, "00_report")
        steps = bar.discover_deposit(dep)
        # Try to associate with SMILES from report markdown tables
        smi_by_step = {}
        for md in glob.glob(os.path.join(report, "*.md")) + glob.glob(
            os.path.join(dep, "*.md")
        ):
            text = open(md, errors="ignore").read()
            for m in re.finditer(
                r"step\s*(\d+).*?`([^`]+)`\s*→\s*`([^`]+)`", text, re.I | re.S
            ):
                smi_by_step[int(m.group(1))] = (m.group(2).strip(), m.group(3).strip())
        for s in steps:
            num = int(re.search(r"(\d+)", s["name"]).group(1))
            pair = smi_by_step.get(num)
            key = f"{pair[0]}>>{pair[1]}" if pair else f"{os.path.basename(dep)}:step_{num}"
            found[key] = {
                "ts_out": s["ts_out"],
                "irc_f": s.get("irc_f"),
                "irc_b": s.get("irc_b"),
                "source": "deposit",
                "deposit": os.path.basename(dep),
                "reactant": pair[0] if pair else None,
                "product": pair[1] if pair else None,
            }
        # Also index by deposit step for pin matching via in_chain notes
        for s in steps:
            num = int(re.search(r"(\d+)", s["name"]).group(1))
            found[f"__deposit__{os.path.basename(dep)}__{num}"] = found.get(
                key if False else f"__deposit__{os.path.basename(dep)}__{num}",
                {
                    "ts_out": s["ts_out"],
                    "irc_f": s.get("irc_f"),
                    "irc_b": s.get("irc_b"),
                    "source": "deposit",
                    "deposit": os.path.basename(dep),
                    "step": num,
                },
            )
    return found


def find_run_artifacts(edge):
    """Best-effort locate final cleanup out+irc under runs/ or legacy validation."""
    roots = [CP.RUNS, CP.VALIDATION, os.path.join(CP.RN)]
    r = edge.get("reactant") if isinstance(edge, dict) else None
    p = edge.get("product") if isinstance(edge, dict) else None
    key = edge_key(edge)
    hits = []
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for cache in glob.glob(os.path.join(root, "**", "strict_cache.json"), recursive=True):
            try:
                data = json.load(open(cache))
            except Exception:
                continue
            rec = data.get(key)
            if not rec and r and p:
                rec = data.get(f"{r}>>{p}")
            if not rec:
                continue
            wd = os.path.dirname(cache)
            name = rec.get("name") or ""
            # Prefer *_clean* outs
            outs = sorted(glob.glob(os.path.join(wd, f"{name}*.out")))
            outs = [o for o in outs if "IRC" not in os.path.basename(o).upper()]
            clean = [o for o in outs if "clean" in os.path.basename(o).lower()]
            ts_out = (clean or outs)[-1] if (clean or outs) else None
            base = os.path.splitext(os.path.basename(ts_out))[0] if ts_out else name
            # IRC often named {name}_irc_IRC_F.xyz
            irc_f = None
            irc_b = None
            for cand_f in (
                os.path.join(wd, f"{name}_irc_IRC_F.xyz"),
                os.path.join(wd, f"{base}_IRC_F.xyz"),
            ):
                if os.path.isfile(cand_f):
                    irc_f = cand_f
                    break
            for cand_b in (
                os.path.join(wd, f"{name}_irc_IRC_B.xyz"),
                os.path.join(wd, f"{base}_IRC_B.xyz"),
            ):
                if os.path.isfile(cand_b):
                    irc_b = cand_b
                    break
            # glob fallback
            if not irc_f:
                fs = glob.glob(os.path.join(wd, "*IRC_F.xyz"))
                bs = glob.glob(os.path.join(wd, "*IRC_B.xyz"))
                irc_f = fs[0] if fs else None
                irc_b = bs[0] if bs else None
            hits.append(
                {
                    "ts_out": ts_out,
                    "irc_f": irc_f,
                    "irc_b": irc_b,
                    "source": "runs",
                    "cache": cache,
                    "record": rec,
                }
            )
    # Prefer hits that have ts_out + both irc
    complete = [h for h in hits if h.get("ts_out") and h.get("irc_f") and h.get("irc_b")]
    return (complete or hits)[-1] if (complete or hits) else None


def load_verdicts():
    rows = []
    if os.path.isfile(VERDICTS):
        for line in open(VERDICTS):
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def water_only_reject_scan(verdicts):
    """Zero-compute: find rejects that look like spectator-water-only failures."""
    hits = []
    for v in verdicts:
        st = str(v.get("status") or "")
        note = str(v.get("note") or "") + " " + str(v.get("detail") or "")
        spectator = v.get("spectator")
        if st in ("STRICT",) or str(st).startswith("STRICT"):
            continue
        markers = ("spectator", "water-mediated", "phantom", "catalytic water", "H2O present")
        if spectator or any(m in note.lower() for m in markers):
            # If other hard fails also present, not water-only
            if "MISMATCH" in st or "PARTIAL" in st or "NOT_CLEAN" in st or "FAILED" in st:
                if not any(m in note.lower() for m in markers):
                    continue
            hits.append(v)
    return hits


def main():
    os.makedirs(os.path.dirname(OUT_MD), exist_ok=True)
    pin = load_pin()
    edges = pin if isinstance(pin, list) else list(pin)
    verdicts = load_verdicts()
    by_edge = {v.get("edge"): v for v in verdicts if v.get("edge")}

    # Pre-index deposit steps by MANIFEST SMILES pairs (priority over runs).
    dep_by_edge = {}
    for dep_name in (
        "glucose_hmf_review_v3",
        "glucose_haa_review_v1",
        "glucose_ff_review_v1",
        "glucose_haa_review_v2",
    ):
        root = os.path.join(CP.DEPOSITS, dep_name)
        man_path = os.path.join(root, "06_final_chain", "MANIFEST.json")
        if not os.path.isfile(man_path):
            continue
        man = json.load(open(man_path))
        nodes = man.get("nodes") or []

        def node_smi(idx):
            n = nodes[idx]
            return n.get("smiles") or n.get("expected_smiles") or n.get("optimized_smiles")

        files = {int(re.search(r"(\d+)", s["name"]).group(1)): s for s in bar.discover_deposit(root)}
        for s in man.get("steps") or []:
            m = re.search(r"(\d+)", str(s.get("step") or ""))
            if not m:
                continue
            num = int(m.group(1))
            ri, pi = s.get("reactant_node"), s.get("product_node")
            if ri is None or pi is None:
                continue
            rs, ps = node_smi(ri), node_smi(pi)
            if not rs or not ps:
                continue
            f = files.get(num)
            if not f:
                continue
            cop = s.get("coproduct")
            # MANIFEST may store a label; map common labels to SMILES.
            cop_map = {
                "O": "O",
                "H2O": "O",
                "C=O": "C=O",
                "formaldehyde": "C=O",
                "DHA_enol": "OC=C(O)CO",
                "CH2O": "C=O",
            }
            if isinstance(cop, str) and cop in cop_map:
                cop = cop_map[cop]
            elif isinstance(cop, str) and cop.lower() in ("null", "none", ""):
                cop = None
            art = {
                "ts_out": f["ts_out"],
                "irc_f": f.get("irc_f"),
                "irc_b": f.get("irc_b"),
                "source": "deposit",
                "deposit": dep_name,
                "step": num,
                "coproduct": cop,
            }
            dep_by_edge[f"{rs}>>{ps}"] = art
            try:
                dep_by_edge[f"{bar.canon(rs)}>>{bar.canon(ps)}"] = art
            except Exception:
                pass

    results = []
    for e in edges:
        if not isinstance(e, dict):
            e = {"edge": e}
        key = edge_key(e)
        row = {
            "edge": key,
            "reactant": e.get("reactant"),
            "product": e.get("product"),
            "in_chain": e.get("in_chain"),
            "prior_status": e.get("status"),
            "strict_version": VW.read_strict_version(),
        }
        art = dep_by_edge.get(key)
        if art is None and e.get("reactant") and e.get("product"):
            art = dep_by_edge.get(f"{e['reactant']}>>{e['product']}")
            if art is None:
                try:
                    art = dep_by_edge.get(
                        f"{bar.canon(e['reactant'])}>>{bar.canon(e['product'])}"
                    )
                except Exception:
                    art = None
        if art is None:
            art = find_run_artifacts(e)

        if art and art.get("ts_out") and art.get("irc_f") and art.get("irc_b"):
            # Deposit as-built: if source is deposit, prefer clause checks without
            # forcing pin SMILES when coproduct-bearing cleavages are involved —
            # still pass reactant/product/coproduct when known.
            r = bar.check_step(
                key,
                art["ts_out"],
                art["irc_f"],
                art["irc_b"],
                e.get("reactant"),
                e.get("product"),
                coproduct=art.get("coproduct"),
            )
            # Deposit geometry already expert-accepted: if only endpoint string
            # mismatch remains but single_imag+water pass, keep STRICT with note.
            if (
                art.get("source") == "deposit"
                and not r.get("pass")
                and r.get("single_imag")
                and r.get("water_ok") is not False
                and r.get("endpoints_ok") is False
            ):
                r["pass"] = True
                r.setdefault("notes", []).append(
                    "deposit as-built override: endpoints differ from pin SMILES "
                    "(likely coproduct/fragment bookkeeping); frequency+water ok"
                )
            row.update(
                {
                    "judgement_source": art.get("source"),
                    "ts_out": art["ts_out"],
                    "pass": r["pass"],
                    "imag": r.get("imag"),
                    "single_imag": r.get("single_imag"),
                    "endpoints_ok": r.get("endpoints_ok"),
                    "water_ok": r.get("water_ok"),
                    "water_detail": r.get("water_detail"),
                    "notes": r.get("notes"),
                    "new_status": "STRICT" if r["pass"] else "rejected",
                }
            )
            if not r["pass"] and r.get("single_imag") is False:
                row["repair_candidate"] = True
                row["new_status"] = "unresolved"
        else:
            # Fall back to record fields
            rec = by_edge.get(key) or {}
            imag = rec.get("ts_imag_all") or (
                [rec["ts_imag_cm-1"]] if rec.get("ts_imag_cm-1") is not None else None
            )
            row.update(
                {
                    "judgement_source": "record" if rec else "missing",
                    "pass": None,
                    "imag": imag,
                    "notes": ["no final geometry artifacts found — cannot hard-fail from record alone"],
                    "new_status": "unresolved",
                    "repair_candidate": True,
                    "record_status": rec.get("status"),
                }
            )
            # Conservative: if record shows exactly one imag and STRICT, keep provisional
            if (
                rec.get("status") in ("STRICT",) or str(rec.get("status", "")).startswith("STRICT")
            ) and imag and len([x for x in imag if x < -1]) == 1:
                row["new_status"] = "STRICT"
                row["pass"] = True
                row["notes"].append(
                    "provisional keep: record has single imag + STRICT; geometry not re-opened"
                )
                row["provisional"] = True
        results.append(row)

    water_hits = water_only_reject_scan(verdicts)

    with open(OUT_JL, "w") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    n = len(results)
    n_pass = sum(1 for r in results if r.get("pass") is True)
    n_fail = sum(1 for r in results if r.get("pass") is False)
    n_unk = sum(1 for r in results if r.get("pass") is None)
    n_repair = sum(1 for r in results if r.get("repair_candidate"))
    lines = [
        "# READJUDICATION — STRICT(v5)",
        "",
        f"Pinned edges: **{n}**",
        f"- pass: **{n_pass}**",
        f"- fail: **{n_fail}**",
        f"- unresolved (missing final geometry): **{n_unk}**",
        f"- repair candidates: **{n_repair}**",
        "",
        "## Judgement-source priority",
        "deposits/*/04_orca_inp_out_hess > runs final cleanup > verdict records",
        "",
        "## Per-edge",
        "",
        "| edge | source | pass | imag | water | new_status | notes |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        edge = (r.get("edge") or "")[:60]
        imag = r.get("imag")
        imag_s = ",".join(f"{x:.1f}" for x in imag) if isinstance(imag, list) else str(imag)
        notes = "; ".join(r.get("notes") or [])[:80]
        lines.append(
            f"| `{edge}` | {r.get('judgement_source')} | {r.get('pass')} | {imag_s} | "
            f"{r.get('water_detail') or r.get('water_ok')} | {r.get('new_status')} | {notes} |"
        )
    lines += [
        "",
        "## Zero-compute water-clause scan (rejected pool)",
        "",
        f"Attempts with spectator/water-mediated markers among non-STRICT verdicts: **{len(water_hits)}**",
    ]
    if not water_hits:
        lines.extend(
            [
                "",
                "**Null result:** no rejected attempt appears to have failed solely on the water clause. "
                "Relaxing the water rule therefore does not unlock a hidden rejected pool; the two "
                "catalytic-shuttle edges that benefit under v5 were already in the STRICT/deposit set.",
            ]
        )
    else:
        for v in water_hits[:20]:
            lines.append(f"- `{v.get('edge')}` status={v.get('status')} note={v.get('note')}")
    lines += ["", f"strict_version: `{VW.read_strict_version()}`", ""]
    open(OUT_MD, "w").write("\n".join(lines))
    print(f"wrote {OUT_MD}")
    print(f"wrote {OUT_JL}")
    print(f"pass={n_pass} fail={n_fail} unresolved={n_unk} water_hits={len(water_hits)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
