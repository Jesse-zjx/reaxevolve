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

## What the historical record can and cannot show

Of 63 revisions, **7 close with a measurement** and **55 are explicitly `not_closable`**. The
reason is stated per record; it is one of two things, and neither is "nothing reused it":

**The version numbering was renumbered.** The early ledger carried two id spellings for one
skill (`.skills/x` and `.skills/x/SKILL.md`), which produced two parallel version lineages for
the same file. Merging them into one lineage renumbered the versions — but the attempts in
`attempt_vectors.jsonl` record the *original* numbers, so for the merged asset the ledger's
`v42` and an attempt's `v2` are not comparable. `close_revisions.py` refuses to compare them
rather than reporting a lower bound as a result.

**No vectored attempt records that asset.** Attempts from before the asset-version vector was
introduced cannot say which version they ran under, so they are invisible to this analysis.

The consequence for the capability claim is worth stating plainly: the repair/transfer analysis
is supported for the revisions that close, and for anything run in this repository from here on
(`verdict_writer.stamp` records the full vector on every attempt). It is *not* recoverable for
the renumbered stretch of the historical ledger. Reporting those 55 as "no downstream use"
would be a measurement claim the data does not support.

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
