#!/usr/bin/env python3
"""An unusable IRC endpoint must be a rejection, never a crash.

`endpoint_matches` already specified the right behaviour — its docstring says endpoints that fail
bond perception are rejected, and the return guards on `None not in got`. The guard was
unreachable: `frag_canon` returns None for a fragment RDKit cannot perceive, and sorting None
against anything raises TypeError, so the function died before deciding.

That is worse than a wrong verdict. In the loop a crash in the validator means the attempt
produces no verdict at all: it neither counts as an accepted edge nor as a rejection, and the
compute spent on it leaves no record to learn from. A naive interpolation guess in the
bar-resolution probe hit exactly this.

The invariant under test is narrow and load-bearing: unperceivable endpoints reject, and
perceivable endpoints decide exactly as they did before.
"""
from __future__ import annotations

import os
import sys

PKG = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PKG, "scripts", "validate"))

FAILS: list[str] = []


def ok(m):
    print(f"  OK  {m}")


def fail(m):
    print(f" FAIL {m}")
    FAILS.append(m)


def main() -> int:
    import endpoint_match as EM

    print("== 1. a fragment RDKit cannot perceive rejects instead of raising ==")
    # Drive the real function with a stubbed perceiver: the point is the None handling, not
    # RDKit's chemistry. Two Nones is the case that crashed; one None crashed too.
    real = EM.frag_canon
    try:
        for n_none, label in ((1, "one"), (2, "two"), (3, "three")):
            calls = {"i": 0}

            def stub(sym, xyz, _n=n_none, _c=calls):
                _c["i"] += 1
                return None if _c["i"] <= _n else "O"

            EM.frag_canon = stub
            frags = EM.atom_fragments
            EM.atom_fragments = lambda s, x, _k=n_none + 1: [(["O"], [(0.0, 0.0, 0.0)])] * _k
            try:
                import tempfile

                with tempfile.NamedTemporaryFile("w", suffix=".xyz", delete=False) as fh:
                    fh.write("1\n\nO 0.0 0.0 0.0\n")
                    path = fh.name
                try:
                    res, got, exp = EM.endpoint_matches(path, ["O"])
                except TypeError as e:
                    fail(f"{label} unperceivable fragment(s) still raises: {e}")
                    continue
                finally:
                    os.unlink(path)
                if res:
                    fail(f"{label} unperceivable fragment(s) was ACCEPTED: got={got}")
                else:
                    ok(f"{label} unperceivable fragment(s) -> rejected, got={got}")
            finally:
                EM.atom_fragments = frags
    finally:
        EM.frag_canon = real

    print("\n== 2. perceivable endpoints decide as before ==")
    real_frag, real_atoms = EM.frag_canon, EM.atom_fragments
    try:
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".xyz", delete=False) as fh:
            fh.write("1\n\nO 0.0 0.0 0.0\n")
            path = fh.name
        try:
            cases = [
                (["O", "CO"], ["O", "CO"], True, "matching multiset accepts"),
                (["O", "CO"], ["O", "O"], False, "different multiset rejects"),
                (["CO", "O"], ["O", "CO"], True, "order does not matter"),
            ]
            for frags, expected, want, label in cases:
                seq = list(frags)
                it = {"i": 0}

                def stub(sym, xyz, _s=seq, _i=it):
                    v = _s[_i["i"] % len(_s)]
                    _i["i"] += 1
                    return v

                EM.frag_canon = stub
                EM.atom_fragments = lambda s, x, _k=len(seq): [(["O"], [(0.0, 0.0, 0.0)])] * _k
                res, got, exp = EM.endpoint_matches(path, expected)
                if bool(res) != want:
                    fail(f"{label}: got {bool(res)}, expected {want} (got={got} exp={exp})")
                else:
                    ok(label)
        finally:
            os.unlink(path)
    finally:
        EM.frag_canon, EM.atom_fragments = real_frag, real_atoms

    print("\n==== SUMMARY ====")
    if FAILS:
        print(f"{len(FAILS)} failure(s):")
        for f in FAILS:
            print(" -", f)
        return 1
    print("ENDPOINT MATCH ROBUST")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
