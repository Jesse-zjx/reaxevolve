# D-28 — Saturation panel (preregistered)

**Decision**: A2  
**Locked**: mechanism panel + K + ε (do not change post hoc).

## Panel (three mechanism classes)

| Class | Representative kinds | Role |
|---|---|---|
| Dehydration | `dehydration`, aromatizing dehydration | Furanic cascade |
| Dry proton transfer | keto↔enol / enediol tautomerization (dry ladder) | H-shift without catalytic water |
| Retro-aldol | C–C cleavage with β-carbonyl activation | Branching to HAA / C2–C3 |

## Stopping rule

- Window size **K = 3** consecutive finished Explore→Validate rounds.
- Relative growth threshold **ε = 5%**: stop when each of the last K rounds has
  `d_strict / max(1, n_strict_before) < 0.05` **or** `d_strict == 0` for all K
  (implementation may use the stricter operational gate `d_strict == 0` for K rounds
  as a sufficient condition; report which fired).

## Reporting

Report cumulative STRICT vs attempt/core-hour curves with the panel label and (K, ε).
Do not retune K/ε after seeing the curve.
