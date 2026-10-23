# Rediscovery from SMILES alone

Every elementary step of the three expert-reviewed deposits was rebuilt using the automated
dispatcher and nothing else: reactant and product SMILES in, guess generation, OptTS,
NumFreq and IRC out. No geometry, atom index or mechanism was taken from the deposits. The
deposited numbers were used only afterwards, to score the result.

This is **negative control B** in `evidence/controls.md` — a hard baseline, not a
should-fail control. It measures how far the guessing stack gets when it is refused the
answer.

**Result: 7 of 20 steps closed as STRICT**, 4 of them on the deposited saddle with the
imaginary frequency agreeing to 7.1 cm⁻¹ on average. Full table:
[`REPRODUCTION_REPORT.md`](REPRODUCTION_REPORT.md).

## Files

| File | Role |
|---|---|
| `comparison.json` | Scored result, one row per deposit step. The data everything else reads. |
| `results/*.json` | Raw per-step outcome as the dispatcher recorded it (20 files). |
| `render_report.py` | Renders `REPRODUCTION_REPORT.md` from `comparison.json`. |
| `REPRODUCTION_REPORT.md` | Generated. Do not hand-edit. |
| `run_shard.py` | Historical runner that produced `results/`. It called the retired `validate_candidate.py` dispatcher, not the live `run_qm_step.py` loop. Kept as the definition of what was run. |

```bash
python experiments/rediscovery/render_report.py           # regenerate the report
python experiments/rediscovery/render_report.py --check   # fail if the report is stale
```

The report is generated rather than written because the hand-maintained version shipped with
the campaign said six steps closed while the scored data said seven: a later round recovered
`HMF_s2` and the prose was never updated. Generating it makes that class of drift impossible.

## Not distributed

Per-run ORCA scratch, live monitoring scripts and the single-host launch wrappers describe
one machine rather than the experiment, and are gitignored. `run_shard.py` is kept because it
is the definition of what was run; reproducing the sweep needs roughly 180 CPU-hours at the
4 cores per job used here.

## Reading discipline

Do not merge these counts into the accepted-network count in
`evidence/state/NETWORK_STATE.md`. That one counts edges in the network under STRICT(v5);
this one counts rediscovery attempts against a fixed 20-step target. Cite this as the
hardness of the guessing problem under a strict bar, not as a verdict on the system.
