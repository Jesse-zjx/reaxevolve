#!/usr/bin/env python3
"""Mass-balance gate for candidate reaction steps.

An elementary step must conserve atoms. A hypothesis whose reactant atom counts do
not match product + coproduct can never pass STRICT: the IRC will not connect the
stated endpoints, so the QM spend is wasted before it starts. Template Explore
conserves atoms by construction (RDKit graph transforms); LLM Explore does not, and
in an earlier campaign roughly half the proposed steps did not balance — including
the terminal step into a target, so the route being pursued ended in a step no IRC
could satisfy.

This enforces a conservation law and fills in the `coproduct` field the hypothesis
schema already defines. It supplies no mechanism and it is not part of acceptance:
`policy/acceptance/STRICT.md` remains the only bar for a verdict.

Deliberately absent: the seed→target stoichiometric ladder used in an earlier
single-target campaign. That filter assumed carbon was conserved along a route, so
with HAA (C2) and furfural (C5) among the targets it would discard every valid
C-C-cleavage intermediate. Progress toward targets is measured instead by
`strict_distance_to_targets` in scripts/graph/build_reaction_network.py.

Verdicts:
  balanced                 atom counts match exactly (coproduct as given)
  balanced_implicit_nH2O   matches once n water molecules are added as coproduct
  unbalanced               cannot be balanced by water alone
  unparseable              RDKit could not read a SMILES

Run standalone for a report:
  python loop/mass_balance.py            # audit graph + candidate queue
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PKG, "scripts", "lib"))
import chem_paths as CP  # noqa: E402

CP.bootstrap()

WATER = "O"
MAX_IMPLICIT_WATER = 1  # more than one water lost is not one elementary step


def _atoms(smiles: str):
    from rdkit import Chem, RDLogger

    RDLogger.DisableLog("rdApp.*")
    m = Chem.MolFromSmiles(smiles or "")
    if m is None:
        return None
    m = Chem.AddHs(m)
    d = defaultdict(int)
    for a in m.GetAtoms():
        d[a.GetSymbol()] += 1
    return d


def check(reactant: str, product: str, coproduct: str | None = None) -> dict:
    """Balance verdict for one step, plus the coproduct needed to close it."""
    cr = _atoms(reactant)
    cp = _atoms(product)
    if cr is None or cp is None:
        return {"verdict": "unparseable", "ok": False, "delta": None, "coproduct": coproduct}

    total = defaultdict(int, cp)
    if coproduct:
        cc = _atoms(coproduct)
        if cc is None:
            return {"verdict": "unparseable", "ok": False, "delta": None, "coproduct": coproduct}
        for k, v in cc.items():
            total[k] += v

    delta = {k: cr.get(k, 0) - total.get(k, 0) for k in set(cr) | set(total)}
    delta = {k: v for k, v in delta.items() if v}
    if not delta:
        return {"verdict": "balanced", "ok": True, "delta": {}, "coproduct": coproduct}

    n = delta.get("O", 0)
    if delta.get("C", 0) == 0 and 1 <= n <= MAX_IMPLICIT_WATER and delta.get("H", 0) == 2 * n:
        co = ".".join([WATER] * n) if not coproduct else f"{coproduct}.{'.'.join([WATER] * n)}"
        return {
            "verdict": f"balanced_implicit_{n}H2O",
            "ok": True,
            "delta": delta,
            "coproduct": co,
        }
    return {"verdict": "unbalanced", "ok": False, "delta": delta, "coproduct": coproduct}


def ok(reactant: str, product: str, coproduct: str | None = None) -> bool:
    return bool(check(reactant, product, coproduct).get("ok"))


def counts(smiles: str) -> dict | None:
    a = _atoms(smiles)
    return dict(a) if a is not None else None


def _render(c: dict) -> str:
    order = ["C", "H", "O"]
    keys = order + sorted(k for k in c if k not in order)
    return "".join(f"{k}{c[k]}" for k in keys if c.get(k))


def formula(smiles: str) -> str | None:
    c = counts(smiles)
    return _render(c) if c else None


def required_product_formula(reactant: str, waters: int = 0) -> str | None:
    """Formula the product must have for a step losing `waters` water molecules.

    The model reliably gets the bond change right and the atom count wrong — its
    "repairs" routinely came back with an extra CH2O. Stating the target formula turns
    the repair into arithmetic it can check itself.
    """
    c = counts(reactant)
    if not c:
        return None
    out = dict(c)
    out["O"] = out.get("O", 0) - waters
    out["H"] = out.get("H", 0) - 2 * waters
    if out.get("O", 0) < 0 or out.get("H", 0) < 0:
        return None
    return _render(out)


def _iter_graph():
    path = os.path.join(CP.GRAPH, "reaction_network.json")
    if not os.path.isfile(path):
        return
    net = json.load(open(path))
    for src, coll in (
        ("edge", (net.get("edges") or {}).values()),
        ("hypothesis", (net.get("hypotheses") or {}).values()),
    ):
        for e in coll:
            if e.get("reactant") and e.get("product"):
                yield src, e


def audit() -> dict:
    by_verdict = Counter()
    by_status = defaultdict(Counter)
    offenders = []
    for src, e in _iter_graph():
        res = check(e.get("reactant"), e.get("product"), e.get("coproduct"))
        by_verdict[res["verdict"]] += 1
        by_status[str(e.get("status"))][res["verdict"]] += 1
        if not res["ok"]:
            offenders.append(
                {
                    "source": src,
                    "status": e.get("status"),
                    "kind": e.get("kind") or e.get("reaction_kind"),
                    "reactant": e.get("reactant"),
                    "product": e.get("product"),
                    "coproduct": e.get("coproduct"),
                    "delta": res["delta"],
                    "verdict": res["verdict"],
                }
            )
    return {
        "by_verdict": dict(by_verdict),
        "by_status": {k: dict(v) for k, v in by_status.items()},
        "n_infeasible": len(offenders),
        "infeasible": offenders,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    rep = audit()
    if a.json:
        print(json.dumps(rep, indent=2, ensure_ascii=False))
        return 0
    print("balance verdicts:", rep["by_verdict"])
    print("\nby status:")
    for st, c in sorted(rep["by_status"].items()):
        print(f"  {st:12} {c}")
    print(f"\ninfeasible (cannot balance): {rep['n_infeasible']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
