# generate-ts-guesses

## Purpose
Generate high-quality transition state (TS) guesses for a given reaction edge.

## Input
- `edge_id` (str): Unique identifier of the edge.
- `reactant_smiles` (str): SMILES of the reactant.
- `product_smiles` (str): SMILES of the product.
- `kind` (str): Reaction kind, e.g., isomerization, tautomerization, dehydration.
- `attempt_history` (list, optional): Previous guess outcomes for this edge (failure modes, etc.).

## Output
A list of guess objects, each containing:
- `guess_id` (str): e.g., `r0_g0`
- `xyz` (str): XYZ geometry of the guess
- `metadata` (dict): method, constraints, expected imag mode, etc.

## Quality constraints
- **No more than 2 guesses per edge** unless explicitly requested by a higher-level strategy.
- Each guess must be a **saddle point candidate** with a single imaginary frequency corresponding to the reaction coordinate.
- **Reject** any guess that after a quick pre‑optimization shows:
  - no imaginary mode,
  - only soft modes (< 100 cm⁻¹),
  - multiple imaginary modes,
  - or an imaginary mode vector that does not connect reactant and product.

## Procedure
1. **Analyse the reaction**
   - Identify the bonds broken/formed between reactant and product.
   - Determine the primary reaction coordinate (atom indices).

2. **Generate an initial guess**
   - Use a coordinate‑driven approach (e.g., linear interpolation of the reaction coordinate, or a relaxed scan) to produce a geometry close to the barrier top.
   - If the edge involves a ring opening/closing, use a constrained optimisation that enforces the necessary bond changes.

3. **Refine the guess**
   - Run a saddle‑point optimisation (e.g., Berny algorithm with Opt=TS) starting from the initial guess.
   - Perform a frequency calculation to confirm one imaginary mode.

4. **Validate the guess**
   - Check that the imaginary mode vector displaces the geometry toward the reactant in one direction and toward the product in the other.
   - Require the absolute imaginary frequency to be > 200 cm⁻¹ for a meaningful barrier.
   - If the guess fails these checks, try a different interpolation or discard it.

5. **Return the refined guess**
   - Only return guesses that pass the validation.
   - If no valid guess is found after two attempts, return an empty list and log the reason.

## Avoid known failure patterns
- **`no_dominant_mode`** (soft modes only): The guess is a flexible minimum, not a TS. → Reject early; do not submit.
- **`one_end_only`**: The TS connects only one end. → Check that the imaginary mode reaches both minima.
- **`no_match`**: The TS connects different species. → Ensure the atoms match the reactants/products.

## Integration
This skill is called by the Explore stage. The output guesses are passed to the Validate stage for QM calculation and STRICT adjudication.