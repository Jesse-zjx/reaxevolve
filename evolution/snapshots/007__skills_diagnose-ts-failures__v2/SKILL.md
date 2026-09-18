# Diagnose TS Failures

This skill provides rules for diagnosing transition state (TS) search failures reported by the validation stage. The goal is to propose actionable next steps to improve the chance of obtaining a valid TS and IRC connection.

## Inputs
- `failure_mode`: one of `no_endpoint_record`, `no_dominant_mode`, `one_end_only`, `no_match`, `multi_imag`
- `guess_details`: including imaginary modes, endpoint match flags, and any error messages.

## Output
- A diagnostic message and a recommended action for the next TS guess.

## Rules

### 1. `no_endpoint_record`
**Symptom:** The IRC calculation did not produce endpoint records, meaning either the TS optimization failed or the IRC did not converge.

**Diagnosis:**
- If `imaginary_modes` is null or empty, the TS optimization did not find a saddle point (no negative frequency). This indicates the initial guess geometry is far from the true TS.
- If `imaginary_modes` contains a negative frequency (e.g., -300 cm⁻¹), the TS optimization may have converged to a saddle point but the IRC failed to reach reactants or products.

**Recommended actions:**
1. **No imaginary mode:** The guess must be refined. Use a different reaction coordinate (e.g., change the bond being broken/formed) or generate a new guess by interpolating between reactant and product with a more physically motivated reaction path. Consider using a constraint scan or a different starting geometry.
2. **Imaginary mode present but no endpoints:** The TS is likely a valid saddle point but the IRC failed. Re-run the IRC with:
   - Smaller step size (e.g., 0.1 amu^(1/2)·bohr → 0.05)
   - More steps (e.g., 100 → 200)
   - Different IRC algorithm (e.g., LQA vs EulerPC)
   - Re-orientation of the TS geometry to align the imaginary mode with the reaction path.
3. **If TS optimization status was not converged (e.g., max steps reached):** Re-run the TS optimization with tighter convergence criteria (GradRms < 1e-4, MaxDisplacement < 1e-3) and ensure the mode is followed correctly.

### 2. `no_dominant_mode`
**Symptom:** The TS has multiple imaginary modes (more than one) making it not a first-order saddle point.

**Diagnosis:** The geometry optimized to a higher-order saddle point, which is not a valid TS.

**Recommended actions:**
- Use mode-following (e.g., `opt=(ts,modredundant)` in Gaussian) to track the desired mode.
- Re-optimize from a different initial geometry that is closer to the reaction path.
- Check if the guess is too symmetric; break symmetry slightly.

### 3. `one_end_only`
**Symptom:** One IRC endpoint matches either reactant or product, but the other does not.

**Diagnosis:** The TS connects the desired species pair but the IRC drifted to an unintended minimum on one side.

**Recommended actions:**
- Use the matched endpoint as a constraint and re-optimize the TS geometry with a guess biased toward the unmatched side.
- Perform a constrained optimization along the reaction coordinate to locate the missing minimum.
- If the unmatched side is only a few steps away, re-run IRC with a slightly larger step or a different direction.

### 4. `no_match`
**Symptom:** Neither IRC endpoint matches the expected reactant or product.

**Diagnosis:** The TS connects a different pair of species; the assumed mechanism is incorrect.

**Recommended actions:**
- Re-assess the reaction mechanism; the guess may correspond to a different pathway.
- Generate a new TS guess based on an alternative bond reorganization.
- If the TS still has the correct atom connectivity, consider that the TS leads to unexpected intermediates; these could be added as new nodes.

### 5. `multi_imag` (if reported)
**Symptom:** More than one imaginary frequency, but may be captured as `no_dominant_mode`.

**Diagnosis:** As above, not a valid TS.

**Recommended actions:**
- Use normal mode projection to follow the desired mode.
- Re-optimize with a different initial displacement.

## General guidelines
- Always verify that the TS guess has the same atom connectivity and formal charge as the desired reaction.
- For each failure, the loop should generate a new guess with adjusted parameters, not blindly retry the same guess.
- If a failure mode persists after two revisions, consider changing the reaction kind or exploring alternative pathways.