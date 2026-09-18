# Generate transition state guesses

## Goal
Produce high-quality initial TS guesses for the given reaction SMILES.
Use the reaction kind to choose the best guess strategy.

## General guidelines
- For each guess, output a 3D geometry (XYZ or SDF) that is likely to be a saddle point.
- Prefer guesses that have a single imaginary frequency > 200i cm-1.
- If the guess fails validation, analyse the reason and adjust.

## Tautomerization / isomerization
- These reactions often involve proton shifts or double-bond migrations.
- The reaction coordinate can be soft; guesses frequently exhibit small imaginary modes (< 200i cm-1) or multiple modes.
- **Strategy to avoid `no_dominant_mode` failures:**
  1. Initial guess: linear interpolation between reactant and product along the dominant internal coordinate (e.g., O–H bond length for proton transfer).
  2. Perform a constrained optimisation along that coordinate, freezing the coordinate at the midpoint.
  3. If the resulting structure still has a soft mode, re-generate with a smaller step (e.g., shift the frozen coordinate by 0.05 Å toward the product).
  4. Ensure the guess has a single imaginary frequency of magnitude > 200i cm-1; if not, discard and try a different internal coordinate.
- **Next-guess rules after failure:**
  - `no_dominant_mode`: the guess was not a true saddle point. Re-generate using a different reaction coordinate (e.g., C–H distance instead of O–H) or a tighter constraint.
  - `no_endpoint_record`: the TS guess may be valid but IRC failed; try a different initial guess or increase IRC steps.

## Dehydration / dehydrogenation
- These reactions involve breaking of O–H or C–H bonds.
- Ensure the guess includes a stretched bond (e.g., O–H at 1.8 Å) and a suitable leaving group.
- If `no_endpoint_record` occurs, verify that the IRC calculation is set to run long enough to reach the product well.

## Other reaction kinds
- Use standard TS optimisation methods with a Hessian guess.
- If repeated failures occur, switch to a more robust method (e.g., QST2, QST3) or use a different initial geometry.