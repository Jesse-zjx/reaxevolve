# D-29 — fixed-asset comparison protocol (preregistered)

**Decision**: B2 + D1 + C-aux · **Status**: locked, not yet run
**Body rule**: no script names in the paper body; point here for operational detail.

Fixed before any arm is run. Nothing below may be changed after seeing a result: the point of
writing it down first is that the reported numbers are not the ones that happened to look best.

## The task, and an honest limitation

**Task**: rebuild the five elementary steps of the glucose → HMF route from reactant and
product SMILES alone. No geometry, atom index or mechanism may be taken from
`deposits/glucose_hmf_review_v3`; the deposited numbers are used only afterwards, to score.

| | |
|---|---|
| Route | glucose (open chain) → HMF, 5 steps |
| Step list | the STRICT path in `graph/canonical/reaction_network.json`, identical to the deposit chain |
| Scoring | per step: does it meet STRICT(v5) clauses 2–4; and does it land on the deposited saddle (imaginary frequency within 40 cm⁻¹) |
| Primary endpoint | is a geometry-continuous STRICT chain delivered end to end (yes/no), plus core-hours used |
| Secondary | steps closed out of 5; of those, how many recover the deposited saddle |

**This is a rediscovery task, not a held-out task, and must be reported as such.** D-29 admits
either; this one is the rediscovery option. The final asset set was shaped during a campaign
that included this route, so the route is not unseen and the comparison cannot support a claim
about generalisation to new chemistry. What it can support is narrower and still worth
measuring: *given the same budget and the same acceptance bar, can each asset set rebuild a
route from SMILES alone.* Any sentence implying the HMF route was withheld from the final assets
would be false.

A genuinely held-out arm would need a target neither asset set was exposed to. That is a
separate, later experiment; it is not this one, and this protocol does not license that wording.

## Arms

Both arms run the same framework — `policy/`, `loop/`, `scripts/` are identical. Only the asset
set differs, and **Reflect is closed on both sides**: no revision may land during evaluation, so
the comparison is between asset versions and not between a learning period and a frozen one.

| Arm | Asset set | Version vector | Contents |
|---|---|---|---|
| initial | `assets/initial` | `sha256:94458f7c2a70ad9c` | 5 declarative skills, geometry toolkit, QM driver. No candidate enumerator, no scoring, no guess ladder. |
| final | `assets/final` | `sha256:7d9a93b062b2f80a` | 6 skills, enumerator + `motif_score`, novelty screen, per-kind guess ladder, full workflow. |

Vector hash = sha256 of the `skills` and `tools` tables of that set's `tools/VERSIONS.json`,
sorted keys, first 16 hex characters. Repository state at locking: `2f85913`.

The initial arm has no guess ladder, so its guesses come from the generic interpolation route in
`generate-ts-guesses`. That is the asset set as it was; substituting a better generator would
make the arms differ in more than the asset version.

## Budget

| | |
|---|---|
| Cap per arm | **180 core-hours** |
| Per-guess wall clock | 5400 s |
| Cores per job | 16 |
| Escalation | if **neither** arm delivers a chain within the cap, both caps are raised together and the raise is recorded here with its reason. Never one arm alone; never after only one arm has run. |

Sizing note: an earlier 20-step from-SMILES sweep cost of order 180 CPU-hours
(`experiments/rediscovery/`), so five steps at roughly 45 CPU-hours leaves about fourfold
headroom. The cap is meant to be generous enough that "did not deliver" means the asset set
could not, not that it ran out of money.

## Reporting

- Primary: delivered / not delivered, per arm, with core-hours used.
- Secondary: steps closed, saddle agreement, and the failure mode of each step that did not
  close (ids from `policy/failure_modes.md`).
- The observational cumulative-STRICT curve may appear as an auxiliary panel of main figure 2.
  It is **not** the comparison: a curve over a campaign confounds asset version with elapsed
  time and budget spent.
- Report the rediscovery caveat above in the same place as the result, not in a footnote.

## Running an arm

The step list is locked in `preregistration/panel.json` under `c2_task_route`, and the task file the
runner consumes is derived from it by `scripts/eval/make_task.py --c2` rather than written by hand.
The runner refuses a task containing any step the preregistration does not hold, so the prohibition
below is enforced rather than merely stated.

```bash
python scripts/eval/make_task.py --c2
python scripts/eval/arm_runner.py --set initial --task runs/tasks/c2_route.json --cap-core-h 180
python scripts/eval/arm_runner.py --set final   --task runs/tasks/c2_route.json --cap-core-h 180
```

Reflect is closed in both arms by prevention and by detection: `asset_snapshot.py` refuses to bump
while an arm runs, and the runner hashes each arm's own assets before and after, so an arm that
edited a skill directly — which the skills' write and edit tools allow — voids itself.

## Prohibitions

- No post-hoc substitution of the task or the step list.
- No raising one arm's cap, and no raising either cap after a single arm has run.
- No asset edit during evaluation, in either arm.
- The diagnostic panel (`saturation_panel.md`) is disjoint from this route and must stay so; if
  a panel edge ever needs to come from this route, this protocol changes first and the change
  is recorded.
- Historical STRICT edges produced under session-style Reflect must not be described as having
  come from the automated loop.
