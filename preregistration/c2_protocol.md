# D-29 — C2 held-out pathway protocol (preregistered)

**Decision**: B2 + D1 + C-aux  
**Body rule**: zero script names in the paper body; point here for operational detail.

## Held-out paths

Fill concrete path IDs before the C2 run (do not invent after seeing outcomes):

| slot | path_id | start → target | notes |
|---|---|---|---|
| C2-a | _TBD_ | _TBD_ | 1–2 held-out paths total |
| C2-b | _TBD_ (optional) | _TBD_ | |

## Core-hour caps

| path_id | cap (core-h) |
|---|---|
| C2-a | _TBD_ |
| C2-b | _TBD_ |

## Asset snapshots

- **Initial assets**: first snapshots under `evolution/snapshots/` (or tagged vector in
  `tools/VERSIONS.json` at C2 start) — record hash/vector ID here at launch.
- **Final assets**: last snapshots / version vector at C2 stop.

| marker | versions_vector_id / snapshot dir | UTC |
|---|---|---|
| initial | _fill at launch_ | |
| final | _fill at stop_ | |

## Aux figure

Cumulative STRICT (or accepted-step) curve vs core-hours may appear as fig-2 auxiliary
panel; not a license to rename scripts in the body.

## Prohibitions

- No post-hoc path substitution.
- No raising caps after a path fails.
- Historical STRICT edges from session-style Reflect must not be described as fully_auto.
