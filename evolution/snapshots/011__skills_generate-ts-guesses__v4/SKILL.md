# Skill: generate-ts-guesses

## Purpose
Generate transition-state (TS) guesses for a given reactant-product pair
that are likely to yield a single dominant imaginary frequency and well-defined
IRC endpoints connecting the two species.

## Input
- `reactant_gjf`: Gaussian input file for the reactant
- `product_gjf`: Gaussian input file for the product
- `reaction_kind`: string (e.g., "dehydration", "isomerization_or_tautomerization",
  "ring_closure", "dehydrogenation", "fragmentation") – optional hint

## Output
A list of TS guess structures, each as a Gaussian input file with
`#p opt=(ts,calcfc,noeigentest) freq=noraman` or similar TS-calculation
settings.

## Strategy

### Core principles
- **Single-imaginary seeking**: Design guesses to give one dominant imaginary
  mode (>300 cm⁻¹ absolute) that connects reactant and product. Avoid guesses
  that merely slide along flat potentials (soft modes <200 cm⁻¹).
- **Pre‑organization**: The guess should resemble the higher-energy structure
  along the reaction coordinate, not an arbitrary intermediate. Use the
  reacting atoms’ geometry and bond‑breaking/forming distances.
- **Early-path kinds**: For reactions that can proceed via multiple elementary
  steps, prefer the earliest step (e.g., simple proton transfer or bond
  rotation) over composite rearrangements. Avoid guesses that combine two
  distinct chemical changes when a single step suffices.
- **Fewer, better staged guesses**: Generate at most 5 guesses per pair.
  Rank them by expected saddle-point quality. If the first guess fails
  (e.g., no endpoint record), the next should be structurally distinct
  rather than a minor variation.

### Generation procedure
1. **Identify reacting atoms**: Map the atoms that change connectivity
   between reactant and product. Use the atom‑mapping from the reaction
   SMILES if available, or infer from substructure differences.
2. **Build the TS guess**:
   - Start from the reactant geometry, but modify the positions of the
     reacting atoms to be halfway between reactant and product values.
   - For bond‑breaking: increase the distance to ~1.2–1.5× the equilibrium
     bond length.
   - For bond‑forming: reduce the distance to ~1.5–1.8 Å, depending on
     atom types.
   - For ring closures: pre‑orient the chain so that the terminal atoms
     are within 2.5–3.0 Å and with appropriate angle for cyclization.
   - For dehydration or proton transfers: include a bridging water or
     assisting group if needed, but keep the guess minimal.
   - Do not introduce large rearrangements of spectator groups; maintain
     the rest of the molecule close to reactant geometry.
3. **Validate the guess**:
   - Ensure the guess has a single negative frequency in a quick
     frequency calculation (if possible, e.g., using a cheap method).
     If not, discard and try a different approach.
   - For each guess, specify in the comment line the intended reaction
     coordinate (e.g., "breaking C1-O2 bond, forming O2-H3").
4. **Output format**: Each guess as a separate GJF file with keywords
   `#p opt=(ts,calcfc,noeigentest) freq=noraman scf=(xqc)`. Include
   the charge and multiplicity from the reactant.

### Learning from failures
If previous TS attempts for a similar reaction kind failed with:
- **no_endpoint_record**: The IRC did not reach either endpoint. This
  suggests the guess is far from the true saddle point or the potential
  surface is too flat. In the next guess, make the guess more asymmetric
  (closer to the reactant or product) and use a tighter optimization
  criterion (opt=verytight).
- **no_dominant_mode**: The only imaginary frequency is small (<200 cm⁻¹)
  or there are multiple small ones, indicating a shallow ridge rather than
  a saddle. Avoid guesses with soft torsions or hydrogen‑bond
  rearrangements. Instead, focus on heavy‑atom bond breaking/forming.
- **one_end_only**: The IRC connects to one endpoint but not the other.
  The guess is biased toward one side. Shift the guess 10–20% toward the
  missing endpoint along the reaction coordinate.

### Example
For reactant `O=CC(O)C(O)C(O)C(O)CO` and product `O=C(CO)C(O)C(O)C(O)CO`
(isomerization/tautomerization), a good guess would be a structure where
 the aldehyde proton is halfway between the O1 and C2, with the O1–C2 bond
 partially broken and C2–H partially formed. The comment:
 "breaking O1-C2, forming C2-H; guess 1 of 3".

## Constraints
- Do not generate guesses that require changing the molecular formula.
- Do not generate guesses for reactions that are not chemically plausible
  under the given conditions (neutral, gas‑phase or implicit solvent).
- Always respect the expected charge and spin multiplicity.
