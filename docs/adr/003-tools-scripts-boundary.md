# ADR 003 — `tools/` vs `scripts/` evolution boundary

## Status
Accepted (2026-08-08)

## Context
Method text separates evolvable Skills/Tools from non-evolvable infrastructure and human-set
policy. The old layout mixed guess generators, validators, and one-off campaign scripts under
`tools/`.

## Decision
| Tree | Evolvable? | Contents |
|---|---|---|
| `.skills/` | yes | declarative recipes |
| `tools/{guess,expand,screen,workflow}/` | yes | executables + `VERSIONS.json` |
| `policy/` | no | STRICT, QM protocol, budget |
| `scripts/` | no | paths, validators, graph ops, reflect, viz, qa |
| `loop/` | no (driver) | four-stage orchestration |

Rename map for migrated assets: `evolution/ASSET_RENAMES.json`.

## Consequences
Reflect may edit only `.skills/` and `tools/`. fully_auto Reflect (stage 2) enforces the same
whitelist in code.
