# Generate TS Guesses (v2)

**Purpose:** Produce a small set of high-quality transition-state guesses for the given reaction edge.

## Input
- `reactant` SMILES
- `product` SMILES
- `reaction_kind` (e.g., dehydration, isomerization_or_tautomerization, ring_closure)
- `constraints` (e.g., conservation of atom/bond numbers)

## Output
- A JSON list of guess objects, each containing:
  - `ts_geometry` (XYZ format or similar)
  - `irc_required`: true  (always true)
  - `comment`: short note on how the guess was generated

## Guessing Strategy

### 1. Limit the number of guesses
- **Maximum 3 guesses** per edge, unless the reaction is a simple dehydration of a single hydroxyl group; then up to 4.
- For isomerization_or_tautomerization, limit to **2 guesses** (high failure rate).

### 2. Prioritise early-path kinds
- Prefer reactions that stay close to the reactant skeleton: dehydration, ring closure, tautomerisation.
- Avoid late-stage rearrangements that require large geometrical changes.

### 3. Single-imaginary-mode seeking
- Each guess must be generated with a method that explicitly seeks a single imaginary frequency (e.g., using a coordinate-driving or eigenvector-following technique).
- Do not produce guesses that are likely to give multiple imaginary modes or flat PES regions.

### 4. Reaction‑kind‑specific rules
- **Dehydration:** Build a guess with the leaving OH and a neighbouring hydrogen, forming a water-like complex. Ensure the TS geometry is close to both reactant and product.
- **Isomerization/Tautomerization:** Use a simple proton-shift model; keep all heavy atoms nearly fixed. Limit to 2 guesses and prefer those that can be driven by a single coordinate.
- **Ring closure:** Use a constrained geometry with the forming bond at ~2.0 Å and a single imaginary mode along the closure coordinate.

### 5. IRC endpoint guarantee
- Every guess must be labelled with `irc_required: true`.
- The TS geometry must be such that a downhill IRC (both directions) can reach the reactant and product without large rearrangements.
- If a guess is expected to give ambiguous endpoints, **do not include it**.

### 6. Avoid repetition of known failure modes
- Before proposing a guess, check the failure digest for the current campaign:
  - If the same reaction kind shows repeated `no_endpoint_record` or `no_dominant_mode`, avoid similar guess geometries.
- For a given edge, do not generate a guess that is essentially the same as a previously failed one.

## Example
```json
[
  {
    "ts_geometry": "...",
    "irc_required": true,
    "comment": "Dehydration–OH at C2 and H at C3, single-imag-mode sought"
  }
]
```