# Diagnose TS Failures

## Overview
This skill provides rules for interpreting TS validation results and prescribing next guesses for Explore based on common failure modes.

## Failure Modes and Next-Guess Rules

### no_endpoint_record
If the failure mode is 'no_endpoint_record' (no IRC endpoints found), the TS may be a false saddle point or the IRC calculation did not converge. For the next guess:
- If the imaginary frequency is > 100 cm⁻¹, increase IRC_MaxPoints to 200 and try the reverse direction.
- If the imaginary frequency is ≤ 100 cm⁻¹ or missing, the TS is likely not a true saddle point; do not retry the same geometry. Instead, generate a new guess for the same reaction kind with a different geometry perturbation.

### no_dominant_mode
If the failure mode is 'no_dominant_mode' (only soft modes < 300 cm⁻¹), the guess did not cross the reaction coordinate. Next guess: tighten the geometry perturbation or use a more constrained search for the transition state.

### one_end_only
If the failure mode is 'one_end_only' (one endpoint matches, the other does not), the IRC ended at an unexpected intermediate. Next guess: use the mismatched endpoint as a reactant or product for a new edge, or re-run the IRC with a different initial direction.

### no_match
If the failure mode is 'no_match' (neither endpoint matches the expected reactant or product), the reaction mechanism hypothesis is likely incorrect. Next guess: do not retry the same edge; instead, propose a different reaction kind or a different intermediate.