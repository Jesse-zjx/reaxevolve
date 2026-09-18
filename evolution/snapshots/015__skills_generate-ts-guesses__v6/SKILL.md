# Generate Transition-State Guesses

This skill produces 3D structures that are plausible transition states for a given reaction.

## Quality-first generation
- For each reaction, generate at most 3 guesses, each with a distinct chemical rationale (e.g., bond-breaking, bond-forming, concerted).
- Prefer guesses that involve a single dominant imaginary frequency after a quick Hessian calculation.

## Pre-validation step
- After building a guess, run a frequency calculation with a tight convergence (e.g., `opt=(ts,calcall,noeigentest) freq`).
- Discard any guess that does **not** have exactly one imaginary frequency with magnitude > 100 cm⁻¹.
- If the guess passes, proceed to the full IRC calculation; otherwise, discard it and generate a backup.

## Backup strategy
- If all initial guesses fail the pre-validation, generate one more guess by interpolating the reactant and product along the reaction coordinate (e.g., using the breaking/forming bond distances).
- Apply the same pre-validation.

## Context
- The current campaign shows a high rate of guesses with no dominant imaginary mode (soft modes only), leading to wasteful IRC attempts that never record endpoints.
- This revision aims to filter out such guesses early, saving core-hours and increasing the fraction of TS guesses that lead to a clear IRC path.