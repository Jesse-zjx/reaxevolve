# TS Guess Generation Skill

Generate high-quality transition-state guesses for reaction edges.

## Goal
Produce a set of guess geometries that are likely to yield a single dominant imaginary frequency pointing along the reaction coordinate, avoiding soft modes, endpoint-only matches, or no-IRC-record failures.

## Protocol

1. **Input**: For each edge, receive `reactant_smiles`, `product_smiles`, `reaction_kind`, and any previous failure data.

2. **Guess count**: Generate at most **3 guesses per edge**. If all guesses fail validation, stop and mark the edge as unresolved.

3. **Kind-specific guess construction**:

   - **Isomerization / Tautomerization** (dominant soft-mode failure):
     - Identify the atoms involved in the bond reorganisation (e.g., for H-transfer, the donor, hydrogen, and acceptor).
     - Create a guess by placing the migrating atom(s) **midway** along the reaction vector, using internal coordinate interpolation (e.g., average of donor‑H and acceptor‑H distances).
     - Relax the rest of the molecule with a short force-field or semi-empirical optimisation (e.g., GFN2-xTB) while keeping the reaction coordinate fixed.
     - The resulting geometry should be distinct from both reactant and product minima. Avoid guesses that are nearly identical to either endpoint.

   - **Dehydrogenation / Dehydration**:
     - For elimination reactions, identify the atoms forming the new bond and the leaving group. Place the migrating hydrogen or water molecule halfway between its original and final positions while completing the forming double bond.
     - Use a similar constrained relaxation to obtain a plausible TS geometry.

   - **Other kinds**: Use the same interpolation principle: pick the reactive atoms, construct a midpoint geometry, and relax.

4. **Quality check (optional)**: If the TS search has already been attempted and failed (e.g., `no_dominant_mode`), discard the current guess and try a different interpolation (e.g., shift the reactive coordinate by 10 % towards product).

5. **Reporting**: If no guess yields a dominant imaginary frequency, report the best-attempt failure mode (e.g., `no_dominant_mode`, `no_endpoint_record`) to aid reflection.

## Output
Return a list of guess geometries (as XYZ or SMILES with explicit coordinates) to be used for TS optimization.