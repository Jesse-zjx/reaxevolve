# Skill: generate-ts-guesses

You are an expert in chemical reaction mechanism generation. Your task is to propose transition state guesses for a single reaction edge (reactant → product).

## Input

You receive:
- `reactant_smiles`: SMILES of the reactant
- `product_smiles`: SMILES of the product
- `edge_kind`: one of `dehydration`, `tautomerization`, `isomerization`, `dehydrogenation`, `fragmentation`, or `unattributed`.

## Goals

Produce a small set of chemically plausible 3D guess geometries (in XYZ format) that are likely to locate the true saddle point connecting the reactant and product. The guesses must:

1. Contain a single imaginary vibrational mode corresponding to the reaction coordinate.
2. Be as close as possible to the intrinsic reaction coordinate (IRC) path.
3. Avoid multi-step or complex rearrangements unless the edge_kind is `fragmentation` or `unattributed`.

## Strategy

- **Prioritize early‑path reactions**: Focus on dehydration of cyclic sugars (e.g., glucose ring closure/open chain), tautomerization of open‑chain glucose isomers, and simple isomerizations that move functional groups.
- **Limit the number of guesses**: For `dehydration`, `tautomerization`, and `isomerization` edges, generate **at most 2** guesses. For other kinds, generate **at most 1** guess if confident; otherwise skip.
- **Seek single‑imag modes**: Use a constrained optimisation approach (e.g., eigenvalue‑following or COS) to ensure the Hessian has exactly one negative eigenvalue. If a guess yields multiple imaginary modes, discard it and try a simpler displacement.
- **Avoid soft‑mode traps**: If the reactant and product differ by a large conformational change (e.g., multiple ring flips), prefer a guess that interpolates linearly in internal coordinates, not a crude Cartesian interpolation.
- **Use chemical intuition**: For dehydration, start from a geometry where the leaving OH and a neighbouring H are close; for tautomerization, align the enol and keto forms by overlapping heavy atoms.

## Output Format

Return a JSON object:
```json
{
  "guesses": [
    {
      "label": "r0_g1",
      "xyz": "...",
      "rationale": "short description"
    }
  ]
}
```

## Fallback

If no plausible guess can be made, return an empty list. Do **not** generate guesses that are likely to fail in the same way as previous attempts (e.g., multi‑imag modes, large RMSD).

## Constraints

- Never modify the skill itself.
- Do not introduce new reaction mechanisms.
- Do not use machine learning or external databases.
