---
name: qm-execution
description: >-
  v0 QM execution plumbing for chem-genesis: cache lookup, step workdir layout,
  driving tools/workflow/run_qm_step.py (xTB OptTS → DFT OptTS+NumFreq → IRC),
  and reading the verdict. Contains no reaction-kind guess ladders and no Key Lessons.
---

# QM execution (v0)

Mechanics only. Acceptance is `policy/acceptance/STRICT.md` (v5) via
`scripts/validate/verdict_writer.py`. This skill does **not** tell you which
guess coordinate to try.

## Pipeline

1. **Cache first.** Before spending DFT, look for an existing key
   `reactant>>product` in `graph/caches/**/strict_cache.json` and under the step
   workdir. If status is already `STRICT` or `rejected` with a final detail,
   reuse it — do not re-run ORCA unless `--force`.
2. **Build the step directory** under `runs/validation/<step_id>/`:
   - `R.xyz` / `P.xyz` (from `tools/geometry/smi_to_xyz.py` if needed)
   - `reaction_mapping.json` (`tools/geometry/map_reaction_atoms.py`)
   - `record.json` (managed by `tools/record_update.py` + `loop/skill_runner.py`)
   - guess xyz files under `round_N/`
3. **Drive QM** with the floor driver (xTB polish, then DFT):

```bash
$CHEM_PY tools/workflow/run_qm_step.py \
  --name <step_id> \
  --guess <guess.xyz> \
  --reactant "<SMI_R>" \
  --product "<SMI_P>" \
  [--coproduct O] \
  --workdir runs/validation/<step_id> \
  --nprocs 16
```

Floor method ladder (human-set starting point, not a rediscovered lesson):

1. ORCA/xTB `OptTS` on the guess (cheap geometry polish; on failure, fall back to the raw guess)
2. r2SCAN-3c/CPCM `OptTS + NumFreq` (uses the xTB hessian when available)
3. r2SCAN-3c/CPCM `IRC` → `verdict_writer` / STRICT v5

4. **Read the result JSON** printed by the driver / written into
   `strict_cache.json`. Status ∈ `{STRICT, evidence_ok, rejected, unresolved}`.
   Look at `xtb_preopt` (`ok` | `failed_fallback_to_raw_guess`) when diagnosing cost.

## Toolchain

| Tool | Default path |
|------|----------------|
| ORCA 6.1.1 | `$ORCA_DIR` / `/root/orca_6_1_1_linux_x86-64_shared_openmpi418_nodmrg` |
| xTB (via ORCA `%xtb`) | bundled with ORCA; standalone `$XTB_BIN` also present |
| Python | `$CHEM_PYTHON` / harness env |

## What this skill deliberately omits

- Per-`reaction_kind` guess ladders (dry proton / water relay / scan2d / NEB)
- Soft-mode cleanup recipes and frequency early-out windows
- Motif-specific Key Lessons

Those may appear later only via Reflect + `evolution/` snapshots.
