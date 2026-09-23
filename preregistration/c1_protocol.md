# C1 — repair and transfer replay protocol (preregistered)

**Status**: confirmed, not yet run. Locked before any compute; the point of writing it first is that
the reported numbers are not the ones that happened to look best. The selection rule below may not
change after an arm has run.

**Reporting requirement**: the paper body must state that selection was keyed on failure mode and
why — the record's triggers are aggregate digests and attempts carry no reaction kind, so a
mechanism-class selection would have required a classifier written with the outcomes visible. A
reader who expects the mechanism-class framing the narrative uses elsewhere is entitled to see that
this deviation was forced by the record and decided before the runs, not chosen afterwards.

**Claim under test**: structured QM feedback produces traceable revisions to Skills/Tools that
change subsequent behaviour — not merely on the instance that triggered them, but on other
instances of the same failure mode.

**What would falsify it**, stated before any run: no behaviour change; or a change that cannot be
attributed to the revision's activation point; or improvement on the trigger instance with no
improvement on the non-trigger instances. The third is the one to watch, because a revision that
only fixes its own trigger is indistinguishable from overfitting to a single calculation.

## Why two replays and not one

A revision was written in response to a specific failure. Re-running that failure with the
revision in place is the **repair replay**: it establishes that the revision does what its
`intended_effect` says. It cannot establish generality, because the revision was authored while
looking at that instance.

The **transfer replay** runs instances of the same failure mode that the revision was *not*
authored against. This is where the claim is actually at risk, and it is reported separately and
with equal prominence. A protocol that reported only the repair arm would be measuring whether we
can describe a fix we already made.

## Selection rule, fixed in advance

The ledger holds 50 `qm_feedback` revisions; replaying all of them is not affordable, so the
subset must be chosen by a rule rather than by inspection of outcomes.

**The rule is keyed on failure mode, not on mechanism class.** This departs from the outline's
description and the reason is a property of the record, not a preference: revisions were triggered
by *aggregate* failure digests ("isomerization_or_tautomerization has 5 `no_endpoint_record`,
unattributed has 3 `no_dominant_mode`"), never by a single named attempt, and attempts carry no
reaction-kind field at all. A mechanism-class-keyed selection would therefore require a classifier
applied to attempts after the fact — and that classification would be ours, written with the
outcomes visible. Keying on failure mode uses what Reflect actually recorded and what the
revisions actually targeted.

For each targeted failure mode with at least two qualifying instances on each side of the activation
point. Which modes those are is decided by the rule, not chosen: the resolver reports the ones that
qualify and the reason each rejected mode failed to. On the present record both `no_dominant_mode`
and `no_endpoint_record` qualify, giving 8 instances and 16 runs.

A mode's instances must be classifiable, which required recovering something. The attempt stream
records asset versions and ordering but not imaginary modes or endpoint flags, and the canonical
`graph/canonical/verdicts.jsonl` covers an earlier period that does not overlap the revisions at
all — so for a while no attempt near a revision could be classified without inventing a reading of
its `detail` string. The 70 per-attempt verdict caches those attempts referenced had been left in
scratch and are now archived under `graph/caches/strict_caches/genesis_validation/`, 103 kB, which
makes all 116 cache references resolve and lets the existing classifier do the work.

1. **Revision under test** — the lowest-`seq` revision in `evolution/EVOLUTION_LOG.jsonl`
   satisfying all of: `class == "qm_feedback"`; `failure_mode` includes the mode; a non-null
   `activation_point`; a resolvable `evolution/snapshots/` entry; and a `first_downstream_use`
   whose edge appears in `evolution/attempt_vectors.jsonl`, which is what allows the revision to be
   located in the attempt stream (50 of 66 revisions can be). Lowest `seq` is specified so the
   choice cannot follow the result.
2. **Activation index** — the position in the time-ordered attempt stream of that revision's
   `first_downstream_use` edge. Attempts before it ran under `asset_version_before`; attempts from
   it onward ran under `asset_version_after`.
3. **Repair instances** — the last two attempts *before* the activation index whose recorded
   detail maps to the targeted mode. These are the instances the digest was summarising, so they
   are what the revision was authored against.
4. **Transfer instances** — the first two attempts *from the activation index onward* whose detail
   maps to the targeted mode. The revision was not authored against these: they had not happened
   yet.

Mapping from a recorded `detail` string to a failure mode uses the existing classifier, not a
fresh judgement — the same one `policy/failure_modes.md` and `scripts/qa/test_failure_taxonomy.py`
hold to agree.

If either side of a mode has fewer than two instances, that mode contributes fewer and it is
reported rather than backfilled from another mode.

`scripts/qa/resolve_c1_selection.py` applies the rule and writes `preregistration/c1_selection.json`,
committed **before** any run so the mapping from rule to instances is auditable and cannot drift.
`--check` reasserts that the committed file still follows the rule, and runs in the smoke test and in
`scripts/qa/verify_clone.sh`: an edit to the selection that the rule does not produce fails there.

### The snapshots restore SKILL.md and not the whole asset

55 of the 59 entries in `evolution/snapshots/` contain only `SKILL.md`, while some skills also
carry companion files — `diagnose-ts-failures` has one, `pathway-method` has two. So a snapshot
cannot faithfully reconstruct an asset as it stood at a given version, and the `before` arm is not
a historical reconstruction.

It is still a valid comparison, for a checkable reason: **no revision in the ledger touched a
companion file.** All 66 changed `SKILL.md` or a single-file tool. Holding companion files
identical across arms therefore leaves the arms differing only in the text each revision actually
changed. What is lost is the ability to call the `before` arm "the system as it was"; what is
retained is a controlled comparison of the revised text, which is what the claim needs.

This must be stated wherever the replay is reported. If a future revision does touch a companion
file, the snapshot mechanism has to be extended before that revision can be replayed.

### What the replay adds over the number already in the ledger

`expectation_met` in the ledger already compares outcomes before and after each revision, over a
balanced window of the historical stream. It is observational: the two windows differ in elapsed
campaign time, in what else was being revised, and in which edges happened to be in play. The
replay's entire contribution is that it removes those confounds by re-running *matched* instances
with every other asset pinned. If the replay merely reproduced `expectation_met`, it would not be
worth the compute; the point is that it can disagree with it, and a disagreement is a finding about
the observational metric.

## Arms

Per instance, two runs differing only in the version of the asset under test.

| Arm | Asset under test | Every other asset |
|---|---|---|
| before | content of `evolution/snapshots/<seq-1>…` for that asset, i.e. `asset_version_before` | pinned to the revision's `asset_versions_at_revision` vector |
| after | content at `asset_version_after` | pinned to the same vector |

Held identical across arms: the input geometry and its fingerprint, the QM protocol
(`policy/qm_protocol/PROTOCOL.md`), the acceptance bar (STRICT v5), the per-guess wall clock, the
core count, the guess budget per instance, and every asset other than the one under test.

**Reflect is closed in both arms.** No revision may land during a replay; a replay that provoked
a revision would no longer be a comparison between two asset versions.

Replays run against a materialised snapshot tree, not the live repository. The revisions under
test mostly name skills from the initial lineage (`generate-ts-guesses`, `diagnose-ts-failures`,
`qm-execution`), which the live tree no longer carries under those names — so the runner has to
build the asset set for each arm from `evolution/snapshots/` and `evolution/ASSET_RENAMES.json`
rather than mutating anything in place.

## Outcome measures

Primary, per instance: does the run reach STRICT(v5), and at what core-hour cost.

Secondary, per instance: the failure mode of the outcome, from `policy/failure_modes.md`. The
revision's stated target mode is declared in advance from its `intended_effect`, so "the targeted
mode went away" is checkable rather than narrative.

Reported per class and in aggregate:

- repair: outcome on the trigger instance, before vs after
- transfer: outcome on each non-trigger instance, before vs after
- whether the targeted failure mode fell, and whether a *different* mode took its place — a
  revision that trades one failure for another has changed behaviour without improving it, and
  that is a reportable outcome, not a null result

## Budget

| | |
|---|---|
| Instances | 2 failure modes × (2 repair + 2 transfer) = up to 8 |
| Runs | up to 16 (each instance in both arms) |
| Cores per run | 16 |
| Per-guess wall clock | 5400 s, matching the C2 protocol |
| Guess budget per instance | 3 guesses per arm, identical across arms |
| Cap | **180 core-hours total**, not per arm |
| Escalation | if the cap is reached before every selected instance has run in **both** arms, the run stops and the partial set is reported with the instances that did not run named. No raise for one class or one arm alone. |

## Prohibitions

- No substitution of a trigger or transfer instance after a run. The selection rule resolves them
  before any compute.
- No change to the guess budget, wall clock or core count between arms, or after seeing an arm.
- No asset edit during the replay, in either arm, including the asset under test.
- No reporting the repair arm without the transfer arm.
- If a replay's `before` arm happens to succeed where the historical record shows it failed, that
  is reported as a **discrepancy with the historical record**, not quietly dropped. It would mean
  the historical failure depended on something the pinned vector does not capture, which is itself
  a finding about the ledger's completeness.
- No claim that a revision *caused* a downstream accepted edge. The replay measures behaviour
  change on matched instances; it does not license attributing specific STRICT edges to specific
  revisions.
- No reporting of the replay in place of `expectation_met`, or vice versa. They measure different
  things and a disagreement between them is reportable, not resolvable by preferring one.
- Three attempts in the historical stream are `unresolved` because the validator crashed at the
  `endpoint_match` seam rather than returning a verdict (since fixed). Those attempts carry no
  outcome and must not be selected as repair or transfer instances, nor counted as failures of any
  mode.

## Prerequisites — met

Neither this protocol nor C2 could run until an arm runner existed. `scripts/eval/arm_runner.py`
now materialises a chosen asset set into an isolated tree, verifies that the tree declares that set
and resolves its own roles, refuses an arm that can reach the other set's assets or the deposited
answers, records the revision ledger's digest before and after so a revision landing mid-arm voids
the arm, and accounts core-hours against the cap. Both arms pass its dry run, and that dry run is
part of `scripts/qa/verify_clone.sh`.

The related defect is fixed: skills are now resolved by role through `assets/roles.json` rather than
by name, so the loop runs against either set. It previously named two initial-set skills and could
not run against the final set at all.

The `before` arm's rollback is implemented and checked. `--snapshot-asset` with `--snapshot` rolls one
asset back and reports which files came from the snapshot and which were left at the arm's content,
refusing to describe a partial restore as a whole one. `scripts/qa/test_replay_rollback.py` holds
three invariants: the rollback changes the file, files outside the snapshot are untouched, and no
ledger revision touches a companion file — the last being the condition under which a partial restore
is an acceptable comparison at all. The test was itself checked by sabotaging the rollback into a
no-op and confirming it fails.

Tasks are derived from this protocol rather than written by hand: `scripts/eval/make_task.py`
emits one per failure mode and arm from `c1_selection.json`, and the runner refuses any step not
present in the preregistration. Reflect being closed is now enforced as well as detected —
`asset_snapshot.py` refuses to bump while an arm is running, and the runner hashes the arm's own
assets before and after, which is what catches an arm editing its own skill directly. The skills
run with write and edit tools, so the ledger digest alone would not have seen that.

Nothing further blocks a run. `scripts/qa/test_arm_contract.py` covers the seams a dry run cannot
reach, which is where both of the runner's earlier defects sat.
