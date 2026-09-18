# Diagnose TS Failures

This skill provides rules for diagnosing why a TS validation failed and suggests next actions.

## Failure Modes

### no_match
- Both IRC endpoints do not match the reactant or product. This suggests the TS connects a different pair of species. Action: Abandon this edge.

### one_end_only
- One IRC endpoint matches reactant or product, but the other does not. This indicates the TS is correct in one direction but the other endpoint needs restructuring. Action: Use the matched endpoint as a starting point and run a constrained optimization towards the other species with a soft constraint.

### no_endpoint_record
- No IRC endpoints were recorded. This can happen if the TS optimization did not produce a first-order saddle (0 or >1 imaginary modes), or the IRC calculation failed to converge. Action: Do not re-run the same guess. Instead, generate a new guess by performing a linear transit scan between the reactant and product, then optimize the maximum energy point as a TS candidate. If the scan fails, skip this edge.

### no_dominant_mode
- The TS has a very small imaginary mode (|ν| < 300 cm⁻¹) or multiple soft modes. This indicates the guess is not a genuine TS but a shallow minimum or artifact. Action: Reject the guess and try a different reaction coordinate, e.g., use a different proton transfer path or a different bond-breaking sequence. Consider using a template-based TS guess.
