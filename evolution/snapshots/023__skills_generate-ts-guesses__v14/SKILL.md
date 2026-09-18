# Skill: Generate TS Guesses

## Purpose
Propose initial transition state (TS) guess geometries for a given reaction. The goal is to provide guesses that are likely to converge to a valid saddle point with a single dominant imaginary vibrational mode, corresponding to the reaction coordinate.

## Context
This skill is used by the Explore stage to generate TS guesses before submitting them to QM validation. Poor guesses lead to failed validations – especially **no_dominant_mode** (soft modes only) or **no_endpoint_record** (IRC incomplete). These failures waste core‑hours and stall the discovery of new STRICT edges.

## Input
- `reactant_smiles` (SMILES string)
- `product_smiles` (SMILES string)
- `reaction_kind` (e.g., dehydration, tautomerization, dehydrogenation, isomerization, fragmentation)
- `reaction_smarts` (optional, SMARTS pattern describing the transformation)

## Output
A list of one or more TS guess geometries, each as a 3D structure (e.g., XYZ or SDF). No more than **2 guesses** per reaction – quality over quantity.

## Methodology

### 1. Prioritize guess generation by reaction type
- **Proton transfer / tautomerization**: The TS is usually a symmetric or near‑symmetric midpoint where the moving proton is roughly halfway between the donor and acceptor atoms. Use a guess where the proton is placed at 50 % of the distance, and the rest of the molecule is geometry‑optimised (but keep the proton fixed).
- **Dehydration / elimination**: The TS involves breaking a C–O bond and forming a C=C bond. The guess should have the leaving H₂O partially detached (O–C distance ≈ 1.5–2.0 Å) and the double bond partly formed (C–C distance ≈ 1.5 Å).
- **Dehydrogenation**: Similar to dehydration but with H₂ leaving. The guess should have the two H atoms partially removed and the forming double bond.
- **Isomerization (ring‑opening/closing)**: The TS involves a bond breaking/forming. Place the bond at the midpoint of the reaction coordinate (e.g., 1.7–2.0 Å for a single bond).
- **Fragmentation**: The TS is a stretched bond. Use a guess with the bond elongated to ~1.5–2.0 Å.

### 2. Generate guess using template interpolation
1. Generate 3D conformers of reactant and product.
2. Align the two structures by the atoms that remain unchanged (the reaction core).
3. Perform a linear interpolation of the atomic positions of the reacting atoms (e.g., 50 % along the path).
4. This interpolated geometry is the first guess.

### 3. (Optional) Second guess from a relaxed scan
If computational resources allow, perform a relaxed scan along the reaction coordinate (e.g., the bond distance) and take the maximum‑energy point as the second guess. This is especially useful for flat potential energy surfaces (tautomerizations) where the linear interpolation may be too far from the true TS.

### 4. Pre‑validation of the guess (critical)
Before outputting, the generating agent should **check** that the guess is likely to possess a single imaginary mode:
- If a quick frequency calculation is possible (e.g., using a semi‑empirical method), do it. If the guess shows multiple imaginary modes or no imaginary mode, adjust the geometry (e.g., move the proton slightly) and re‑evaluate.
- If no quick check is possible, apply heuristics: for a simple bond breaking/forming, a guess with the bond at the midpoint usually yields one imaginary mode. For more complex cases, ensure the guess is not an intermediate (e.g., with a flat potential) by checking that the energy is higher than both reactant and product.

### 5. Output format
Each guess must include:
- The 3D geometry (XYZ or SDF)
- A label (e.g., `guess_1`, `guess_2`)
- A brief comment on how it was generated (e.g., "linear interpolation of proton transfer")

## Do’s & Don’ts
- **Do** limit to 2 guesses per reaction.
- **Do** prefer early‑pathway reactions (closer to glucose) to keep the search focused.
- **Do** discard any guess that is essentially an intermediate (energy lower than the expected barrier) or has obvious steric clashes.
- **Don’t** generate guesses for reactions that have already been attempted and failed with the same failure mode. Instead, wait for the next iteration of the skill.
- **Don’t** blindly enumerate many guesses – each bad guess wastes core‑hours.

## Expected Improvement
By following this skill, the TS guesses should have a higher chance of yielding a single dominant imaginary mode, thereby reducing the `no_dominant_mode` failure rate and increasing the number of validated TS edges that can potentially become STRICT.