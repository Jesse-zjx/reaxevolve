# generate-ts-guesses

Generate a single, high-quality transition-state (TS) guess for the proposed reaction.

## Goal

Produce a TS geometry that is likely to converge to a saddle point with **exactly one imaginary frequency** when optimized.

## Method

1.  **Align**: Superimpose the reactant and product geometries (Kabsch or equivalent) to minimize root-mean-square deviation.
2.  **Average**: Compute the Cartesian average of the aligned structures.
3.  **Displace**: For atoms that change connectivity (bond breaking/forming), add a small displacement (0.1–0.3 Å) along the vector from the reactant to the product position. For all other atoms, use the average position.
4.  **Prune**: Remove any atom clashes (distance < 1.0 Å) by pushing the involved atoms apart along their connecting vector.
5.  **Output**: Return the atomic coordinates in XYZ format (element x y z). Do **not** output multiple guesses.

## Constraints

- Only generate **one guess per reaction**.
- If the guess fails to produce a valid TS (no imaginary frequency after optimization), do **not** generate additional guesses for the same edge; report the failure and let the downstream diagnostic handle it.
- The guess must be chemically reasonable (no bonds broken that are not intended, no unrealistic bond angles).

## Success Criteria

A successful guess leads to a TS optimization that finds a saddle point with exactly one imaginary frequency, enabling IRC to verify the endpoint connectivity.