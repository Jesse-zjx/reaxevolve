# Generate TS Guesses

## Purpose
Generate initial transition-state (TS) guess geometries for a proposed reaction edge.

## Input
- reactant SMILES
- product SMILES
- reaction kind (e.g., tautomerization, dehydration, isomerization, dehydrogenation, fragmentation)

## Output
List of TS guess geometries (xyz) and a brief rationale for each.

## Guiding Principles
1. The guess must be structurally intermediate between reactant and product.
2. Prioritize the most chemically plausible pathway: major bond-breaking/forming events.
3. For tautomerization, isomerization, and similar low-barrier rearrangements:
   - Generate **only one guess per edge**.
   - Build the guess by linear interpolation of internal coordinates (bond lengths, angles, dihedrals) at 50% reaction progress, followed by a constrained minimization along the orthogonal modes to release strain.
   - Perform a frequency calculation on the guess. If the guess does **not** have exactly one imaginary mode (dominant mode), discard it and do not submit. If the imaginary mode is not dominant (multimode or very soft, <100 cm⁻¹), adjust the guess by displacing along the reaction coordinate and re-evaluate.
   - Do **not** generate multiple guesses for the same edge unless the first guess fails with a different, non‑soft failure mode (e.g., dissociation).
4. For dehydration, dehydrogenation, and fragmentation:
   - Generate up to two guesses: one with a cyclic transition structure, one with a linear or early‑stage approach.
   - Prioritize guess geometries that are likely to have a single prominent imaginary mode corresponding to the bond being broken/formed.
5. Avoid guess geometries that are essentially identical to reactant or product.
6. If no reasonable guess can be generated, report an empty list.

## Rationale
This revision directly addresses the repeated failure mode "no_dominant_mode" seen in isomerization/tautomerization and unattributed reactions, where many guesses produced soft, multi‑imaginary modes that did not lead to a true TS and wasted core‑hours.