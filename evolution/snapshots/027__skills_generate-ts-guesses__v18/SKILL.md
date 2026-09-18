# generate-ts-guesses

## Purpose
Generate transition state (TS) guess geometries for a given reaction step. The goal is to produce at most three guesses that are likely to be saddle points of index 1 (exactly one imaginary frequency) and that connect the specified reactant and product.

## Inputs
- `reactant`: SMILES of the reactant
- `product`: SMILES of the product
- `reaction_kind`: e.g., dehydration, tautomerization, dehydrogenation, isomerization, fragmentation
- `previous_failures`: (optional) list of previous guess outcomes with failure modes (e.g., `no_dominant_mode`, `one_end_only`, `no_match`, `no_endpoint_record`)

## Outputs
Return a JSON array of guess objects, each with:
- `guess_id`: unique identifier
- `priority`: float (0.0–1.0), higher = more likely to succeed
- `rationale`: short explanation of the chemical reasoning
- `geometry`: XYZ block or SMILES with atom mapping (if the tooling supports it)

## Guidelines

### 1. Chemical intuition
- Identify the key bond changes (which bonds break/form).
- For tautomerization: proton transfer between two heavy atoms; the TS should have a near-linear O–H–O or C–H–O arrangement with the proton roughly in the middle.
- For dehydration: elimination of water; the TS should involve elongation of the C–OH bond, H abstraction by the leaving OH, and formation of a double bond. Consider a cyclic transition state if applicable.
- For dehydrogenation: H₂ loss; the TS often involves two hydride transfers or a concerted elimination.
- For isomerization: bond reorganization; identify the migrating group and the resulting bond changes.

### 2. Geometry construction
- Use a physical interpolation between reactant and product if possible (e.g., LST or IDPP).
- If building manually, set bond lengths to intermediate values (e.g., 1.5 × equilibrium for breaking/forming bonds) and adjust angles to approach the TS geometry.
- Ensure the guess is not a local minimum (no imaginary frequencies) or a second-order saddle. Aim for a single large imaginary frequency corresponding to the reaction coordinate.
- Avoid frozen bonds or artificial constraints that produce many soft modes.

### 3. Learning from failures
- If `previous_failures` contains `no_dominant_mode` (soft modes only), the guess was too flexible or the reaction coordinate was not captured. Try a more constrained guess with a clear single reaction coordinate.
- If `one_end_only`, the guess is biased toward one side. Adjust the geometry to be more balanced between reactant and product.
- If `no_match`, the guess connects different species; re-examine the atom mapping and the intended reaction.
- If `no_endpoint_record`, the IRC calculation may have failed or the endpoints were not recorded. Ensure the guess is close enough to the reaction path.

### 4. Practical limits
- Generate at most 3 guesses per edge.
- Order by decreasing confidence (priority).
- For edges with many prior failures, consider generating only 1–2 high-quality guesses rather than many low-quality ones.

## Examples
<example>
  "reactant": "O=CC(O)C(O)C(O)C(O)CO",
  "product": "O=C(CO)C(O)C(O)C(O)CO",
  "reaction_kind": "tautomerization",
  "guesses": [
    {
      "guess_id": "r1_g1",
      "priority": 0.9,
      "rationale": "Proton transfer from the terminal O to the carbonyl O via a 6-membered ring transition state; the proton is placed midway between the two oxygens.",
      "geometry": "..."
    }
  ]
</example>

## Failure handling
Always check `previous_failures`. If the last guess failed with `no_dominant_mode`, the next guess must explicitly state why it will have a single dominant imaginary mode (e.g., using a tighter constraint on the reaction coordinate). If the last guess failed with `one_end_only`, adjust the geometry to be more symmetric with respect to the forward and reverse directions.