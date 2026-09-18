# Skill: generate-ts-guesses

## Purpose
Given a reactant and product SMILES pair (and optionally the reaction kind), produce a small set of initial TS guess geometries that are likely to converge to a saddle point with a single dominant imaginary frequency.

## Input
- `reactant_smiles`: string
- `product_smiles`: string
- `reaction_kind` (optional): string, e.g., "tautomerization", "dehydration", "dehydrogenation", "fragmentation", "isomerization"

## Output
A list of TS guess structures (usually in XYZ format) with a label.

## Core principles
1. **Fewer, higher-quality guesses are better than many weak ones.** The QM validation is expensive; each guess should have a high probability of becoming a valid strict edge.
2. **Avoid interpolation-based guesses for tautomerizations and isomerizations** where the atom connectivity changes but the overall shape is similar. Simple linear interpolation between reactant and product often yields a geometry that is a local minimum on the potential surface, leading to a soft mode (imaginary frequency < 100 cm⁻¹) rather than a true saddle point.
3. **For proton transfers (tautomerization), use a single guess based on a typical TS geometry for that functional group.** Displace the transferring hydrogen along the O–H…O or C–H…O vector, with the hydrogen roughly midway between donor and acceptor, and adjust the heavy-atom distances to be consistent with a partial bond.
4. **For dehydration and ring‑closure reactions, generate guesses by distorting the reactant along the bond that is formed or broken**, using a distance that is ~0.5–0.7 of the equilibrium bond length (i.e., partially formed).
5. **For dehydrogenation, identify the C–H bond being broken and displace the hydrogen outward while keeping the carbon environment planarizing** if needed.
6. **When a guess fails with a soft mode (imaginary frequency < 100 cm⁻¹ or no dominant mode), do not resubmit the same guess type; instead, create a new guess with a larger distortion along the expected reaction coordinate.**
7. **If multiple guesses are needed, provide at most 2–3 structurally distinct starting points.** If the first guess succeeds, the rest are discarded.

## Specific guidelines by reaction kind
- **Tautomerization**: START with a single guess where the moving hydrogen is placed along the donor–acceptor axis at a distance of ~1.3 Å from each heavy atom. Do not use an interpolation between reactant and product.
- **Dehydration**: Two guesses: (i) the OH group and neighboring H are brought closer, with the H–O distance ≈ 1.5 Å and the C–O distance ≈ 1.8 Å; (ii) a similar geometry but with the leaving water already partially detached.
- **Dehydrogenation**: One guess with the leaving H at ~1.8 Å from the carbon, and the remaining fragment planarized.
- **Ring‑closure**: Use a template where the two reacting atoms are at a distance of ~2.0–2.5 Å and the dihedral angle is near the expected transition state.
- **Fragmentation**: The bond being broken should be stretched to ~1.8–2.0 Å; keep the rest of the molecule relaxed.

## After a failure
If the edge is re‑queued after a failure (e.g., from the diagnose‑ts‑failures skill), the generate‑ts‑guesses skill should be called again with the failure mode information. It must not repeat the same guess. Instead, use the failure mode to decide on a more aggressive distortion or a different dihedral angle, and produce exactly one new guess.

## Notes
- The QM workflow will optimize the guess and compute frequencies. The goal is to obtain a structure with exactly one imaginary frequency > 300 cm⁻¹ (or at least > 100 cm⁻¹) that is the dominant mode, and that connects the reactant and product via IRC.
- Do not generate guesses that are far from chemical intuition; keep bond lengths and angles within reasonable ranges to avoid immediate dissociation.