# TSBench lane (supplementary)

Everything in this directory except this file is gitignored. Nothing here is part of the
main loop, and no number produced here may be combined with a STRICT count.

## What this lane is for

TSBench is a 78-reaction benchmark that asks an agent to build a 3D transition-state
structure from a reactant/product specification, then verifies it with an automated
pipeline (TS optimisation → frequency analysis → bidirectional IRC → endpoint SMILES
match), returning failures to the agent for a diagnosis-driven revision round. It ships
546 published per-evaluation records across seven models with a three-round budget.

Two reasons it is the right supplementary evaluation here:

1. **The initial asset set came from it.** `assets/initial/.skills/generate-ts-guesses`
   and `.../diagnose-ts-failures` are TSBench's two fixed skills, and
   `assets/initial/tools/geometry/*` plus `record_update.py` are its tool set. The left
   arm of the fixed-asset comparison is therefore a published baseline rather than
   something reconstructed for the paper.
2. **TSBench's own loop does not evolve its skills.** It runs two fixed skills for three
   rounds. So "same reactions, same model, same validator, three rounds, with asset
   revision switched on" is a comparison whose only variable is the Reflect loop.

## Two experiments, in this order

**A — transfer.** Run the initial asset set and the final asset set over the benchmark,
three rounds each, and compare. Cheap: no new evolution, small gas-phase molecules.
A negative result is informative and reportable — the final skills were shaped on aqueous
sugar chemistry, so per-subset reporting (simple / intermediate / complex) is the honest
granularity.

**B — controlled evolution.** Run the full loop with Reflect enabled on one subset and
evaluate on the others, against the published per-subset baseline. Split by subset, never
evolve and report on the same reactions, and cap at three rounds for any comparison
against published numbers.

Do **not** hand-edit the evolved skills to suit these reactions. That converts a held-out
benchmark into a tuning set and discards the one property this lane depends on.

## Acceptance in this lane is TSBench's, not STRICT

| | Main loop | This lane |
|---|---|---|
| Criterion | `policy/acceptance/STRICT.md` v5 | TSBench: single imaginary frequency + bidirectional IRC endpoints match the target pair |
| Level | r²SCAN-3c / CPCM(water) / DEFGRID3 | GFN2-xTB through ORCA's XTB interface |
| Species | neutral, closed-shell, aqueous | includes charged species and non-singlet multiplicities |

STRICT v5 requires neutral endpoints, so a large part of the benchmark could never be
scored under it. The two criteria answer different questions and their counts must never
be added, averaged, or presented on one axis.

## Local checkout

The corpus is not vendored. Point the lane at a local clone:

```bash
export TSBENCH_ROOT=/path/to/TSBench-main     # holds benchmark/, files/, results/
export ORCA_CMD="$(command -v orca)"
export XTBEXE=/path/to/xtb
```

TSBench needs a cclib patch for ORCA 6.1.1 xTB output and a coding-agent CLI launcher;
both are documented in its own README. It is MIT licensed — cite it when reporting any
number from this lane.

## Isolation

`benchmark/` and `results/` hold the reaction manifest, reference transition states, and
published scores. The main loop must never read them:
`scripts/qa/isolation_audit.py` treats those paths as violations and runs every Reflect
round, so "the evolved assets never saw the evaluation set" is a checked property rather
than an assurance. This lane is exempt because reading them is its whole purpose, which
is why it lives outside the audited tree.

## Convention for supplementary work

Any evaluation that is not the main campaign follows this pattern: its own top-level
directory, contents gitignored, a tracked `README.md` stating its acceptance criterion
and why its numbers are not comparable to STRICT, and no imports from it into `loop/`.
