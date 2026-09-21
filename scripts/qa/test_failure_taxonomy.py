#!/usr/bin/env python3
"""The failure classifier and the taxonomy must not drift apart.

`policy/failure_modes.json` is the protected taxonomy every revision record cites.
`scripts/reflect/failure_digest.py::classify` is what assigns a mode to a recorded attempt.
If the classifier can emit a label the taxonomy does not contain, then "the same failure
class" stops being decidable and the transfer analysis loses its sampling frame — quietly,
because nothing errors.

Checks:
  1. every label `classify` can return is in the taxonomy
  2. every chemistry mode in the taxonomy is either reachable from `classify` or explicitly
     assigned elsewhere (the gate and the wall-clock stop)
  3. every failure mode cited in the ledger is in the taxonomy
"""
from __future__ import annotations

import ast
import json
import os
import sys

PKG = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PKG, "scripts", "reflect"))

TAXONOMY = os.path.join(PKG, "policy", "failure_modes.json")
DIGEST = os.path.join(PKG, "scripts", "reflect", "failure_digest.py")
LEDGER = os.path.join(PKG, "evolution", "EVOLUTION_LOG.jsonl")

# Modes assigned by a component other than the classifier, so absent from its return set.
ASSIGNED_ELSEWHERE = {
    "wall_time": "loop/skill_runner.py, on the per-guess wall clock",
    "mass_unbalanced": "scripts/graph/add_hypothesis.py, at the conservation gate",
}

FAILS: list[str] = []


def ok(msg):
    print(f"  OK  {msg}")


def fail(msg):
    print(f" FAIL {msg}")
    FAILS.append(msg)


def classifier_labels() -> set[str]:
    """String literals returned by `classify`, read from the source.

    Read statically rather than by calling it: enumerating every input that reaches every
    branch would be its own fixture problem, and the question here is what the function is
    *able* to return.
    """
    tree = ast.parse(open(DIGEST).read())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "classify":
            out = set()
            for sub in ast.walk(node):
                if isinstance(sub, ast.Return) and isinstance(sub.value, ast.Constant):
                    if isinstance(sub.value.value, str):
                        out.add(sub.value.value)
            return out
    raise SystemExit("classify() not found in failure_digest.py")


def main() -> int:
    tax = json.load(open(TAXONOMY))
    chem = set((tax.get("chemistry") or {}).get("modes") or {})
    proc = set((tax.get("process") or {}).get("modes") or {})
    allowed = chem | proc
    version = tax.get("taxonomy_version")
    print(f"taxonomy {version}: {len(chem)} chemistry + {len(proc)} process modes")

    print("\n== 1. classifier labels are in the taxonomy ==")
    labels = classifier_labels()
    extra = sorted(labels - allowed)
    if extra:
        fail(f"classify() can return label(s) absent from the taxonomy: {extra}")
    else:
        ok(f"all {len(labels)} classifier labels are declared")

    print("\n== 2. taxonomy chemistry modes are reachable ==")
    unreachable = sorted(chem - labels - set(ASSIGNED_ELSEWHERE))
    if unreachable:
        fail(f"declared but nothing assigns them: {unreachable}")
    else:
        ok("every chemistry mode is assigned by the classifier or a named component")
    for mode, where in sorted(ASSIGNED_ELSEWHERE.items()):
        if mode in chem:
            ok(f"{mode}: assigned by {where}")

    print("\n== 3. ledger cites only declared modes ==")
    if not os.path.isfile(LEDGER):
        ok("no ledger yet")
    else:
        bad = {}
        for line in open(LEDGER):
            if not line.strip():
                continue
            rec = json.loads(line)
            modes = rec.get("failure_mode")
            if modes is None:
                continue  # reorganization records carry no failure mode
            if isinstance(modes, str):
                modes = [modes]
            for m in modes:
                if m not in allowed:
                    bad.setdefault(m, []).append(rec.get("seq"))
        if bad:
            for m, seqs in sorted(bad.items()):
                fail(f"undeclared mode {m!r} at seq {seqs[:8]}")
        else:
            ok("every cited mode is declared")

    print("\n==== SUMMARY ====")
    if FAILS:
        print(f"{len(FAILS)} failure(s)")
        return 1
    print("TAXONOMY CONSISTENT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
