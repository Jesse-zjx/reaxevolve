# Generate TS Guesses Skill

This skill proposes initial transition-state (TS) guesses for a given reaction edge.

## Input
- reactant SMILES
- product SMILES
- reaction kind (if known)

## Output
A list of TS guess geometries, each with a brief justification.

## Guidelines

### General
- Use chemical intuition: TS should resemble the reaction coordinate, not a reactant/product conformer.
- Avoid guesses that are simple conformational changes (e.g., ring flips, rotations) with no bond breaking/forming.
- For tautomerization and isomerization, ensure the guess involves a distinct proton transfer or bond reorganization, not a soft mode.

### Tautomerization / Isomerization
- These are the most common failure modes (soft imaginary frequencies).
- **Critical**: Before proposing a guess, verify that the TS candidate involves a clear bond breaking and forming between two heavy atoms or a proton and a heavy atom, not just a geometric rearrangement.
- If the reactant and product differ only by a proton shift, the TS guess must place the proton midway along the donor–acceptor vector, with appropriate bond lengths (e.g., ~1.2–1.4 Å).
- Avoid guesses that would simply rotate a hydroxyl group or invert a ring – these typically yield imaginary frequencies < 100 cm⁻¹ and are not productive.

### Dehydration / Dehydrogenation
- For dehydration, the TS guess should involve a water molecule leaving group, not just a hydroxyl rotation.
- For dehydrogenation, ensure the TS has a partially formed H–H bond if relevant.

### Ring Opening
- Place the TS at the bond that breaks, with a distance of ~2.0–2.5 Å.

## Strategy
- Generate at most 3–5 high-quality guesses per edge, not an exhaustive list.
- Prioritize guesses that are chemically plausible and likely to yield a single dominant imaginary mode > 100 cm⁻¹.
- If a reaction kind has a history of soft-mode failures, reduce the number of guesses and increase quality.