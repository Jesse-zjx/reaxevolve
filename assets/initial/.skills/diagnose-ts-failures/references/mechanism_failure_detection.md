# Mechanism failure detection

Companion note for `diagnose-ts-failures` (genesis v0 stub).

## Rule

Treat a **mechanism** as failed (set `if_need_new_mechanism: true` for that branch) when:

1. At least **two** guesses that share the same mechanism hypothesis, and
2. Those guesses had **sane** initial geometries (preserved bonds intact per `inquire`), and
3. Their ORCA outcomes share the **same failure pattern** (same dominant class among:
   OptTS crash, wrong number of imaginary modes, IRC ends mismatching R/P,
   IRC collapse to reactant or product only, mode following the wrong coordinate).

## What this is not

- A single failed guess is not enough — it may be a bad stage (early/middle/late).
- A fused / chemically impossible guess is a **geometry** failure, not a mechanism failure.
- `branch_decision: stop_this_branch` stops that branch only; other mechanisms continue.

## Action

When the rule fires, feedback must tell the generator to abandon that bond-change
pattern and propose a **fundamentally different** formed/broken bond set, not only
tweak distances on the same mechanism.
