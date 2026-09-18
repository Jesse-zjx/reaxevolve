# Deposits

One tree per delivered route. A deposit is an **output**: a self-contained evidence bundle
a reviewer can check without running the loop. Expert confirmation checks the explanation
and the completeness of the materials; it never rewrites an edge verdict and never writes
back into Graph Memory.

| Deposit | Route | Steps | Size |
|---|---|---|---|
| `glucose_hmf_review_v3` | glucose → HMF | 5 | 11 M |
| `glucose_haa_review_v1` | glucose → HAA, short retro-aldol route | 4 | 4.6 M |
| `glucose_haa_review_v2` | glucose → HAA via the furfural trunk (second, independent route) | 6 | 7.6 M |
| `glucose_ff_review_v1` | glucose → furfural | 11 | 13 M |

Two independent routes to HAA is a structural fact about the network, not a novelty claim.

## As-built verification

```bash
python policy/acceptance/check_strict_bar.py --deposit deposits/<name>
```

All 26 steps meet STRICT(v5) clauses 2–4 as-built: exactly one imaginary frequency, raw
IRC endpoints optimising to the exact neutral reactant and product, and atom conservation
under the discrete-water rule. One step in `glucose_haa_review_v1` is a catalytic proton
shuttle (water's hydrogens exchange between the two IRC ends), which clause 4 admits; it
is reported as `shuttle` rather than silently passed.

The checker runs in **as-built** mode: it records what the files contain and does not
re-judge accepted work. `glucose_hmf_review_v3` and `glucose_haa_review_v1` were computed
before DEFGRID3 was adopted throughout and therefore carry a mixed integration grid. That
is why clause 1 requires the grid to be quoted next to every frequency — the checker
prints the as-built grid per step for exactly this reason. A mixed grid is a provenance
fact to disclose, not a failure to hide.

## Known gap

`glucose_haa_review_v2` has no rendered report under `00_report/` — it is the only one of
the four without one. Its report content is `README_FOR_EXPERT.md` plus
`05_docs/FINAL_STRICT_CHAIN.md`, and the primary evidence under `04_orca_inp_out_hess/` is
complete, so the package verifies; what is missing is the convenience rendering.

## Layout (identical in every deposit)

```
00_report/                 report and energetics manifest
01_chain_nodes_xyz/        optimised minima along the chain
02_transition_states_xyz/  TS geometries
03_irc_endpoints_xyz/      raw IRC endpoints, before and after optimisation
04_orca_inp_out_hess/      ORCA inputs, outputs and Hessians (the primary evidence)
05_docs/                   method notes for the reviewer
06_final_chain/            the chained geometries as delivered
README_FOR_EXPERT.md       what to check, and what was corrected after review
```

Geometric continuity is the property that makes a chain a route rather than a set of
steps: the optimised IRC product endpoint of step *i* is the reactant geometry of step
*i+1*, with atoms conserved end to end.
