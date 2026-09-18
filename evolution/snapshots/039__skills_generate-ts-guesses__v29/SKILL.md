# Generate TS Guesses Skill

Generate transition state guesses for a given reactant→product pair and reaction kind.

## Instructions

1. **Analyze the transformation** – identify bonds broken/formed and the expected reaction coordinate.
2. **Generate 1–3 guesses**, each with a distinct geometry (e.g., early, middle, late along the path).
3. **Prefer guesses with a single dominant imaginary mode** (target >|200i cm⁻¹|). Avoid producing structures that are likely to give only soft modes (<|100i|) or multiple small imaginary frequencies.
4. **For flexible molecules** (e.g., sugars, polyols):
   - Constrain dihedrals or ring torsions to avoid excessive floppiness.
   - Use a tighter initial Hessian model if available.
5. **Ensure IRC endpoints can be reached**:
   - The guess should lie on a path that clearly connects reactant and product without large rearrangements.
   - For elimination reactions (dehydration, dehydrogenation), explicitly place the migrating hydrogen near the acceptor and the leaving group antiperiplanar.
   - For tautomerizations, align the proton transfer with the π-system.
6. **Provide a short rationale** for each guess explaining why it is expected to have a dominant imaginary mode and connect to the endpoints.
7. **If previous guesses have failed** with `no_dominant_mode` or `one_end_only`, bias the next guesses toward structures that are closer to the expected transition state (e.g., use a tighter interpolation or a different reaction coordinate).
8. **Output format**: each guess as a multi-line XYZ block preceded by a comment with the guess ID and rationale.

## Example

```
# guess r1_g1: early TS with forming C-O bond, expected imag ~500i
[XYZ coordinates]
```

## Notes

- Do not modify the verdict criteria or policy.
- This skill is used by the Explore stage to propose new TS guesses.