# reaxevolve

A role-decomposed agentic system that expands and validates a quantum-chemical reaction
network for the aqueous valorization of glucose, and revises its own reusable Skills and
Tools from the structured feedback those calculations produce.

Human-set boundaries: the product targets, the compute budget, and a single
delivery-grade acceptance criterion. Everything else — which candidate steps to propose,
how to guess a transition state, what to spend the next core-hour on — is decided by the
editable asset surface, and that surface is what evolves.

```
Explore ──▶ Validate ──▶ Remember ──▶ Reflect ──┐
   ▲                                            │
   └────────────── revised Skills / Tools ◀──────┘
```

Network growth is a by-product of looking for deliverable routes. There is no second
driver and no batch expansion mode.

## What is fixed and what evolves

| | Contents | Evolvable |
|---|---|---|
| `policy/` | STRICT(v5) acceptance clauses, QM protocol, targets and budget | **no** |
| `scripts/` | graph writer, verdict writer, evidence parsers, evolution bookkeeping, QA | **no** |
| `loop/` | the four stages and their scheduling | **no** |
| `.skills/` | declarative domain workflows | yes |
| `tools/` | guess generators, the candidate enumerator and its scoring, screens, QM workflow | yes |

A revision can change what gets proposed and in what order. It cannot change what counts
as a pass: edge status is written only by `scripts/validate/verdict_writer.py` under
`policy/acceptance/STRICT.md`, so a bad template or a bad weight costs compute and cannot
manufacture a verdict. Every revision is snapshotted and appended to
`evolution/EVOLUTION_LOG.jsonl` before it lands; every attempt records the full asset
version vector from `tools/VERSIONS.json`.

## Acceptance

**STRICT (v5)** — `policy/acceptance/STRICT.md` plus its single implementation
`policy/acceptance/check_strict_bar.py`. Four clauses per elementary step: r²SCAN-3c /
CPCM(water) level; exactly one imaginary frequency; raw IRC endpoints optimise to the
exact neutral reactant and product; atom-conserving and geometrically chained, with the
discrete-water rule distinguishing a catalytic proton shuttle from a spectator water.

There is no second bar. Driver early-exits are compute throttles and never emit a status.

## Targets

Glucose → HMF, glycolaldehyde (HAA), furfural. Two of the three change the carbon count,
so nothing in this repository assumes a carbon-preserving route. Full statement:
`policy/targets_and_budget.md`.

## Layout

| Path | Contents |
|---|---|
| `policy/` | Human-set boundaries. Not evolvable. |
| `loop/` | `run_loop.py` (Explore→Validate→Remember→Reflect), the two Explore paths, candidate selection, the mass-balance gate, `fully_auto/` for applying Reflect revisions |
| `.skills/`, `tools/` | The live editable asset surface |
| `assets/initial`, `assets/final` | Frozen asset sets for the fixed-asset comparison |
| `scripts/` | Non-evolvable machinery: `graph/`, `validate/`, `reflect/`, `viz/`, `qa/`, `smoke_test.py` |
| `evolution/` | Pre-change snapshots, `EVOLUTION_LOG.jsonl`, `ASSET_RENAMES.json` |
| `graph/` | Graph Memory: `canonical/` state, `caches/`, `derived/` views |
| `evidence/` | Experience Memory, loop state, audits, archives |
| `deposits/` | Expert-confirmable delivery packages |
| `experiments/rediscovery/` | Rebuilding the delivered routes from SMILES alone — the hard baseline |
| `preregistration/` | Saturation rule and the fixed-asset comparison protocol |
| `docs/paper`, `docs/adr` | Method contract, outline, decision ledger, architecture decisions |
| `tsbench/` | Supplementary transfer evaluation. Separate acceptance criterion; see its README |
| `runs/` | QM scratch (gitignored) |

## Explore has two paths

Path A enumerates the confirmed frontier with reaction templates: deterministic,
atom-conserving by construction, broad, and free of model tokens. It runs first.

Path B is then given path A's coverage report and asked for the complement — steps the
template SMARTS cannot express (concerted aromatization, hydride shifts, skeletal
rearrangements), preferentially from species where path A has run out of options.

Both write through `scripts/graph/add_hypothesis.py`, so both pass the same
atom-conservation gate and land in one queue with one schema. Selection afterwards does
not care which path produced a candidate, only what it scored.

## Getting started

```bash
cp .env.example .env          # only needed for the LLM Explore path and Reflect
npm install                   # pins the project-local pi CLI

python scripts/smoke_test.py                      # no DFT, no API
python loop/run_loop.py --dry-run                 # stage wiring only
python loop/mass_balance.py                       # audit the graph for conservation
python loop/select_candidates.py --top 8          # what the next round would compute
```

One command that clones this repository and checks everything a reader receives — deposits
verify as built, the accepted count re-derives from the shipped evidence, the network agrees
with the audited pin, every documented path resolves, the generated reports match their data,
and the loop wires up. No DFT, no API:

```bash
bash scripts/qa/verify_clone.sh
```

Reading the evidence without running anything:

```bash
python policy/acceptance/check_strict_bar.py --deposit deposits/<name>   # as-built, per step
python scripts/graph/build_reaction_network.py                           # re-derive the counts
python scripts/qa/check_doc_paths.py                                     # every documented path resolves
cat evidence/state/NETWORK_STATE.md                                      # the only source for counts
cat evidence/controls.md                                                 # does the bar have resolution?
cat experiments/rediscovery/REPRODUCTION_REPORT.md                       # from SMILES alone
cat evolution/EVOLUTION_LOG.md                                           # what changed, on what evidence
```

Spending real CPU to prove the toolchain works end to end (needs ORCA and xTB):

```bash
python scripts/qm_smoke.py     # r²SCAN-3c / CPCM(water) on a molecule that finishes in seconds
```

A real round spends ORCA and API budget:

```bash
python loop/run_loop.py --rounds 24 --budget-hours 10000 \
    --top 8 --cap 4 --nprocs 16 --wall-s 5400 --fully-auto
```

`--no-llm` restricts Explore to the template path (no API spend). `--stop-on-targets any`
stops at the first target instead of requiring all three.

## Requirements

ORCA 6.1.1 and xTB 6.7.1 for validation; Python ≥ 3.10 with RDKit and NetworkX; Node ≥ 20
for the project-local `pi` CLI used by Explore path B and Reflect. Paths resolve through
`scripts/lib/chem_paths.py` and can be overridden with `ORCA_DIR`, `XTB_BIN`,
`CHEM_PYTHON`, `CHEM_*`.

## Reading order

1. `policy/acceptance/STRICT.md` — the only thing that decides whether a step counts
2. `policy/targets_and_budget.md` — what was asked for and what it was allowed to cost
3. `docs/paper/Method_Framework_for_Review.md` — the method contract
4. `assets/README.md` — the two asset sets and why they are the comparison
5. `evolution/EVOLUTION_LOG.md` — what changed, on what evidence
