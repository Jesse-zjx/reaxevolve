# Diagnose TS Failures – Evolvable Skill

This skill is invoked after a TS optimization and IRC attempt has failed according to the STRICT policy. It receives the failure information (guess ID, reactant/product SMILES, imaginary modes, endpoint match status, any error logs) and must produce a diagnostic report and a concrete next‑guess strategy.

## General Approach

1. Parse the failure mode from the verdict.
2. Inspect the TS optimization convergence and frequency analysis if available.
3. Determine the most likely cause: poor initial guess, flat PES, or a genuine mechanistic mismatch.
4. Output a recommendation for the next guess (or a decision to abandon the edge).

## Failure Mode Rules

### `no_endpoint_record`
**Cause**: IRC calculation did not produce endpoint records – either the IRC job failed, crashed, or the endpoints were not saved.

**Diagnostic steps**:
- Check if the TS optimization converged to a saddle point (exactly one imaginary frequency).
- Verify that the IRC job was actually submitted and completed; if not, re‑submit with tighter convergence (`maxpoints=200`, `stepsize=10`, `LQA` integrator) and ensure the checkpoint file is written.
- If the TS frequency file is missing, re‑run the frequency calculation with `freq` and `iop(7/33=1)` to save the Hessian.

**Next guess**:
- If the TS optimization converged to a proper saddle, re‑run the IRC with the same TS geometry but with the robust settings above.
- If the TS optimization failed to converge, discard the guess and generate a new one using a different initial geometry (e.g., shift the bond‑breaking/forming atoms by 0.1 Å along the expected reaction coordinate).

### `no_dominant_mode`
**Cause**: The imaginary mode(s) are soft (|ν| < 100 cm⁻¹) and the IRC endpoints do not match the expected reactant/product. The guess did not correspond to a genuine first‑order saddle.

**Diagnostic steps**:
- Examine the magnitude of the lowest non‑zero frequency. If it is < 100 cm⁻¹, the guess is likely a valley‑ridge inflection point or a higher‑order saddle.
- Check the IRC paths: they may have terminated early due to small gradients.

**Next guess**:
- Take the final TS geometry and displace along the imaginary mode vector (normalized) to generate a new guess that is closer to a true saddle.
- Alternatively, perform a relaxed scan along the suspected reaction coordinate (e.g., bond length) to locate a structure with a single dominant imaginary frequency, then use that as the new guess.
- If the same soft‑mode failure occurs for >2 guesses on the same edge, consider the edge as a symmetry‑forbidden or extremely flat PES and flag it for manual review.

### `one_end_only`
**Cause**: One IRC endpoint matches the expected reactant or product, but the other endpoint does not match. The TS connects a different pair of species.

**Diagnostic steps**:
- Identify the mismatched endpoint geometry and its SMILES representation.
- Check whether the mismatched endpoint is a plausible intermediate or a higher‑energy conformer.

**Next guess**:
- Use the mismatched endpoint as a new reactant (or product) to propose a new edge that might be chemically meaningful.
- If the mismatched endpoint is of no interest, discard the guess and try a different initial guess that forces the expected motion (e.g., by freezing the key atoms during TS optimization).

### `no_match`
**Cause**: Neither IRC endpoint matches the expected reactant or product. The TS connects a completely different pair.

**Diagnostic steps**:
- Compare the two IRC endpoints to known species in the graph. They may correspond to an already‑known edge or a new edge.
- If the TS connects a known pair but the expected reactant/product is different, the guess likely followed a different reaction coordinate.

**Next guess**:
- If the TS connects a new, chemically plausible pair, propose that new edge for exploration.
- Otherwise, abandon the current guess and try a different mechanism (e.g., a different protonation state or a different conformer).

## Integration

After producing the next‑guess recommendation, the workflow should submit the new guess for TS optimization. The skill should not modify the STRICT adjudication, only supply a better starting point.

## Fallback

If no failure mode is recognized, or the same failure repeats after 3 attempts, flag the edge for manual inspection and stop further attempts.