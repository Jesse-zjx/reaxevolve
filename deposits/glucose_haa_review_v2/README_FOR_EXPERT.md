# Glucose → HAA — route HAA_R2 (v2, for expert review)

**Level of theory:** ORCA, r²SCAN-3c / CPCM(water), **DEFGRID3** throughout the new step
and for the reused FF-backbone steps.

**Acceptance bar (identical to prior deposits):** every elementary step has an OptTS with
**exactly one imaginary frequency**, and a raw IRC whose **two endpoints** give the exact
neutral canonical SMILES of reactant and product (multi-fragment products allowed as
`A.B`). Product of step *n* = reactant of step *n*+1. **No catalytic/phantom water.**

## Why this package

`glucose_haa_review_v1` (HAA_R1) is the short branching retro-aldol route and was already
expert-validated. This package is a **second, complete glucose→HAA route** that shares the
furfural-backbone opening and then branches at D-xylulose:

```
glucose → fructose → 2,3-enediol → 3-ketohexose → C5-enediol (+HCHO)
       → D-xylulose → HAA + DHA-enol
```

Steps 1–5 are **literally the same calculations** as `glucose_ff_review_v1` steps 1–5
(already expert-validated). Only **step 6** is new chemistry for this target.

## The route (6 elementary steps)

| # | reaction | reactant → product | imag (cm⁻¹) | ΔE‡ | ΔE |
|---|---|---|---|---|---|
| 1 | aldose-ketose isomerization | `O=CC(O)C(O)C(O)C(O)CO` → `O=C(CO)C(O)C(O)C(O)CO` | -434.6 | 34.5 | -2.1 |
| 2 | keto-enol enolization | `O=C(CO)C(O)C(O)C(O)CO` → `OCC(O)=C(O)C(O)C(O)CO` | -2042.5 | 62.7 | 4.1 |
| 3 | enol-keto ketonization | `OCC(O)=C(O)C(O)C(O)CO` → `O=C(C(O)CO)C(O)C(O)CO` | -2032.5 | 61.0 | -3.6 |
| 4 | retro-aldol C-C cleavage | `O=C(C(O)CO)C(O)C(O)CO` → `OC=C(O)C(O)C(O)CO` + `C=O` | -932.3 | 29.8 | 28.7 |
| 5 | enediol->ketose (dry) | `OC=C(O)C(O)C(O)CO` → `O=C(CO)C(O)C(O)CO` | -1630.0 | 57.3 | -7.9 |
| 6 | retro-aldol C–C cleavage (xylulose → HAA + DHA-enol) | `O=C(CO)C(O)C(O)CO` → `O=CCO` + `OC=C(O)CO` | -540.8 | 30.6 | 27.6 |

Co-products: formaldehyde (step 4), DHA-enol (step 6). Main-line terminus: **HAA** `O=CCO`.

## Directory layout
- `00_report/` — (optional HTML)
- `01_chain_nodes_xyz/` — node geometries
- `02_transition_states_xyz/` — 6 transition states
- `03_irc_endpoints_xyz/` — IRC endpoints (+ trajectories)
- `04_orca_inp_out_hess/` — ORCA evidence (`.out` / `.hess` / `.inp`)
- `05_docs/` — `VERIFICATION.json`, `FINAL_STRICT_CHAIN.md`
- `06_final_chain/` — assembled route + `MANIFEST.json`

## What to focus on

1. **Step 6** (new): xylulose C–C cleavage → HAA + DHA-enol, imag −540.8, DEFGRID3.
2. Cross-step continuity at the xylulose node (end of step 5 = start of step 6).
3. Steps 1–5 may be skimmed if you already signed off `glucose_ff_review_v1`; they are unchanged copies.
