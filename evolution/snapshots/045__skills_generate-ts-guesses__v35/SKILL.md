# Skill: generate-ts-guesses

Generate transition-state guess structures for a given reaction edge (reactant → product).

## Goal
Produce a small set of high-quality TS guesses that are likely to yield a single dominant imaginary
frequency connecting the specified reactant and product.  Avoid flooding the queue with guesses
that lead to soft modes, endpoint mismatches, or no endpoint records.

## Guidelines

1. **Limit the number of guesses.**  For most edges, aim for 2–4 guesses; do not exceed 5.
   - Use the first guess for a simple linear interpolation or a relaxed scan midpoint.
   - If the reaction is a multi-step transformation (e.g., ring-opening + dehydration),
     break it into elementary steps and guess only the first kinetically relevant step.

2. **Guess generation strategy.**
   - For isomerization/tautomerization: produce a guess that is a weighted average of the
     reactant and product geometries (e.g., 50:50) with key atoms (the migrating H or bond-breaking
     atoms) slightly displaced toward the product.  Use a small displacement (0.1–0.3 Å) to avoid
     landing in flat regions.
   - For ring-opening: stretch the breaking bond by 0.3–0.5 Å and relax the rest of the ring
     with a constraint, then remove the constraint for the final guess.
   - For dehydration/dehydrogenation: identify the leaving group and the acceptor atom; place the
     H in a bridging position (1.2–1.5 Å from donor and acceptor) and adjust the heavy-atom
     distances accordingly.

3. **Avoid guesses that produce soft modes.**
   - Do not guess a structure that is essentially a local minimum of the reactant or product
     (e.g., a slight rotation of a hydroxyl group).  Such guesses often yield imaginary frequencies
     below 100 cm⁻¹ that do not correspond to the reaction coordinate.
   - If a previous guess for the same edge gave a soft mode (< -150 cm⁻¹) and no endpoint match,
     do not repeat it.  Instead, vary the displacement direction or add a weak constraint that
     forces the reaction coordinate to be stiffer.

4. **Prioritise early-path kinds.**
   - Ring-opening and tautomerization are often early steps in the glucose-to-HMF network.
     Spend more effort on these, as they are more likely to lead to STRICT edges.
   - Dehydration and dehydrogenation are later steps; generate guesses only if the earlier
     steps have been validated.

5. **Output format.**
   For each guess, provide:
   - `guess_id`: a unique label (e.g., `r{round}_g{index}`)
   - `geometry`: xyz block or SMILES with coordinates
   - `method`: brief description of how the guess was constructed

## Constraints
- Do **not** generate guesses for edges that are obviously impossible (e.g., breaking a C–C bond
  without any driving force).
- Do **not** generate guesses that would require more than 30 atoms to keep the system size
  manageable.
- All guesses must respect the atom connectivity of the reactant and product (no atom creation
  or deletion).
