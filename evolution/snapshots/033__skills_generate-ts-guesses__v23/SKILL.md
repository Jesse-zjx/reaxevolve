# Generate TS Guesses Skill

## Purpose
Produce high-quality initial transition-state geometries for a given reactant-product pair. The goal is to minimise the occurrence of soft or non-reactive modes that lead to `no_dominant_mode` failures.

## Strategy

1. **Prefer directed guesses** from a relaxed scan of the key bond that is breaking or forming. If a scan is not feasible, use a linear-interpolation-along-reaction-coordinate (LIRC) approach, but only when the reactant and product are close in geometry (RMSD < 1.5 Å over core atoms).
2. **Avoid large conformational changes** that are not captured by a single simple reaction coordinate (e.g., ring openings involving multiple bond reorganisations). For those, split into sub-steps or request a multi‑guess staging.
3. **Generate at most 2–3 candidates per edge**, dropping any that are energetically unreasonable (e.g., > 100 kcal mol⁻¹ above either endpoint) or that differ from the reactant/product by more than 3 Å in key atom positions.
4. **Immediately filter by frequency** (if the driver allows): after gradient minimisation to a first-order saddle point, discard any guess that yields:
   - No imaginary frequency, or
   - An imaginary frequency with magnitude < 200 cm⁻¹ (soft mode), or
   - More than one imaginary frequency.
   If discarded, fall back to a different generation method (e.g., a different scan coordinate or a different dihedral) before returning the guess.
5. **Flag low-confidence guesses** for early-path kinds (tautomerisation, dehydration) that are known to be tricky; only propose them if the middle has already failed with the same approach.

## Output

Provide a JSON list of guesses, each with:
- `geometry` (XYZ or SDF),
- `method` (scan, LIRC, manual),
- `expected_imag_mode` (description of the bond motion),
- `confidence` (high/medium/low).

Only return guesses that passed the frequency filter (or, if the driver does not permit pre‑filtering, include a note that the guess is expected to have a strong single imaginary frequency).