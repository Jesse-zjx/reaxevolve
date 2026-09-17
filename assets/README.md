# Asset sets

Two frozen snapshots of the editable surface. The framework (`policy/`, `loop/`,
`scripts/`) is identical for both — only Skills and Tools differ, which is what makes
them comparable.

| | `initial/` | `final/` |
|---|---|---|
| Skills | 5, declarative and general-purpose: generate a TS guess, diagnose why it failed, run the QM step, assemble a chain, keep memory | 6, campaign-shaped: per-reaction-kind guess ladder, which motifs can pass the bar, chain assembly and packaging discipline |
| Candidate enumerator | **absent** | `expand/templates_expand.py` — four reaction SMARTS plus graph-based ring close/open |
| Candidate scoring | **absent** | `motif_score` (inside the enumerator) plus `screen/diversity.py` novelty |
| Guess generators | **absent** | `guess/` — constrained scan, dual scan, 2D scan, dry proton transfer, water relay, NEB |
| QM driver | `workflow/run_qm_step.py` | same driver plus the ORCA/xTB workflow, soft-mode cleanup and candidate validator |
| Geometry toolkit | identical | identical |

The largest single difference is not wording inside a skill file. It is the presence or
absence of the enumerator and its scoring function: under `initial/` the loop can only
propose one step at a time and has no basis for ranking what to compute, while under
`final/` it enumerates a frontier and orders the queue by learned chemistry (for
example, β-elimination starting from an enol is promoted and the same elimination from a
non-enol carbon is pushed down, because the second kind kept failing at the IRC stage).

## Why these two are the comparison

Acceptance is fixed (`policy/acceptance/STRICT.md` v5) and never varies between arms, so
a difference in outcome is a difference in the assets and not in the bar. Neither arm may
write assets during evaluation: Reflect is closed on both sides, so the comparison is
between asset versions and not between "a period when the system was learning" and "a
period when it was not". Protocol and endpoints: `preregistration/c2_protocol.md`.

## Relationship to the repository root

The root `.skills/` and `tools/` are the live, runnable copy and currently correspond to
`final/`. `assets/` holds frozen copies so an evaluation can be pinned to one set even
after the live copy moves on. When a Reflect revision lands in the root, `final/` is
stale until it is re-frozen; `initial/` never changes.

Every attempt record carries the full version vector from `tools/VERSIONS.json`, so a
verdict can always be traced back to the asset set that produced it.
