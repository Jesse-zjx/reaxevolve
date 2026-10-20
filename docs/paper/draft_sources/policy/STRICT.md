# STRICT acceptance bar (v5)

**Version**: `v5`  
**Authority**: this file + `policy/acceptance/check_strict_bar.py` (single implementation).  
**Not evolvable**: agents may not edit this directory. Skills/Tools point here; they do not restate clauses.

This is the **only** scientific acceptance bar for edge/path verdicts. There is no separate
loop-screen bar. Early-exit heuristics inside QM drivers are compute throttles only and must
not emit a status label.

## Four clauses (every elementary step)

1. **Level**: `! r2SCAN-3c OptTS NumFreq (Very)TightSCF DEFGRID3 CPCM(water)` for deposit-grade
   work. IRC and node minima also `r2SCAN-3c ... DEFGRID3 CPCM(water)`. GFN2-xTB is allowed only
   for TS guesses — an xTB-only pass is never a validated edge. Integration grid is reported
   as-built next to every frequency (DEFGRID2 may appear in historical deposits).

2. **Exactly one imaginary frequency** in the final NumFreq block (`len(imag) == 1`). Residual
   soft modes must be cleaned before acceptance; do not report a second-order saddle as STRICT.

3. **Raw IRC endpoints**, after unconstrained optimization, give the **exact neutral**
   canonical SMILES of reactant and product (RDKit, charge=0). Reject charged / zwitterionic /
   tautomer endpoints that are not the intended species.

4. **Chained + atom-conserving**, with the **discrete water rule**:
   - Each step is a neutral↔neutral isomerization (same atom count) or a real dehydration
     (−3 atoms with water as a genuine product), or a catalytic proton shuttle under the rule below.
   - If both IRC ends contain a complete neutral H₂O fragment, compare the **atom indices** of
     the hydrogens bonded to that water oxygen (ORCA IRC preserves atom order):
     - **Different H indices** on the two ends → catalytic proton shuttle → **allowed**.
       Water provenance must be a declared chain component; atom conservation is counted on the
       water-including system (oxygen conserved; hydrogens exchange — the catalyst signature).
     - **Identical** O + H + H atom identities on both ends → spectator water → **rejected**.
   - Pure spectator water (same three atoms on both ends) is never STRICT under v5.

## Scope

- Applies to all **new** work and to re-adjudication of network STRICT edges under
  `strict_version=v5`.
- Expert-confirmed deposits are audited with the same clauses; packaging audits may report
  findings without rewriting archived deposit files.
- Skills/Tools may evolve guess recipes; they may **not** change these clauses or write
  `evidence` / `endpoint` / `verdict` fields.
