# Generate TS Guesses

This skill creates initial guess geometries for transition state optimizations.

## Strategy

To reduce the rate of "no_dominant_mode" failures (soft modes rather than saddle points), adopt the following improved guess-generation methods:

1. **Reaction coordinate scan (preferred):** For each reaction kind, perform a constrained optimization scan along the primary reaction coordinate (e.g., a bond length or angle). Identify the maximum energy point and use that geometry as the TS guess. This usually yields a better starting point for saddle optimization.

2. **Linear synchronous transit (LST):** If the reactant and product are known, generate a guess by linear interpolation of atomic positions. This is effective for simple transformations.

3. **Template-based guesses:** For common reaction types (e.g., 1,2-hydride shifts, dehydration), use pre-defined approximate TS geometries from known mechanisms.

4. **Avoid extreme/random guesses:** Do not generate guesses far from the expected reaction path; prioritize guesses that are geometrically close to the expected TS region.

5. **Stage guesses:** First generate a small set of high-confidence guesses (e.g., from a scan or template). If all fail, then expand to more exploratory guesses, but avoid repeating the same failure mode.

6. **For isomerization/tautomerization:** Use a hydrogen transfer coordinate scan between donor and acceptor atoms. The scan should vary the H–donor distance while relaxing other coordinates.

7. **For dehydration:** Use a scan of the C–O bond length of the leaving group, or a scan of the forming C=C bond.

8. If a scan is not feasible, use a guess that places the reacting atoms at a midpoint between reactant and product geometries, with other atoms relaxed.

This strategy aims to produce guesses with a clear imaginary mode and reduce the number of "no_dominant_mode" failures.