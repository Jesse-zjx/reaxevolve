# Skill: generate-ts-guesses

## Purpose
Generate initial transition-state geometry guesses for a given reaction. The guesses must be plausible saddle-point candidates that connect the specified reactant and product, and they should minimise the risk of the dominant failure modes observed in the campaign: soft-mode (no dominant imaginary frequency) and missing IRC endpoint records.

## Core rules
1. **Single-imag aim** – Every guess must be a structure expected to have *exactly one* imaginary frequency after optimisation. Do not submit a guess that is likely to be a minimum (all real frequencies) or a high-order saddle.
2. **Quality over quantity** – Generate at most **two** guesses per reaction. If the first guess fails with a soft-mode or no-endpoint failure, do not simply re-randomise; use a different chemical intuition or interpolation method for the second attempt.
3. **Reaction-coordinate anchoring** – The guess must lie along the reaction coordinate. For bond-breaking/forming reactions, place the guess near the midpoint of the breaking/forming bond distance(s). For tautomerisation, use a linear interpolation of Cartesian coordinates weighted 50:50 between reactant and product, then relax the key dihedral/angle if needed.
4. **Avoid extreme geometries** – Do not use guesses that are very early or very late along the reaction path (e.g., <20% or >80% of the bond-breaking progress). Such guesses often converge to the reactant or product basin, yielding one-end-only or no-match failures.
5. **Pre-check mode** – If possible, run a cheap frequency calculation on the guess before submitting the full TS optimisation. Reject any guess that shows no imaginary frequency or multiple large imaginary frequencies.

## Failure-aware adjustments
- **no_dominant_mode (soft mode)**: This indicates the guess is close to a flat, flexible region of the PES rather than a true saddle. Mitigation: increase the bond-breaking/forming distance separation slightly, or add a small geometric perturbation that breaks the symmetry causing the flat mode.
- **no_endpoint_record**: Often caused by IRC not being run or crashing. Ensure the guess is submitted with IRC explicitly requested. The skill `qm-execution` should be configured to always run IRC after TS optimisation; if not, flag the reaction.
- **one_end_only**: The guess is too close to reactant or product. Shift the key coordinate towards the missing endpoint.
- **no_match**: The TS connects different species pair. Re-examine the atom mapping; the guess may be linking the wrong atoms. Use a different atom-mapping or a different reaction centre.

## Reaction-kind specific guidance
- **Tautomerisation** (proton shifts): Generate guesses by interpolating the proton position between donor and acceptor. Use a distance of ≈1.3 Å to each oxygen as starting point. The donor-H-acceptor angle should be near 180°.
- **Dehydration / Dehydrogenation**: Use the breaking C–O or C–H bond distance extended to ~1.8–2.0 Å, and the forming O–H or H–H distance set to ~1.2 Å. Keep the rest of the geometry reactant-like.
- **Isomerisation (ring-open/close)**: Interpolate the ring-closing/opening bond to ~2.0 Å and adjust the dihedral angle to near the transition-state value expected from chemical intuition.

## Output format
Return a list of guesses, each containing:
- `guess_id`: short identifier
- `geometry`: XYZ or SMILES with 3D coordinates
- `rationale`: why this guess is expected to be a saddle point

## NOT allowed
- Do not generate more than 2 guesses per reaction.
- Do not submit guesses without a clear chemical rationale.
- Do not reuse the same interpolation method after a failure without a significant parameter change.