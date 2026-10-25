#!/usr/bin/env python3
"""The acceptance gate must not pass on missing evidence.

A TS output with one imaginary frequency and no IRC used to set pass=True and
adjudicate to STRICT. That contradicts STRICT.md clauses 3-4. This test pins
the repair; it does not re-judge archived edges.
"""
from __future__ import annotations

import os
import sys

PKG = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PKG, "policy", "acceptance"))
sys.path.insert(0, os.path.join(PKG, "scripts", "validate"))

import check_strict_bar as bar  # noqa: E402
import verdict_writer as vw  # noqa: E402

TS = os.path.join(
    PKG,
    "deposits/glucose_haa_review_v1/04_orca_inp_out_hess/transition_states/step_1_TS.out",
)
IRC_F = os.path.join(PKG, "deposits/glucose_haa_review_v1/03_irc_endpoints_xyz/step_1_IRC_F.xyz")
IRC_B = os.path.join(PKG, "deposits/glucose_haa_review_v1/03_irc_endpoints_xyz/step_1_IRC_B.xyz")


def check(cond, msg):
    if not cond:
        raise SystemExit("FAIL: " + msg)
    print("ok:", msg)


def main():
    if not os.path.isfile(TS):
        raise SystemExit("missing fixture " + TS)

    r = bar.check_step("noirc", TS)
    check(r["single_imag"] is True, "fixture still has one imaginary mode")
    check(r["endpoints_ok"] is None, "no IRC → endpoints not checked")
    check(r["water_ok"] is None, "no IRC → water not checked")
    check(r["pass"] is False, "missing IRC must not pass")
    check(r.get("incomplete") is True, "incomplete flag set")

    adj = vw.adjudicate_with_policy(TS, None, None, "C", "CC", name="noirc")
    check(adj["pass"] is False, "adjudicate does not pass without IRC")
    check(adj["status"] == "unresolved", "missing IRC maps to unresolved, not STRICT")

    # Clause 1 is part of pass when the other clauses are actually checked.
    r2 = bar.check_step("withirc", TS, IRC_F, IRC_B)
    check("level_ok" in r2, "level_ok is computed")
    if r2["endpoints_ok"] is not None and r2["water_ok"] is not None:
        check(
            r2["pass"] == all(
                (
                    r2["level_ok"],
                    r2["single_imag"],
                    r2["endpoints_ok"],
                    r2["water_ok"],
                    r2.get("atoms_ok", True),
                )
            ),
            "pass is the conjunction of clauses 1-4 when evidence is complete",
        )

    check(
        bar.level_ok_from_keywords("! r2SCAN-3c OptTS NumFreq TightSCF CPCM(water)") is True,
        "CPCM(water) satisfies clause 1",
    )
    check(
        bar.level_ok_from_keywords("! r2SCAN-3c OptTS NumFreq TightSCF CPCM(hexane)") is False,
        "CPCM(hexane) does not satisfy clause 1",
    )
    check(
        bar.level_ok_from_keywords("! r2SCAN-3c OptTS NumFreq TightSCF CPCM") is False,
        "bare CPCM does not satisfy clause 1",
    )
    # Real IRC pair of a different reaction, declared as ethanol→ethene.
    r3 = bar.check_step("nor", TS, IRC_F, IRC_B, reactant="CCO", product="C=C")
    check(r3["endpoints_ok"] is False, "two non-reactant ends do not satisfy clause 3")
    check(r3["pass"] is False, "neither-is-reactant cannot be STRICT")

    import tempfile
    from pathlib import Path

    td = Path(tempfile.mkdtemp())
    small = td / "a.xyz"
    big = td / "b.xyz"
    small.write_text("3\n\nO 0 0 0\nH 1 0 0\nH 0 1 0\n")
    big.write_text("5\n\nC 0 0 0\nH 1 0 0\nH 0 1 0\nH 0 0 1\nH -1 0 0\n")
    r4 = bar.check_step("atoms", TS, str(small), str(big), reactant="O", product="C")
    check(r4.get("atoms_ok") is False, "atom count change other than 0/±3 is recorded")
    check(r4["pass"] is False, "atom non-conservation cannot pass STRICT")

    ch2 = td / "ch2.xyz"
    water = td / "water.xyz"
    h2 = td / "h2.xyz"
    ch4 = td / "ch4.xyz"
    ch2o = td / "ch2o.xyz"
    ch2o_w = td / "ch2o_w.xyz"
    ch2.write_text("3\n\nC 0 0 0\nH 1 0 0\nH 0 1 0\n")
    water.write_text("3\n\nO 0 0 0\nH 1 0 0\nH 0 1 0\n")
    h2.write_text("2\n\nH 0 0 0\nH 1 0 0\n")
    ch4.write_text("5\n\nC 0 0 0\nH 1 0 0\nH 0 1 0\nH 0 0 1\nH -1 0 0\n")
    ch2o.write_text("4\n\nC 0 0 0\nO 1.2 0 0\nH -0.5 0.9 0\nH -0.5 -0.9 0\n")
    ch2o_w.write_text(
        "7\n\nC 0 0 0\nO 1.2 0 0\nH -0.5 0.9 0\nH -0.5 -0.9 0\n"
        "O 3 0 0\nH 3.8 0.6 0\nH 3.8 -0.6 0\n"
    )
    r5 = bar.check_step("swap", TS, str(ch2), str(water), reactant="C", product="O")
    check(r5.get("atoms_ok") is False, "same atom count with a C/O swap is not conserved")
    r6 = bar.check_step("plus3", TS, str(h2), str(ch4), reactant="[H][H]", product="C")
    check(r6.get("atoms_ok") is False, "+3 atoms that are not water cannot pass")
    check(
        bar.element_conserved(
            bar.read_xyz_atoms(str(ch2o)),
            bar.read_xyz_atoms(str(ch2o_w)),
        )
        is True,
        "+3 with a water fragment in the xyz is allowed",
    )
    etoh = td / "etoh.xyz"
    ethene = td / "ethene.xyz"
    etoh.write_text(
        "9\n\nC 0 0 0\nC 1.5 0 0\nO 2.3 1.1 0\n"
        "H -0.4 0.9 0\nH -0.4 -0.5 0.8\nH -0.4 -0.5 -0.8\n"
        "H 1.9 -0.9 0.5\nH 1.9 -0.9 -0.5\nH 3.1 0.9 0\n"
    )
    ethene.write_text(
        "6\n\nC 0 0 0\nC 1.3 0 0\nH -0.5 0.9 0\nH -0.5 -0.9 0\nH 1.8 0.9 0\nH 1.8 -0.9 0\n"
    )
    r7 = bar.check_step("ghostw", TS, str(etoh), str(ethene), reactant="CCO", product="C=C")
    check(r7.get("atoms_ok") is False, "±H2O delta without water coproduct or fragment fails")
    check(
        bar.element_conserved(
            bar.read_xyz_atoms(str(etoh)),
            bar.read_xyz_atoms(str(ethene)),
            coproduct="O",
        )
        is True,
        "declared water coproduct makes the ±H2O delta real",
    )

    print("all gate checks passed")


if __name__ == "__main__":
    main()
