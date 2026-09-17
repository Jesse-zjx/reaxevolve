---
name: pathway-method
description: >-
  Operating recipe for QM reaction-pathway validation and packaging under the
  STRICT(v5) bar defined in policy/acceptance (not restated here). Distills the
  glucose→HMF/HAA/FF campaigns into a reusable recipe: reaction-kind TS-guess
  ladder, mechanism-selection rules, OptTS/soft-mode cleanup, deposit packaging.
  Use when validating an elementary step, building/repairing a QM reaction chain,
  or batch-exploring new pathways to a target product. Acceptance clauses live
  only in policy/acceptance/STRICT.md.
---

# Pathway method (operating recipe)

Three deposits are **expert-validated and accepted as delivered** — they are the reference
standard for packaging, not a second acceptance bar:
`glucose_hmf_review_v3/` (5 steps), `glucose_haa_review_v1/` (4 steps),
`glucose_ff_review_v1/` (11 steps). Under STRICT(v5) deposit as-built is **20/20**.

The rules below are the **operating recipe for new edges** (guessing / cleanup / packaging).
DEFGRID3 was phased in over the campaign; as-built parameters in `reference.md` are provenance.

## Acceptance bar (pointer only)

**`policy/acceptance/STRICT.md` (v5)** + **`policy/acceptance/check_strict_bar.py`**.
This skill's `scripts/check_strict_bar.py` is a shim. Do not restate the four clauses here.
Clause 4 is the discrete water test (catalytic shuttle allowed; spectator rejected).

## Mechanism-selection rules
- **Prefer dry routes.** Catalytic water is allowed under v5 only when the discrete water
  test shows a true shuttle and water is a declared chain component. Do not sprinkle
  spectator water to force a pass — find a dry neutral↔neutral route first.
- **Terminal enediol → carbonyl: go to the ketose, not the aldose.** Dry enediol→aldose (terminal
  C=O) collapses to a zwitterion; dry enediol→ketose (internal C=O) is clean (mirrors HMF step 2).
  Then reach the aldose via a separate ketose→aldose isomerization if needed (see FF case).
- **Aldose↔ketose isomerization is one clean concerted step** (hydride + proton, two different H's)
  — validated for glucose↔fructose and xylulose↔xylose.
- Prefer the **aldose dehydration cascade** (glucose→HMF, xylose→furfural) as the furanic route;
  it needs no catalytic water. Ketoses funnel in via one isomerization.

## Per-kind TS-guess ladder
| reaction kind | method | driving coordinate(s) |
|---|---|---|
| dehydration / aromatization | constrained scan (dual for aromatization) | break C–O (+ transfer β-H to the leaving OH) |
| keto↔enol tautomerization | **dry** `dry_proton_guess.py` (see note) | form C–H from the enol O–H proton (O→C 1,3-shift) |
| retro-aldol C–C cleavage | dual scan | stretch Cα–Cβ + drive β-OH proton to the carbonyl O |
| ring close / open (hemiketal) | anomeric dual scan | C···O(ring) + proton to/from carbonyl O |
| aldose↔ketose isomerization | **2D scan** `scan2d.py` | form hydride C→C *and* form proton O→O (two H's) |

`dry_proton_guess.py` is automatic: it atom-maps reactant to product and locates the migrating H.
`proton_scan.py` is the hand-indexed DFT scan; it produced the deposited tautomerizations and remains
suitable for one-off work.

Then, per candidate: rank guesses by GFN2 energy (highest = most TS-like) and DFT-validate the top few.

## OptTS + cleanup recipe (guesses drift; expect to iterate)
1. OptTS from the scan peak with `TS_Active_Atoms {reactive atoms}`. It **often drifts to a soft
   mode** (single imag ≈ −40..−250, wrong saddle).
2. Fix: build **interpolated guesses** between the scan peak `p_k` and the next point `p_{k+1}`
   (proton/H roughly midway); try fractions f≈0.4/0.5/0.55; the one with a **strong single
   imaginary** (matching the expected mode, e.g. −1500..−2100 for proton transfer) is the TS.
3. **Confirm chemistry first**: run IRC and check endpoints *before* polishing — a strong-imaginary
   TS can still connect the wrong species (zwitterion) → the mechanism is wrong.
4. **Soft-mode cleanup** for a residual small negative: parse the soft normal mode from `ts.hess`,
   displace geometry ±0.7·mode, re-OptTS. For a tiny residual (≈ −4..−50) use **VeryTightSCF +
   `Recalc_Hess 3` + tight `TolE/TolG/TolD`** to push it positive → exactly one imaginary.
5. IRC from the clean single-imaginary TS at DEFGRID3; re-check strict endpoints.

## Workflow for one step
Copy this checklist and track progress:
```
- [ ] pick reaction kind → guess method from the ladder
- [ ] guess: dry_proton_guess.py (proton transfer) / constrained scan (dehydration) / scan2d.py (2 H's)
      — or a hand-indexed DFT relaxed scan (`proton_scan.py`) → locate the peak
- [ ] OptTS from peak, then interpolated guesses if it drifts
- [ ] IRC → confirm endpoints are the intended neutral species (no zwitterion, no phantom water)
- [ ] soft-mode cleanup → exactly one imaginary; DEFGRID3 IRC from the clean TS
- [ ] Gate: `scripts/check_strict_bar.py` reports PASS (see below) — do not proceed on a FAIL
```

## Bundled script (execute it; don't re-derive the checks by hand)
**`scripts/check_strict_bar.py`** — verifies clauses 1-4 against the actual ORCA output and the
raw IRC endpoint geometries. Two modes, matching the policy that the bar governs new work and does
not reopen accepted deposits:
```bash
# gate a new edge (pass/fail; exit 1 on failure)
python scripts/check_strict_bar.py --ts ts.out --irc-f irc_IRC_F.xyz --irc-b irc_IRC_B.xyz \
       --reactant "<neutral SMILES>" --product "<neutral SMILES>"

# provenance record for an existing deposit (reports, never re-judges; always exit 0)
python scripts/check_strict_bar.py --deposit /path/to/glucose_ff_review_v1
```
It prints per-step imaginary modes, the as-built integration grid, and ok/FAIL per clause for
single-imaginary, endpoint identity and "no spectator water on both ends". Run it as the final
gate of every new step, and after assembling any deposit. Requires `rdkit` for clauses 3-4
(they are skipped with a note if it is missing). Reference results: `glucose_ff_review_v1`
reports 11/11 with a uniform DEFGRID3.

## External tools (canonical locations — not bundled, they are part of the running pipeline)
- `templates/path-validator-workspace/resources/strict_validate.py` — OptTS+NumFreq+IRC + strict
  endpoint check (`--active-atoms`, `--spectators`). Its `endpoint_matches()` compares the
  multiset of stereo-stripped neutral canonical SMILES of the IRC fragments and forces
  `DetermineBonds(charge=0)`, so charged and zwitterionic endpoints cannot match; use
  `sv.endpoint_matches(xyz,[smi])` for ad-hoc checks. (`EXACT_SMILES_ONLY=1` is the equivalent
  switch in `orca_xtb_workflow.classify_endpoint_match`, not a flag of this script.)
- `.../resources/dry_proton_guess.py` — automatic dry proton-transfer guesses (atom-maps R→P, locates the
  migrating H, GFN2 H→acceptor scan + a concerted donor-H/H-acceptor grid). **Primary method for new
  proton-transfer edges**; it is what replaced the water relay.
- `.../validation/ff_chain/proton_scan.py` — 1D DFT relaxed scan of a forming bond (dry proton shift),
  hand-indexed. Used for the deposited tautomerizations; keep for one-off DFT scans.
- `.../validation/bridge_stepC/iso5b/scan2d.py` — 2D scan of two forming bonds (concerted hydride+proton).
- `.../resources/tools/xyz_to_smiles.py` — perceive SMILES of an xyz (spots zwitterions).
- `.../validation/ff_finalize/{assemble_review_v1,gen_report,cross_consistency}.py` — build the deposit.
- Deposit self-test: `<deposit>/05_docs/build_scripts/self_check.py` (reads only deposited files;
  prints `SINGLE-IMAGINARY n/n · STRICT-IRC n/n · VERDICT PASS`).
- Network/batch: `reaction_network/{build_reaction_network,templates_expand,validate_candidate,auto_loop}.py`.

## Deposit packaging (mirror the accepted layout)
`00_report/` (HTML) · `01_chain_nodes_xyz/` (DEFGRID3 minima) · `02_transition_states_xyz/` ·
`03_irc_endpoints_xyz/` · `04_orca_inp_out_hess/` (TS out/inp/hess + IRC out) · `05_docs/`
(`FINAL_STRICT_CHAIN.md`, `VERIFICATION.json`, `cross_step_consistency.json`,
`energetics_manifest.json`, `build_scripts/`) · `06_final_chain/` (+`MANIFEST.json`) ·
`README_FOR_EXPERT.md`. Always end by running `self_check.py` → must print `VERDICT PASS`.

## Diversity layer (find multiple distinct routes, not one)
`reaction_network/diversity.py` prevents the search collapsing to one route per target
(novelty search + Quality-Diversity/MAP-Elites + a Reasoning-Path-Divergence gate):
- **novelty scoring**: `templates_expand` scores `motif + NOVELTY_WEIGHT*novelty` (novelty =
  1 − max Tanimoto of the product vs already-explored species) → pushes QM into new space.
- **diverse batch selection**: `auto_loop` picks each round via `diversity.select_diverse`
  (greedy quality + λ·min-distance, DPP/farthest-point) instead of top-N by score, so the
  QM budget is not spent on near-duplicate candidates.
- **route QD archive + divergence gate**: `enumerate_routes` keeps only routes that are
  <60% edge-overlap *and* occupy a new behavioral niche (`route_descriptor`: carbon trajectory,
  fragmenting?, via-ketose?, reaction-kind set). Reports `n_distinct_niches` / mean overlap.
Use these knobs to widen coverage and to quantify route diversity (a paper metric).

## Batch exploration (network growth)
Loop `auto_loop.py`: build graph → `templates_expand.py` (enumerate new candidate edges from the
**confirmed** frontier only — single-fragment species that are STRICT/validated endpoints) →
validate top-N in parallel shards → merge → rebuild. Favor small / retro-aldol / proven-motif
candidates; cap per-guess DFT wall-clock.

**Measured yield of the automated layer: 2 STRICT out of 115 attempts dispatched at DFT.** (Not to be
confused with the xTB-era figure of 118 edges screened in `ts-validation-strategy` — that one is about
the acceptance policy, this one about the guess ladder.) By reaction kind:
dehydration 1/57, keto→enol 0/27, ring closure 0/22, ring opening 1/5, retro-aldol 0/4. Two distinct
causes, and they call for different responses:
- At `cap=1` the top-GFN2 guess is typically a clean TS with the **wrong** IRC endpoints — the guess from
  the reaction-appropriate method ranks lower and never gets validated. Use `cap≥3`.
- The 0/27 on keto→enol was a dispatcher defect, not chemistry: tautomerization was routed only through
  `water_relay_guess.py`, whose both-end spectator water cannot clear the bar. Fixed by putting
  `dry_proton_guess.py` first. Read a 0/N as a bug hypothesis before a chemical conclusion.

The three accepted deposits were built by reaction-specific methods, not by this loop; its value is
network growth and triage, and those numbers are the honest measure of what it does on its own.
See `reference.md` for cost/yield and the operational (process-group) lessons.

## Full details, exact commands, case studies
See [reference.md](reference.md): per-method ORCA templates, the FF enediol→xylulose→xylose fix
(zwitterion case study), soft-mode/VeryTight snippets, the three deposits' validated edge tables,
and the process-management lessons.
