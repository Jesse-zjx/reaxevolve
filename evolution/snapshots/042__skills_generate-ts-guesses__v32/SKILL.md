# Generate TS Guesses

## Strategy
- For each reaction edge proposed by Explore, generate at most 2 TS guesses.
- Prioritize early-path reactions (depth from glucose ≤ 3) and reactions with kind expected to lead toward HMF (dehydration, tautomerization, ring-opening).
- For tautomerization (proton transfer): guess geometry with proton midway between donor and acceptor, keeping bond lengths ~1.3 Å for both donor-H and H-acceptor. Use a constrained optimization if possible.
- For dehydration: guess geometry with breaking C-O bond elongated to 1.8 Å and forming O-H bond at 1.2 Å, with water fragment oriented to leave.
- Avoid guesses that only involve simple bond rotations or conformational changes unless they are on the critical path.
- Do not generate guesses for reactions where the reactant and product are far (depth > 5) unless the target HMF is reachable from that region.
- If a previous guess for the same reaction failed with "no_dominant_mode", do not generate a similar guess; instead, perturb along the lowest imaginary mode from the failed TS optimization output (if available) or use a different reaction coordinate.