# Generate TS Guesses

## Objective
Generate transition state (TS) guesses for a given reaction (reactant -> product). The guess should be a structure that approximates the saddle point, with a single imaginary frequency corresponding to the reaction coordinate.

## Input
- Reactant SMILES
- Product SMILES
- Reaction kind (e.g., dehydration, isomerization, tautomerization, etc.)

## Output
- A list of guess structures (in XYZ or SDF format) with associated reaction coordinates.

## Guidelines

### 1. Identify the Reaction Coordinate
Determine the key bond-breaking and bond-forming events. For example:
- Dehydration: C-O bond cleavage and O-H bond formation, possibly with water elimination.
- Isomerization/Tautomerization: Proton transfer or ring opening/closing.
- Dehydrogenation: C-H bond cleavage and H-H bond formation.

### 2. Construct Guess Geometries
- Use a linear interpolation or coordinate driving approach between reactant and product to create an initial guess.
- For each guess, ensure that the forming and breaking bonds are partially formed/broken (e.g., bond orders ~0.5).
- Avoid guesses that are too close to either endpoint (reactant or product) — these often yield soft modes.
- Prefer guesses that have a well-defined transition state character, such as a four-membered ring for proton transfers or a concerted bond reorganization.

### 3. Avoiding Soft Modes (no_dominant_mode failures)
Soft modes (imaginary frequencies < 200 cm^{-1}) often indicate that the guess is in a shallow minimum rather than a true saddle point. To avoid this:
- **Do not** use guesses that are simple rotations or conformational changes; these rarely produce a dominant imaginary frequency.
- For isomerization/tautomerization, ensure the proton transfer is accompanied by a significant change in the molecular skeleton (e.g., ring opening/closure). If the reaction is a simple tautomerization of a linear chain, consider a guess with a cyclic transition state.
- For ring-opening reactions, constrain the breaking bond to be elongated and the forming bond to be partially formed, with a clear path.
- If the guess yields a soft mode, discard it and try a different guess with a more constrained geometry, perhaps by freezing certain dihedral angles.

### 4. Multiple Guesses
Generate up to 5 guesses per reaction, each with a different initial guess (e.g., different endpoints, different reaction coordinate assumptions). Rank them by expected quality (e.g., based on steric hindrance, strain).

### 5. Output Format
Each guess should include:
- The XYZ coordinates of the guess structure.
- The reaction coordinate type (e.g., "proton transfer", "ring closure").
- A brief justification of why this guess is expected to produce a dominant imaginary mode.

## Example
For the tautomerization of glucose open-chain to cyclic form, a good guess might involve a partial ring closure with an elongated C-O bond and a forming O-H bond, ensuring the imaginary mode corresponds to the ring closure.