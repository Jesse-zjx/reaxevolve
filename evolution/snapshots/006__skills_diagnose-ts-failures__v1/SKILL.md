# Diagnose TS Failures

This skill provides rules for diagnosing transition state validation failures and suggests next steps.

## Failure Modes

### no_endpoint_record
- **Meaning:** IRC did not produce endpoint records.
- **Action:** Do not retry the same guess. Generate a new TS guess using a different bond-breaking/forming pattern or starting geometry. Avoid the same reaction coordinate.

### no_dominant_mode
- **Meaning:** The imaginary frequency is too low or not dominant.
- **Action:** Refine TS guess geometry or adjust optimization method.

### one_end_only
- **Meaning:** IRC connected one endpoint but drifted for the other.
- **Action:** Treat as partial success; use the connected endpoint as a constraint for next guess.

### no_match
- **Meaning:** Neither endpoint matches reactant or product.
- **Action:** Reject the guess; the mechanism hypothesis is likely wrong.
