#!/usr/bin/env python3
"""Build blinded novelty-triage cards from deposit packages.

Four deposits → unique elementary steps (HAA_R2 steps 1–5 are the same calculations as
FF steps 1–5). Cards strip route provenance; KEY.private.json maps card_id → deposit/step.

  python3 scripts/reflect/build_novelty_cards.py
  python3 scripts/reflect/build_novelty_cards.py --seed 20260804
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
from pathlib import Path

from rdkit import Chem, RDLogger

RDLogger.DisableLog("rdApp.*")

HERE = Path(__file__).resolve().parent
PKG = HERE.parents[1]
DEPOSITS_DIR = PKG / "deposits"
OUT_DIR = PKG / "evidence" / "novelty_triage"

DEPOSITS = (
    "glucose_hmf_review_v3",
    "glucose_haa_review_v1",
    "glucose_ff_review_v1",
    "glucose_haa_review_v2",
)


def canon(s: str | None) -> str | None:
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
    im = st.get("imag_cm-1")
    if im is None:
        im = st.get("imag_cm")
    if isinstance(im, list):
        im = im[0] if im else None
    return float(im) if im is not None else None


def load_steps():
    rows = []
    for dep in DEPOSITS:
        man_path = DEPOSITS_DIR / dep / "06_final_chain" / "MANIFEST.json"
        man = json.loads(man_path.read_text())
        nodes = man["nodes"]
        for st in man["steps"]:
            rn, pn = st["reactant_node"], st["product_node"]
            r = node_smiles(nodes, rn)
            p = node_smiles(nodes, pn)
            cop = st.get("coproduct")
            if cop and cop not in (None, "null"):
                # keep coproduct as reported; water often stored as "O"
                cop_c = canon(cop) if Chem.MolFromSmiles(str(cop)) else cop
            else:
                cop_c = None
            im = imag_of(st)
            rows.append(
                {
                    "deposit": dep,
                    "step": st.get("step"),
                    "kind": st.get("kind") or st.get("title") or st.get("step"),
                    "reactant": r,
                    "product": p,
                    "coproduct": cop_c,
                    "imag_cm-1": im,
                    "barrier_fwd_kcal": st.get("barrier_fwd_kcal"),
                    "dE_rxn_kcal": st.get("dE_rxn_kcal"),
                }
            )
    return rows


def dedupe_key(row):
    # Same chemistry + same saddle fingerprint → one card (FF 1–5 ≡ HAA_R2 1–5).
    im = row["imag_cm-1"]
    im_r = round(abs(im), 1) if im is not None else None
    return (row["reactant"], row["product"], row["coproduct"], im_r)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20260804)
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    a = ap.parse_args()
    a.out_dir.mkdir(parents=True, exist_ok=True)

    steps = load_steps()
    groups = {}
    for row in steps:
        groups.setdefault(dedupe_key(row), []).append(row)

    unique = []
    for key, members in groups.items():
        primary = members[0]
        unique.append(
            {
                "reactant": primary["reactant"],
                "product": primary["product"],
                "coproduct": primary["coproduct"],
                "kind_label": primary["kind"],
                "imag_cm-1": primary["imag_cm-1"],
                "barrier_fwd_kcal": primary["barrier_fwd_kcal"],
                "dE_rxn_kcal": primary["dE_rxn_kcal"],
                "provenance": [
                    {"deposit": m["deposit"], "step": m["step"]} for m in members
                ],
            }
        )

    rng = random.Random(a.seed)
    order = list(range(len(unique)))
    rng.shuffle(order)

    cards = []
    key_map = {}
    for i, ui in enumerate(order, 1):
        u = unique[ui]
        cid = f"C{i:02d}"
        card = {
            "card_id": cid,
            "reactant_smiles": u["reactant"],
            "product_smiles": u["product"],
            "coproduct_smiles": u["coproduct"],
            "reaction_type_hint": u["kind_label"],
            "ts_imag_cm-1": u["imag_cm-1"],
            "barrier_kcal": u["barrier_fwd_kcal"],
            "dE_kcal": u["dE_rxn_kcal"],
            "level": "r2SCAN-3c / CPCM(water)",
        }
        cards.append(card)
        key_map[cid] = {
            "provenance": u["provenance"],
            "dedupe_key": {
                "reactant": u["reactant"],
                "product": u["product"],
                "coproduct": u["coproduct"],
                "imag_round_abs": round(abs(u["imag_cm-1"]), 1) if u["imag_cm-1"] else None,
            },
        }

    # Write cards.jsonl
    jsonl = a.out_dir / "cards.jsonl"
    with jsonl.open("w") as f:
        for c in cards:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    # cards.md (expert-facing)
    md = a.out_dir / "cards.md"
    lines = [
        "# Novelty triage cards (blind)",
        "",
        f"Seed `{a.seed}`. {len(cards)} unique elementary steps after deduplicating "
        f"{len(steps)} deposit steps (HAA_R2 steps 1–5 share ORCA evidence with FF steps 1–5).",
        "",
        "Do **not** infer which deposit or route a card belongs to. Classify each card as a / b / c "
        "per `PROTOCOL.md`. Fill `FORM.csv`.",
        "",
    ]
    for c in cards:
        lines += [
            f"## {c['card_id']}",
            "",
            f"- Reactant: `{c['reactant_smiles']}`",
            f"- Product: `{c['product_smiles']}`",
            f"- Coproduct: `{c['coproduct_smiles']}`" if c["coproduct_smiles"] else "- Coproduct: _(none)_",
            f"- Type hint (may be incomplete): {c['reaction_type_hint']}",
            f"- Imaginary mode: {c['ts_imag_cm-1']} cm⁻¹",
            f"- ΔE‡ / ΔE (electronic, kcal/mol): {c['barrier_kcal']} / {c['dE_kcal']}",
            f"- Level: {c['level']}",
            "",
        ]
    md.write_text("\n".join(lines) + "\n")

    # KEY.private.json
    key_path = a.out_dir / "KEY.private.json"
    key_path.write_text(
        json.dumps(
            {
                "seed": a.seed,
                "n_deposit_steps": len(steps),
                "n_unique_cards": len(cards),
                "cards": key_map,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )

    # FORM.csv
    form = a.out_dir / "FORM.csv"
    with form.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "card_id",
                "class_abc",
                "confidence_1to5",
                "citation_or_note",
                "reviewer_id",
                "date",
            ]
        )
        for c in cards:
            w.writerow([c["card_id"], "", "", "", "", ""])

    # PROTOCOL.md
    protocol = a.out_dir / "PROTOCOL.md"
    protocol.write_text(
        """# Novelty triage protocol (blind three-way classification)

## Purpose

Locate the paper: discovery vs verification infrastructure. Even if most steps are **(b)**,
that is a clean publishable claim — mechanisms proposed in the literature but never computed
to a strict TS/IRC bar.

## Classes

For each card, choose exactly one:

| Class | Meaning |
|---|---|
| **a** | Literature has proposed this elementary transformation **and** a TS (or equivalent stationary-point search) has been reported at a comparable or higher level of theory for the same or closely related species. |
| **b** | Literature has proposed the transformation (or it is textbook/mechanism-standard for this chemistry) **but** no TS at comparable level is known for this specific step. |
| **c** | Literature has **not** proposed this elementary step (to the reviewer’s knowledge). |

Comparable level ≈ DFT hybrid or meta-GGA with continuum solvation, or higher. Purely
mechanistic cartoons without a reported saddle do **not** count as (a).

## Blinding rules

1. Cards omit deposit name, route id, campaign date, and whether the step came from the
   automated loop.
2. Do **not** open `KEY.private.json` before finishing your own classifications.
3. Do **not** open `draft_classification.md` before finishing (that file is a non-blind
   draft for later reconciliation).
4. Type hints on cards may be incomplete or generic; judge from the SMILES pair.

## Deliverable

Fill `FORM.csv`: `class_abc` ∈ {a,b,c}, `confidence_1to5`, optional `citation_or_note`.

## Scope

Unique cards after deduplication across
`glucose_hmf_review_v3`, `glucose_haa_review_v1`, `glucose_ff_review_v1`,
`glucose_haa_review_v2`. Shared FF/HAA_R2 backbone steps appear once.
"""
    )

    print(f"deposit steps {len(steps)} → unique cards {len(cards)}")
    print(f"wrote {jsonl}")
    print(f"wrote {md}")
    print(f"wrote {form}")
    print(f"wrote {protocol}")
    print(f"wrote {key_path}  (private — gitignored)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
