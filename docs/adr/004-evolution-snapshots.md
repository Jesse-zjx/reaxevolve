# ADR 004 — Evolution snapshots and per-asset version vectors

## Status
Accepted (2026-08-08)

## Context
§5.2 / §9.1 require proving “revise then reuse” and that non-tested assets stayed fixed across
a comparison. A single global git hash is insufficient (docs/deposits are gitignored; multiple
assets change independently).

## Decision
- Before any asset edit: snapshot to `evolution/snapshots/<UTC>__<asset_id>__v<N>/`.
- Append one `EVOLUTION_LOG.jsonl` row with §5.2 fields R.
- Versions are **per-asset** monotonic integers in `tools/VERSIONS.json`.
- Every attempt stores the **full version vector** (entire `VERSIONS.json`) so two replays can
  be compared without a global snapshot number.
- Historical `evidence/evolved_artifacts_review_v1` and `asset_evolution.jsonl` are backfilled
  with `unknown` for missing fields — never fabricated.

## Consequences
D-29 initial/final asset sets are the first/last snapshots. Asset appearance dates after this
ledger are machine timestamps; pre-ledger dates remain dialogue-recovered estimates.
