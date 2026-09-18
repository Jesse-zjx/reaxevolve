# Generate TS Guesses Skill

## Purpose
Propose initial transition state guesses for Explore stage.

## Guidelines
- For each edge, generate at most 3 guesses. Prioritize stepwise changes over concerted multiple-bond changes.
- Ensure each guess has a clear reaction coordinate that can be described as a single bond breaking/forming or a simple proton transfer.
- Avoid guesses that involve simultaneous changes at multiple distant sites, as they often yield soft modes.
- If a previous guess for the same edge failed due to soft modes (imaginary frequency < 300 cm^-1 or multiple modes), do not repeat a similar guess. Instead, try a different atom ordering, a different interpolation path, or a different reaction kind.
- For tautomerization, prefer guesses that correspond to a well-defined single proton shift with minimal rearrangement of the rest of the molecule.
- For dehydration, focus on the specific C-O bond cleavage and H-shift, avoiding excessive ring reorganization.
- Use the reactant and product geometries provided; do not generate guesses that require large structural reorganizations without a clear path.

## Output
Produce a list of guess specifications, each with a label, atom mapping, and an initial TS geometry estimate.