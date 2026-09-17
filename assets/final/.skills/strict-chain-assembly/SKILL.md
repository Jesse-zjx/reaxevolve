---
name: strict-chain-assembly
description: >-
  Assemble, finalize, and package a complete strict QM-validated reaction chain
  (e.g. glucose→HMF) from individually validated elementary edges, and produce an
  expert-review deliverable. Use after per-edge TS validation when you need to:
  stitch validated STRICT edges into a connected route, close remaining gaps with
  the right TS-guess method, clean spurious soft imaginary modes, finalize unified
  chained geometries, verify front/back endpoint consistency, compute energetics,
  and build the review folder + HTML report. Encodes the methods that closed the
  glucose→HMF chain (dry proton/2D scans, anomeric retro-hemiketal scan,
  scan>NEB, soft-mode cleanup, EXACT_SMILES_ONLY). Covers assembly and packaging;
  skill pathway-method defines the per-step acceptance bar and wins on
  any conflict.
---

# Strict reaction-chain assembly, finalization & review

Prereq: each elementary edge validated to the STRICT bar (single imaginary mode +
raw IRC endpoints = exact neutral reactant/product). See skills `qm-reaction-validation`,
`strict-edge-criterion`, `ts-validation-strategy`. Bar enforced by
`templates/path-validator-workspace/resources/strict_validate.py`.

> Acceptance clauses: `policy/acceptance/STRICT.md` (v5). This skill does not redefine them.

## Operating disciplines (what made the expert-approved chain work)
The validated glucose→HMF chain did NOT come from blind template-enumeration + one-shot
validation of top-scored candidates (that yields ~0 STRICT). It came from:
1. **Motif-aware selection**: pick edges matching proven strict-able motifs (direct
   tautomerization; β-elimination *from* an enol with a vicinal-OH relay; hemiketal ring
   open/close with vicinal OH). Deprioritize hard sub-types (aromatization of a
   not-fully-formed ring, anomeric→oxocarbenium). See `templates_expand.motif_score`.
2. **Persistence per hard edge**: do NOT stop after 2 guesses. Escalate the method
   ladder + soft-mode cleanup (displace along a spurious soft imaginary + reopt) +
   more guesses/sites until STRICT or budget exhausted. Hard steps (e.g. the anomeric
   ring closure) needed many attempts.
3. **Harvest actual IRC endpoints**: every real TS's raw IRC connects two real neutral
   species; record that as a `qm_real` edge — the perceived products become new seeds — even when the
   endpoints do not match the proposed pair. This accumulates an edge pool over time — the chain was
   assembled from such an accumulated pool, not one clean pass.
Engine: `reaction_network/{templates_expand,validate_candidate,build_reaction_network}.py`;
`discovered_cache.json` = harvested qm_real edges; tiers: STRICT (exact to target) vs qm_real.

## A. Harvest edges & find the route
Strict results accumulate in many `**/strict_cache.json` files. Build a directed
graph and BFS from reactant to target over `status=='STRICT'` edges:
```bash
rg -l strict_cache.json; # then load each, canonicalize R>>P (RDKit), BFS glucose→HMF
```
Expect components separated by 1-2 missing connector steps ("gaps"). Identify each
gap as the pair of (product-of-front-component, reactant-of-back-component).

## B. TS-guess method ladder (pick by reaction kind)
NEB highest-image guesses are unreliable for floppy polyol/water systems (collapse
to multi-imaginary or zwitterion endpoints). Prefer constrained scans.
> Rule adopted after the furfural review, applying to new edges (see section C and skill
> `pathway-method`): the bar rejects a step whose IRC carries a spectator H₂O on *both* endpoints,
> so the old water-relay proton-transfer recipe is superseded by dry proton / 2D scans — route
> a terminal-enediol tautomerization dry via the ketose, then a separate ketose→aldose
> isomerization. This is forward-looking guidance; it does not reopen an accepted deposit.

| reaction kind | guess generator | evidence |
|---|---|---|
| dehydration / aromatizing dehydration | `constrained_scan_guess.py` (C–O ± β-H relaxed scan) | HMF s1 (−1410.1), HMF s3 (−1533.0), aromatizing HMF s5 (−830.4), FF s7/s9/s11 |
| proton transfer (tautomerization / enolization / ketonization) | **dry** `dry_proton_guess.py` | see note below |
| aldose↔ketose isomerization | 2D concerted scan `scan2d.py` | FF s1 (−434.7), FF s6 (−766.5), HAA s1 (−474.2) — two H's move, so it is not a proton transfer |
| ring open / close (hemiketal / hemiacetal) | targeted anomeric scan | HMF s4 (−1574.5), FF s10 (−1621.5); see `gap1_anomeric.py` |

`dry_proton_guess.py` atom-maps reactant to product, locates the migrating H, and runs a GFN2 scan of
H→acceptor plus a concerted donor-H / H-acceptor grid. It is the method for new proton-transfer edges;
`water_relay_guess.py` is deprecated for new work, because its IRC carries a spectator H₂O on both ends
and a new edge is no longer accepted on that basis. It covers single-H shifts only; an aldose↔ketose
isomerization moves a hydride C→C *and* a proton O→O, so it needs the 2D coordinate instead. The
hand-indexed DFT scan `proton_scan.py` remains available for one-off proton work.

For the anomeric case, stretch the anomeric C–O while driving the C–OH proton onto the ring O (the
retro-hemiketal coordinate). A generic auto-mapped scan picks the **wrong** C–O and lands on a furanic
isomer.

Validate every guess with `strict_validate.py`; accept the first STRICT. Run
several scan points (e.g. dual C–O / H–O grid) and take the highest-energy ones.

General fallback and efficiency measures (in `reaction_network/`):
- **Active-learning TS sampler** (`active_learning_ts.py`): golden-section interpolation
  between matched reactant/product geometries + quadratic peak fit, constraining the
  changing (active) bonds. Kind-agnostic; add its guesses to the per-kind ones.
- **Energy-filter pruning** (GFN2, in `validate_candidate.py`): skip candidates whose
  reaction ΔE is hopelessly endothermic (product side = separately-optimized fragments
  summed, so fragmentations aren't clash-penalized); then rank all guesses by GFN2
  energy and DFT-validate only the top few. Cuts wasted DFT.

## C. Enforce the exact bar
Set `EXACT_SMILES_ONLY=1` (default in `orca_xtb_workflow.classify_endpoint_match`):
only exact neutral-SMILES double-end matches pass: no InChI, tautomer or zwitterion
tolerance, and no one-sided `product_match`.

> Expert-enforced after the furfural review: **do not rely on stripping a catalytic
> water as a spectator.** A step whose IRC carries a standalone H₂O on BOTH endpoints
> is rejected (the water has no provenance and breaks atom-count chaining). Every step
> must be a neutral↔neutral isomerization (same atom count) or a real dehydration (water
> a genuine product on one side). If a step only closes with a bridging water, the
> mechanism is wrong — reroute (e.g. terminal enediol → ketose, dry, then a separate
> ketose→aldose isomerization). See skill `pathway-method` (authoritative
> recipe + mechanism-selection rules + the FF zwitterion case study).

## D. Soft-mode cleanup (when a TS has a tiny extra imaginary)
A real reaction TS sometimes carries a spurious soft imaginary (e.g. -35 cm⁻¹
hydroxyl/CH₂OH torsion) → second-order saddle, fails "exactly one imaginary".
Fix: parse that mode from the `.hess` `$normal_modes`, displace the TS geometry
±0.6 along it, re-OptTS (TightOpt + DEFGRID3 + Recalc_Hess), check for a single
imaginary; then re-run IRC and confirm endpoints unchanged. See `displace_s4.py`.

## E. Finalize unified chained geometries
Re-optimize each node once (r2SCAN-3c Opt TightSCF CPCM(water)) so a single
canonical geometry is shared: product of step n ≡ reactant of step n+1 = the same
file. See `finalize_chain.py`. Verify each optimized node reproduces its expected
canonical SMILES.

## F. Cross-step endpoint consistency (front/back match)
For each shared node optimize BOTH adjacent IRC endpoints; require identical
canonical SMILES and (ideally) same minimum energy. See `verify_consistency.py`.
Same-SMILES but different rotamer (ΔE a few kcal, barrierless) is acceptable —
adopt the lower-energy conformer as canonical and state that explicitly. So that a reviewer
does not have to take it on trust, also emit `chain_shared_nodes/step_n_product.xyz` ==
`step_{n+1}_reactant.xyz` (byte-identical copies of the canonical node).

## G. Energetics
Water reference single point for mass balance of dehydration steps. Report
barriers ΔE‡ and ΔE per step. Electronic ΔE is the minimum; reviewers will also
want **ΔG‡** (use the existing Hessians) and optionally DLPNO-CCSD(T) single
points; neutral uncatalyzed barriers are high (real HMF chemistry is acid/water
catalyzed) — state this limitation.

## H. Expert-review package layout
```
glucose_hmf_review_vN/
  00_report/        self-contained HTML (render molecule images from the .xyz files)
  01_chain_nodes_xyz/   canonical node geometries (one per node)
  02_transition_states_xyz/   the TSs (each single imaginary)
  03_irc_endpoints_xyz/   raw IRC F/B + chain_shared_nodes/ (product n == reactant n+1)
  04_orca_inp_out_hess/   TS .out+.hess (freq evidence) + IRC .out
  05_docs/          FINAL_*.md, VERIFICATION.json, cross_step_consistency.json, manifest
  06_final_chain/   assembled nodes+TS+MANIFEST.json
  README_FOR_EXPERT.md
```
Generate the HTML report directly from the deposited files (draw nodes from xyz via
`rdDetermineBonds`, read imag from `*_TS.out`, barriers from MANIFEST) so it cannot
drift out of sync. The deposit is untracked and has no git history, so archive it before editing.

## I. Pre-flight checklist (the 5 things experts flag — verify programmatically)
1. Every step has a barrier (ΔE‡ present, non-null).
2. Every step has a TS with EXACTLY one imaginary mode (final NumFreq block).
3. Each step's xyz matches the report (render report images from the xyz; display
   the xyz-derived canonical SMILES).
4. Front/back endpoint identity: product(n) == reactant(n+1) (byte-identical node).
5. Single-route folder: scan ALL xyz; no species from other routes. (TS geometries
   perceive as charged/partial-bond — that is expected, not a foreign species.)

## Scripts (this campaign; under validation/cpcm_chain/)
`gap1_anomeric.py` (anomeric retro-hemiketal) · `gap_dehyd.py` (scan dehydration) ·
`displace_s4.py` (soft-mode cleanup) · `finalize_chain.py` · `verify_consistency.py` ·
`gen_report_v3.py` (HTML from files). Hand-indexed DFT proton/2D scans: `proton_scan.py`,
`scan2d.py`.

For new proton-transfer edges the dispatcher now calls `resources/dry_proton_guess.py`
automatically and only falls back to `water_relay_guess.py` if the dry scan yields nothing;
the spectator-water allowance (`--spectators O`) is asserted only on that fallback, so a dry
saddle is judged without it. `water_relay_guess.py` is otherwise retained only for reproducing
the older HAA step — DEPRECATED, do not use for new edges. Generic driver:
`resources/auto_validate_driver.py` (combined NEB+scan+interp guess plan,
continue-past-failure, EXACT_SMILES_ONLY); its water-relay branch is likewise deprecated
under the current bar.
