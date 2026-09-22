# Bar-resolution negative control

Does the acceptance bar reject a method that should fail? Without an answer, "every accepted edge
met the bar" is also consistent with a bar that accepts almost anything.

The probe reaches a deposited dry saddle by uniform linear interpolation between reactant and
product geometries — no reaction-coordinate reasoning — and submits the result to the unmodified
acceptance path.

| file | |
|---|---|
| `../../preregistration/bar_resolution_probe.md` | design and the three outcomes, **committed before the calculation** |
| `run_probe.sh` | the run: geometry → naive guesses → unmodified acceptance path |
| `verdicts/g{1,2,3}.json` | the verdict records, copied out of the untracked run tree |
| `render_report.py` | classifies each verdict against the declared outcomes |
| `RESULT.md` | generated; do not edit by hand |

## Result

All three candidates were rejected, and the informative part is *which* clause did it: each was a
clean single-imaginary-mode saddle, so a bar that asked only "is this a proper transition state?"
would have accepted all three. They were rejected because the IRC does not relax to the stated
reactant and product. The endpoint clause is what carries the weight.

## Regenerating

```bash
python experiments/bar_resolution/render_report.py --write   # from the tracked verdicts, seconds
bash experiments/bar_resolution/run_probe.sh                 # re-run the QM, ~2.5 h on 16 cores
```

The renderer prefers `verdicts/` so the report regenerates in a fresh clone; it falls back to
`runs/bar_resolution/` when the probe has just been run.

## What this control does not show

It is one step and one guess method: it shows the bar rejects *this* naive method *here*, and does
not bound the false-accept rate in general. It says nothing about false rejections — how often the
bar turns away a correct mechanism is what negative control B measures (`evidence/controls.md`).
