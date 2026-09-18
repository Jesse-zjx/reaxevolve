# SKILL: generate-ts-guesses

## Purpose
Produce a small set of high-quality initial TS geometry guesses for a given reaction edge, aiming for a single imaginary mode connecting the reactant and product.

## Input
- `edge`: dict with reactant SMILES, product SMILES, reaction kind, priority.
- `graph_context`: surrounding graph state (nodes, edges, STRICT edge count).

## Output
A list of TS geometry guesses, each with a geometry (XYZ string) and a label (e.g., `r0_g1`). Maximum 2 guesses per edge.

## Procedure
1. **Analyze reaction type**: identify bond changes (forming/breaking) and major atom movements.
2. **Generate guess(es)**:
   a. Use a linear interpolation between reactant and product geometries (weighted 0.5) as a starting point, then displace along the reaction coordinate.
   b. If the reaction involves ring formation/breaking, use a constrained ring-opening guess.
   c. Avoid generating guesses that are too close to either endpoint (to prevent one-end-only failures).
3. **Prioritize early-path kinds**: dehydration, tautomerization, ring closure (if toward HMF). For late-stage or complex ring transformations, consider only if simpler paths have failed.
4. **Discard low-quality guesses**: if initial Hessian calculation (if available) suggests no imaginary mode or a very soft mode (< 100 cm⁻¹), discard that guess and try a different displacement.
5. **Return** the list of guesses with geometries.

## Guidelines
- **Fewer, better**: Aim for 1–2 guesses per edge, not many. Quality over quantity.
- **Single-imag focus**: The goal is a TS with exactly one imaginary mode. If a guess repeatedly yields only soft modes, skip that edge and suggest a different reaction mechanism.
- **Avoid extremes**: Don't guess late-stage HMF-adjacent edges unless intermediate steps are already validated.
- **Log failures**: Record which guesses led to soft-mode failures, and use that information to adjust future guesses.