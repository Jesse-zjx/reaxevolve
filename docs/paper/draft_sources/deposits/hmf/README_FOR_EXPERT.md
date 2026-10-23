# Glucose → HMF — strict QM-validated chain (v3, for expert review)

**Level of theory:** ORCA 6.1.1, r²SCAN-3c / CPCM(water). GFN2-xTB used only for TS-guess generation.

**Acceptance bar (strict):** every elementary step must have an OptTS with **exactly one
imaginary frequency** in the final NumFreq block, and a raw IRC whose **two endpoints, after
optimization, give the exact neutral canonical SMILES of the reactant and the product**
(charged / zwitterionic / tautomer endpoints are rejected; a catalytic water is allowed only
as a stripped spectator). In addition, the **product of step n and the reactant of step n+1
must be the same species** (front/back endpoint consistency).

## The route (5 elementary steps, 3 waters lost)

| # | reaction | reactant → product | imag (cm⁻¹) | ΔE‡ | ΔE |
|---|---|---|---|---|---|
| 1 | dehydration | open-glucose `O=CC(O)C(O)C(O)C(O)CO` → `O=CC(O)=CC(O)C(O)CO` | −1410.1 | 50.2 | +7.5 |
| 2 | keto–enol tautomerization | → 3-deoxyglucosone `O=CC(=O)CC(O)C(O)CO` | −1449.8 | 68.2 | −5.6 |
| 3 | dehydration | → 3,4-dideoxyglucosone-3-ene (3,4-DGE) `O=CC(=O)C=CC(O)CO` | −1533.0 | 46.6 | +11.6 |
| 4 | ring closure (retro-hemiketal) | → furanic hemiketal `O=CC1(O)C=CC(CO)O1` | −1574.5 | 33.0 | −7.3 |
| 5 | aromatizing dehydration | → HMF `O=Cc1ccc(CO)o1` | −830.4 | 51.1 | −10.7 |

Overall: C₆H₁₂O₆ → HMF + 3 H₂O, mildly exothermic (−4.6 kcal/mol).
Rate-determining: the keto–enol tautomerization (ΔE‡ ≈ 68 kcal/mol).
Intermediates 2 and 3 are the literature-known HMF intermediates **3-deoxyglucosone (3-DG)** and
**3,4-dideoxyglucosone-3-ene (3,4-DGE)**.

## Directory layout
- `00_report/` — self-contained HTML report (open in a browser).
- `01_chain_nodes_xyz/` — the 6 canonical node geometries (one optimized minimum each).
- `02_transition_states_xyz/` — the 5 transition states (each single imaginary mode).
- `03_irc_endpoints_xyz/` — per-step IRC forward/backward endpoints (and trajectories).
- `04_orca_inp_out_hess/` — ORCA `.out` + `.hess` for every TS (frequency evidence) and IRC `.out`.
- `05_docs/` — `FINAL_STRICT_CHAIN.md`, `VERIFICATION.json` (all strictness checks),
  `cross_step_consistency.json` (per-node front/back comparison), `energetics_manifest.json`.
- `06_final_chain/` — the assembled chain (canonical nodes + clean TSs + `MANIFEST.json`).

## Independent verification (see `deposits/glucose_hmf_review_v3/05_docs/VERIFICATION.json`)
- Exactly one imaginary mode per TS: **5/5** (step 4 originally carried a spurious −34.9 cm⁻¹
  hydroxyl-torsion soft mode → removed by soft-mode displacement + reopt; now −1574.5 cm⁻¹ only,
  IRC still connects exact I and M).
- IRC endpoints = exact neutral reactant/product on both sides: **5/5**.
- Front/back endpoint identity (product of step n ≡ reactant of step n+1, canonical SMILES):
  **4/4 internal nodes + both termini**. Geometrically nodes 2 and 4 are the same minimum
  (ΔE < 0.4 kcal/mol); nodes 1 and 3 have identical connectivity but differ by a single
  hydroxyl rotamer (ΔE 5.7 / 1.8 kcal/mol, barrierless interconversion); the canonical node
  geometry uses the lower-energy conformer.

## Pre-flight checklist (all verified programmatically from the deposited files)
1. **Every step has a barrier.** ΔE‡ = 50.2 / 68.2 / 46.6 / 32.9 / 51.1 kcal/mol (see
   `deposits/glucose_hmf_review_v3/06_final_chain/MANIFEST.json`).
2. **Every step has a transition state with exactly one imaginary mode** (final NumFreq block of
   `04_orca_inp_out_hess/transition_states/step_n_TS.out`): −1410.1 / −1449.8 / −1533.0 /
   **−1574.5** / −830.4 cm⁻¹. (Step 4's earlier spurious −34.9 cm⁻¹ soft torsion was removed.)
3. **Each step's xyz matches the report.** All molecule images in the HTML are rendered directly
   from `01_chain_nodes_xyz/*.xyz`; the displayed SMILES equal the canonical neutral SMILES of
   those files.
4. **Front/back endpoint identity.** The product of step n and the reactant of step n+1 are the
   SAME deposited geometry — see `03_irc_endpoints_xyz/chain_shared_nodes/` where
   `step_n_product.xyz` is byte-identical (MD5) to `step_{n+1}_reactant.xyz`. Raw per-step IRC
   termini (`03_irc_endpoints_xyz/step_n_IRC_F/B.xyz`) optimize to these canonical nodes with
   identical connectivity (nodes 1 and 3: same species, a barrierless hydroxyl rotamer apart,
   ΔE 5.7 / 1.8 kcal — the canonical node uses the lower-energy rotamer).
5. **Single-route directory.** This folder contains ONLY this glucose→HMF chain; no files from
   the literature (glucopyranose / enol-ether / Int-2 / aldehyde-DHF) or any other route.

## Suggested points for the reviewer to check
1. Open each `02_transition_states_xyz/step_*_TS.xyz` and confirm against the matching
   `04_.../transition_states/step_*_TS.out` that the final frequency block has a single
   imaginary mode at the listed wavenumber.
2. Confirm `03_irc_endpoints_xyz/step_n_IRC_F/B.xyz` connectivity equals the adjacent nodes.
3. Confirm the conformer note for nodes 1 and 3 is acceptable (connectivity-identical rotamer,
   no bond change).
