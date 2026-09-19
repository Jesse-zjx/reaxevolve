# Archived: Negative control A (spectator-water / water-relay)

Moved out of `evidence/controls.md` during the STRICT(v5) refactor.

**Why archived:** the six `force_water` rows recorded `imag_got: None / imag_all: None / n_imag: None`
— they never located a TS, so the water clause was never triggered. They are not
bar-discriminating evidence under v4 or v5.

**Gap after removal:** the main controls note no longer has a bar-resolution negative.
Preferred cheap replacement: the optional linear-interpolation / naive-guess control
already sketched in `controls.md` (re-run one deposit step from linear R–P interpolation).

---
## Negative control A — spectator-water / water-relay under the current dry bar

**Definition:** force the water-relay guess path (`force_water: true`) on steps that are dry
in the deposits (or the one deposited water shuttle), then judge with the **current** bar
(no spectator H₂O on both IRC ends).

Expected: **no new STRICT edge** (bar must refuse provenance-free catalytic water).

Source: `experiments/repro_v1/jobs_water.json` + `results/*` with `force_water: true`
(launcher: `start_water_control.sh`).

| id | step | wall_s | NPROCS × wall | status under current pipeline |
|---|---|---|---|---|
| HAA_s4 | glycolaldehyde-enol → HAA (deposited water shuttle) | 2610.9 | 4 × 2610.9 s ≈ 2.9 CPU-h | `no_strict` |
| HMF_s2 | HMF tautomerization | 27466.4 | 4 × 27466.4 s ≈ 30.5 CPU-h | `no_strict` |
| FF_s8 | FF tautomerization | 12563.1 | 4 × 12563.1 s ≈ 14.0 CPU-h | `PARTIAL_MATCH` (not STRICT) |
| FF_s2 | FF enolization | 42641.1 | 4 × 42641.1 s ≈ 47.4 CPU-h | `no_strict` |
| FF_s3 | FF ketonization | 38836.1 | 4 × 38836.1 s ≈ 43.2 CPU-h | `no_strict` |
| FF_s5 | FF enediol→ketose | 30592.1 | 4 × 30592.1 s ≈ 34.0 CPU-h | `no_strict` |

**Read as:** under the current dry protocol the water-relay path does **not** mint new STRICT
edges, including on HAA s4 (the step that was accepted only under protocol v3 — see
`BAR_HISTORY.md`). That is bar-discriminating evidence, not a capability failure.

