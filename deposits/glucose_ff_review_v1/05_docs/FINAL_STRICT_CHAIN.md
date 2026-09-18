# Glucose -> Furfural - final strict chain (v1, corrected: no catalytic water)

Level: **r2SCAN-3c/CPCM(water), DEFGRID3**. GFN2-xTB only for TS guesses.

## Nodes (DEFGRID3-optimized minima)

| idx | name | SMILES | E (Eh) |
|---|---|---|---|
| 0 | node_0_open_glucose | `O=CC(O)C(O)C(O)C(O)CO` | -687.102179 |
| 1 | node_1_open_fructose | `O=C(CO)C(O)C(O)C(O)CO` | -687.105489 |
| 2 | node_2_fructose_23enediol | `OCC(O)=C(O)C(O)C(O)CO` | -687.098987 |
| 3 | node_3_3ketohexose | `O=C(C(O)CO)C(O)C(O)CO` | -687.104645 |
| 4 | node_4_C5_enediol | `OC=C(O)C(O)C(O)CO` | -572.572722 |
| 5 | node_5_xylulose | `O=C(CO)C(O)C(O)CO` | -572.585354 |
| 6 | node_6_open_xylose | `O=CC(O)C(O)C(O)CO` | -572.580737 |
| 7 | node_7_xylo_3deoxy_enol | `O=CC(O)=CC(O)CO` | -496.151611 |
| 8 | node_8_3deoxyxylosone | `O=CC(=O)CC(O)CO` | -496.147418 |
| 9 | node_9_xylo_dicarbonyl_ene | `O=CC(=O)C=CCO` | -419.702654 |
| 10 | node_10_furanic_hemiketal | `O=CC1(O)C=CCO1` | -419.712226 |
| 11 | node_11_furfural | `O=Cc1ccco1` | -343.301625 |

water E = -76.428657 Eh; formaldehyde E = -114.486154 Eh

## Steps

| # | reaction | imag (cm-1) | dE‡ | dE | coproduct |
|---|---|---|---|---|---|
| 1 | aldose-ketose isomerization | -434.6 | 34.5 | -2.1 | - |
| 2 | keto-enol enolization | -2042.5 | 62.7 | 4.1 | - |
| 3 | enol-keto ketonization | -2032.5 | 61.0 | -3.6 | - |
| 4 | retro-aldol C-C cleavage | -932.3 | 29.8 | 28.7 | C=O |
| 5 | enediol->ketose (dry) | -1630.0 | 57.3 | -7.9 | - |
| 6 | ketose-aldose isomerization | -766.5 | 38.5 | 2.9 | - |
| 7 | dehydration | -1459.8 | 48.3 | 0.3 | O |
| 8 | keto-enol tautomerization | -2137.8 | 67.8 | 2.6 | - |
| 9 | dehydration | -1541.1 | 43.4 | 10.1 | O |
| 10 | ring closure (hemiketal) | -1621.5 | 36.3 | -6.0 | - |
| 11 | aromatizing dehydration | -872.9 | 50.0 | -11.3 | O |

**Overall** C6H12O6 -> furfural + HCHO + 3 H2O: dE = 17.8 kcal/mol (electronic).
Rate-determining: step 8 keto-enol tautomerization (dE‡ ~= 67.8 kcal/mol).

## Key correction vs earlier draft

The earlier draft's step 5 (C5-enediol -> xylose) used a **catalytic water** (23-atom TS) that had no
provenance from step 4 (which produces no water) - the expert correctly flagged that steps 4 and 5 did
not connect. It is now replaced by **two DRY, HMF-clean elementary steps with NO catalytic water**:
- step 5: C5-enediol -> **D-xylulose** (enediol->ketose ketonisation; internal C=O, clean neutral, like HMF step 2)
- step 6: D-xylulose -> D-xylose (ketose-aldose isomerisation; concerted hydride+proton shift, like glucose->fructose)
Both are 20-atom neutral<->neutral, single imaginary, exact-SMILES IRC. The chain is now fully continuous
(product of step n == reactant of step n+1) with zero phantom water.

## Strictness summary

- single imaginary per TS: 11/11
- IRC exact neutral-SMILES double-end: 11/11
- front/back node identity: 10/10 internal + termini
