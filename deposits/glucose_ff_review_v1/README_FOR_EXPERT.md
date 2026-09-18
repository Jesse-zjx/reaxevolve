# Glucose → Furfural — strict QM-validated chain (v1, corrected for expert review)

**Level of theory:** ORCA 6.1.1, r²SCAN-3c / CPCM(water), **DEFGRID3 throughout** (TS OptTS+NumFreq,
IRC, and node minima). GFN2-xTB used only for TS-guess generation.

**Acceptance bar (identical to the glucose→HMF v3 deposit):** every elementary step has an OptTS with
**exactly one imaginary frequency** in the final NumFreq block, and a raw IRC whose **two endpoints, after
optimization, give the exact neutral canonical SMILES of the reactant and the product** (charged /
zwitterionic / tautomer endpoints rejected). The **product of step n and the reactant of step n+1 are the
same species**. **No catalytic/phantom water anywhere** — every step is either a neutral↔neutral
isomerization (same atom count) or a real dehydration (water counted as a product).

## Correction addressing the expert's step-5 comment
The earlier draft's step 5 (C5-enediol → xylose) used a **catalytic water** (23-atom TS whose IRC endpoints
both carried an H₂O). Since step 4 (retro-aldol) produces **no** water, that water had no provenance and
steps 4↔5 did not connect. We verified by QM that the *dry* C5-enediol→xylose 1,3-H shift collapses to a
**zwitterion** (not neutral xylose) — i.e. that terminal enediol→aldose intrinsically needs a water shuttle.
It is therefore replaced by **two dry, HMF-clean steps** that route through the 2-ketopentose:

- **step 5**: C5-enediol → **D-xylulose** (enediol→ketose; forms an *internal* C=O — clean neutral, exactly
  the motif of HMF's own dry tautomerization step 2). Single imaginary −1630.0 cm⁻¹.
- **step 6**: D-xylulose → D-xylose (ketose→aldose isomerization; concerted hydride+proton shift — the same
  transformation class as the validated glucose→fructose step 1). Single imaginary −766.5 cm⁻¹.

Both are 20-atom neutral↔neutral with exact-SMILES IRC endpoints and **zero catalytic water**, so the whole
chain is now atom-count continuous end to end.

## The route (11 elementary steps; C6 → C1 + C5 retro-aldol bridge, then ketopentose→furfural cascade)

| # | reaction | reactant → product | imag (cm⁻¹) | ΔE‡ | ΔE |
|---|---|---|---|---|---|
| 1 | aldose–ketose isomerization | open-glucose → open-fructose | −434.7 | 34.5 | −2.1 |
| 2 | enolization | → D-fructose 2,3-enediol | −2042.5 | 62.7 | +4.1 |
| 3 | ketonization | → 3-ketohexose | −2032.5 | 61.0 | −3.6 |
| 4 | **retro-aldol C–C cleavage** | → C5 enediol **+ HCHO** | −932.3 | 29.8 | +28.7 |
| 5 | **enediol→ketose (dry)** | → **D-xylulose** `O=C(CO)C(O)C(O)CO` | −1630.0 | 57.3 | −7.9 |
| 6 | **ketose→aldose isomerization** | → **D-xylose** `O=CC(O)C(O)C(O)CO` | −766.5 | 38.5 | +2.9 |
| 7 | dehydration | → xylo 3-deoxy-enol (+H₂O) | −1459.8 | 48.3 | +0.3 |
| 8 | keto–enol tautomerization | → 3-deoxyxylosone | −2137.8 | 67.8 | +2.6 |
| 9 | dehydration | → xylo unsat. dicarbonyl (+H₂O) | −1541.1 | 43.4 | +10.1 |
| 10 | ring closure (hemiketal) | → furanic hemiketal | −1621.5 | 36.3 | −6.0 |
| 11 | aromatizing dehydration | → furfural (+H₂O) | −872.9 | 50.0 | −11.3 |

Overall C₆H₁₂O₆ → furfural (C₅H₄O₂) + HCHO + 3 H₂O, ΔE = **+17.8 kcal/mol** (electronic energy only;
the retro-aldol fragmentation dominates the endothermicity; releasing four small molecules makes it
entropically driven). Rate-determining: the 3-deoxyxylosone keto–enol tautomerization (ΔE‡ ≈ 67.8), the
same rate-limiting motif and barrier as the glucose→HMF chain (68.2).

## Directory layout (identical scheme to glucose_hmf_review_v3)
- `00_report/` — self-contained HTML report (open in a browser); molecule images are RDKit renderings of
  the canonical neutral SMILES of the deposited node `.xyz` files.
- `01_chain_nodes_xyz/` — the **12** canonical node geometries (DEFGRID3-optimized minima).
- `02_transition_states_xyz/` — the **11** transition states (each single imaginary mode).
- `03_irc_endpoints_xyz/` — per-step IRC forward/backward endpoints (+ trajectories).
- `04_orca_inp_out_hess/` — ORCA `.inp`/`.out`/`.hess` for every TS + IRC `.out`.
- `05_docs/` — `FINAL_STRICT_CHAIN.md`, `VERIFICATION.json`, `cross_step_consistency.json`,
  `energetics_manifest.json`, and `build_scripts/` (assembly + `self_check.py`).
- `06_final_chain/` — the assembled chain (canonical nodes + clean TSs + `MANIFEST.json`).

## Independent verification (`05_docs/build_scripts/self_check.py`, reads ONLY the deposited files)
```
SINGLE-IMAGINARY: 11/11    STRICT-IRC: 11/11
deposited: 12 nodes, 11 transition states
VERDICT: PASS (HMF-parity)
```
- Exactly one imaginary mode per TS: **11/11**.
- IRC endpoints = exact neutral reactant/product on both sides: **11/11** (no water on any endpoint).
- Front/back endpoint identity (product of step n ≡ reactant of step n+1): **10/10 internal nodes + both
  termini** (`cross_step_consistency.json`, `all_consistent: true`).

## Suggested points for the reviewer to check
1. Confirm the new steps 5–6 (`step_5_ketonization`, `step_6_isomerization`) have single imaginary modes and
   that their IRC endpoints are the neutral C5-enediol / D-xylulose / D-xylose (no water) — this is the fix
   to the step-4↔5 connectivity issue.
2. Open each `02_transition_states_xyz/step_*_TS.xyz` against the matching `04_.../*_TS.out` frequency block.
3. Confirm the retro-aldol step 4 IRC splits into C5-enediol + formaldehyde (no water) on the product side.
