# Evolution record

What changed in the editable asset surface, on what evidence, and whether it worked.

| File | Role |
|---|---|
| `EVOLUTION_LOG.jsonl` | Append-only, one record per revision attempt. The primary evidence for the capability claim. |
| `EVOLUTION_LOG.md` | Generated human view. |
| `snapshots/NNN__<asset>__vN/` | The asset as it was *before* that revision, so the change can be diffed. |
| `ASSET_RENAMES.json` | How the initial asset set maps onto the final one: renames, merges, splits, retirements. |
| `attempt_vectors.jsonl` | The attempt stream these revisions were measured on. Each line carries the asset-version vector in force when it ran. |

## What a record says, and when

A record is **opened** at Reflect time with what the revision was for, and **closed** later with
what happened:

| Field | Written | Meaning |
|---|---|---|
| `failure_mode` + `taxonomy_version` | open | Ids from `policy/failure_modes.md`. Validated on write; free text is refused. |
| `trigger_evidence` | open | The recorded failures that motivated it. |
| `intended_effect` | open | What should measurably change. |
| `outcome` | open | `applied`, or `rolled_back` if the patch failed its checks. |
| `snapshot` | open | Pre-change copy. |
| `first_downstream_use` | close | The first attempt that ran under the revised version. |
| `expectation_met` | close | Whether the targeted failure mode became less frequent. May be false. |
| `closed_status` / `closed_reason` | close | `closed`, or why it cannot be. |

Closing is derived, never asserted: `python scripts/reflect/close_revisions.py [--apply]`.

## A rolled-back revision is recorded as rolled back

`loop/fully_auto/apply_revision.py` snapshots first, applies the patch, then runs a syntax
check, a callable probe for the enumerator and scorer, and the repository smoke test. Only
after all of those pass does it bump the version and append the ledger record. If any check
fails the file is restored and the attempt is recorded with `outcome: rolled_back` and no
version bump.

This ordering matters because it was once the other way round: the bump and the ledger entry
came first, so a revision that failed its checks and was reverted still appeared in the ledger
as one that landed, and `tools/VERSIONS.json` claimed a version no file had.

## Two version lineages, and why records carry `origin_*`

The early ledger used two id spellings for one skill — `.skills/x` and `.skills/x/SKILL.md` —
and each kept its own counter, in two different places in `VERSIONS.json`: the `skills`
section, keyed by bare name, and a flat top-level key. The attempts recorded both.

Merging them into one readable lineage renumbered the versions, which briefly made the ledger
and the attempts incomparable and left 55 records un-closable. Each record therefore also
carries the identifiers the attempts actually use:

| Field | Which numbering |
|---|---|
| `asset_id`, `asset_version_before/after` | the merged, readable lineage |
| `origin_asset_id`, `origin_version_before/after` | what the attempt vectors carry |

`close_revisions.py` resolves against `origin_*`, which is what restored 50 of the 63.

## What the historical record shows

**50 of 63 close**, and 12 are `not_closable` with the reason recorded per record — the
remaining one is the reorganization entry, which has no failure mode to measure. The two
reasons are "no vectored attempt records this asset" (the tool revisions and the later skill
work, which post-date the attempt stream) and "the revised version is above the highest any
attempt records" (the campaign stopped before an attempt ran under it). Neither means nothing
reused the asset.

Of the 50, **37 give a direction**: the targeted failure mode fell after 15 revisions and rose
or held after 22. That distribution is the point. A ledger in which every revision met its
expectation would be evidence of nothing except that the expectations were written loosely.

## `expectation_met` is observational, not a replay

Read it as a weak signal and nothing more. It compares the last 12 attempts before a revision
with the first 12 after, both restricted to attempts that record the asset. The method's causal
arm is the repair/transfer replay, which re-runs *the same instance* under the old and the new
asset version with everything else held fixed; that is a separate experiment and this is not a
substitute for it.

The windows are bounded and balanced deliberately. Computed the obvious way — every attempt
before against every attempt after — it produced 39 apparent failures whose `rate_after` climbed
monotonically as the sample fell from 57 to 2, because consecutive revisions then share almost
their entire before-window and the after-window collapses toward the end of a campaign. That
number described where each revision sat in the run, not what it did. Below six attempts on
either side the field reports `inconclusive` rather than a direction.

A revision attributed to a process mode reports `not_applicable`: the chemistry classifier
cannot emit process modes, so scoring one against attempt failure rates would compare a
category against one it cannot contain and always report failure.

## Why `attempt_vectors.jsonl` is here and not under `graph/`

It is evolution evidence, not Graph Memory. The attempts it records belong to the run the
ledger describes, which is not the run that produced the reaction network shipped under
`graph/`. Merging it into the network would mix two campaigns' reaction data, so
`build_reaction_network.py` does not read it and only `close_revisions.py` does.

## Discipline

A capability claim needs the whole chain: recorded QM feedback → a named asset changed → a
later attempt reused it under a recorded version vector. Record count, ledger length and
elapsed time are not substitutes. A revision whose `expectation_met` is false is still a
revision, and a ledger in which it is never false is not evidence of anything.
