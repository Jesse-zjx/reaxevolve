# Generate TS Guesses

## Procedure

For each reaction kind, generate initial TS guesses via linear interpolation between reactant and product conformers.

## Improved Guess for Tautomerization and Isomerization

Due to a high rate of failures with no dominant imaginary mode (soft modes), the following additional step is added:

For tautomerization and isomerization reactions, after generating the initial guess via interpolation, perform a constrained optimization along the estimated reaction coordinate (e.g., the distance between migrating hydrogen and the acceptor) to obtain a tighter guess. Use a step size of 0.1 Å and select the geometry with the highest energy as the new guess. This produces a guess that is closer to the true saddle point and more likely to yield a single imaginary frequency.

If the constrained scan fails, fall back to a manual geometry where the hydrogen is placed midway between donor and acceptor and the donor-acceptor distance is adjusted to 2.5 Å.