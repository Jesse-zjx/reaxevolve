# Failure-mode taxonomy

**Version**: `v1` · **Machine-readable**: `policy/failure_modes.json` · **Not evolvable**

A protected input resource, in the same sense as the acceptance clauses: Reflect must cite
ids from this table and may summarise over them, but may not add, rename or redefine one.
Changing this file is a human act and starts `v2`.

## Why it is versioned, and why it is here rather than in a skill

Every revision record names `(failure_mode, taxonomy_version)`. That pair is what makes
"the same failure class" machine-decidable, and the transfer arm of the capability claim
depends on exactly that: it asks whether a revision triggered by one instance also helps on
*independently drawn instances of the same class* that were not the trigger. If the class
label were free text, that sampling could not be done — and before this file existed it
could not: the ledger carried sixteen distinct spellings for four real modes, including
`no_dominant_mode`, `no_dominant_mode and no_endpoint_record`,
`no_endpoint_record / no_dominant_mode` and `multi-kind: no_endpoint_record + no_dominant_mode`.

It lives in `policy/` because a taxonomy the system could rewrite would let it relabel its
own failures, and an attribution is only as good as the labels it quantifies over.

## Chemistry modes

Assigned by `scripts/reflect/failure_digest.py::classify` from the recorded attempt — never
by a model. `scripts/qa/test_failure_taxonomy.py` asserts the classifier emits nothing
outside this table, so the taxonomy and the classifier cannot drift apart silently.

| id | meaning | what it implicates |
|---|---|---|
| `ok` | met the endpoint criterion | — (not a failure) |
| `ts_not_converged` | OptTS never landed on a saddle | guess geometry or scan coordinate, not the mechanism |
| `multiple_imaginary` | more than one imaginary mode past the contaminant threshold | soft-mode cleanup |
| `no_dominant_mode` | only soft modes: a floppy minimum, not a saddle | the guess did not cross the reaction coordinate |
| `no_endpoint_record` | no IRC endpoint record | driver or IRC settings, not the mechanism |
| `both_ends_reactant` | both IRC ends optimise to the reactant | saddle on the wrong side of the intended barrier |
| `both_ends_product` | both IRC ends optimise to the product | as above, opposite direction |
| `one_end_only` | one end matches, the other wanders | direction roughly right; other end needs pre-organisation |
| `no_match` | neither end is a target species | the saddle connects a pair nobody asked for |
| `wall_time` | abandoned on the per-guess wall clock | cost, not chemistry; carries no evidence about the step |
| `mass_unbalanced` | refused by the conservation gate before any calculation | the proposal; no IRC could connect the stated endpoints |

`wall_time` and `mass_unbalanced` are listed with the chemistry modes because they attach to
a specific step, but note what they are: one is a budget outcome and the other is arithmetic.
Neither is evidence that a reaction does not exist, and neither may be reported as one.

## Process modes

Failures of the machinery rather than of a chemical hypothesis. A revision attributed to one
of these is recorded as `plumbing` class and **supports no capability claim**.

| id | meaning |
|---|---|
| `tool_crash_reported_as_result` | a tool failed to run and its output was recorded as a chemical negative |
| `stale_path_reference` | a documented or hard-coded path does not exist in this repository |
| `path_alias` | a written path used an alias the filesystem does not have |
| `low_candidate_yield` | Explore produced too few admissible candidates to keep validation busy |
| `near_duplicate_spend` | budget went to near-duplicates of what was already explored |

## Usage

`scripts/reflect/asset_snapshot.py` validates `--failure-mode` against this table and
records the taxonomy version on the revision. Multiple ids are allowed, comma-separated,
when one revision addresses more than one mode:

```bash
python scripts/reflect/asset_snapshot.py --bump \
    --asset-id .skills/generate-ts-guesses --path .skills/generate-ts-guesses \
    --failure-mode no_dominant_mode,no_endpoint_record \
    --trigger-evidence "..." --intended-effect "..." --scope "..."
```

An id outside the table is rejected rather than accepted as free text. Records written
before this file existed carry their original string in `failure_mode_raw` alongside the
mapped ids, and are marked `taxonomy_version: v1-backfilled` so a reader can tell a
contemporaneous label from a retrofitted one.
