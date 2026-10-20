# Targets and budget

Human-set campaign bounds. Agents may not change this file. It is not part of the
acceptance criterion — that is `policy/acceptance/STRICT.md` (v5) and nothing else.

Budget knobs are **operational**. They may be revised when measured wall-clock or
core-hour costs make the previous cap produce only timeout verdicts, i.e. no learning
signal. Revising a budget is not an evolution event and is not recorded as one.

## Product targets

| Target | SMILES | Carbon | Role |
|---|---|---|---|
| HMF | `O=Cc1ccc(CO)o1` | C6 | Furanic product, carbon-preserving from glucose |
| HAA | `O=CCO` | C2 | C–C cleavage product (retro-aldol branch) |
| Furfural (FF) | `O=Cc1ccco1` | C5 | Pentose branch after one carbon is lost |

Two of the three targets change the carbon count, so **no filter in this repository may
assume a carbon-preserving route**. An earlier single-target campaign used a
seed→target dehydration ladder (species must be C6H(12−2k)O(6−k)); that filter is
deliberately absent here because it would discard every HAA and furfural intermediate.
Progress toward targets is measured by `strict_distance_to_targets` in
`scripts/graph/build_reaction_network.py`.

## Seed nodes

| Role | Species | SMILES |
|---|---|---|
| Start | glucose, cyclic | `OCC1OC(O)C(O)C(O)C1O` |
| Start | glucose, open | `O=CC(O)C(O)C(O)C(O)CO` |

Xylose (cyclic and open) is used to prime the template frontier for the pentose branch.
Priming the frontier is not an accepted edge: a route still has to be built out of
STRICT steps from a glucose seed.

## Feasibility gate (single, target-independent)

| Gate | Rule | Where |
|---|---|---|
| Mass balance | reactant atoms == product + coproduct, allowing one implicit H2O | `loop/mass_balance.py`, enforced in `scripts/graph/add_hypothesis.py` |

Atom conservation is arithmetic over the reactant and product a proposal already
states. It supplies no mechanism, it applies to any target, and it is not part of
acceptance. Its purpose is to stop QM being spent on steps whose IRC could never
connect the stated endpoints.

## Budget defaults (loop)

| Knob | Default | Meaning |
|---|---|---|
| Core-hour cap | 10000 | Cumulative hard stop |
| Per-guess wall time | 5400 s | Abandon a guess if exceeded |
| Default nprocs | 16 | DFT/xTB parallel width per job |
| Template candidates landed / round | 24 | `--template-top` |
| LLM hypotheses requested / round | 4 | `--llm-top` |
| Candidates considered / round | 8 | `--top` |
| Candidates validated / round | 4 | `--cap` |
| Max attempts / candidate edge | 3 | `--max-attempts`; >1 is what makes "the same edge passed after the asset changed" observable |
| Saturation stop | K=3, ε=5% | The **preregistered** criterion (`preregistration/panel.json`), evaluated by `loop/saturation.py`. Reports which of the two conditions fired. |
| Idle stop | 3 rounds | Operational brake only: no new STRICT edge **and** no asset revision. Not the preregistered criterion, and logged as a distinct reason. |
| Success stop | all targets | `--stop-on-targets all\|any\|never` |

The distinction between the last two matters. Stopping because relative growth fell below ε is a
statement about diminishing returns; stopping because nothing happened for three rounds is a
statement about the run. Only the first licenses freezing the asset set for the fixed-asset
comparison, and the loop records which one ended it.

## QM floor is human-set, not evolved

The starting QM ladder — GFN2-xTB OptTS → r²SCAN-3c OptTS+NumFreq → r²SCAN-3c IRC, at
the level fixed in `policy/qm_protocol/PROTOCOL.md` — is **human-set starting
capability**. It is not an evolved finding and must never be reported as one. Reflect
may revise `tools/workflow/run_qm_step.py` under the usual snapshot discipline, but the
functional, basis, solvation model and thermochemistry are pinned by policy and are
outside the editable surface.

## Stop conditions (any one)

1. Every target in the table above has a STRICT route from a glucose seed
   (`--stop-on-targets any` to stop at the first).
2. Cumulative QM core-hours >= the cap.
3. The preregistered saturation rule fires: for each of the last K=3 rounds, relative growth in
   accepted edges is below ε=5%, or there is no growth at all for all K. The diagnostic panel is
   re-measured at the same time. Rule and panel: `preregistration/`.
4. `--idle-stop` consecutive rounds with neither a new STRICT edge nor an asset revision
   (operational brake).
