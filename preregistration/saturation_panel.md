# D-28 — saturation panel (preregistered)

**Decision**: A2 · **Locked**: panel, K and ε. Do not change after seeing a curve.

Answers one question: when has revising the assets stopped paying, so the set can be frozen and
the fixed-asset comparison can begin.

## Why the panel is fixed in advance

If saturation were judged on whichever edges happened to fail in a given round, the stopping
decision would be made on the same data it is evaluated against — the run would stop wherever
the numbers looked best. A small fixed panel makes the judgement independent of what the round
happened to produce.

**The panel is disjoint from the C2 task.** Every edge below was checked against the
glucose → HMF route in `c2_protocol.md` and excluded if it appeared there, so a stopping
decision cannot indirectly fit the evaluation set. All nine edges already have attempt records,
so the baseline costs no new computation.

## The panel — three mechanism classes, three edges each

Chosen to span outcomes, not to look good: a panel of only-passing edges can only detect
regression, and one of only-failing edges can only detect improvement.

### Concerted dehydration

| # | Reactant → product | Kind | Status at locking | imag (cm⁻¹) | Attempts |
|---|---|---|---|---|---|
| D1 | `OCC1OC(O)(CO)C(O)C1O` → `OC=C1OC(CO)C(O)C1O` | dehydration | validated | −1035.9 | 2 |
| D2 | `OC=C1C=CC(O)(CO)O1` → `O=Cc1ccc(CO)o1` + H₂O | dehydration | PARTIAL_MATCH | −502.7 | 2 |
| D3 | `OC=C1C=CC(O)(CO)O1` → `OC=c1ccc(=CO)o1` + H₂O | dehydration | NOT_CLEAN_TS | −154.1 | 2 |

**Limitation, stated because it bounds what this class can show**: no STRICT dehydration is
available here — every dehydration that meets the bar lies on the C2 route and is therefore
excluded. This class can detect improvement but not regression. Do not read a flat D-class as
evidence of stability.

### Dry proton transfer

| # | Reactant → product | Kind | Status at locking | imag (cm⁻¹) | Attempts |
|---|---|---|---|---|---|
| P1 | `O=CC(O)C(O)C(O)C(O)CO` → `O=C(CO)C(O)C(O)C(O)CO` | isomerization | STRICT | −434.7 | 4 |
| P2 | `OCC1OC(O)C(O)C(O)C1O` → `O=CC(O)C(O)C(O)C(O)CO` | isomerization | validated | −201.1 | 1 |
| P3 | `O=CC(O)C(O)C(O)=CO` → `OC=C(O)C(O)C(O)=CO` | keto_to_enol | NOT_CLEAN_TS | −248.0 | 1 |

### Retro-aldol

| # | Reactant → product | Kind | Status at locking | imag (cm⁻¹) | Attempts |
|---|---|---|---|---|---|
| R1 | `O=C(CO)C(O)C(O)C(O)CO` → `O=CC(O)CO` + H₂O | retro_aldol | STRICT | −758.1 | 7 |
| R2 | `O=CC(O)C(O)C(O)C(O)CO` → `O=CC(O)C(O)CO` + H₂O | retro_aldol | PARTIAL_MATCH | −386.4 | 6 |
| R3 | `O=CC(O)C(O)C(O)C(O)CO` → `O=CCO` + H₂O | retro_aldol | NOT_CLEAN_TS | −27.1 | 1 |

R3 is a one-step C6 → C2 cleavage. It is implausible as an elementary step and the record shows
a near-zero mode; it is in the panel as a hard negative, not as a route candidate.

Edges whose species are strained-ring enumeration artefacts (three-membered rings) were excluded
even where the outcome tier fitted: a diagnostic panel should measure the tools on chemistry the
campaign is about.

## Stopping rule

- Window: **K = 3** consecutive finished Explore→Validate rounds.
- Threshold: **ε = 5%**. Stop when, for each of the last K rounds,
  `d_strict / max(1, n_strict_before) < 0.05`, **or** `d_strict == 0` for all K.
- The stricter operational gate (`d_strict == 0` for K rounds) may be used as a sufficient
  condition. **Report which of the two fired.**
- The panel is re-measured under the current asset set at each window; the quantity compared is
  the pass rate over the nine edges and the core-hours per passing edge.

## Reporting

- Cumulative STRICT against attempts and against core-hours, labelled with the panel and with
  (K, ε).
- Per-class pass rate across windows, with the dehydration limitation noted above.
- Do not retune K or ε after seeing the curve. Do not substitute a panel edge for one that moved
  in a convenient direction.
- The panel is **not** the C2 evaluation set and its numbers are not comparable to C2's: it
  measures whether revision has stopped paying, not whether one asset set beats another.
