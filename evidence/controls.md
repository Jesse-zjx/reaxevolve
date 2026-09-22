# Positive / negative controls for the STRICT bar

These controls measure **whether the acceptance bar can tell a known-good method from a
should-fail method**. They are **not** skill-utility benchmarks and must not be folded into
main figure 2.

Campaign configuration for the from-SMILES reproduction (see `experiments/rediscovery/run_shard.py`):
**NPROCS=4** per job, up to 8 sequential shards on a 32-core host. Wall times below are
seconds of wall clock as recorded in `experiments/rediscovery/results/*.json` or
`experiments/rediscovery/comparison.json`.

## Positive control (ceiling) — start from a deposited TS geometry

**Definition:** take the already-converged OptTS geometry from a deposit, re-run NumFreq + IRC
under the current bar. Expected: PASS (single imag, exact neutral endpoints).

**What we have today**

| Evidence | Result |
|---|---|
| `policy/acceptance/check_strict_bar.py --deposit glucose_hmf_review_v3` (STRICT v5) | 5/5 |
| `policy/acceptance/check_strict_bar.py --deposit glucose_ff_review_v1` | 11/11 |
| `policy/acceptance/check_strict_bar.py --deposit glucose_haa_review_v1` (STRICT v5) | **4/4** (s4 catalytic shuttle allowed) |
| `check_strict_bar.py --deposit glucose_haa_review_v2` | 6/6 |

The deposits are themselves the existence proof of the ceiling: when the guess **is** the
accepted saddle, the bar accepts it. The from-SMILES reproduction campaign below deliberately
**does not** feed deposited geometries — it regenerates guesses — so it is not this positive
control.

## Negative control A — archived

Moved to `evidence/archive/controls_negative_A_water_relay.md`.

Those six `force_water` attempts never located a TS (`imag_got/all/n_imag = None`), so they
do not discriminate the water clause. The bar-resolution gap this note used to flag is filled by
negative control C below.

## Negative control B — from-SMILES reproduction without deposited TS (hard baseline)

**Definition:** regenerate guesses from R/P SMILES only (no deposited TS), same ORCA bar.
This is a difficult baseline for tools, not a “should always fail” control; report it as the
observed pass rate of the guessing stack.

Source: `experiments/rediscovery/comparison.json` (20 deposit steps). The per-step table is
generated from it in `experiments/rediscovery/REPRODUCTION_REPORT.md` — prefer that over the
abbreviated buckets below, which are a summary.

| outcome bucket | n | ids (abbrev.) |
|---|---|---|
| STRICT | 7 | HMF_s2, HMF_s3, HMF_s5, HAA_s1, FF_s1, FF_s7, FF_s9 |
| PARTIAL_MATCH | 1 | FF_s2 |
| NOT_CLEAN_TS / MISMATCH / TIMEOUT | 12 | remaining |

Aggregate wall (from the `wall` field in `experiments/rediscovery/comparison.json`, seconds): sum ≈ 1.6×10⁵ s wall
across 20 jobs at NPROCS=4 → order **~180 CPU-h** for the full 20-step from-SMILES pass
(exact per-step walls in that file).

**Read as:** 7/20 from-SMILES recoveries at NPROCS=4 show the tools are neither trivial nor
useless; the 13 misses are the cost of refusing deposited geometries. Do not cite this as
“the system fails” — cite it as the hardness of the guessing problem under the strict bar.

## Negative control C — bar resolution under a naive guess (run)

**Definition:** reach a deposited dry saddle by uniform linear interpolation, a method with no
reaction-coordinate reasoning, and submit the result to the unmodified acceptance path. Design
and the three outcomes, declared before the calculation:
`preregistration/bar_resolution_probe.md`. Result, generated from the verdict records:
`experiments/bar_resolution/RESULT.md`.

Step: `O=C(CO)C(O)C(O)C(O)CO` → `OCC(O)=C(O)C(O)C(O)CO`, keto → enol proton transfer, deposited
saddle −2042.5 cm⁻¹ (`deposits/glucose_ff_review_v1` step 2). Neither a C2 route step nor a
diagnostic panel edge, so running it perturbs neither.

**Read as:** the bar rejected the naive candidates, and — the more informative part — it rejected
them on the endpoint clause rather than on the frequency count. The candidates were clean
single-mode saddles, just not the ones connecting the stated reactant and product. A bar that
asked only "is this a proper transition state?" would have accepted them. This is the evidence
that the IRC endpoint criterion is what carries the weight.

This control also found a defect in the acceptance path, which is part of what it was worth
running for: an IRC endpoint whose fragments RDKit cannot perceive made `endpoint_matches` raise
instead of reject, because the guard for that case sat behind a `sorted()` that could not order
`None`. In the loop a crash there means the attempt yields **no verdict at all** — it counts as
neither an accepted edge nor a rejection, and the compute leaves nothing to learn from. Fixed,
with the invariant pinned by `scripts/qa/test_endpoint_match.py`; the fix cannot change any
accept/reject decision, since unperceivable endpoints were already specified as rejections.

## How to use in the outline

- Methods / §3.5: positive control + neg B measure ceiling and guessing hardness; neg C measures
  bar resolution and identifies the endpoint clause as the one doing the work.
- Do **not** merge into main figure 2’s cumulative STRICT curve.
