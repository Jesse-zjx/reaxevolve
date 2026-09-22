#!/usr/bin/env python3
"""The guess generators must be able to reach the tools they depend on.

This exists because of a failure that produced no error. Every generator in the ladder looked
for the atom mapper under `tools/resources/tools/`, the retired workspace layout. The mapper
call is wrapped in `except Exception -> print WARNING`, so nothing raised: each generator
silently fell back to an element-grouped nearest-neighbour map and carried on producing guesses
built on a degraded mapping — in the asset set the comparison's final arm depends on.

A reachability check is cheap and catches the whole class. Checks:
  1. each generator imports
  2. every module-level path constant pointing into the repository resolves
  3. the atom mapper actually runs and returns a mapping
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile

PKG = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GUESS = os.path.join(PKG, "tools", "guess")
PY = sys.executable

FAILS: list[str] = []


def ok(msg):
    print(f"  OK  {msg}")


def fail(msg):
    print(f" FAIL {msg}")
    FAILS.append(msg)


# Hand-run scripts that parse sys.argv at import time. They are not importable modules and are
# not part of the automated ladder; `ladder.py` selects among the generators below.
NOT_IMPORTABLE = {"proton_scan.py", "scan2d.py"}


def generators() -> list[str]:
    return sorted(
        f for f in os.listdir(GUESS)
        if f.endswith(".py") and not f.startswith("_") and f not in NOT_IMPORTABLE
    )


def main() -> int:
    print("== 1. generators import ==")
    sys.path[:0] = [GUESS, os.path.join(PKG, "tools", "geometry"),
                    os.path.join(PKG, "scripts", "lib")]
    for fn in generators():
        name = fn[:-3]
        try:
            spec = importlib.util.spec_from_file_location(name, os.path.join(GUESS, fn))
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
            ok(fn)
        except Exception as e:
            fail(f"{fn}: {type(e).__name__}: {e}")

    print("\n== 2. no generator points at a path that does not exist ==")
    # Catch the retired layout by name as well as by resolution: a path built from a variable
    # can resolve today and still encode the wrong assumption.
    retired = ("resources/tools", 'WS / "resources"', "qm-workspace", "path-validator-workspace")
    for fn in generators():
        src = open(os.path.join(GUESS, fn)).read()
        for pat in retired:
            if pat in src:
                fail(f"{fn} still references the retired layout: {pat!r}")
        for m in re.finditer(r'REPO\s*/\s*"([^"]+)"\s*/\s*"([^"]+)"(?:\s*/\s*"([^"]+)")?', src):
            parts = [p for p in m.groups() if p]
            target = os.path.join(PKG, *parts)
            if not os.path.exists(target):
                fail(f"{fn}: REPO/{'/'.join(parts)} does not exist")
    if not FAILS:
        ok("every repo-relative constant in the ladder resolves")

    print("\n== 3. the atom mapper satisfies the contract its consumer reads ==")
    # The point of asserting the contract and not merely that the mapper runs: the guess ladder
    # wraps the mapper call in `except Exception -> WARNING` and falls back to an element-grouped
    # nearest-neighbour map. A mapper that runs but returns a shape the consumer cannot read
    # therefore degrades every generator with no error anywhere. That is what happened when the
    # ladder from one campaign was paired with the geometry toolkit from another: their
    # `--json-out` contracts differ, one writing the full record and the other a compact subset
    # without `reactant_to_product`.
    R, P = "O=C(CO)C(O)C(O)C(O)CO", "OCC(O)=C(O)C(O)C(O)CO"  # keto -> enol, same heavy formula
    try:
        import auto_guess as AG  # noqa: WPS433
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            xyz = Path(td) / "r.xyz"
            sub = subprocess.run(
                [PY, os.path.join(PKG, "tools", "geometry", "smi_to_xyz.py"), R, str(xyz)],
                capture_output=True, text=True, cwd=PKG,
            )
            if not xyz.is_file():
                fail(f"could not build a probe geometry: {(sub.stderr or sub.stdout)[-200:]}")
            else:
                res = AG.heavy_atom_map(R, P, xyz)
                maps = (res or {}).get("mappings") or []
                if not maps:
                    fail("heavy_atom_map returned no `mappings`: the ladder would silently fall "
                         "back to a nearest-neighbour map")
                else:
                    n = len(maps[0].get("reactant_to_product") or {})
                    if n < 6:
                        fail(f"only {n} heavy-atom pairs for a C6 pair")
                    else:
                        ok(f"heavy_atom_map returned {n} heavy-atom pairs")
    except Exception as e:
        fail(f"heavy_atom_map raised: {type(e).__name__}: {e}")

    print("\n== 4. the initial asset set keeps its own mapper contract ==")
    # The two sets are not interchangeable: the initial set's skills read the compact fields
    # (formed_bonds / broken_bonds), the final set's ladder reads reactant_to_product.
    init = os.path.join(PKG, "assets", "initial", "tools", "geometry", "map_reaction_atoms.py")
    fin = os.path.join(PKG, "assets", "final", "tools", "geometry", "map_reaction_atoms.py")
    if not os.path.isfile(init) or not os.path.isfile(fin):
        fail("one of the asset sets has no mapper")
    else:
        i_compact = "compact_mapping_records" in open(init).read()
        f_compact = "compact_mapping_records" in open(fin).read()
        if not i_compact:
            fail("initial set mapper no longer writes the compact record its skills read")
        elif f_compact:
            fail("final set mapper writes the compact record, which its guess ladder cannot read")
        else:
            ok("initial writes compact, final writes the full record")

    print("\n==== SUMMARY ====")
    if FAILS:
        print(f"{len(FAILS)} failure(s):")
        for f in FAILS:
            print(" -", f)
        return 1
    print("GUESS LADDER REACHABLE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
