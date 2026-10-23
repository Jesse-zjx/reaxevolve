# Strict Pathway Validation — reference

Env for ORCA/xtb:
```bash
export PATH=/root/xtb/xtb-dist/bin:/root/orca_6_1_1_linux_x86-64_shared_openmpi418_nodmrg:$PATH
export LD_LIBRARY_PATH=/root/orca_6_1_1_linux_x86-64_shared_openmpi418_nodmrg:$LD_LIBRARY_PATH
PY=/root/miniforge3/envs/harness/bin/python3
```

## ORCA input templates

DFT relaxed scan point (constrained opt; chain geometries point-to-point):
```
! r2SCAN-3c CPCM(water) Opt NoPop DEFGRID3
%geom Constraints { B <a> <b> <d> C } end end
%maxcore 4000
%pal nprocs 8 end
* xyzfile 0 1 s.xyz *
```

OptTS + NumFreq:
```
! r2SCAN-3c OptTS NumFreq TightSCF DEFGRID3 CPCM(water)
%geom Calc_Hess true Recalc_Hess 5 TS_Active_Atoms {<reactive atom idxs, 0-based>} end
      TS_Active_Atoms_Factor 1.5 MaxIter 150 end
%maxcore 4000
%pal nprocs 12 end
* xyzfile 0 1 guess.xyz *
```

IRC from a TS (read its Hessian):
```
! r2SCAN-3c IRC TightSCF DEFGRID3 CPCM(water)
%irc MaxIter 150 InitHess read Hess_Filename "irc.hess" end
%maxcore 4000
%pal nprocs 16 end
* xyzfile 0 1 ts.xyz *
```

VeryTight cleanup (kills tiny residual negative freq, e.g. −4..−50):
```
! r2SCAN-3c OptTS NumFreq VeryTightSCF DEFGRID3 CPCM(water)
%geom Calc_Hess true Recalc_Hess 3 TS_Active_Atoms {...} end TS_Active_Atoms_Factor 2.0
      MaxIter 200 end
%maxcore 4000
%pal nprocs 10 end
* xyzfile 0 1 guess.xyz *
```

Node minimum:
```
! r2SCAN-3c Opt TightSCF DEFGRID3 CPCM(water)
```

## Extract results
```python
import re
t=open("ts.out").read()
b=t[t.rfind("VIBRATIONAL FREQUENCIES"):]
imag=[float(m.group(1)) for m in re.finditer(r"([-\d.]+)\s*cm\*\*-1\s*\*\*\*imaginary",b)]
E=float(re.findall(r"FINAL SINGLE POINT ENERGY\s+(-?\d+\.\d+)",t)[-1])
# IRC converged: "IRC HAS CONVERGED" / "HURRAY" in irc.out; endpoints irc_IRC_F.xyz / irc_IRC_B.xyz
```

## Soft-mode displacement cleanup
Parse the soft (closest-to-zero negative) normal mode from `ts.hess` (`$vibrational_frequencies`,
`$normal_modes`), displace `c ± 0.7*vec`, re-OptTS. If two guesses both give one imaginary, keep
either; prefer the one whose |imag| matches the reactive mode. See
`glucose_ff_review_v1/05_docs/build_scripts/` and `tools/workflow/soft_mode_cleanup.py`.

## PARTIAL_MATCH rescue: read the actual IRC endpoints (do not trust the product guess)
A `PARTIAL_MATCH` with a **strong** imaginary is usually a real, clean edge whose product you
mis-guessed. Perceive the actual IRC-terminus SMILES (`tools/xyz_to_smiles.py`) — if both ends are
neutral closed-shell species, set *those* as reactant/product and re-validate → often STRICT after a
soft-mode cleanup. Example (HAA 2nd route): D-xylulose retro-aldol was scored PARTIAL because the
guess was DHA `OCC(=O)CO`; the real IRC_B was glycolaldehyde `O=CCO` + the C3-**enediol** `OC=C(O)CO`.
Using the true products + cleaning a −50 cm⁻¹ soft mode gave STRICT (−540.8), a distinct HAA route.

## OptTS-from-scan interpolation (drift fix)
```python
# between scan peak p_k and next p_{k+1}, place the migrating atom midway
c=(1-f)*c_peak + f*c_next      # f in {0.40,0.50,0.55}
```
Launch OptTS from each; the correct TS has a strong single imaginary AND an IRC that connects the
intended neutral species.

## Case study — the glucose→FF step-5 fix (why the ketose route)
- Retro-aldol gives the **C5-enediol** `OC=C(O)C(O)C(O)CO`.
- Dry enediol→**xylose** (aldose, terminal C=O): the 1,3-H shift's product optimizes to a
  **zwitterion** `[H][O+]=C(C[O-])...` (H bridges O···C at ~1.9 Å) — NOT neutral xylose. Confirmed
  by DFT. This zwitterion is what tempts you into bolting on a catalytic water; the fix is to change
  the target, not to add the water.
- Dry enediol→**xylulose** (2-ketose, internal C=O) `O=C(CO)C(O)C(O)CO`: clean neutral, single
  imag −1630, strict IRC. (Mirrors HMF's dry step-2 enol→ketone.)
- Then **xylulose→xylose** (ketose→aldose, concerted hydride+proton 2D scan): clean neutral, single
  imag −766 after soft-mode cleanup, strict IRC. Rejoins the validated xylose→furfural cascade.
- Lesson encoded in the rule: terminal enediol → ketose (dry), reach aldose by a separate
  isomerization; never bolt a water onto a retro-aldol (it drifts off the C–C saddle and is
  mechanistically artificial).

## Validated edge tables (the three accepted deposits)
All values r2SCAN-3c/CPCM(water), cm⁻¹, verified against each deposit's TS `.out`. **Grid differs
between deposits** (see clause 1 of `SKILL.md`) — compare frequencies only *within* a deposit.

glucose→HMF (`glucose_hmf_review_v3`, 5 steps; DEFGRID3 on 1/5 — step 4 only, rest DEFGRID2):
dehydration −1410.08 / tautomerization −1449.78 / dehydration −1532.96 / ring-closure −1574.52
(DEFGRID3) / aromatization −830.39. RDS taut ΔE‡≈68.

glucose→HAA (`glucose_haa_review_v1`, 4 steps; DEFGRID3 on 1/4 — step 2 only): glucose→fructose iso
−474.15; →glyceraldehyde retro-aldol −758.07 (DEFGRID3); retro-aldol −942.10; →glycolaldehyde
water-mediated taut. −920.12 (11-atom IRC: the substrate plus one participating H₂O). As-built
note for reproducing this route: step 4 uses the water-mediated tautomerization mechanism, and 3/4
TS calcs use the default grid. Expert-accepted as delivered. The dry enediol→ketose recipe given
in `SKILL.md` is the route to use when building a new tautomerization edge, not a correction to
this one.

glucose→furfural (`glucose_ff_review_v1`, 11 steps, fully HMF-clean, DEFGRID3 on 11/11):
iso −434.65 / enolization −2042.51 / ketonization −2032.48 / retro-aldol −932.28 /
**enediol→xylulose −1629.95** / **xylulose→xylose −766.50** / dehydration −1459.81 / taut −2137.83 /
dehydration −1541.14 / ring-closure −1621.48 / aromatization −872.91.
Overall C6H12O6→furfural+HCHO+3H₂O ΔE≈+17.8 (electronic; entropy-driven). RDS taut ΔE‡≈68.

Cross-deposit check: HAA step 1 and FF step 1 are the same reaction (open-glucose→open-fructose) and
the same saddle geometry (distance-spectrum rms 0.003 Å); the −474.15 vs −434.65 difference is due
entirely to the grid (default vs DEFGRID3). The two deposits are therefore mutually consistent, but a
frequency should always be quoted with its grid.

## Batch exploration cost / yield (measured)
- DFT strict validation of one flexible-sugar step ≈ OptTS+NumFreq+IRC ~ 0.5–2 h at DEFGRID3.
- 8 parallel shards × 4 cores fills 32 cores (`NPROCS=4`). Per-guess wall-clock cap ≈ 70 min.
- Automated strict yield, measured over the whole campaign: **2 STRICT / 115 dispatched attempts**
  (dehydration 1/57, keto→enol 0/27, ring closure 0/22, ring opening 1/5, retro-aldol 0/4). At
  `--cap 1` the top-GFN2 guess is typically a clean TS with the **wrong** IRC endpoints (MISMATCH) — the
  guess from the reaction-appropriate method (dry proton / 2D concerted / targeted anomeric) is ranked
  lower and never gets validated. The keto→enol 0/27 was a dispatcher defect (tautomerization routed
  only through the water relay), not a chemical result.
  Use `--cap 3+` and the cleanup recipe. The hard steps need the per-reaction methods above.
- Frontier hygiene: expand only from **single-fragment, confirmed** species (STRICT/validated/qm_real
  endpoints); failed candidates auto-dedupe (they enter the graph as failed edges).

## Failure modes / anti-patterns (learned the hard way — do NOT repeat)
- **Dry terminal enediol → aldose = zwitterion.** A terminal enediol's dry 1,3-H shift to the
  aldehyde optimizes to `[H][O+]=C(C[O-])...`, never neutral xylose. Route via the KETOSE instead
  (enediol→ketose is clean), then a separate ketose→aldose isomerization. (glucose→FF step-5 fix.)
- **Retro-aldol only works where a carbonyl β-activates the breaking C–C.** 3-ketohexose C3–C4
  cleaves cleanly (ketone-activated, −932, STRICT). But **open-glucose direct C2–C3 retro-aldol is
  NOT a clean elementary step**: all TS guesses (1D peak, 2D, 4 parallel MEP guesses) collapse to a
  saddle whose IRC connects glucose↔glucose (fragments recombine); no neutral concerted fragmenting
  TS. → Don't attempt retro-aldol on an aldose where only the C1 aldehyde is available; first reach a
  ketose/deoxyosone that activates the target C–C.
- **Never bolt a spectator water onto a retro-aldol TS.** Adding a water + OptTS drifts off the C–C
  saddle downhill to the product (loses the reactive mode). Water isn't part of the C–C cleavage.
- **Dehydration needs the β-H co-driven.** A single C–O stretch scan just climbs monotonically
  (heterolytic, no TS peak / no water formed). Use a dual scan (break C–O + form the leaving O–H
  from the β-H) or `constrained_scan_guess` (C–O ± β-H), or the E-elimination won't complete.
- **Don't guess the product SMILES for the auto-validator on hard steps.** SMILES→xyz can build a
  bad geometry → GFN2 ΔE_rxn blows up (e.g. 2573 kcal) → the candidate is falsely pruned. Use
  scan-based discovery (let the IRC reveal the product) for anything non-trivial.
- **cap=1 gives clean-but-wrong-endpoint TSs.** The top-GFN2 guess is often a clean saddle that
  IRCs to the wrong species (MISMATCH); the correct method's guess isn't ranked first. Use cap≥3.
- **strict_validate needs an ABSOLUTE `--workdir`** (it `os.chdir`s internally; a relative path
  fails after chdir).

## Operational notes (process management for long ORCA jobs)
- **Never `pkill -f <pattern>` where the pattern can match the agent's own shell wrapper** — it kills
  the agent's own session. Kill by **process group**: launch long jobs with
  `setsid nohup ...`, record the PGID, and `kill -9 -<PGID>`. ORCA MPI children share the launcher's
  PGID, so a group kill cleans `orca` + `orca_scfresp_mpi` + `mpirun` at once.
- `pgrep -f foo` self-matches the checking command; use `pgrep -cx orca` for exact-name counts.
- When killing a mid-round `auto_loop`, first **merge the shard caches** (`auto_shards/dispatch_*.json`,
  `discovered_*.json`) into the canonical caches so completed work is not lost.
- Long ORCA jobs: launch with `setsid nohup`, poll the `.out`; size waits to the job (OptTS+IRC on
  ~20-atom sugars ≈ 30–60 min each).
