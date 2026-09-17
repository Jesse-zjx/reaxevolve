---
name: qm-reaction-validation
description: >-
  Mechanics only — how to drive the ORCA+xTB scripts for a TS search: cache
  lookup, step-directory setup, guess generation, running the workflow, reading
  results. Does NOT define the acceptance bar; skill pathway-method
  is authoritative, and an xTB-only pass is a guess pre-filter, never a
  validated edge. Use when actually invoking the ORCA/xTB scripts or wiring up a
  step directory, not when deciding whether a step passes.
---

# QM Reaction Validation with ORCA+xTB

> Scope: this is the xTB-era mechanics skill (how to drive the ORCA/xTB scripts). It does not define
> the acceptance bar. The authoritative bar is skill `pathway-method`: DFT throughout
> (`r2SCAN-3c/CPCM(water)` + DEFGRID3), exactly one imaginary mode, raw IRC endpoints exactly the
> neutral reactant/product, chained + atom-conserving, and NO catalytic/spectator water. An xTB-only
> pass (`--n-jobs 4 --nprocs-per-job 1` below) is a pre-filter for guesses, never a validated edge.

> Acceptance clauses: `policy/acceptance/STRICT.md` (v5). This skill does not redefine them.

## Quick Start

### 1. Check the caches first — never recompute an edge

Current caches, keyed `R_SMI>>P_SMI` (RDKit-canonical):
```bash
# every strict_validate run writes one of these next to its workdir
rg -l strict_cache.json
# the dispatcher's record of every attempt, so failed candidates are not retried
reaction_network/dispatch_cache.json
# endpoints harvested from mismatched IRCs (candidate edges in their own right)
reaction_network/discovered_cache.json
```
A hit with `status: STRICT` is a validated edge; reuse it. A hit with any other status means the
edge was already attempted — read *why* before spending DFT on it again.

> `templates/yarp-workspace/resources/qm_validation_cache.json` is the campaign-era cache. It is
> read-only history now: `build_reaction_network.py` still merges its edges into the network, but new
> results do not go there. Don't write to it.

### 2. Determine reaction kind, then take the guess method from the authoritative ladder

The atom difference tells you the reaction class; the guess method for that class is defined by skill
`pathway-method` ("Per-kind TS-guess ladder"), not here. Current mapping, restated only so
the invocations below make sense:

| Atom diff (R−P) | Kind | Guess method | Script |
|------------------|------|--------------|--------|
| 0 | proton transfer (tautomerization / enolization) | dry proton scan | `resources/dry_proton_guess.py` |
| 0 | aldose↔ketose isomerization | 2D concerted hydride + proton scan | `validation/bridge_stepC/iso5b/scan2d.py` |
| 0 | other isomerization | interpolation between mapped geometries | `resources/auto_guess.py` |
| 3 | dehydration (−H₂O) | dual constrained scan (C–O + β-H) | `resources/constrained_scan_guess.py` |

`resources/neb_guess.py` also exists and is what the xTB-era workflow used. NEB highest-image guesses
are unreliable for floppy polyol systems (they collapse to multi-imaginary or zwitterionic endpoints),
so treat NEB as a last resort behind the scan-based methods above.

### 3. Set up step directory

```bash
STEP_DIR=validation/<name>
mkdir -p $STEP_DIR
# Write yarp_route.json with reactant_smiles, product_main_smiles, product_balanced_smiles, reaction_kind
# Generate reactant.xyz: python resources/smi_to_xyz.py "SMILES" $STEP_DIR/reactant.xyz
```

`yarp_route.json` is the filename the guess generators and `validate_candidate.py` still read; it is a
naming leftover, not a dependency on YARP enumeration.

### 4. Generate TS guesses and run ORCA

```bash
cd templates/path-validator-workspace
# For dehydration:
python resources/constrained_scan_guess.py --step-dir $STEP_DIR --round 0 --n-guesses 9
# For isomerization:
python resources/auto_guess.py --step-dir $STEP_DIR --round 0 --n-guesses 9

# Run ORCA workflow (xTB-only, strict endpoint matching):
python resources/orca_xtb_workflow.py \
  --input $STEP_DIR/auto_guess_manifest.round_0.json \
  --output $STEP_DIR/orca_workflow_output.round_0.json \
  --orca-cmd /root/orca_6_1_1_linux_x86-64_shared_openmpi418_nodmrg/orca \
  --n-jobs 4 --nprocs-per-job 1

# Run ORCA workflow with DFT IRC (Plan B hybrid — recommended):
python resources/orca_xtb_workflow.py \
  --input $STEP_DIR/auto_guess_manifest.round_0.json \
  --output $STEP_DIR/orca_workflow_output.round_0.json \
  --orca-cmd /root/orca_6_1_1_linux_x86-64_shared_openmpi418_nodmrg/orca \
  --n-jobs 2 --nprocs-per-job 4 --irc-method r2SCAN-3c
```

### 5. Interpret results

- `status: success` + `endpoint_match_kind: strict` = both IRC endpoints match. **Only accepted result.**
- `status: failure` + `endpoint_match_kind: product_match` = product matches but reactant does not. **NOT accepted.** IRC failed to trace back to reactant. Re-validate with DFT IRC (`--irc-method r2SCAN-3c`).
- `status: failure` + `endpoint_match_kind: mismatch` = wrong product. The saddle is still real chemistry: record `actual_products_found` and re-validate with that pair as the declared endpoints.

### 6. Update cache and clean up

`strict_validate.py` writes its own `strict_cache.json`; when driving it through the dispatcher, the
attempt is also recorded in `dispatch_cache.json`. Remove `.gbw`, `.densities`, `.tmp` files after each
run — they dominate the disk footprint.

## Key Lessons

- **β-H distance > 2.5 Å** in constrained scan → xTB finds an alternative rearrangement instead of the
  dehydration. Re-pick the β-H (or the leaving OH) rather than pushing the scan further.
- **Linear interpolation fails for dehydrations** — atom count mismatch.
- **C₆H₈O₄ → C₆H₆O₃ (3rd dehydration)**: xTB systematically struggles with this step. Try multiple C₆H₈O₄ isomers.
- **IRC actual products** from failed validations are valuable — `harvest_endpoints()` writes them
  into `discovered_cache.json` and they become candidate edges in their own right. (They used to be
  fed back as YARP seeds; that loop is retired.)

## Automated Loop

Batch validation is driven by `reaction_network/auto_loop.py`, which dispatches each
candidate edge through `validate_candidate.py` and judges it against the strict bar:

```bash
/root/miniforge3/envs/harness/bin/python3 reaction_network/auto_loop.py
```

## Environment

```bash
export PATH="/root/xtb/xtb-dist/bin:$PATH"
export LD_LIBRARY_PATH="/root/orca_6_1_1_linux_x86-64_shared_openmpi418_nodmrg:$LD_LIBRARY_PATH"
PYTHON=/root/miniforge3/envs/harness/bin/python3
ORCA_CMD=/root/orca_6_1_1_linux_x86-64_shared_openmpi418_nodmrg/orca
```
