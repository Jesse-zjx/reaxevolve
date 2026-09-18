# Generate TS Guesses

This skill creates initial transition state guesses for reaction edges in the Explore stage.

## Guidelines

- For each reaction kind, generate a guess geometry that is approximately halfway between the reactant and product along the expected reaction coordinate.
- Ensure the guess has a single imaginary frequency in the range 300–2000 cm⁻¹ (characteristic of a TS). If the imaginary frequency is lower than 300 cm⁻¹, the guess is likely a minimum and should be adjusted.
- For tautomerization and isomerization: place the transferring proton at a distance halfway between donor and acceptor atoms, and adjust the bond angles to promote a four-membered ring TS if applicable.
- For dehydration: ensure the leaving O–H bond is stretched and the adjacent C–O bond is partially broken, and the C=C bond is forming. The water molecule should be oriented to leave.
- For dehydrogenation: stretch the C–H bond and H–C bond on adjacent carbons, and ensure the hydrogen is placed between them.
- If the QM calculation yields a soft mode (<200 cm⁻¹), modify the guess by moving the atoms further along the reaction coordinate and resubmit.
- Avoid geometries that are too close to reactants or products; the guess should be distinct from both minima.