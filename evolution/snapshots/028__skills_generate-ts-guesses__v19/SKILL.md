# generate-ts-guesses skill

Given a reaction edge with reactant and product SMILES, generate a small set of high-quality transition state guesses. The goal is to produce guesses that are likely to converge to a true first-order saddle point connecting the two species.

## Input
- reactant_smiles (str)
- product_smiles (str)
- reaction_kind (str, optional)

## Output
- A list of TS guess geometries (xyz format) with metadata.

## Guidelines
1. Generate at most 3 guesses per edge. Prioritize quality over quantity.
2. Use interpolation methods that respect the reaction coordinate: e.g., LST (linear synchronous transit) or QST2 if available. Avoid random perturbation.
3. For each guess, perform a quick preliminary Hessian calculation (or use a cheap method) to check for imaginary frequencies. Discard guesses that have no imaginary mode or multiple large imaginary modes before full TS optimization.
4. If the interpolation yields a guess with zero imaginary modes, adjust the structure to break symmetry or add a small displacement along the expected reaction mode.
5. For tautomerization/isomerization, focus on the proton transfer path; use a guess with the transferring hydrogen positioned midway between donor and acceptor atoms.
6. If an edge has already had multiple failed attempts (as per recent history), default to no more than 1 guess, or skip if all previous attempts failed due to soft modes.
7. Ensure that the guess does not correspond to a stable intermediate (minimum) by checking the energy gradient; if the gradient is very small, perturb the structure.

## Rationale
This revision aims to reduce the high rate of "no_dominant_mode" failures (soft modes) observed in the TS validation, which wastes computational resources and hinders the discovery of valid STRICT edges.