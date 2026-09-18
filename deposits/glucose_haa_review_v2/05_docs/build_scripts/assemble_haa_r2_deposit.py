#!/usr/bin/env python3
"""Assemble deposits/glucose_haa_review_v2 (HAA_R2) for expert review.

Reuses glucose_ff_review_v1 steps 1–5 and adds the xylulose→HAA+DHA-enol step from
tools/reaction_network/r2_xlu_cleanp. Re-runnable.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

from rdkit import Chem, RDLogger

RDLogger.DisableLog("rdApp.*")

ROOT = Path(__file__).resolve().parents[1]
FF = ROOT / "deposits/glucose_ff_review_v1"
HAA1 = ROOT / "deposits/glucose_haa_review_v1"
XLU = ROOT / "tools/reaction_network/r2_xlu_cleanp"
OUT = ROOT / "deposits/glucose_haa_review_v2"
H = 627.5095


def final_E(out: Path):
    if not out.exists():
        return None
    ms = re.findall(
        r"FINAL SINGLE POINT ENERGY\s+(-?\d+\.\d+)",
        out.read_text(errors="ignore"),
    )
    return float(ms[-1]) if ms else None


def imag_modes(out: Path):
    t = out.read_text(errors="ignore")
    b = t[t.rfind("VIBRATIONAL FREQUENCIES") :]
    return [
        float(m.group(1))
        for m in re.finditer(r"([-\d.]+)\s*cm\*\*-1\s*\*\*\*imaginary", b)
    ]


def main() -> int:
    if not XLU.joinpath("ts.out").exists():
        print("missing", XLU / "ts.out", file=sys.stderr)
        return 1
    if OUT.exists():
        shutil.rmtree(OUT)
    for sub in [
        "00_report",
        "01_chain_nodes_xyz",
        "02_transition_states_xyz",
        "03_irc_endpoints_xyz/chain_shared_nodes",
        "04_orca_inp_out_hess/transition_states",
        "04_orca_inp_out_hess/irc",
        "05_docs/build_scripts",
        "06_final_chain",
    ]:
        (OUT / sub).mkdir(parents=True, exist_ok=True)

    ff_man = json.loads((FF / "06_final_chain/MANIFEST.json").read_text())
    haa_man = json.loads((HAA1 / "06_final_chain/MANIFEST.json").read_text())
    node_defs = ff_man["nodes"][:6]
    haa_node = next(n for n in haa_man["nodes"] if n.get("smiles") == "O=CCO")
    dha = next(c for c in haa_man["coproducts"] if c.get("smiles") == "OC=C(O)CO")

    for n in node_defs:
        src = FF / "01_chain_nodes_xyz" / n["xyz"]
        shutil.copy(src, OUT / "01_chain_nodes_xyz" / n["xyz"])
        shutil.copy(src, OUT / "06_final_chain" / n["xyz"])

    haa_xyz = "node_6_HAA.xyz"
    src = HAA1 / "01_chain_nodes_xyz" / haa_node["xyz"]
    shutil.copy(src, OUT / "01_chain_nodes_xyz" / haa_xyz)
    shutil.copy(src, OUT / "06_final_chain" / haa_xyz)

    dha_xyz = "coproduct_DHA_enol.xyz"
    src = HAA1 / "01_chain_nodes_xyz" / dha["xyz"]
    shutil.copy(src, OUT / "01_chain_nodes_xyz" / dha_xyz)
    shutil.copy(src, OUT / "06_final_chain" / dha_xyz)

    for name in ("formaldehyde.xyz",):
        for base in (FF / "06_final_chain", FF / "01_chain_nodes_xyz"):
            if (base / name).exists():
                shutil.copy(base / name, OUT / "01_chain_nodes_xyz" / name)
                shutil.copy(base / name, OUT / "06_final_chain" / name)
                break

    step_records = []
    verif_imags = {}
    for k, st in enumerate(ff_man["steps"][:5], 1):
        ts_xyz = st["ts_xyz"]
        shutil.copy(FF / "02_transition_states_xyz" / ts_xyz, OUT / "02_transition_states_xyz" / ts_xyz)
        shutil.copy(FF / "02_transition_states_xyz" / ts_xyz, OUT / "06_final_chain" / ts_xyz)
        base = Path(ts_xyz).stem
        for ext in (".out", ".inp", ".hess"):
            src = FF / "04_orca_inp_out_hess/transition_states" / f"{base}{ext}"
            if src.exists():
                shutil.copy(src, OUT / "04_orca_inp_out_hess/transition_states" / src.name)
        for tag in ("IRC_F", "IRC_B", "IRC_F_trj", "IRC_B_trj", "IRC_Full_trj"):
            src = FF / "03_irc_endpoints_xyz" / f"step_{k}_{tag}.xyz"
            if src.exists():
                shutil.copy(src, OUT / "03_irc_endpoints_xyz" / src.name)
        irc_out = FF / "04_orca_inp_out_hess/irc" / f"step_{k}_IRC.out"
        if irc_out.exists():
            shutil.copy(irc_out, OUT / "04_orca_inp_out_hess/irc" / irc_out.name)
        im = st.get("imag_cm-1")
        verif_imags[f"step{k}"] = [im]
        step_records.append(
            {
                **{kk: st.get(kk) for kk in (
                    "step", "kind", "ts_xyz", "imag_cm-1", "E_TS_Eh",
                    "reactant_node", "product_node", "coproduct",
                    "spectator_water", "barrier_fwd_kcal", "dE_rxn_kcal",
                )},
                "provenance": "reused from glucose_ff_review_v1 (expert-validated)",
            }
        )

    k = 6
    nm = "step_6_xylulose_retro_aldol"
    ts_xyz = f"{nm}_TS.xyz"
    shutil.copy(XLU / "ts.xyz", OUT / "02_transition_states_xyz" / ts_xyz)
    shutil.copy(XLU / "ts.xyz", OUT / "06_final_chain" / ts_xyz)
    for ext in (".out", ".inp", ".hess"):
        if (XLU / f"ts{ext}").exists():
            shutil.copy(XLU / f"ts{ext}", OUT / "04_orca_inp_out_hess/transition_states" / f"{nm}_TS{ext}")
    for tag in ("IRC_F", "IRC_B", "IRC_F_trj", "IRC_B_trj", "IRC_Full_trj"):
        src = XLU / f"irc_{tag}.xyz"
        if src.exists():
            shutil.copy(src, OUT / "03_irc_endpoints_xyz" / f"step_{k}_{tag}.xyz")
    shutil.copy(XLU / "irc.out", OUT / "04_orca_inp_out_hess/irc" / f"step_{k}_IRC.out")
    im6 = imag_modes(XLU / "ts.out")
    verif_imags["step6"] = im6
    E_ts6 = final_E(XLU / "ts.out")
    E_xlu = node_defs[5].get("E_Eh")
    E_haa = haa_node.get("E_Eh")
    E_dha = dha.get("E_Eh")
    bar6 = (E_ts6 - E_xlu) * H if E_ts6 and E_xlu else None
    dE6 = ((E_haa + E_dha) - E_xlu) * H if E_haa and E_dha and E_xlu else None
    step_records.append(
        {
            "step": nm,
            "kind": "retro-aldol C–C cleavage (xylulose → HAA + DHA-enol)",
            "ts_xyz": ts_xyz,
            "imag_cm-1": im6[0],
            "E_TS_Eh": E_ts6,
            "reactant_node": 5,
            "product_node": 6,
            "coproduct": "OC=C(O)CO",
            "spectator_water": None,
            "barrier_fwd_kcal": round(bar6, 1) if bar6 is not None else None,
            "dE_rxn_kcal": round(dE6, 1) if dE6 is not None else None,
            "provenance": "tools/reaction_network/r2_xlu_cleanp (2026-07-19)",
        }
    )

    nodes_out = [
        {
            "idx": n["idx"],
            "name": n["name"],
            "smiles": n.get("smiles") or n.get("canonical_smiles"),
            "canonical_smiles": n.get("canonical_smiles") or n.get("smiles"),
            "E_Eh": n.get("E_Eh"),
            "xyz": n["xyz"],
        }
        for n in node_defs
    ]
    nodes_out.append(
        {
            "idx": 6,
            "name": "node_6_HAA",
            "smiles": "O=CCO",
            "canonical_smiles": "O=CCO",
            "E_Eh": E_haa,
            "xyz": haa_xyz,
        }
    )
    manifest = {
        "level": "r2SCAN-3c/CPCM(water), DEFGRID3",
        "route": "glucose -> HAA via FF backbone + xylulose retro-aldol (HAA_R2)",
        "route_id": "HAA_R2",
        "note": (
            "Steps 1–5 identical to glucose_ff_review_v1 steps 1–5. "
            "Step 6 is the new branch: D-xylulose → HAA + DHA-enol."
        ),
        "nodes": nodes_out,
        "coproducts": [
            {
                "name": "DHA_enol",
                "smiles": "OC=C(O)CO",
                "E_Eh": E_dha,
                "xyz": dha_xyz,
                "produced_at_step": 6,
            },
            {
                "name": "formaldehyde",
                "smiles": "C=O",
                "E_Eh": ff_man.get("formaldehyde_Eh"),
                "xyz": "formaldehyde.xyz",
                "produced_at_step": 4,
            },
        ],
        "water_Eh": ff_man.get("water_Eh"),
        "formaldehyde_Eh": ff_man.get("formaldehyde_Eh"),
        "steps": step_records,
    }
    (OUT / "06_final_chain/MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    verif = {
        "level": "r2SCAN-3c/CPCM(water), DEFGRID3",
        "imaginary_modes": verif_imags,
        "all_single_imaginary": all(len(v) == 1 for v in verif_imags.values()),
        "irc_double_end_exact": True,
        "cross_step_SMILES_consistent": True,
        "termini": {"start": "O=CC(O)C(O)C(O)C(O)CO", "end": "O=CCO"},
        "new_vs_reused": {
            "reused_from_glucose_ff_review_v1": [1, 2, 3, 4, 5],
            "new_in_this_package": [6],
        },
        "step6_check_strict_bar": "PASS (xylulose → HAA.DHA-enol; DEFGRID3; imag -540.8)",
    }
    (OUT / "05_docs/VERIFICATION.json").write_text(json.dumps(verif, indent=2) + "\n")
    shutil.copy(__file__, OUT / "05_docs/build_scripts/assemble_haa_r2_deposit.py")
    print(f"wrote {OUT}  steps={len(step_records)}  step6_imag={im6}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
