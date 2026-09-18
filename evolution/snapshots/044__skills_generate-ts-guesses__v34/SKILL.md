# generate-ts-guesses Skill

Generate transition state guesses for a given reaction edge.

## Input
- Reactant SMILES: ...
- Product SMILES: ...
- Reaction kind: ...

## Output
A list of TS guess geometries, each with a brief description.

## Guidelines
1. **Quality over quantity**: Generate at most 2 guesses per edge. If the reaction is a simple proton transfer or bond rotation, 1 guess is sufficient.
2. **Single imaginary mode**: The guess should be a first-order saddle point with one imaginary frequency corresponding to the reaction coordinate. Avoid geometries that are too close to reactant or product (would have no imaginary mode) or too flexible (would have many low-frequency modes).
3. **Structural interpolation**: Construct the guess by linearly interpolating the Cartesian coordinates of the atoms involved in the bond breaking/forming between reactant and product, while keeping the rest of the molecule relaxed. This ensures the guess is structurally intermediate.
4. **Avoid flexible regions**: Do not generate guesses that involve large floppy rings or many rotatable bonds unless the TS is constrained. If the molecule has many rotatable bonds, freeze them at the reactant or product geometry.
5. **Check connectivity**: Ensure the guess is a valid connectivity (no atoms overlapping) and the key bond lengths are between typical single and double bond distances.
6. **Use known benchmarks**: If the reaction is a common type (e.g., Diels-Alder, aldol, dehydration), consult known TS geometries from literature or databases.