# Glucose → HAA (route HAA_R2) — STRICT chain for expert review

**Level:** ORCA 6.x, r²SCAN-3c / CPCM(water), **DEFGRID3**.

**Relation to prior deposits:** Steps 1–5 are the opening of `glucose_ff_review_v1` (already expert-validated). Step 6 is new: D-xylulose → HAA + DHA-enol.

**Acceptance bar:** single imaginary mode; raw IRC ends = exact neutral canonical SMILES; product of step n = reactant of step n+1; no catalytic water.

| # | kind | reactant → product (+co) | imag | ΔE‡ | ΔE | provenance |
|---|------|--------------------------|------|-----|-----|------------|
| 1 | aldose-ketose isomerization | `O=CC(O)C(O)C(O)C(O)CO` → `O=C(CO)C(O)C(O)C(O)CO` | -434.6 | 34.5 | -2.1 | reused from glucose_ff_review_v1 (expert |
| 2 | keto-enol enolization | `O=C(CO)C(O)C(O)C(O)CO` → `OCC(O)=C(O)C(O)C(O)CO` | -2042.5 | 62.7 | 4.1 | reused from glucose_ff_review_v1 (expert |
| 3 | enol-keto ketonization | `OCC(O)=C(O)C(O)C(O)CO` → `O=C(C(O)CO)C(O)C(O)CO` | -2032.5 | 61.0 | -3.6 | reused from glucose_ff_review_v1 (expert |
| 4 | retro-aldol C-C cleavage | `O=C(C(O)CO)C(O)C(O)CO` → `OC=C(O)C(O)C(O)CO` + `C=O` | -932.3 | 29.8 | 28.7 | reused from glucose_ff_review_v1 (expert |
| 5 | enediol->ketose (dry) | `OC=C(O)C(O)C(O)CO` → `O=C(CO)C(O)C(O)CO` | -1630.0 | 57.3 | -7.9 | reused from glucose_ff_review_v1 (expert |
| 6 | retro-aldol C–C cleavage (xylulose → HAA + DHA-enol) | `O=C(CO)C(O)C(O)CO` → `O=CCO` + `OC=C(O)CO` | -540.8 | 30.6 | 27.6 | tools/reaction_network/r2_xlu_cleanp (20 |

## Directory layout
- `00_report/` — placeholder (HTML optional)
- `01_chain_nodes_xyz/` — main-line nodes + key coproducts
- `02_transition_states_xyz/` — 6 TS geometries
- `03_irc_endpoints_xyz/` — per-step IRC F/B (+ trajectories when present)
- `04_orca_inp_out_hess/` — ORCA `.out`/`.hess`/`.inp` for TS and IRC
- `05_docs/` — VERIFICATION.json, this file
- `06_final_chain/` — assembled chain + MANIFEST.json

## Independent check (step 6)
```
python3 .skills/strict-pathway-validation/scripts/check_strict_bar.py \
  --ts 04_orca_inp_out_hess/transition_states/step_6_xylulose_retro_aldol_TS.out \
  --irc-f 03_irc_endpoints_xyz/step_6_IRC_F.xyz \
  --irc-b 03_irc_endpoints_xyz/step_6_IRC_B.xyz \
  --reactant "O=C(CO)C(O)C(O)CO" --product "O=CCO.OC=C(O)CO"
```
Expected: PASS, imag −540.8, DEFGRID3.
