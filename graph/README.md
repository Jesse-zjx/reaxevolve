# Graph Memory

The persistent scientific state: species, proposed and validated elementary steps, their
verdicts, observed IRC endpoints, and the expansion frontier. Only
`scripts/validate/verdict_writer.py` assigns an edge status; only
`scripts/graph/build_reaction_network.py` writes the canonical file.

## Where the numbers come from

Every count in prose must cite `evidence/state/NETWORK_STATE.md`, which is generated.
Never hard-code a count into a document, and never read one from a stored summary block.

| File | Role |
|---|---|
| `canonical/reaction_network.json` | The state. Nodes keyed by node id, edges keyed by edge id. |
| `canonical/verdicts.jsonl` | Append-only archive of every attempt's judgement. |
| `canonical/audited_strict_edges.json` | The pin: the audited STRICT set under a named acceptance version. |
| `canonical/accepted_network.json` | STRICT-only projection, for publication views. |
| `canonical/routes.json` | Enumerated routes per target. |
| `caches/strict_caches/**/strict_cache.json` | Raw per-attempt driver records, 162 files. The evidence the rebuild merges. |
| `derived/` | Regenerated views. Not tracked; rebuild from the state. |

## Rebuild order, and why it matters

```
raw evidence            caches/strict_caches/**            what a driver observed
   ↓ merge
recorded judgements     evidence/audit/readjudication.jsonl
                        evidence/audit/demoted_from_pin_v5.jsonl
   ↓ overlay
canonical state         canonical/reaction_network.json
   ↓ pin + date
reported numbers        evidence/state/NETWORK_STATE.md
```

Judgements are applied **after** the cache merge, because a cache entry records what one
run observed while a re-adjudication records what a later audit decided about that
observation. Getting this order wrong is not a cosmetic bug: the audit under the current
acceptance version demoted eight edges by rewriting the state and the pin but not the
caches, so merging caches alone silently re-promotes all eight and reports 38 STRICT
instead of 30. `build_reaction_network.py` therefore reads the two audit ledgers and
stamps each affected edge with a `readjudication` block recording the cache status, the
new status, and the reason. The original cache file is never modified.

Refresh everything with:

```bash
python scripts/reflect/repin_state.py
```

which rebuilds, consolidates verdicts, re-dates the timeline, re-pins, and rewrites
`NETWORK_STATE`.

## Current state

243 nodes, 325 edges, **30 STRICT**. The network's STRICT set and the pin are identical,
edge for edge. All three targets have a STRICT route from a glucose seed, and the shortest
chain lengths match the delivered deposits step for step: HMF 5, HAA 4, furfural 11.

## Two status vocabularies

`NETWORK_STATE.md` reports both, and they answer different questions.

**Buckets** are the documented four (`CONTEXT.md`): accepted (STRICT), evidence_ok,
rejected, unresolved. This is the acceptance-facing view; `graph_views.bucket()` is the
only place the mapping lives.

**Raw statuses** are driver-level tokens (`no_strict`, `NOT_CLEAN_TS`, `MISMATCH`, …),
kept because Reflect diagnoses on the distinction between them. They are not acceptance
categories and must not be presented as such.

Some older cache entries appended free text to the status, e.g.
`NOT_CLEAN_TS (imag modes=[-248.0])`, which split one status into as many values as there
were runs. `build_reaction_network.py::split_status` separates the token from the detail
at merge time. It does not remap the vocabulary and does not change any judgement.

## Provenance strings

Records carry a `source` naming the cache or scratch directory they came from. These were
written under an earlier directory layout and were repointed at migration using the
`layout` map in `evolution/ASSET_RENAMES.json`. One archive keeps its original strings on
purpose: `evidence/audit/verdicts_pre_runs_migration_*.jsonl` is a snapshot of the state
*before* that rewrite, so rewriting it would defeat its purpose.

One record was dropped rather than repointed: a `TS_FAILED` run whose reactant and product
had been recorded as `.xyz` file paths instead of SMILES. It carried no frequency, no
endpoints and no species identity, and keeping it would have put two nodes into the graph
whose SMILES were filesystem paths.
