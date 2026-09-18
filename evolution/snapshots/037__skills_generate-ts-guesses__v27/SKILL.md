# generate-ts-guesses

Generate a ranked list of initial TS guess geometries for a given reaction (reactant + product SMILES).

## Input
- reactant_smiles: string
- product_smiles: string
- reaction_kind: string (e.g., isomerization_or_tautomerization, dehydration, etc.)

## Output
A JSON array of guesses, each with a geometry (xyz) and a priority score.

## Procedure
1. Parse the reactant and product SMILES, generate 3D conformers, and align them to a common frame.
2. Generate a set of initial guesses using the following methods:
   - Linear interpolation between reactant and product (0.4, 0.5, 0.6 points along the distance-weighted interpolation).
   - Product-like template: start from the product geometry and perturb along the reaction coordinate towards the reactant.
   - Reactant-like template: start from the reactant geometry and perturb towards the product.
   - If a known reaction fingerprint is available, use a pre-trained guess generator.
3. **Filter out guesses that are too similar to either endpoint.** For each guess:
   - Compute the RMSD to the reactant and product geometries (after alignment).
   - If the RMSD to either is less than 0.5 Å, discard the guess.
   - If the guess is discarded, generate a new guess by displacing the discarded guess along the vector from reactant to product (or vice versa) by 0.5 Å.
   - Repeat until a guess with RMSD > 0.5 Å to both endpoints is obtained (max 5 attempts).
4. Compute a simple energy estimation (e.g., using a force field) for each guess and add a bias term for guesses that are known to be promising for the reaction kind.
5. Rank guesses by energy (lower is better) and return the top N (where N is configurable, default 3).

## Notes
- The filtering step is critical to avoid guesses that lie in flat regions of the potential energy surface, which often result in 'no_dominant_mode' failures (soft mode, not a genuine saddle point).
- Do not discard guesses that are dissimilar but have high energy; they may still lead to valid TS structures.
- The RMSD threshold of 0.5 Å is a heuristic; adjust if the reaction involves large conformational changes.