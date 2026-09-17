---
name: ts-validation-strategy
description: >-
  Subordinate TS-guess playbook for sugar/HMF reaction paths — covers guess
  generation per reaction kind, constrained scans for dehydration, IRC endpoint
  debugging, and measured per-kind success. Still current, but does NOT define the
  acceptance bar: skill pathway-method is authoritative and wins on any
  conflict (two outdated clauses here are flagged inline). Use when generating a TS guess,
  choosing a method for a reaction kind, or debugging an IRC endpoint mismatch.
---

# TS Validation Strategy for Glucose→HMF Pathways

> Scope: skill `pathway-method` defines the current acceptance bar (HMF standard). This
> skill is the earlier TS-guess playbook; where the two differ, that skill governs. Two clauses were
> tightened after the furfural review and are marked SUPERSEDED at the point where they appear.

> Acceptance clauses: `policy/acceptance/STRICT.md` (v5). This skill does not redefine them.

## STRICT-bar campaign experience (2026-06)
> Background reading: `templates/yarp-workspace/STRICT_ROUTE_STRATEGY.md` — the campaign-era strategy
> record. It sits in the YARP workspace for historical reasons; route search itself no longer goes
> through YARP enumeration.

- **Bar**: every step's raw IRC ends must equal the neutral reactant and the neutral product, and the
  next step's reactant is the previous step's product.
- **Tool**: `resources/strict_validate.py` (OptTS + NumFreq + IRC, RDKit-constitution endpoint check;
  `--active-atoms` focuses the TS mode).

> SUPERSEDED for new work (post-furfural review): the bar is **exactly one imaginary mode** — a small
> residual floppy mode is a failure; clean it by soft-mode displacement plus a VeryTight re-optimization.
> Also, do not use `--spectators` to carry a relay water through: on a new edge a standalone H₂O on both
> IRC ends is rejected. (Forward-looking only — the three accepted deposits stand as delivered.)
Proven STRICT edges (all from the three accepted deposits — see `strict-edge-criterion` for the full
motif table with route/step tags): open-glucose→open-fructose (direct concerted iso, −474.15, HAA s1);
open-fructose→2,3-enediol (direct keto→enol, −2042.5, FF s2); β-elimination dehydration from the enol
(−1410.1, HMF s1); aromatizing anomeric dehydration to HMF (−830.4, HMF s5) and to furfural
(−872.9, FF s11); β-carbonyl-activated retro-aldol C–C cleavage (−932.3, FF s4).
Key method lessons:
1. Isomerizations/tautomerizations: run them as direct concerted intramolecular H-shifts (no water);
   build the product with matched atom ordering, then DFT OptTS + TS_Active_Atoms. Water-relay
   tautomerization fails (floppy soft modes → −140 cm⁻¹ pseudo-saddle).
   > NARROWED for new work: the guess came from xTB NEB-TS in the xTB era. Use
   > `dry_proton_guess.py` instead (see the refinements section); NEB is now a last resort.
2. Dehydrations are E1cb-like: must start *from* the enol; the leaving OH is protonated by a vicinal OH
   (direct O–H···O ~2.4 Å), NOT a long-range water relay. The "relay water" is usually a spectator.
3. A monotonic scan is not evidence that the mechanism is wrong. A scan along a *single bare*
   coordinate reads monotonic, or fragments, even where a real TS exists — vicinal-assist was ruled out
   on exactly that basis and later proved correct. Co-drive the second coordinate (the proton) instead
   of abandoning the mechanism.
   > NARROWED for new work: the xTB-era conclusion was to switch to NEB-TS. What actually generalizes
   > is *dual* versus *single* coordinate, not scan versus NEB — the dual C–O/β-H constrained scan is
   > the reliable workhorse (see the refinements section), and NEB is the unreliable one here.
4. Known difficult: the first dehydration of a fully-hydroxylated sugar (fructose→3-DG), which is the
   rate-limiting step of the HMF route. It was resolved dry in the accepted chain, as an E1cb-like
   β-elimination *from* the enol with a vicinal-OH relay, guessed by a dual C–O/β-H constrained scan
   (`glucose_hmf_review_v3` step 1, −1410.1). The old suggestion to add a 2–4 H₂O proton-wire cluster is SUPERSEDED — such a cluster leaves
   spectator waters on both IRC ends and fails the current bar.
5. Avoid anomeric/ketal dehydrations (barrierless oxocarbenium, charged IRC endpoint, never strict).

## Refinements from the completed glucose→HMF closure (full chain passed expert review)
The final connected strict route is open-glucose → 3-deoxyglucosone-enol → 3-DG → 3,4-DGE →
furanic hemiketal → HMF (dehydration −1410.1, tautomerization −1449.8, dehydration −1533.0, ring-closure
−1574.5, aromatizing dehydration −830.4). Method ladder that actually closed the gaps (use skill
`strict-chain-assembly`):
- Dehydration / aromatizing dehydration: the **constrained C–O (± β-H) relaxed scan**
  (`constrained_scan_guess.py`) is the reliable workhorse — it produced the guesses behind HMF s1
  (−1410.1), HMF s3 (−1533.0) and the aromatizing HMF s5 (−830.4). The dual C–O/H–O scan followed by
  OptTS on the highest point is robust; only a single bare coordinate is not (lesson 3 above).
- Ring open/close (hemiketal): NOT a generic NEB. Use a **targeted anomeric scan** — stretch the
  anomeric C–O while driving that carbon's -OH proton onto the ring O (retro-hemiketal coordinate). The
  auto-mapper otherwise scans the wrong C–O and lands on a furanic isomer (`gap1_anomeric.py`).
- Proton-transfer where the dry intramolecular path goes through a zwitterion: **do NOT patch it with
  an explicit water relay** (`water_relay_guess.py` is DEPRECATED for new edges — its IRC keeps a
  spectator H₂O on both ends, and a new edge is no longer accepted on that basis). Instead re-route the
  mechanism dry: a terminal enediol goes to the
  ketose (internal C=O), then reach the aldose by a separate ketose→aldose isomerization
  (concerted hydride+proton). See the FF step-5 case study in skill
  `pathway-method`. (Simple aldose↔ketose was always fine dry.)
- Routine proton transfers no longer need hand-picked atom indices: `dry_proton_guess.py`
  atom-maps reactant→product, identifies the migrating H, and scans it onto the acceptor.
  Its concerted grid deliberately spans early geometries — these shifts are strongly
  asynchronous (the accepted HMF step-2 saddle sits at d(O-H)=1.48 Å with d(H-C) still
  1.90 Å), so a grid centered on a half-transferred H misses the saddle.
- **NEB highest-image guesses are unreliable** for floppy polyol/water systems (collapse to
  multi-imaginary / charged endpoints) — prefer scans.
- **Soft-mode cleanup**: if a valid TS carries a tiny extra imaginary (~−30 cm⁻¹ torsion), displace
  along that normal mode and re-OptTS to get a clean single-imaginary saddle (`displace_s4.py`).
- Enforce `EXACT_SMILES_ONLY=1` (`orca_xtb_workflow.classify_endpoint_match`; `strict_validate.py`
  applies the same rule directly in `endpoint_matches`). Then finalize unified node geometries + cross-step consistency +
  review package (skill `strict-chain-assembly`).

## Validated reaction types (DFT, from the 3 accepted deposits — supersedes the old xTB table)
Every kind below now has at least one STRICT, single-imaginary, DFT-validated example, so none of
them may be "skipped". Frequencies in cm⁻¹, r2SCAN-3c/CPCM(water).

| Reaction Type | STRICT examples (imag) | Recommended TS-guess method |
|---------------|------------------------|-----------------------------|
| **Dehydration** (−H₂O) | −1410.1, −1533.0 (HMF); −1459.8, −1541.1 (FF) | dual constrained scan: break C–O + drive β-H |
| **Aromatizing dehydration** | −830.4 (HMF); −872.9 (FF) | dual constrained scan (aromatization drives it) |
| **Aldose↔ketose isomerization** | −474.15/−434.65 (glucose→fructose, same TS at 2 grids); −766.5 (xylulose→xylose) | `scan2d.py` 2D scan (concerted hydride + proton, TWO H's) |
| **Tautomerization / enolization** | −1449.8 (HMF); −2042.5, −2032.5, −2137.8, −1630.0 (FF) | **dry** `dry_proton_guess.py` (automatic); `proton_scan.py` = hand-indexed DFT scan (O→C 1,3-shift) |
| **Ring close/open (hemiketal)** | −1574.5 (HMF); −1621.5 (FF) | targeted anomeric scan (C···O(ring) + proton) |
| **Retro-aldol C–C cleavage** | −932.3 (FF); −758.1, −942.1 (HAA) | dual scan: stretch Cα–Cβ + β-OH proton → carbonyl O |
| **Hydration** (+H₂O) | none | untested — no validated example yet |

Note the isomerization row: the same saddle geometry gives −474.15 at DEFGRID2 (ORCA's default) and
−434.65 at DEFGRID3 (≈40 cm⁻¹ grid sensitivity for this soft mode). Always report the grid.

## TS Guess Generation: Decision Tree

```
Is it a dehydration step?
├── Yes → use constrained_scan_guess.py
│   ├── Identify breaking C–O bond:
│   │   1. Try map_reaction_atoms.py (atom mapping)
│   │   2. Validate: β-H distance < 4.0 Å?
│   │   3. If not → RDKit fallback (enumerate ALL C–OH, rank by product similarity)
│   ├── Run C–O stretch scan (1.6–3.2 Å, 7 points)
│   ├── Run dual C–O + H-O scan (8 configs)
│   └── Select top-9 by xTB energy → ORCA workflow
├── Is it an isomerization (e.g., glucose↔fructose)?
│   └── NEVER skip the TS — under the strict bar every step needs its own single-imaginary
│       TS + IRC. Use scan2d.py (concerted hydride + proton); glucose↔fructose = −474.15/−434.65.
├── Is it a tautomerization / enolization?
│   └── Dry dry_proton_guess.py (automatic O→C 1,3-shift; proton_scan.py if you want to
│       drive a DFT scan by hand). Do NOT add a relay water.
├── Is it a retro-aldol C–C cleavage?
│   └── Dual scan: stretch Cα–Cβ + drive the β-OH proton onto the carbonyl O.
│       Requires a carbonyl β-activating the breaking C–C (aldose C2–C3 direct does NOT work).
└── Other → auto_guess.py (interpolation between mapped geometries)
    └── Reaction-agnostic, so it ignores the reaction coordinate; use it only when no
        per-kind method above applies
```
> The old branch "isomerization → skip TS validation, generate product XYZ from SMILES" was an
> xTB-era shortcut and has been removed: it cannot produce a validated edge under the current bar.

### Phase-2 queue scoring (2026-08)
`tools/reaction_network/templates_expand.py` `motif_score` now **penalizes dehydration when the
reactant is not an enol** (`[OX2H][#6X3]=[#6]`). Candidates remain enumerable, but the QM budget
prefers E1cb-like enol→alkene dehydrations that match the proven STRICT motif. Non-enol
dehydrations were the main source of `dehydration` / `no_match` in `failure_digest`. Expectation
tracked in Experience Memory (`upd_*` with `--kind dehydration --failure no_match`).

## Critical Lessons Learned

### 1. Water Stripping is Essential
After a successful dehydration step, `product.xyz` contains the organic product + H₂O.
The next step's `reactant.xyz` must be **stripped of water** or **regenerated from SMILES**.

- **Connectivity-based stripping** works when water is physically separated (>1.3Å from organic)
- **SMILES regeneration** (via `smi_to_xyz.py`) is the robust fallback when water is H-bonded

### 2. Bond Identification: Product Similarity > Geometry
When identifying which C–OH to break for dehydration:

- **β-H distance alone is unreliable**: closest β-H ≠ correct reaction site
- **Product similarity matching** works better: simulate dehydration at each C–OH,
  compare simulated product to expected product via Tanimoto similarity
- **Atom mapping** (`resources/tools/map_reaction_atoms.py`) is best when it works, but fails
  for ~40% of SMILES pairs → always have an RDKit fallback

### 3. A plausible SMILES transformation is not an elementary step
This is the finding that eventually retired the YARP enumeration stage, and it
generalises to any rule- or LLM-based proposer: a transformation can be perfectly
sensible on paper and still not be one elementary reaction on the PES.

**Pattern observed**: the first dehydration from glucose/fructose works perfectly.
The second consistently finds a **real TS** (imag = −600 to −1700 cm⁻¹) whose IRC
connects to a **different isomeric product** than the one proposed.

**Implication**: regioselectivity predictions for later intermediates (which C–OH
leaves) are not reliable enough to spend QM on blindly, and the "wrong" product the
IRC actually gives is often the correct chemistry. Let the IRC decide connectivity;
triage candidates with `strict-edge-criterion` before committing compute.

### 4. Endpoint Matching Tiers
```
strict       : both IRC endpoints match the expected R/P exactly → accept
product_match: one endpoint matches expected product, other does not
               → reject (the IRC failed to trace back to the reactant; unreliable)
mismatch     : neither endpoint matches → reject for the proposed pair, but harvest
               the perceived endpoints as a candidate edge (see §5)
```
Only `strict` match counts as validated. The old policy of accepting `product_match` produced
0 fully-validated pathways out of **118 edges tested in the xTB-era screen (2026-05)** — every
"success" fell apart once both IRC ends had to match.

> Two campaign totals get quoted and they are *not* the same measurement. This one is 118 edges from the
> **xTB-era screen**, and it says the *acceptance policy* was wrong. The other, in
> `pathway-method`, is **2 STRICT / 115 attempts dispatched at DFT**, and it says the
> *automated guess ladder* has a low hit rate. Different eras, different denominators, different lesson.

### 5. What the "Wrong" IRC Products Tell Us
A TS with the correct reactant but an unexpected product is still real chemistry: the
saddle connects two genuine neutral species, just not the pair that was proposed.

- Perceive the actual IRC termini. If both are neutral closed-shell, that pair is a
  **candidate edge in its own right** — re-validate with those as the declared endpoints
  rather than discarding the run.
- Do NOT record it as a validated edge for the originally proposed product.
- This rescue is how the D-xylulose retro-aldol became a STRICT edge (−540.8, single
  imaginary, exact endpoints): it first scored PARTIAL against a guessed DHA product,
  and the real IRC gave glycolaldehyde plus the C3-enediol. That edge carries HAA route 2;
  record in `reaction_network/r2_xlu_cleanp/strict_cache.json` (it is not one of the three
  deposits, so verify it there rather than under a deposit).

`validate_candidate.harvest_endpoints()` does this automatically, writing the perceived
pair into `discovered_cache.json` so the network grows even from a mismatch.

> Feedback used to be routed back into YARP's `search_graph.json`. That loop is retired —
> route search no longer goes through YARP enumeration (see `trash/README.md`); harvested
> endpoints now go straight into the reaction network and the candidate queue.

## Files Reference

| File | Purpose |
|------|---------|
| `resources/strict_validate.py` | The acceptance gate: OptTS + NumFreq + IRC + strict endpoint match |
| `resources/constrained_scan_guess.py` | Dual constrained-scan TS guesses (dehydration / aromatization) |
| `resources/dry_proton_guess.py` | Dry proton-transfer TS guesses (tautomerization / enolization) |
| `resources/auto_guess.py` | Reaction-agnostic interpolation guesses; fallback only |
| `resources/auto_validate_driver.py` | Orchestrates validation pipeline |
| `resources/orca_xtb_workflow.py` | ORCA+xTB TS opt → freq → IRC workflow |
| `resources/smi_to_xyz.py` | SMILES → 3D XYZ via RDKit+xTB |
| `validation/path_queue.json` | xTB-era pending-step queue, read by `auto_guess.py --all-pending`. Batch work now runs through `reaction_network/auto_loop.py` and `dispatch_cache.json` |
