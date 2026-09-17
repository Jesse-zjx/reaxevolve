# ADR 002 — Single verdict source

## Status
Accepted (2026-08-08)

## Context
`strict_validate.py` used a looser frequency screen and could emit STRICT; `check_strict_bar.py`
enforced the delivery bar. Early-out status strings embedded payloads (`NOT_CLEAN_TS (imag=…)`).

## Decision
- Only **STRICT(v5)** is an acceptance bar. Early-outs are compute throttles and map to
  `{unresolved, rejected}` + `detail` — they never mint STRICT.
- Sole checker: `policy/acceptance/check_strict_bar.py`.
- Sole write entry for status/verdict fields: `scripts/validate/verdict_writer.py`
  (stamps `strict_version` + full `tools/VERSIONS.json` vector).
- Endpoint matching lives in `scripts/validate/endpoint_match.py` only.

## Consequences
INV-WRITE: LLMs and skills must not write `evidence`/`endpoint`/`verdict` fields directly.
Smoke tests assert the writer path and version stamps.
