# Generate Transition State Guesses

## Purpose
Produce high-quality transition state (TS) guess geometries for a given reactant-product pair.

## Procedure

### 1. Atom Mapping
- Determine the reaction SMARTS and map atoms in the reactant and product.
- Use a reliable mapping tool (e.g., Indigo, RxnMapper).

### 2. Structure Alignment
- Align reactant and product atoms using a least-squares fit to minimize RMSD of mapped atoms.
- Translate so that the geometric center of mapped atoms is at the origin.

### 3. Initial Guess Generation
- Create a linear interpolation of Cartesian coordinates:
  `TS_guess = w * reactant + (1-w) * product`
  with default weight `w = 0.5`.
- If the reaction involves a significant geometry change, use a weighted blending of internal coordinates (distance, angle, dihedral) for the reaction coordinate.

### 4. Pre-optimization
- Run a fast semi-empirical optimization (e.g., GFN2-xTB or ANI-2x) on the interpolated structure to refine the guess.
- Constrain the reaction coordinate (e.g., distance between forming/breaking atoms) during optimization to keep the structure near the TS.

### 5. Frequency Verification
- Compute the Hessian (vibrational frequencies) at the optimized guess.
- Requirement: Exactly one imaginary frequency with magnitude > 100 cm⁻¹.
- If multiple imaginary modes exist, the structure is likely a local minimum (not a saddle).

### 6. Adaptive Weight Adjustment
- If the frequency check fails (no dominant imaginary mode or multiple):
  - Adjust `w` by ±0.2 (e.g., 0.3, 0.7) and repeat steps 3–5.
  - If still fails, try a small displacement along the reaction coordinate vector (e.g., stretch forming bond by 0.1 Å).
- After 3 attempts, if no valid guess is found, discard the guess and move to the next candidate.

### 7. Output
- Return the final guess geometry (XYZ) and the imaginary frequency value.
- If no valid guess obtained, return a flag indicating failure.

## Notes
- This procedure specifically addresses the common failure modes:
  - `no_dominant_mode`: soft modes due to guess being a local minimum.
  - `no_endpoint_record`: caused by IRC not connecting to minima; a proper saddle guess helps IRC converge.
- For ring closure/opening reactions, interpolation weight may need to be asymmetric (e.g., 0.3) to favor the more strained side.