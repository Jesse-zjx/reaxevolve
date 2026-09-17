# Pre-registered QM protocol

Human-set protocol for deposit-grade and triage QM. Agents may not change this file.

## Theory and solvent

| Stage | Method | Notes |
|-------|--------|-------|
| TS guess | GFN2-xTB (optional) | Never a validated edge by itself |
| OptTS + NumFreq | r2SCAN-3c / CPCM(water) / DEFGRID3 | Deposit-grade |
| IRC | r2SCAN-3c / CPCM(water) / DEFGRID3 | Re-run at DEFGRID3 before deposit promotion |
| Endpoint minima | r2SCAN-3c / CPCM(water) / DEFGRID3 | Before SMILES comparison |

Batch triage may leave IRC on the ORCA default grid for budget reasons; promotion to deposit
requires IRC re-run at DEFGRID3. Quote the as-built grid next to every reported frequency.

## Soft-mode cleanup

If NumFreq shows more than one imaginary mode, run soft-mode cleanup (displace along soft
mode → re-OptTS → NumFreq) before accepting or rejecting. Record cleanup provenance on the
attempt; do not overwrite without provenance.

## Acceptance

All delivery-grade claims use **STRICT(v5)** only — see `policy/acceptance/STRICT.md`.
Early exits in drivers are compute throttles and do not emit status labels.
