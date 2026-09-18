# Generate TS Guesses Skill

## Purpose
Propose transition-state (TS) guesses for unresolved edges in the reaction network, aiming to create new STRICT edges that advance the route toward HMF.

## Input
- A list of unresolved reaction edges (reactant → product pairs) with their kind (dehydration, tautomerization, dehydrogenation, etc.)
- Current network state (what is already known)

## Output
- A set of TS guesses, each with a 3D geometry and a label.

## Core Rules
1. **Prefer single‑imaginary modes.** Every guess must correspond to a well‑defined saddle point with exactly one imaginary frequency. Check the Hessian of the initial guess; if it shows multiple large imaginary modes or a dominant soft mode (< 100 cm⁻¹), discard the guess and try a different geometry.
2. **Favor chemically simple steps.** The mechanism should involve a single bond‑breaking/forming event (e.g., proton transfer, water elimination). Avoid guesses that require simultaneous ring‑opening/closure and dehydration unless the ring already exists in the reactant and the dehydration is a simple elimination from that ring.
3. **Prioritise early‑path dehydration and tautomerization.** Dehydration of aldoses to form enols or furanoids is the most direct route to HMF. Tautomerization (keto‑enol) is also benign. Dehydrogenation should be considered only when a suitable alcohol is already adjacent to a carbonyl.
4. **Keep the geometry close to the reactant.** The TS guess should be no more than 2–3 Å from the reactant structure. Large conformational jumps (e.g., breaking a pyranose ring to form a linear chain) are unlikely to yield a usable TS; instead, propose a stepwise process.
5. **Limit the number of guesses per edge.** For each unresolved edge, provide at most 2 guesses. If the first guess fails, the second may be a refined version (e.g., tighter initial Hessian, explicit solvent molecule if needed). Do not flood the queue with low‑confidence guesses.
6. **Use standard naming.** Label each guess as `r<edge_index>_g<guess_number>`, e.g., `r1_g2`.

## When to skip a guess
- If the product is more than 2 heavy‑atom rearrangements away from the reactant.
- If the edge kind is “fragmentation” and the products are small molecules (C1–C2) – fragmentation rarely produces a clean TS in one step.
- If the reactant already contains a rigid ring and the product requires breaking that ring – such a step is better handled by a sequence of two edges (ring‑opening then dehydration).

## Success metrics
After validation, the guess should show:
- A single imaginary frequency between 100 cm⁻¹ and 2000 cm⁻¹ (dominant mode).
- IRC endpoints that match the reactant and product (both forward and backward).
- No missing endpoint records.

## Revision history
- v1: initial version
- v2: added rules for single‑imaginary mode, geometric proximity, and skip conditions to reduce no_endpoint_record and no_dominant_mode failures.