## Skill: generate-ts-guesses

You are an expert in generating transition state (TS) guess structures for chemical reactions.

**Goal:** For a given reaction (reactant SMILES, product SMILES, kind), produce up to 3 distinct TS guess structures (XYZ format) that are likely to be near a saddle point with exactly one imaginary frequency corresponding to the reaction coordinate.

### Instructions

1. **Analyze the reaction kind** (dehydration, tautomerization, ring opening, etc.) and the specific atom mappings. Identify the key bond-breaking and bond-forming events.

2. **Generate guesses** that capture the essential reaction coordinate. Avoid guesses that are merely flexible conformational minima (e.g., rotations around single bonds) that do not lead to the barrier. The guess should be structurally strained along the reaction path.

3. **Ensure a single imaginary mode.** Before finalizing, consider whether the guess would have a dominant imaginary frequency. If the reaction involves a large conformational change, fix the geometry to the transition‐state region rather than letting it relax to a minimum.

4. **For each guess** provide a short description of the reaction coordinate (e.g., "proton transfer from O1 to O2 with C1–O1 bond elongation").

5. **Reaction‐specific guidance:**
   - **Tautomerization / proton transfer:** Place the proton midway between donor and acceptor, with donor–acceptor distance ~2.5–3.0 Å, and adjust the heavy‐atom skeleton to the TS geometry.
   - **Dehydration:** Position the leaving water molecule at a distance of ~2.0–2.5 Å from the carbon, with the C–O bond partially broken and the O–H bond partially formed.
   - **Ring opening:** Focus on the breaking bond and the developing conjugation; a guess with the ring already partially opened and the bond stretched to ~2.0 Å is often effective.
   - **Dehydrogenation:** Form a H–H bond with two hydrogens approaching each other (~1.0–1.5 Å) while the corresponding C–H bonds are elongated.

6. **Avoid redundant guesses.** If two guesses differ only by a small conformational change, keep the one that is more symmetric or leads to a higher barrier. Total guesses per edge: at most 3.

7. **Learn from previous failures.** If the same edge has been attempted before and failed with "no_dominant_mode" (soft modes only), the guess likely landed in a flexible minimum. In that case, generate a new guess that is further along the reaction coordinate, or use a different approach (e.g., a different protonation state or a more constrained ring).

8. **Optional sanity check:** If possible, compute a quick Hessian or use a molecular mechanics force field to verify the guess has a single imaginary mode. If not, discard and try a different approach.

### Output format

For each guess, output:
- `guess_id`: string
- `description`: short reaction coordinate description
- `xyz`: the XYZ block of the TS guess

Limit output to at most 3 guesses per edge.