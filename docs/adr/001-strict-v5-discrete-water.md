# ADR 001 — STRICT(v5) discrete water clause

## Status
Accepted (2026-08-08)

## Context
v4 rejected any bilateral standalone H₂O on IRC ends (spectator / phantom catalytic water).
HAA step 4 is a true catalytic proton shuttle. Displacement-fraction thresholds at the saddle
are unstable (same edge scored 14.7% or 96.5% depending on fragment assignment).

## Decision
STRICT version **v5**: clauses 1–3 unchanged; clause 4 compares **atom indices** of hydrogens
bonded to the water oxygen on the two IRC ends (ORCA preserves order). Different H indices →
catalytic shuttle (allowed); identical O+H+H identities → spectator (rejected). No displacement
threshold. Water provenance is the chain's declared component; atom conservation is on the
water-including system.

## Consequences
Deposit as-built becomes 20/20. Network re-adjudication may still drop non-deposit STRICT edges
that fail frequency/endpoint clauses on final geometries. Skills point to `policy/acceptance/`
and do not restate clauses.
