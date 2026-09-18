# Generate TS Guesses

## Purpose
Propose initial transition-state (TS) geometries for a given reactant→product reaction pair.

## Guiding Principles
- **Quality over quantity**: generate at most **2 guesses per reaction** (unless the reaction is a simple tautomerisation where a single midpoint guess often suffices).
- **Method diversity**: for each reaction, prefer one guess from a reactant-like perturbation and one from a product-like perturbation, unless the reactant and product are very similar.
- **Avoid soft modes**: guess geometries must be pre-optimised to exhibit a single imaginary frequency > 100 cm⁻¹ whenever possible. If a guess yields only soft modes (< 100 cm⁻¹), discard it and do not retry with the same perturbation strategy.
- **Prioritise pending reaction kinds**: focus on dehydration, tautomerisation, and ring-opening reactions that are currently in the queue (see `queue_summary`).
- **Reaction coordinate awareness**: the guess should lie along a plausible reaction coordinate:
  - For bond-breaking/forming reactions (e.g. dehydration, ring-opening): elongate the breaking bond by ~0.5 Å and shorten the forming bond by ~0.5 Å relative to the reactant/product.
  - For isomerisations/tautomerisations: use a linear interpolation or a constrained scan along the key torsion/bond length.
- **No random perturbations**: do not generate guesses by random displacement of atoms; every guess must be based on a chemically meaningful distortion.

## Workflow
1. Analyse the reactant and product SMILES to identify the key bond changes.
2. If the reaction is a tautomerisation, generate one guess from a midpoint geometry (e.g., average of reactant and product internal coordinates).
3. For other reactions, generate:
   - One guess by perturbing the reactant geometry along the reaction coordinate towards the product.
   - One guess by perturbing the product geometry backwards along the reaction coordinate towards the reactant.
4. For each guess, perform a quick gradient minimisation with a fixed reaction coordinate constraint to ensure the mode is clean.
5. If after step 4 the guess exhibits a single imaginary frequency > 100 cm⁻¹, submit it; otherwise mark it as failed and log the reason.

## Output
Return a list of guess configurations, each with:
- `guess_id`
- `method` (reactant_perturb, product_perturb, midpoint)
- `perturbation_detail` (which bonds were altered and by how much)
- `expected_imaginary_frequency` (estimated range)
