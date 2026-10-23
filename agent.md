# Agent rules

You are operating a reaction-network discovery loop: propose elementary steps, validate
them with quantum chemistry, record what happened, and revise the reusable Skills and
Tools from the failures. Chemistry judgement lives in `.skills/` and `tools/`, both of
which you may revise. The acceptance boundary lives in `policy/` and you may not.

## Acceptance

`policy/acceptance/STRICT.md` (**v5**) is the only criterion, and
`policy/acceptance/check_strict_bar.py` is its only implementation. Do not restate its
clauses in a skill, do not add a second bar, and do not describe a driver early-exit as a
status — early-exits are compute throttles.

Status vocabulary: `{STRICT, evidence_ok, rejected, unresolved}` plus an optional
`detail`. Only `scripts/validate/verdict_writer.py` writes a verdict. Never edit a graph
file, a cache or a verdict by hand.

## Task boundary

- Targets, seeds, budget and stop conditions: `policy/targets_and_budget.md`.
- Hypotheses land only through `scripts/graph/add_hypothesis.py`, which enforces atom
  conservation. If it rejects a proposal, fix the chemistry — do not pass
  `--allow-unbalanced` outside diagnostics.
- The QM floor (GFN2-xTB OptTS → r²SCAN-3c OptTS+NumFreq → IRC) is human-set starting
  capability, not an evolved finding. Never report it as one.

## Evolvable vs frozen

| Frozen | Evolvable |
|---|---|
| `policy/` | `.skills/` |
| `scripts/` | `tools/geometry/`, `tools/guess/`, `tools/expand/`, `tools/screen/`, `tools/workflow/` |
| `loop/` | `tools/VERSIONS.json` and the tool shims |
| `assets/initial/` (never changes) | Experience notes via the reflect helpers |

`tools/expand/` and `tools/screen/` are evolvable on purpose: the reaction templates and
the candidate scoring function are where chemistry learned from QM feedback belongs.
They can only decide what is proposed and in what order.

Before any evolvable edit:

```bash
python scripts/reflect/asset_snapshot.py --bump \
    --asset-id tools/expand/templates_expand.py \
    --path tools/expand/templates_expand.py \
    --revision-class qm_feedback \
    --failure-mode <dominant failure mode from the digest> \
    --trigger-evidence "<what in the record made this necessary>" \
    --intended-effect "<what should measurably change next round>" \
    --scope "<which reaction kinds this touches>"
```

Revisions are identified by sequence number and per-asset version, not by wall-clock
time. Write a `trigger_evidence` that a reader can check against the recorded attempts;
"seemed better" is not evidence.

## Discipline for claims

A capability claim needs the whole chain: recorded QM feedback → a named asset changed →
a later attempt reused it under a recorded version vector. Asset count, log length and
elapsed time are not substitutes. If only the triggering instance improved and nothing
transferred, say local fix, not capability.

## Filesystem

Work inside this repository. Outside it you may use only the ORCA tree (`$ORCA_DIR`), xTB
(`$XTB_BIN`), conda/miniforge Python, and ordinary system libraries.

## Runtime

Use the project-local `pi` through `loop/pi_call.sh`. Do not touch a global CLI config.
Credentials live in the gitignored `.env` (`BASE_URL`, `API_KEY`, `MODEL_NAME`).
