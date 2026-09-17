# Context

Glossary for this repository. Terms only — no implementation detail, no plans, no decisions.
Decisions belong in `docs/adr/`; the method contract is `docs/paper/Method_Framework_for_Review.md`.

## Aqueous valorization

The chemical regime this project models: sugars in hot pressurized water, roughly 150–200 °C,
closed-shell ionic and concerted mechanisms. Every calculation uses an implicit water solvation
model (CPCM), so this is the only regime the results describe.

Not to be confused with **pyrolysis**, the dry gas-phase regime above about 400 °C where
radical chemistry dominates. No result in this project supports a claim about pyrolysis.

## Elementary step

One reactant state going to one product state over a single transition state. The unit of
validation: nothing larger is ever validated as a whole.

## Hypothesis

A proposed elementary step (reactant, product, optional kind/coproduct) written into Graph
Memory before or during Explore, not yet carrying a delivery-grade verdict.

## Attempt

One concrete validation try for a hypothesis: guess → OptTS/NumFreq/IRC (or an early-out).
Records must carry `strict_version` and the full `asset_versions` vector from
`tools/VERSIONS.json`.

## Verdict

The status assigned to an attempt through the sole write entry
(`scripts/validate/verdict_writer.py`): one of `{STRICT, evidence_ok, rejected, unresolved}`,
optionally with a `detail` field. LLMs do not write verdicts.

## STRICT step

An elementary step that meets **STRICT(v5)** (`policy/acceptance/STRICT.md`):

1. r2SCAN-3c / CPCM(water) (deposit-grade DEFGRID3), as-built grid reported with frequencies;
2. exactly one imaginary frequency in the final NumFreq block;
3. raw IRC endpoints, after optimization, are the exact neutral reactant and product
   (canonical SMILES; declared coproducts counted);
4. **discrete water rule** — if both ends have a complete neutral H₂O, compare H atom indices
   bonded to the water oxygen: exchanged → catalytic shuttle (allowed, water is a declared
   chain component); identical O+H+H identities → spectator (rejected).

A step that fails any clause is not STRICT. There is no second acceptance bar; driver early-outs
are compute throttles only.

The word is used at two scales and the scale must always be stated:

- **STRICT step** — one edge, as above.
- **STRICT route** — a chain of STRICT steps where each step's product geometry is the next
  step's reactant geometry, with atoms conserved end to end.

## evidence_ok

QM-backed positive signal that is not delivery-grade STRICT (legacy aliases: `validated`,
`qm_real`). Seeds the expansion frontier together with STRICT; never a deposit claim by itself.

## Expansion frontier

Species/edges used as seeds for Explore: **STRICT ∪ evidence_ok**.

## Acceptance projection

Publication / deposit view: **STRICT only**.

## asset_version

Per-asset monotonic integer in `tools/VERSIONS.json`. Attempts store the full version vector,
so a verdict can be traced to the asset set that produced it. Pre-change copies live under
`evolution/snapshots/`; revisions append `evolution/EVOLUTION_LOG.jsonl`.

## revision seq

Repository-wide monotonic counter over `evolution/EVOLUTION_LOG.jsonl`. Revisions are ordered
by `seq` and versioned per asset; they carry no wall-clock timestamp. What has to be checkable
is the **order** of revisions, the evidence that triggered each one, and the snapshot it can be
diffed against — not when it happened.

Consequence for attribution: "asset version v_n was in force for this attempt" is read from the
attempt's own version vector, never inferred from dates.

## revision class

Field on every revision record. `qm_feedback` — driven by recorded QM failures; the only class
that supports a capability claim. `plumbing` — path or format fix. `reorganization` — rename,
split or merge of the asset surface, recorded in `evolution/ASSET_RENAMES.json`.

## asset set

A frozen snapshot of the editable surface (`assets/initial`, `assets/final`). The framework is
identical across sets, so a difference in outcome between them is a difference in assets and not
in the bar. See `assets/README.md`.

## Acceptance date

The moment a step's verdict was recorded as STRICT. It is a property of the verdict itself,
written when the judgement was made, so it dates the acceptance event rather than estimating it.

Neither the date the step was first proposed nor the date any of its calculations ran.

## Calculation date

The moment a quantum-chemistry job started, as recorded by the program that ran it. Many
calculation dates can precede one acceptance date, because a step is usually attempted several
times, and fails several times, before it clears the bar.

## Deposit

A packaged, independently checkable evidence bundle for one route: geometries, ORCA inputs and
outputs, Hessians, energetics manifest, and a report. One tree per route under `deposits/`,
with expert review status stated in that tree's README. Deposits are an **output**: expert
confirmation checks the explanation and the completeness of the materials, and never rewrites an
edge verdict or writes back into Graph Memory.

## Saddle-level agreement

Whether a newly located transition state is *the same* saddle as a deposited one, judged by
imaginary frequency within 40 cm⁻¹. Distinct from the two ideas below, and much rarer than
either.

## Elementary-step rediscovery

Whether the system, run again from the reactant and product alone, finds *some* transition state
that meets the STRICT bar for that step. It may be a different saddle from the deposited one and
still count. This is a weaker claim than saddle-level agreement and a stronger one than merely
connecting the two species.

## Self-evolution

**Skill/Tool evolution** driven by **execution feedback** from quantum-chemical validation: QM
outcomes update Graph Memory; Reflect records Experience Memory and may revise `.skills/` /
`tools/` after an `evolution/` snapshot. A claim requires both that a named asset changed and
that a later attempt reused it under a recorded version vector (revise-then-reuse is checkable).
Appearance timelines alone, or long trial-and-error without update-then-reuse, are not sufficient.

## Graph Memory

The persistent scientific-state graph of molecular species, proposed or validated elementary
steps, validation states, observed IRC endpoints, failure information, and expandable frontier.
Only Validate (via `verdict_writer`) writes edge status. It is not a parallel “asset layer”
beside Skills; it is the external QM-grounded state Reflect reads.

## Experience Memory

Structured lessons and skill/tool update records (with measured utility) written by Reflect.
Distinct from Graph Memory: procedural experience, not scientific edge state.
Seeded `method_hints` rows are machine-derived aggregates, not reflection-authored lessons.

## Skill

A human-readable, reusable domain workflow that guides an agent's later reasoning and tool use.
Evolved by Reflect; not a memory store. Acceptance clauses are **not** Skills — they live in
`policy/`.

## Tool

An executable program for a chemistry-specific task under `tools/` (guess, expand, screen,
workflow). Evolved by Reflect; not a memory store. Non-evolvable drivers and validators live in
`scripts/`.

## Functional-role agentic system

A role-decomposed agentic system defined by operational responsibilities in the four-stage loop
(Explore, Validate, Remember, Reflect) rather than by a claim that a fixed number of
independently autonomous models always run concurrently. Next-step pursuit and budget choices
are part of the agentic loop, not a separate routing file.

## Target-oriented, strictly anchored unified reaction network

A reaction network rooted at glucose and scoped to species and pathways that can reach HMF, HAA,
or furfural. Graph Memory may retain proposed, failed, and partially characterized edges, but
published network views distinguish these evidence states. A complete route contains only
accepted elementary steps and is geometrically chained end to end. It does not claim to exhaust
all aqueous glucose chemistry.

## Capability-demonstration pathway

An expert-reviewed end-to-end quantum-chemistry route used to demonstrate the system's ability
to construct a pathway, validate its elementary steps, and integrate it into the reaction
network. It is also a source of mechanistic insight. It is not, without a separate literature
comparison, a claim that the route is chemically unprecedented.

## Mechanism–method case

A causal case study linking a chemical failure mode or ambiguity to an evolved graph-memory
record, Skill, or Tool, and then to its reuse on a later pathway or network task. The three
canonical cases are cooperative dehydration, dry tautomerization, and beta-carbonyl-activated
retro-aldol cleavage.

## Step autonomy

The property that no human proposed any elementary step in a route. This is the only sense of
autonomy the project claims, and it is narrower than it sounds: the human set the targets, the
acceptance criterion, and the resource budget, and operated the campaign. Unqualified phrases
like "fully autonomous" overstate it and should not be used.

## Intervention

One human message to the agent during a campaign. Interventions divide by what they touch:

- **Monitoring** — asking for status, or telling the agent to continue. Carries no content.
- **Operational** — resources, timeouts, tooling, failures.
- **Chemical** — anything naming a species, a mechanism, a reaction kind, or a criterion.

Only chemical interventions can threaten step autonomy, and only the *directive* ones among
them — a question about a result does not steer the search.
