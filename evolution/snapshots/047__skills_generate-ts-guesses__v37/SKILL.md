# TS Guess Generation Skill (v2)

## Goal
Generate high-quality initial TS geometries for a given reaction edge, to maximise the chance of finding a true first-order saddle point with a single dominant imaginary frequency.

## Input
- `reactant` and `product` SMILES
- `kind` of reaction (e.g., dehydration, tautomerization, isomerization, dehydrogenation, fragmentation)
- `edge_id` and history of prior guesses (if any)

## Output
A list of up to **3** TS guess geometries (XYZ format), each with a short rationale and an estimated imaginary frequency range.

## Procedure
1. **Analyse reaction coordinate** – identify the key bond breaking/forming and the atom(s) that move most during the reaction. For tautomerizations, the migrating proton is the key. For dehydrations, the leaving OH and the proton being removed.
2. **Build a interpolated path** – if the reactant and product are not too different, generate a linear interpolation of internal coordinates (or Cartesian) and locate the highest-energy point. This point is the adiabatic guess.
3. **Perturb along the imaginary mode** – at the highest-energy point, perform a quick frequency calculation (or estimate) to find the lowest-frequency mode. Displace the geometry by 0.3–0.5 Å along that mode in both directions to create an initial TS guess that is not a minimum.
4. **Avoid soft-mode traps** – ensure the guess is not close to a flat minimum. If the estimated imaginary frequency is below 100 cm⁻¹, discard the guess or apply a larger displacement (up to 0.8 Å) along the reaction coordinate. For tautomerizations, always push the proton **at least 0.5 Å** away from both donor and acceptor atoms.
5. **Quality checks** before submission:
   - The guess energy must be higher than both reactant and product (estimate at low level if possible).
   - The gradient norm should be > 0.01 a.u. to avoid landing on a minimum.
   - No severe steric clashes (check interatomic distances > 0.8 Å).
6. **Prioritise** – if the edge already has failed guesses, avoid geometries similar to those that produced `no_dominant_mode` or `no_endpoint_record`. Instead, try a different displacement or a different atom if the reaction allows multiple pathways.

## Reaction-specific guidelines
- **Tautomerization / isomerization**: use a simple proton-shift coordinate. Generate at most 2 guesses: one with the proton midway, and one with the proton slightly closer to the product but still displaced. Ensure the imaginary mode corresponds to the proton transfer.
- **Dehydration**: ensure the C–O bond is stretched to ~1.8 Å and the O–H bond is ~1.2 Å. Use a guess that is product-like in the ring geometry if forming a double bond.
- **Dehydrogenation**: stretch the C–H bond to ~1.6 Å and the H–H distance to ~1.0 Å if possible.
- **Fragmentation**: similar to dehydration but with bond breaking across a ring or chain.

## Return format
```json
[
  {
    "guess_id": "rX_gY",
    "rationale": "str",
    "imag_est": "low|medium|high",
    "geometry": "<xyz>"
  }
]
```

## Notes
- Never submit more than 3 guesses per edge unless explicitly requested by a higher-level strategy.
- If an edge has already failed 3 times with `no_dominant_mode`, report that no further guesses can be generated and suggest alternative approaches (e.g., biased sampling).