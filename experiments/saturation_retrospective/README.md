# Saturation rule, retrospectively

`loop/saturation.py` enforces the preregistered stopping rule for future runs. This directory
asks the separate question of whether the rule would have fired on the campaign that already
happened — and answers it mostly in the negative, which is why it is here rather than folded into
a results section.

| file | |
|---|---|
| `analyse.py` | the analysis; deterministic from tracked inputs |
| `RESULT.md` | generated; do not edit by hand |

```bash
python experiments/saturation_retrospective/analyse.py --write
```

## The finding

The rule fires at one of the five block sizes tried and not at the other four. The campaign's
accepted-edge growth does end in a run of zero-growth blocks, but that run is one block short of
the K=3 the protocol requires, so **the recorded campaign does not meet the preregistered
saturation criterion.**

A second point matters as much: at ε=5%, the threshold only admits a nonzero increment once the
accepted-edge count reaches 20, and this stream reaches 14. So at this scale the preregistered ε
is arithmetically almost the same rule as "no new accepted edge at all", and the distinction the
protocol draws between the two conditions does not yet have room to show itself.

## Why this is here and not in a results section

Rounds do not exist in the recorded campaign — it was session-style — so they have to be
constructed, and the block size is a free parameter. Reporting a single block size chosen after
seeing the outcome would be meaningless, so every size in a stated range is reported and the
conclusion is whatever survives. What survives is that the rule mostly does not fire.

Consequences worth being explicit about:

- Nothing here licenses "the loop ran until saturation". The loop never ran under this rule.
- Any sentence stating that assets were frozen *because* evolution gains had saturated is not
  supported by this analysis, and needs either rewording or a fresh run under the rule.
