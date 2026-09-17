---
name: memory-and-reflection
description: >-
  Four-stage loop procedure (Explore → Validate → Remember → Reflect) for reading
  Graph Memory and Experience Memory, deciding whether to change evolvable
  Skills/Tools, snapshotting into evolution/ before edits, and recording updates
  with measured utility. Use before launching loop/run_loop.py after failures,
  when triageing failure digests, or when closing an asset-evolution expectation.
  Does not redefine STRICT — policy/acceptance/STRICT.md (v5) governs acceptance.
---

# Memory and reflection

This skill governs **Reflect** and the memory read path. The main loop is
`loop/run_loop.py` (Explore → Validate → Remember → Reflect). Validate writes
verdicts only through `scripts/validate/verdict_writer.py`. You do not sit inside DFT.

Human-set boundaries (`policy/`) are **not** evolvable. You may change `.skills/` and
`tools/`; you may **not** mark an edge STRICT or edit `policy/`.

## Four stages

| Stage | Writes | Notes |
|---|---|---|
| Explore | hypotheses via `scripts/graph/add_hypothesis.py` | no template expander |
| Validate | attempt + verdict via `verdict_writer` | STRICT only if policy v5 passes |
| Remember | Graph Memory merge; Experience append-only | no overwrites without provenance |
| Reflect | evolvable assets only, after snapshot | this skill |

## Two memories

| Memory | What | Read with |
|---|---|---|
| Graph Memory | Species, edges, status, frontier | `scripts/reflect/graph_query.py` |
| Experience Memory | Lessons, skill/tool updates + utility | `scripts/reflect/experience_query.py` |

Evidence (`graph/canonical/verdicts.jsonl`, ORCA outs, deposits) is not memory.
Acceptance projection for delivery = STRICT only. Expansion frontier =
`STRICT ∪ evidence_ok` (`scripts/reflect/graph_views.py`).

## Evolution ledger (mandatory before asset edits)

```bash
export CHEM_PY=${CHEM_PY:-/root/miniforge3/envs/harness/bin/python3}

# Snapshot BEFORE editing any evolvable asset
$CHEM_PY scripts/reflect/asset_snapshot.py \
  --asset-id <.skills/... or tools/...> \
  --path <path> --bump \
  --trigger-evidence "<pointer>" \
  --failure-mode "<mode>" \
  --intended-effect "<measurable>" \
  --scope "<what it affects>"
```

Snapshots land in `evolution/snapshots/<UTC>__<asset_id>__v<N>/`.
Each revision appends one line to `evolution/EVOLUTION_LOG.jsonl` (§5.2 fields).
Every attempt must carry the full `tools/VERSIONS.json` vector (written by
`verdict_writer`).

## Fixed order

```bash
# 1) L0 dashboard
$CHEM_PY scripts/reflect/graph_query.py --mode summary

# 2) Experience aligned to dominant failures
$CHEM_PY scripts/reflect/experience_query.py --signature <mode> --kind <kind> --limit 8

# 3) If changing a skill/tool — snapshot + record BEFORE restarting
$CHEM_PY scripts/reflect/asset_snapshot.py --asset-id ... --path ... --bump ...
$CHEM_PY scripts/reflect/experience_record.py open \
  --kind <kind> --failure <mode> \
  --asset <.skills/... or tools/...> \
  --change "<one sentence>" \
  --expect "<measurable expectation>"

# 4) Restart main loop
# $CHEM_PY loop/run_loop.py --rounds 3 --budget-hours 8 --top 4 --cap 2

# 5) Close against the graph (false expectations still close)
$CHEM_PY scripts/reflect/experience_record.py close --id upd_...
```

Reflect stage-1 emits `evidence/state/loop/reflect_bundle.json` (bundle interface).
fully_auto Reflect (LLM applies patches under whitelist) is stage 2 — see
`loop/fully_auto/`. Genesis whitelist: `.skills/` and `tools/` only
(see `loop/fully_auto/apply_revision.py`).

## Status vocabulary

`{STRICT, evidence_ok, rejected, unresolved}` + optional `detail`.
Do not embed payloads in status strings.
