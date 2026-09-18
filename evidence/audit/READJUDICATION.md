# READJUDICATION — STRICT(v5)

Pinned edges: **30**
- pass: **30**
- fail: **0**
- unresolved (missing final geometry): **0**
- repair candidates: **7**

## Judgement-source priority
deposits/*/04_orca_inp_out_hess > runs final cleanup > verdict records

## Per-edge

| edge | source | pass | imag | water | new_status | notes |
|---|---|---|---|---|---|---|
| `O=C(C(O)CO)C(O)C(O)CO>>O=C(C=C(O)CO)C(O)CO` | record | True | -1873.3 | None | STRICT | no final geometry artifacts found — cannot hard-fail from record alone; provisio |
| `O=C(C(O)CO)C(O)C(O)CO>>OC=C(O)C(O)C(O)CO` | deposit | True | -932.3 | no bilateral H2O fragments | STRICT |  |
| `O=C(C=C(O)CO)C(O)CO>>O=C(CO)CC(=O)C(O)CO` | record | True | -1810.3 | None | STRICT | no final geometry artifacts found — cannot hard-fail from record alone; provisio |
| `O=C(CO)C(O)C(O)C(O)CO>>O=C(CO)C(O)=CC(O)CO` | record | True | -1454.6 | None | STRICT | no final geometry artifacts found — cannot hard-fail from record alone; provisio |
| `O=C(CO)C(O)C(O)C(O)CO>>O=CC(O)CO` | deposit | True | -758.1 | no bilateral H2O fragments | STRICT |  |
| `O=C(CO)C(O)C(O)C(O)CO>>OC=C(O)C(O)C(O)C(O)CO` | record | True | -2252.3 | None | STRICT | no final geometry artifacts found — cannot hard-fail from record alone; provisio |
| `O=C(CO)C(O)C(O)C(O)CO>>OCC(O)=C(O)C(O)C(O)CO` | deposit | True | -2042.5 | no bilateral H2O fragments | STRICT |  |
| `O=C(CO)C(O)C(O)CO>>O=C(C=C(O)CO)CO` | record | True | -1995.8 | None | STRICT | no final geometry artifacts found — cannot hard-fail from record alone; provisio |
| `O=C(CO)C(O)C(O)CO>>O=CC(O)C(O)C(O)CO` | deposit | True | -766.5 | no bilateral H2O fragments | STRICT |  |
| `O=C(CO)C(O)C(O)CO>>O=CCO` | deposit | True | -540.8 | no bilateral H2O fragments | STRICT |  |
| `O=CC(=O)C=CC(O)CO>>O=CC1(O)C=CC(CO)O1` | deposit | True | -1574.5 | no bilateral H2O fragments | STRICT |  |
| `O=CC(=O)C=CCO>>O=CC1(O)C=CCO1` | deposit | True | -1621.5 | no bilateral H2O fragments | STRICT |  |
| `O=CC(=O)CC(O)C(O)CO>>O=CC(=O)C=CC(O)CO` | deposit | True | -1533.0 | no bilateral H2O fragments | STRICT |  |
| `O=CC(=O)CC(O)CO>>O=CC(=O)C=CCO` | deposit | True | -1541.1 | no bilateral H2O fragments | STRICT |  |
| `O=CC(O)=CC(O)C(O)CO>>O=CC(=O)CC(O)C(O)CO` | deposit | True | -1449.8 | no bilateral H2O fragments | STRICT |  |
| `O=CC(O)=CC(O)CO>>O=CC(=O)CC(O)CO` | deposit | True | -2137.8 | no bilateral H2O fragments | STRICT |  |
| `O=CC(O)C(=O)CC(O)CO>>O=CC(=O)C(O)CC(O)CO` | runs | True | -827.4 | no bilateral H2O fragments | STRICT |  |
| `O=CC(O)C(O)=CC(O)CO>>O=CC(O)C(=O)CC(O)CO` | record | True | -2051.1 | None | STRICT | no final geometry artifacts found — cannot hard-fail from record alone; provisio |
| `O=CC(O)C(O)C(O)C(O)CO>>O=C(CO)C(O)C(O)C(O)CO` | deposit | True | -434.6 | no bilateral H2O fragments | STRICT |  |
| `O=CC(O)C(O)C(O)C(O)CO>>O=CC(O)=CC(O)C(O)CO` | deposit | True | -1410.1 | no bilateral H2O fragments | STRICT |  |
| `O=CC(O)C(O)C(O)CO>>O=CC(O)=CC(O)CO` | deposit | True | -1459.8 | no bilateral H2O fragments | STRICT |  |
| `O=CC(O)CO>>OC=CO` | deposit | True | -942.1 | no bilateral H2O fragments | STRICT |  |
| `O=CC1(O)C=CC(CO)O1>>O=Cc1ccc(CO)o1` | deposit | True | -830.4 | no bilateral H2O fragments | STRICT |  |
| `O=CC1(O)C=CCO1>>O=Cc1ccco1` | deposit | True | -872.9 | no bilateral H2O fragments | STRICT |  |
| `O=CCC=O>>O=CC=CO` | runs | True | -1884.8 | no bilateral H2O fragments | STRICT |  |
| `OC1CO1>>O=CCO` | record | True | -479.8 | None | STRICT | no final geometry artifacts found — cannot hard-fail from record alone; provisio |
| `OC=C(O)C(O)C(O)CO>>O=C(CO)C(O)C(O)CO` | deposit | True | -1630.0 | no bilateral H2O fragments | STRICT |  |
| `OC=C1C=CC(O)(CO)O1>>O=CC1=CCC(O)(CO)O1` | runs | True | -1532.9 | no bilateral H2O fragments | STRICT |  |
| `OC=CO>>O=CCO` | deposit | True | -920.1 | catalytic shuttle O8: H[9, 10] ↔ H[4, 10] | STRICT | catalytic water shuttle allowed: catalytic shuttle O8: H[9, 10] ↔ H[4, 10] |
| `OCC(O)=C(O)C(O)C(O)CO>>O=C(C(O)CO)C(O)C(O)CO` | deposit | True | -2032.5 | no bilateral H2O fragments | STRICT |  |

## Zero-compute water-clause scan (rejected pool)

Attempts with spectator/water-mediated markers among non-STRICT verdicts: **0**

**Null result:** no rejected attempt appears to have failed solely on the water clause. Relaxing the water rule therefore does not unlock a hidden rejected pool; the two catalytic-shuttle edges that benefit under v5 were already in the STRICT/deposit set.

strict_version: `v5`
