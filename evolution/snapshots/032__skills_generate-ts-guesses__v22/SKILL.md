# generate-ts-guesses

## Purpose
Propose 3-5 initial guess geometries for transition state optimization, given reactant and product SMILES and a reaction kind. The goal is to produce guesses that lead to a first-order saddle point with a single imaginary mode of magnitude > 100 cm⁻¹.

## Procedure
1. Parse reactant and product SMILES, generate 3D conformers.
2. Identify the reaction center (atoms whose bonding changes according to the prescribed reaction kind).
3. For each candidate guess:
   a. Create a linear interpolation between reactant and product at a fraction of 0.4–0.6 along the reaction coordinate (default 0.5).
   b. Apply a small random perturbation along the direction that breaks/forms bonds to ensure the guess is not symmetrically a minimum.
   c. Perform a crude energy minimization with a loose convergence criterion to relieve steric clashes, but stop early if the gradient norm drops below 0.01 au.
   d. Check that the final guess has a gradient norm > 0.005 au and that the distance to the closest endpoint (reactant or product) is at least 0.5 Å RMSD. If not, restart with a different fraction or perturbation.
4. Output the list of guess geometries in XYZ or SDF format, along with a confidence score.

## Quality criteria
- The guess must not be a local minimum (i.e., ensure gradient norm > 0.005 au).
- The guess should be structurally distinct from both reactant and product (RMSD > 0.5 Å).
- If the reaction kind is isomerization/tautomerization, prioritize perturbations that involve moving hydrogens or breaking/forming double bonds.
- If the reaction kind is dehydrogenation or dehydration, ensure the guess includes a partially formed/cleaved bond with appropriate distance (e.g., 1.5–2.0 Å for C–H or C–O).
- Discard guesses that are too similar to previous failed attempts for the same edge (RMSD < 0.2 Å).

## Notes
- If no guess meets quality criteria after 10 attempts, report failure and suggest a different reaction kind or edge.