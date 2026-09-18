# TS Guess Generation Skill

## Purpose
Generate initial TS guess geometries for reaction edges.

## Strategy
For each reaction kind, generate multiple guesses using different strategies:
- Random perturbation of reactant geometry
- Linear interpolation of reactant and product geometries
- Knowledge-based placement of key atoms

### Tautomerization (proton transfer)
Proton transfer reactions are the most common source of low-imaginary or soft-mode failures because the hydrogen is often placed too close to the donor or acceptor, resulting in a geometry that is more like a minimum than a saddle point.

To improve the guess quality:
1. Place the migrating hydrogen at the midpoint between the donor and acceptor atoms.
2. Use the reactant geometry with the hydrogen moved; do not optimize the hydrogen position beforehand.
3. If the donor-acceptor distance is large (>3.0 Å), first shrink the distance by moving the acceptor towards the donor (or vice versa) while keeping the hydrogen at the midpoint.
4. For tautomerization involving a ring (e.g. HMF-related), consider a linear interpolation of reactant and product geometries to obtain a better initial saddle point.

### Dehydrogenation and dehydration
These reactions often fail due to missing IRC endpoint records. The guess generation should ensure that the initial geometry is not too close to the reactant/product and that the driver is configured to run IRC from the TS guess.

### Fragmentation
Fragmentation reactions require a guess that clearly lies between the two fragments. A linear interpolation of the two product fragments (or reactant and product) can be used.

## Notes
- When ambiguous, prefer the guess that is geometrically farthest from both reactant and product minima.
- If multiple guesses are generated, rank them by their RMSD to the midpoint of the reactant and product coordinates.
