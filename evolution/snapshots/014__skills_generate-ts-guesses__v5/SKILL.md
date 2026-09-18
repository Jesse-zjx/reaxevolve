# Transition State Guess Generation

Generate guesses that are **high-quality** rather than numerous. Each guess must have a plausible single imaginary mode to ensure the TS search and IRC can succeed.

## Rules

1. **Limit guesses per reaction to 3** – beyond that, the mechanism is likely not viable or the starting geometry is poor.
2. **Pre‑screen every guess with a fast method** (e.g. GFN2‑xTB or a cheap DFT) before submitting:
   - Run a vibrational frequency calculation on the guess geometry.
   - Accept only guesses with **one imaginary mode** of magnitude **> 100 cm⁻¹**.
   - Discard guesses with multiple imaginary modes or no imaginary mode.
3. **Focus on chemically elementary steps** – especially those that appear in the pending queue (tautomerization, dehydration) but also any isomerization/tautomerization that can be localised.
4. **For tautomerization / isomerization**
   - Use a simple proton‑transfer guess (e.g. a water molecule as a shuttle, or a direct 1,3‑H shift).
   - Avoid guesses that would require large conformational changes; keep the heavy‑atom framework as close as possible to the reactant/product.
5. **For dehydration**
   - Ensure the leaving group (OH) is pre‑oriented to leave as water, and that the adjacent hydrogen is positioned for elimination.
   - If the previous guess gave `one_end_only`, try a geometry that is closer to the product side.
6. **Re‑use failure information**
   - If a reaction already failed with `no_dominant_mode` (soft mode), the guess was too far from the true TS – try a different arrangement or skip the reaction.
   - If it failed with `no_endpoint_record`, the IRC likely diverged or didn’t terminate; the guess geometry may be in a flat region – try a different approach or add a constraint.
7. **Avoid unattributed reactions** – if the algorithm cannot assign a reaction kind, the guess is probably chemically ill‑defined; do not spend attempts on it.

## Output

For each accepted guess, provide the SMILES string of the guess geometry and the rationale (reaction kind and how the guess was constructed).

## Goal

More guesses that immediately yield a single dominant imaginary mode, leading to IRC endpoints that match the intended reactant/product, and finally to STRICT edges.