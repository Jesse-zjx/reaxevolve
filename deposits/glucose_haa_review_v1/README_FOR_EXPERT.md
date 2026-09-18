# Glucose → HAA — strict QM-validated route (v1, for expert review)

**Level of theory:** ORCA 6.1.1, r²SCAN-3c / CPCM(water). GFN2-xTB used only for TS-guess generation.

**Acceptance bar (strict, identical to the glucose→HMF v3 package):** every elementary step must have
an OptTS with **exactly one imaginary frequency** in the final NumFreq block, and a **raw IRC whose two
endpoints give the exact neutral canonical SMILES of the reactant and product** (charged / zwitterionic /
tautomer endpoints rejected; a catalytic water is allowed only as a stripped spectator). In addition, the
**product of step n and the reactant of step n+1 must be the same species** (front/back consistency).

Target: **HAA = hydroxyacetaldehyde / glycolaldehyde `O=CCO`**, a major light-oxygenate biomass-pyrolysis
product.

## The route (4 elementary steps; branching retro-aldol path)

| # | reaction | reactant → product (+ co-product) | imag (cm⁻¹) | ΔE‡ | ΔE |
|---|---|---|---|---|---|
| 1 | aldose–ketose isomerization | open-glucose `O=CC(O)C(O)C(O)C(O)CO` → open-fructose `O=C(CO)C(O)C(O)C(O)CO` | −474.1 | 35.9 | −3.6 |
| 2 | C6 retro-aldol | fructose → glyceraldehyde `O=CC(O)CO` + DHA-enol `OC=C(O)CO` | −758.1 | 35.1 | +29.8 |
| 3 | C3 retro-aldol | glyceraldehyde → glycolaldehyde-enol `OC=CO` + formaldehyde `C=O` | −942.1 | 31.5 | +27.5 |
| 4 | water-catalysed enol→keto tautomerization | glycolaldehyde-enol → **HAA** `O=CCO` (+ H₂O catalytic) | −920.1 | 30.4 | −4.6 |

Main line: glucose → fructose → glyceraldehyde → glycolaldehyde-enol → HAA.
Co-products generated: dihydroxyacetone-enol (step 2), formaldehyde (step 3).
Barriers are all 30–36 kcal/mol (electronic).

## Directory layout (mirrors the glucose_hmf_review_v3 package)
- `00_report/` — self-contained HTML report (open in a browser); all molecule images rendered from the .xyz.
- `01_chain_nodes_xyz/` — 5 canonical node geometries + 3 co-product/spectator geometries.
- `02_transition_states_xyz/` — the 4 transition states (each single imaginary mode).
- `03_irc_endpoints_xyz/` — per-step raw IRC forward/backward endpoints (`step_n_IRC_F/B.xyz`) **and the
  complete IRC trajectories** (`step_n_IRC_F_trj.xyz`, `step_n_IRC_B_trj.xyz`, and the full
  reactant→TS→product path `step_n_IRC_Full_trj.xyz`), plus `chain_shared_nodes/`.
  Full-path frame counts: step1 100, step2 124, step3 88, step4 112.
- `04_orca_inp_out_hess/` — ORCA `.out` + `.hess` for every TS (frequency evidence) and IRC `.out`.
- `05_docs/` — `VERIFICATION.json`, `cross_step_consistency.json`, `energetics_manifest.json`,
  `build_scripts/gen_report.py`.
- `06_final_chain/` — assembled route (canonical nodes + co-products + clean TSs + `MANIFEST.json`).

## Independent verification (see `05_docs/VERIFICATION.json`)
- Exactly one imaginary mode per TS: **4/4**. Step 2 (C6 retro-aldol) initially carried a −13.5 cm⁻¹
  grid-noise soft torsion on the default grid → re-optimised at **DEFGRID3** (the fine grid used for the
  HMF chain) → single imaginary mode **−758.1 cm⁻¹**, IRC still connecting exactly fructose ↔
  glyceraldehyde + DHA-enol.
- Raw IRC endpoints = exact neutral reactant/product on both sides: **4/4** (verified with RDKit
  DetermineBonds, charge=0; a catalytic water at step 4 is stripped as a spectator).
- Front/back consistency: the main-line product of step n and reactant of step n+1 are the same species.
  Deposited as one canonical geometry per node (byte-identical MD5 in `chain_shared_nodes/`). The two
  steps' raw IRC termini optimize to that species with a conformer-only difference: glycolaldehyde-enol is
  the same minimum (0.006 kcal); fructose (0.73) and glyceraldehyde (1.62 kcal) differ only by a hydroxyl
  rotamer (barrierless; smaller than the HMF chain's 5.7 / 1.8 kcal). Canonical node uses the lower-E rotamer.

## Pre-flight checklist (verified programmatically from the deposited files)
1. **Every step has a barrier.** ΔE‡ = 35.9 / 35.1 / 31.5 / 30.4 kcal/mol (`06_final_chain/MANIFEST.json`).
2. **Every step has a TS with exactly one imaginary mode** (final NumFreq block of
   `04_orca_inp_out_hess/transition_states/step_n_TS.out`): −474.1 / **−758.1** / −942.1 / −920.1 cm⁻¹.
3. **Each node xyz matches the report.** HTML images and SMILES are rendered directly from
   `01_chain_nodes_xyz/*.xyz` (charge=0 bond perception).
4. **Raw IRC endpoints exact-match neutral reactant + product** on both sides for all 4 steps.
5. **Single-route directory.** Only this glucose→HAA route is present.

## Honest caveats for the reviewer
- Energies are **electronic** (r²SCAN-3c/CPCM water); no ZPE/thermal/Gibbs corrections yet (same as the
  HMF v3 package).
- The route is a **branching retro-aldol path** (C–C cleavages produce co-products), unlike the linear
  HMF dehydration chain. Co-products (DHA-enol, formaldehyde) are tracked and energy-accounted.
- Intermediates entering steps 3–4 are **enols** (kinetic retro-aldol products); the route explicitly
  includes the enol→keto tautomerization (step 4) to deliver keto HAA.

## Suggested points for the reviewer to check
1. Open each `02_transition_states_xyz/step_*_TS.xyz` and confirm against the matching
   `04_.../transition_states/step_*_TS.out` that the final frequency block has a single imaginary mode.
2. Confirm `03_irc_endpoints_xyz/step_n_IRC_F/B.xyz` fragment connectivity equals the adjacent nodes /
   co-products.
3. Confirm the DEFGRID3 cleanup of step 2 (single −758.1 cm⁻¹) and the conformer note for the shared nodes.
4. Visualise each `03_irc_endpoints_xyz/step_n_IRC_Full_trj.xyz` (e.g. in VMD/Jmol/Avogadro) to watch the
   complete minimum-energy path from reactant through the TS to product for every step.
