# Bar-resolution negative control (preregistered)

**Status**: run. This document was committed before the calculation (`79442bb`), because a control
whose expected outcome is decided afterwards is not a control. Result:
`experiments/bar_resolution/RESULT.md` — all three candidates landed in outcome **A**, and none of
the prohibitions below were exercised.

Fills the gap `evidence/controls.md` names about itself: the positive control shows the bar
accepts a known-good transition state, and negative control B measures how hard the guessing
problem is, but nothing yet shows the bar **rejects a method that should fail**. Without that,
"every accepted edge met the bar" is consistent with a bar that accepts almost anything.

## The probe

Take one deposited step whose correct saddle is known, and reach it with a deliberately naive
method: uniform linear interpolation between reactant and product geometries, with no
reaction-coordinate reasoning. Then submit the result to the unmodified acceptance path.

| | |
|---|---|
| Step | `O=C(CO)C(O)C(O)C(O)CO` → `OCC(O)=C(O)C(O)C(O)CO` |
| Chemistry | keto → enol enolization, intramolecular proton transfer |
| Provenance | step 2 of `deposits/glucose_ff_review_v1` |
| Deposited saddle | −2042.5 cm⁻¹, single imaginary mode |
| Coproduct | none (dry: clause 4's discrete-water test cannot confound the outcome) |
| Guess method | `tools/guess/auto_guess.py` — reaction-agnostic linear interpolation, fractions 0.35 / 0.50 / 0.65 |
| Validation | `tools/workflow/run_qm_step.py` unmodified: xTB OptTS → r²SCAN-3c OptTS+NumFreq → IRC → `policy/acceptance/check_strict_bar` |
| Budget | 16 cores, 5400 s per guess, 3 guesses; order 5 core-hours |

**Why this step.** The true saddle is a proton transfer with a very strong single mode. Uniform
interpolation moves every atom by the same fraction, so it does not place the migrating hydrogen
near the midpoint of the donor–acceptor axis — the one coordinate that matters here. It is dry,
so no water clause is involved. And it is deposited, so the right answer is known exactly rather
than inferred.

**It is neither a C2 route step nor a diagnostic panel edge** (`preregistration/panel.json`), so
running it perturbs neither the comparison task nor the saturation baseline.

## Outcomes, declared in advance

| | Observation | Reading |
|---|---|---|
| **A** | multiple imaginary modes, or only soft modes, or IRC endpoints that are not exactly the neutral reactant and product | **Expected.** The bar rejected a naive method. The bar has resolution on this step. |
| **B** | exactly one imaginary mode **and** IRC endpoints exactly R and P | The bar accepted — correctly, because the naive guess actually solved the step. This is **not** evidence against the bar; it makes the control inconclusive here, and a different step is needed. Report as inconclusive, do not re-roll quietly. |
| **C** | OptTS does not converge, or the run crashes, or the wall clock is hit | No information about the bar. Report as a run failure, not as a control result. |

**What would falsify the bar**: acceptance of a candidate whose raw IRC endpoints are not the
stated neutral reactant and product. That is the failure mode this control exists to look for,
and outcome A must be checked to be a *rejection for the stated reason*, not a rejection for an
unrelated one — the recorded failure mode is reported alongside.

## Prohibitions

- No tuning of the interpolation fractions after seeing a result.
- No switching to a targeted guess method: the point of the probe is that the method is naive.
- No substituting a different step on the grounds that this one returned B. Outcome B is a
  reportable result; a second step may be added, with both reported.
- No edit to `policy/` or to the acceptance implementation for the duration.
