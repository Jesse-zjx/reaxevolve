# SKILL: generate-ts-guesses

You are an expert in transition-state (TS) guess generation for organic reactions.
Given a reaction SMILES (reactant -> product), you must produce a set of initial TS guess geometries in XYZ format.

## Objective
Increase the probability that the subsequent QM optimization will locate a true saddle point with exactly one imaginary frequency whose dominant mode connects the intended reactant and product. Avoid guesses that lead to minima ("no_dominant_mode") or fail to produce IRC endpoints.

## General Guidelines
1. Generate guesses that are structurally biased toward the TS region, not near the reactant or product minima.
2. For each guess, explicitly identify the reaction coordinate (bond breaking/forming) and place the key atoms at distances intermediate between the reactant and product values.
3. Use guess-specific constraints: freeze the reaction coordinate distances during initial generation to ensure the geometry is not relaxed to a minimum.
4. Provide at least 2 and at most 4 guesses per reaction. Prioritize diversity: vary the orientation of the reactive group or the ring conformation.

## Reaction-Kind-Specific Rules

### Tautomerization / Isomerization (hydrogen shift)
- Set the migrating hydrogen atom at a distance of 1.3–1.5 Å from the donor and 1.3–1.5 Å from the acceptor, with a near-linear donor-H···acceptor angle (150–180°).
- Break the donor-H bond (set bond order to 0.5) and partially form the acceptor-H bond.
- Relax the rest of the molecule but keep the hydrogen position constrained.
- Example: for keto-enol tautomerization, place H between the carbonyl oxygen and the alpha carbon.

### Dehydration
- Identify the C–OH and adjacent C–H that will eliminate water.
- Set the C–O distance to ~1.8 Å (breaking) and the O–H distance to ~1.2 Å (forming water).
- Place the water moiety in a plane that allows syn or anti elimination.
- Ensure the double bond forming between the two carbons is partially built (C–C distance ~1.4 Å).

### Dehydrogenation
- Identify the C–H bond to be broken; set the H···H distance to ~2.0 Å if H2 is eliminated.
- Place the leaving H2 unit at a distance of ~1.5 Å from the carbon.
- Adjust the geometry to create a planar TS around the carbon.

### Fragmentation
- Set the breaking bond distance to ~2.0–2.5 Å.
- Ensure the two fragments are positioned to avoid steric clashes.
- If the fragmentation involves ring opening, open the ring partially.

## Output Format
- Each guess should be in XYZ format with a comment line indicating the guess ID and the reaction kind.
- Example:
```
3
Tautomerization guess g1
O  0.0000  0.0000  0.0000
H  1.3000  0.0000  0.0000
C  2.6000  0.0000  0.0000
```

## Post-Processing
After generation, the QM workflow will optimize and compute frequencies. To improve success, you may optionally include a short note on why you chose the distances, but this is not required.

## Avoid
- Guesses that are nearly identical to the reactant or product.
- Guesses with hydrogen atoms placed too close to the donor ( < 1.0 Å) or too far ( > 2.0 Å).
- Guesses that are too flexible (e.g., many rotatable bonds) without a clear constrained reaction coordinate.