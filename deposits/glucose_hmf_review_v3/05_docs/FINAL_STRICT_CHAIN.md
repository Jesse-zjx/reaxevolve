# Glucose → HMF: complete strict QM-validated pathway

Level: ORCA r²SCAN-3c / CPCM(water), GFN2 guesses. Bar: every elementary step has
exactly ONE imaginary mode and raw IRC endpoints whose NEUTRAL canonical SMILES
exactly match the neutral reactant and product on BOTH sides (charged/zwitterionic
endpoints rejected; catalytic water allowed only as a stripped spectator).

| # | reaction kind | reactant SMILES | product SMILES | imag (cm⁻¹) | source |
|---|---|---|---|---|---|
| 1 | dehydration | `O=CC(O)C(O)C(O)C(O)CO` (open glucose, C6H12O6) | `O=CC(O)=CC(O)C(O)CO` (C6H10O5) | −1410.1 | strict_search dh1g |
| 2 | keto–enol tautomerization | `O=CC(O)=CC(O)C(O)CO` | `O=CC(=O)CC(O)C(O)CO` (C6H10O5) | −1449.8 | strict_search taut3 |
| 3 | dehydration | `O=CC(=O)CC(O)C(O)CO` | `O=CC(=O)C=CC(O)CO` (C6H8O4) | −1533.0 | strict_search dh2 |
| 4 | ring closure (retro-hemiketal) | `O=CC(=O)C=CC(O)CO` | `O=CC1(O)C=CC(CO)O1` (C6H8O4) | −1574.5 | gap1_anomeric → s4_disp (cleaned) |
| 5 | aromatizing dehydration | `O=CC1(O)C=CC(CO)O1` | `O=Cc1ccc(CO)o1` = HMF (C6H6O3) | −830.4 | gap_dehyd / hmfarom |

Mass balance: C6H12O6 − 3 H2O → C6H6O3 (steps 1, 3, 5 each lose one water; steps 2, 4 are isomerizations). The chain is connected: each step's product SMILES is the next step's reactant SMILES.

## Key methods that made the hard steps pass
- Exact-bar enforcement in `orca_xtb_workflow.classify_endpoint_match` via `EXACT_SMILES_ONLY=1` (no InChI/tautomer tolerance, no one-sided product_match).
- Dehydrations / aromatization: constrained C–O (± β-H) relaxed scan guesses, not NEB.
- Ring closure (step 4): the auto-mapper kept scanning the wrong C–O bond (giving
  M↔furanic-isomer). The fix was a TARGETED dual scan of the ANOMERIC C1–O5 bond
  (stretch) + the C1-OH proton → O5 (retro-hemiketal coordinate), which gives the
  single-mode TS whose IRC ends are exactly neutral I and M.

## Unified chained geometries (finalized)
Each of the 6 nodes was re-optimized ONCE at r²SCAN-3c/CPCM(water) to a single
canonical geometry, so the same Cartesian geometry is the product of step n and
the reactant of step n+1.  All optimized nodes reproduce the expected canonical
SMILES (verified).  Archive: `validation/cpcm_chain/final_chain/`
(`node_0_glucose.xyz … node_5_HMF.xyz`, `step_1…5_*_TS.xyz`, `water.xyz`,
`MANIFEST.json`).

### Energetics (r²SCAN-3c/CPCM(water); water reference E = −76.42865 Eh)
Node energies (Eh): glucose −687.10278, N1 −610.66216, N2 −610.67116,
I −534.22401, M −534.23563, HMF −457.82409.

Mass-balanced relative energies (kcal/mol, vs glucose, released waters included):
glucose 0.0 → N1 +7.5 → N2 +1.9 → I +13.5 → M +6.2 → HMF+3H2O −4.6
(overall glucose → HMF + 3 H2O is mildly exothermic, −4.6 kcal/mol).

Per-step forward barriers / reaction energies (kcal/mol):
| step | kind | imag cm⁻¹ | ΔE‡ | ΔE |
|---|---|---|---|---|
| 1 | dehydration | −1410 | 50.2 | +7.5 |
| 2 | keto–enol tautomerization | −1450 | 68.2 | −5.6 |
| 3 | dehydration | −1533 | 46.6 | +11.6 |
| 4 | ring closure (retro-hemiketal) | −1579 | 33.0 | −7.3 |
| 5 | aromatizing dehydration | −830 | 51.1 | −10.7 |

Rate-determining step is the keto–enol tautomerization (ΔE‡ ≈ 68 kcal/mol),
consistent with enolization being rate-limiting in thermal HMF formation.

## Independent strict verification (rule out prior failure modes)
A separate pass re-audited the finalized chain:
- **Exactly one imaginary mode per TS** (final NumFreq block): 5/5 pass. Step 4
  initially carried a spurious −34.9 cm⁻¹ soft torsion (a 2nd-order saddle); it was
  removed by displacing along that soft mode and re-optimizing → single mode −1574.5
  cm⁻¹, IRC still connecting exact I and M. (`s4_disp/`)
- **Raw IRC endpoints optimize to the exact neutral reactant and product on both
  sides**: 5/5 pass (no charged/zwitterionic/tautomer endpoints).
- **Cross-step identity (front/back endpoint consistency)**: at every shared node the
  producing step's product and the consuming step's reactant optimize to the IDENTICAL
  neutral canonical SMILES — 4/4 internal nodes + both termini. Geometrically nodes
  2 and 4 are the same minimum (ΔE < 0.4 kcal); nodes 1 and 3 share identical
  connectivity but differ by a single hydroxyl rotamer (ΔE 5.7 / 1.8 kcal, barrierless
  interconversion, no bond change); the canonical node geometry adopts the lower-energy
  conformer.
- Artifacts: `VERIFICATION.json` and `cross_step_consistency.json`, both alongside this file, plus
  `s4_disp/`.
