# Generate TS Guesses Skill

## Purpose
Generate high-quality transition state (TS) guesses for a given reaction (reactant → product) to be validated by QM calculations. The goal is to produce guesses that have a dominant imaginary mode and correctly connect the reactant and product endpoints.

## Inputs
- `reactant_smiles`: SMILES of the reactant
- `product_smiles`: SMILES of the product
- `reaction_kind`: reaction type (e.g., tautomerization, isomerization, dehydration, dehydrogenation, etc.)
- `graph_info`: optional connectivity and ring info

## Output
A list of TS guess structures (in XYZ format or as a procedure to generate them) with associated metadata.

## Guidelines

### General principles
- **Prefer quality over quantity**: Provide 1-2 guesses per reaction, not many. Each guess should be carefully constructed to represent a plausible reaction coordinate.
- **Avoid flexible modes**: The TS must correspond to a saddle point with a single significant imaginary frequency along the reaction coordinate. Avoid guesses that introduce many low-frequency modes (e.g., ring breathing, side-chain rotations) that might mask the reaction path.
- **Use constrained coordinates**: Whenever possible, build the guess using internal coordinate constraints (bond forming/breaking, angle changes) and freeze other degrees of freedom to prevent soft-mode contamination.

### Reaction-specific strategies

#### Tautomerization (proton transfer)
- **Coordinate**: Move the proton from one oxygen to another along the O–H–O axis. Use a linear path with a fixed distance (e.g., 1.0–1.2 Å) for the transferring hydrogen.
- **Freeze backbone**: Keep all other atoms fixed relative to each other to avoid ring distortions.
- **Endpoint correspondence**: Ensure the final structure after TS guess is identical to the target product tautomer (check atom ordering).
- **Example**: For enol → keto tautomerization, place the proton midway between the two oxygens, align the O–H–O angle near 180°, and freeze the rest of the molecule.

#### Isomerization (ring opening/closing)
- **For ring opening**: Identify the bond to be broken. Stretch that bond to ~2.5–3.0 Å while keeping the ring geometry rigid. Avoid any other bond changes.
- **For ring closing**: Pinch the two atoms that will form a bond to ~2.5 Å, using a linear synchronous transit (LST) path from the open-chain reactant to the cyclic product. Freeze the rest of the molecule.
- **Avoid flexible rings**: If the reactant or product contains flexible rings (e.g., furanose, pyranose), use constraints to lock the ring conformation to the more stable chair/envelope form to reduce soft modes.

#### Dehydration (elimination of water)
- **Coordinate**: Simultaneously break the C–O bond and form a C=C double bond. Place the OH group in a leaving position, and bring the hydrogen on the adjacent carbon into alignment.
- **Use a guess structure with partial double-bond character and a stretched C–O distance (1.8–2.0 Å).**

#### Dehydrogenation (oxidation)
- **Coordinate**: Break the C–H bond and form a C=O or C=C double bond. Use a guess where the hydrogen is abstracted by a hydride acceptor (e.g., NAD+ mimic) or, if simulating direct loss, place the hydrogen at an intermediate distance.

### Quality check hints
- After generation, consider whether the guess would likely reproduce the reactant and product when optimized along the IRC. If the reaction coordinate is a simple proton transfer, the TS should be nearly symmetric.
- If the reaction involves multiple steps (e.g., ring opening followed by tautomerization), split into separate guesses for each elementary step to avoid multi-path soft modes.

## Notes
- This skill is called during the Explore stage to generate TS guesses for new edges. Failure modes like "no_dominant_mode" indicate that the guess did not correspond to a saddle point; this revision aims to reduce such failures by enforcing stricter coordinate construction.