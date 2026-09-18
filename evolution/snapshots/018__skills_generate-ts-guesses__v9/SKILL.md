# TS Guess Generation Skill

## Purpose
Generate an ordered list of TS guess geometries for a given reaction edge (reactant → product, reaction kind).

## Input
- `reactant` SMILES
- `product` SMILES
- `reaction_kind` (one of: dehydration, tautomerization, isomerization, dehydrogenation, fragmentation, unattributed)
- `previous_failures` (list of previous guess geometries and failure modes, if any)

## Output
A JSON array of `guess` objects, each with:
- `geometry` (XYZ block or connectivity description)
- `rationale` (one sentence)
- `priority` (number, 1=highest)

## Rules (STRICT v5 compliant)

### General
1. Produce **at most 2 guesses** per edge. If the edge already has 2 failed attempts, output an empty array.
2. The first guess must be the chemically most plausible TS for the given reaction kind, based on textbook mechanisms.
3. The second guess (if needed) must be a minor variation of the first, addressing a specific failure mode from `previous_failures`.
4. All guesses must be in 3D, with explicit connectivity. Avoid linear or planar geometries unless the reaction requires it.
5. Ensure the guess has **exactly one imaginary mode** in the initial Hessian (if calculable) or use a constrained optimization to approach the saddle.
6. Prioritize **early-path** reactions: dehydration, tautomerization (these are the only kinds currently pending).

### Reaction-Specific Guidance
- **Dehydration**: TS involves a cyclic transition state with a proton transfer from a OH group to a neighboring carbon, concerted with loss of water. The geometry should show an elongated C–O bond and a forming O–H bond, with a water-like fragment.
- **Tautomerization**: TS involves a proton shift (e.g., keto-enol). The geometry should show a partially transferred proton between two heavy atoms (O or C).
- **Isomerization**: TS involves bond reorganization (e.g., ring opening/closing). The geometry should show partial bond breaking/forming.
- **Dehydrogenation**: TS involves C–H bond breaking and H–H forming. Place the H atom between the carbon and another H (or metal).
- **Fragmentation**: TS involves bond cleavage. Only generate if a clear low-energy pathway exists.
- **Unattributed**: Do not generate guesses for unattributed edges unless the reactant and product have a clear mechanistic relationship (e.g., same formula). If unclear, output empty array.

### Failure Response
If `previous_failures` includes:
- `no_endpoint_record`: the first guess likely had a soft mode or wrong saddle. Produce a second guess with a **tighter** TS geometry (e.g., using a constrained optimization to the saddle guess).
- `no_dominant_mode`: the imaginary mode was too small. Adjust the geometry to increase the curvature along the reaction coordinate (e.g., stretch the breaking bond further).
- `one_end_only`: the TS connected to only one end. Retry with a guess that is symmetric between reactant and product (e.g., average of both structures).
- `no_match`: the TS connected to different species. The guess may be a different reaction. Try a guess that explicitly connects the given reactant and product.

### Example (for dehydration edge)
```json
[
  {
    "geometry": "... (XYZ for cyclic TS with water elimination) ...",
    "rationale": "Classic E1-like dehydration via cyclic TS",
    "priority": 1
  }
]
```

## Notes
- Do not guess multi-step reactions; each guess must be a single elementary step.
- If the reaction is clearly impossible (e.g., HMF formation from glucose in one step), output empty array.
- The guesses must be chemically valid and consistent with the reaction kind label.