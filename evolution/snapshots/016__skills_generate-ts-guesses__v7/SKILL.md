# Skill: generate-ts-guesses

## Purpose
Generate transition state (TS) guess structures for a given reaction edge. The goal is to produce a guess that, when optimized, yields a saddle point with a single imaginary mode corresponding to the reaction coordinate.

## Instructions
When generating a TS guess:

1. Understand the reaction: Analyze the reactant and product SMILES to identify the bonds broken and formed, and the overall geometry change.
2. Construct a guess geometry that is approximately halfway along the reaction coordinate. Use typical bond lengths: forming/breaking bonds at ~2.0–2.5 Å, other bonds at standard equilibrium lengths.
3. Ensure the guess has a single imaginary mode of substantial magnitude (>100 cm⁻¹). Avoid symmetric arrangements that might lead to degenerate soft modes. For example, if the reaction involves a proton transfer, place the proton between the donor and acceptor with an asymmetric distance to avoid a symmetric double-well.
4. If the reaction is a ring closure or opening, adjust dihedral angles to place the atoms in a near-transition state conformation.
5. Output the guess as a single XYZ block with the correct atom count and element symbols. No commentary.
6. Generate only one guess per call. If the guess fails validation, a subsequent call may generate an alternative guess with a different approach.

## Guidelines for common failure modes
- **No endpoint record**: The guess is not a true TS. Ensure the guess is closer to the saddle point; try a different geometry or a different bond-breaking/forming pattern.
- **No dominant mode**: The guess has only soft modes (<100 cm⁻¹) or multiple modes. The guess likely lacks a clear reaction coordinate. Add asymmetry or choose a different reaction path.
- **One end only**: The guess connects to one reactant/product but not the other. The guess is not symmetric; adjust to make both endpoints accessible.

## Model prompt
When invoking the Gemini model, use the following system prompt:

"You are a computational chemist. Given a reactant SMILES and a product SMILES, generate a transition state guess in XYZ format. The guess should be a saddle point with a single imaginary mode of magnitude >100 cm⁻¹ corresponding to the reaction coordinate. Place the atoms at appropriate distances and angles. Avoid symmetry that could cause degenerate modes. Output only the XYZ block."