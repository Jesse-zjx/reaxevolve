---
name: chain-assembly
description: >-
  v0 chain packaging discipline for reaxevolve: geometric continuity of a
  STRICT path, deposit directory layout, and a five-item preflight checklist.
  Contains no mechanism conclusions and no method ladders.
---

# Chain assembly (v0)

Assemble a glucose → HMF delivery package **only** from edges whose status is
`STRICT` under `policy/acceptance/STRICT.md` v5. Do not invent edges.

## Geometric continuity

For consecutive edges A→B and B→C:

1. Product SMILES of edge *i* (main organic, water stripped) must equal reactant
   SMILES of edge *i+1* after RDKit canonicalization without stereo.
2. Atom ordering in consecutive `*_IRC_*.xyz` / deposit geometries should be
   consistent enough that a human can overlay B without remapping; if not,
   document the remap in the deposit README.
3. Coproducts (e.g. water) are recorded on the edge but do not break the organic
   backbone continuity check.

## Deposit layout

```
deposits/glucose_hmf_genesis_vN/
  README.md                 # path summary, core-hours, asset version vector
  chain.json                # ordered STRICT edges with SMILES + imag + barriers
  steps/
    s1_<tag>/               # per-edge ORCA outs, xyz, hess pointers
    ...
  versions.json             # copy of tools/VERSIONS.json at freeze time
```

## Preflight checklist (5 items)

Before declaring a package complete:

1. [ ] Every edge in `chain.json` has `status: STRICT` from `verdict_writer` with
      `strict_version: v5`.
2. [ ] Organic SMILES continuity holds from glucose seed to HMF target.
3. [ ] Each step directory contains TS out + IRC forward/backward xyz.
4. [ ] `versions.json` matches the attempt-time `tools/VERSIONS.json` vector.
5. [ ] `scripts/qa/isolation_audit.py` has been run for the producing loop and
      shows no out-of-whitelist path hits.

## What this skill deliberately omits

- Motif scoring / which dehydration order is "preferred"
- Method ladders (scan >> NEB, dry PT vs water relay)
- Structure arguments about when CHO must appear

Those conclusions, if rediscovered, belong in Experience Memory + skill
revisions under Reflect — not in this v0 floor.
