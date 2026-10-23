#!/usr/bin/env python3
"""run_qm_step.py v0 — stripped QM driver for reaxevolve.

Pipeline (floor method):
  TS guess xyz
    -> ORCA/xTB OptTS          (cheap geometry polish)
    -> r2SCAN-3c OptTS+NumFreq (DFT saddle + frequencies)
    -> r2SCAN-3c IRC
    -> policy/acceptance/check_strict_bar
    -> scripts/validate/verdict_writer

xTB→DFT is the human-set v0 floor, not a rediscovered lesson. Reflect may later
replace or refine this ladder; do not treat the presence of the xTB step as an
evolved finding.

Genesis deliberately omits campaign-evolved early-outs:
  - no FUSED atom-pair floor table
  - no -300 / -200 cm⁻¹ multi-imag early-return window
Those are answers the evolution loop may rediscover.

Early-outs kept (compute / plumbing only): OptTS crash, missing IRC ends.
If the xTB pre-step fails, DFT still runs from the original guess (floor is
"try xTB first", not "require xTB").
STRICT is granted only when check_strict_bar.check_step(...).pass is True.

Usage:
  python tools/workflow/run_qm_step.py --name STEP --guess ts_guess.xyz \\
     --reactant "SMI_R" --product "SMI_P" [--coproduct O] [--charge 0] [--nprocs 16] \\
     [--workdir DIR] [--irc-only] [--ts-xyz ts.xyz --hess ts.hess] [--no-xtb-preopt]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import time

import numpy as np

_here = os.path.dirname(os.path.abspath(__file__))
_pkg = os.path.dirname(os.path.dirname(_here))
sys.path.insert(0, os.path.join(_pkg, "tools"))
sys.path.insert(0, os.path.join(_pkg, "scripts", "lib"))
sys.path.insert(0, os.path.join(_pkg, "scripts", "validate"))

import chem_paths as _CP  # noqa: E402

_CP.bootstrap()
import endpoint_match as _EM  # noqa: E402
import verdict_writer as _VW  # noqa: E402

ORCA = _CP.ORCA_DIR + "/orca"
ENV = _CP.orca_env(
    MPI_ALLOW_RUN_AS_ROOT="1",
    OMPI_ALLOW_RUN_AS_ROOT_CONFIRM="1",
)


def read_xyz(p):
    L = open(p).read().splitlines()
    n = int(L[0].split()[0])
    sym = [ln.split()[0] for ln in L[2 : 2 + n]]
    xyz = np.array([[float(v) for v in ln.split()[1:4]] for ln in L[2 : 2 + n]])
    return sym, xyz


def run(inp, out):
    with open(out, "w") as f:
        subprocess.run([ORCA, inp], stdout=f, stderr=subprocess.STDOUT, env=ENV)


def clean():
    for pat in (
        "*.gbw",
        "*.densities*",
        "*.tmp",
        "*.tmp.*",
        "*.bas?",
        "*.cpcm",
        "*.cpcm_corr",
        "*.hostnames",
        "*.bibtex",
        "*.carthess",
        "*.inthess.tmp",
        "*.citations.tmp",
    ):
        for f in glob.glob(pat):
            try:
                os.remove(f)
            except OSError:
                pass


def terminated_ok(out):
    return os.path.exists(out) and "ORCA TERMINATED NORMALLY" in open(out).read()


def _final_imag_values(out):
    txt = open(out).read()
    idx = txt.rfind("VIBRATIONAL FREQUENCIES")
    if idx < 0:
        return []
    vals = []
    for ln in txt[idx:].splitlines():
        if "***imaginary mode***" in ln:
            try:
                vals.append(float(ln.split()[1]))
            except (ValueError, IndexError):
                pass
    return sorted(vals)


def _save(res, status=None, detail=None):
    key = f"{res['reactant']}>>{res['product']}"
    st = status if status is not None else res.get("status") or "unresolved"
    # Hash the guess this attempt started from, so the record identifies the job and not just
    # the edge: two attempts on one edge differ precisely in their starting geometry.
    inputs = [p for p in (res.get("guess_path"), res.get("xtb_xyz")) if p and os.path.isfile(p)]
    written = _VW.write_strict_cache(
        "strict_cache.json", key, res, st, detail, input_paths=inputs
    )
    res.clear()
    res.update(written)


def xtb_preopt(name: str, guess: str, charge: int, mult: int, nprocs: int, aa: str) -> str | None:
    """Run ORCA/xTB OptTS. Return polished xyz path, or None on failure."""
    inp = f"{name}_xtb_ts.inp"
    out = f"{name}_xtb_ts.out"
    xyz = f"{name}_xtb_ts.xyz"
    with open(inp, "w") as f:
        f.write(
            "! XTB OptTS TightOpt\n"
            f"%pal nprocs {nprocs} end\n"
            f"%xtb NPROCS {nprocs} end\n"
            "%geom Calc_Hess true Recalc_Hess 5 MaxIter 200\n"
            f"{aa}end\n"
            f"* xyzfile {charge} {mult} {guess}\n"
        )
    run(inp, out)
    if terminated_ok(out) and os.path.isfile(xyz):
        return xyz
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--name", required=True)
    ap.add_argument("--guess")
    ap.add_argument("--reactant", required=True)
    ap.add_argument("--product", required=True)
    ap.add_argument("--coproduct", default=None)
    ap.add_argument("--spectators", default=None)
    ap.add_argument("--charge", type=int, default=0)
    ap.add_argument("--mult", type=int, default=1)
    ap.add_argument("--nprocs", type=int, default=16)
    ap.add_argument("--workdir", default=".")
    ap.add_argument("--ts-xyz")
    ap.add_argument("--hess")
    ap.add_argument("--irc-only", action="store_true")
    ap.add_argument("--active-atoms", default=None)
    ap.add_argument("--ts-mode-bond", default=None)
    ap.add_argument(
        "--no-xtb-preopt",
        action="store_true",
        help="skip the floor xTB OptTS step (DFT from the raw guess)",
    )
    a = ap.parse_args()
    os.chdir(a.workdir)
    res = {
        "name": a.name,
        "reactant": a.reactant,
        "product": a.product,
        "coproduct": a.coproduct,
        "charge": a.charge,
        "ts_imag_cm-1": None,
        "status": None,
        "endpoint_match": None,
        "time": time.strftime("%Y-%m-%d %H:%M"),
        "driver": "run_qm_step.v0",
        "method_ladder": "xtb_optts -> r2SCAN-3c_optts_numfreq -> r2SCAN-3c_irc",
    }

    ts_xyz = a.ts_xyz
    if not a.irc_only:
        aa = ""
        if a.active_atoms:
            idxs = a.active_atoms.replace(",", " ").split()
            aa = f"  TS_Active_Atoms {{{' '.join(idxs)}}} end\n  TS_Active_Atoms_Factor 1.5\n"
        if a.ts_mode_bond:
            i, j = a.ts_mode_bond.replace(",", " ").split()
            aa += f"  TS_Mode {{B {i} {j}}} end\n"

        dft_guess = a.guess
        xtb_ok = False
        if not a.no_xtb_preopt and a.guess:
            polished = xtb_preopt(a.name, a.guess, a.charge, a.mult, a.nprocs, aa)
            if polished:
                dft_guess = polished
                xtb_ok = True
                res["xtb_preopt"] = "ok"
                res["xtb_xyz"] = polished
            else:
                res["xtb_preopt"] = "failed_fallback_to_raw_guess"
            clean()  # drop xTB scratch before the DFT job

        # Prefer an xTB hessian when the pre-step succeeded; otherwise compute at DFT.
        hess_block = "  Calc_Hess true\n"
        xtb_hess = f"{a.name}_xtb_ts.hess"
        if xtb_ok and os.path.isfile(xtb_hess):
            hess_block = f'  Calc_Hess false\n  InHessName "{xtb_hess}"\n'

        with open(f"{a.name}_ts.inp", "w") as f:
            f.write(
                "! r2SCAN-3c OptTS NumFreq TightSCF DEFGRID3 CPCM(water)\n"
                "%geom\n"
                f"{hess_block}"
                "  Recalc_Hess 5\n"
                "  MaxIter 120\n"
                f"{aa}end\n"
                f"%maxcore 4000\n%pal nprocs {a.nprocs} end\n"
                f"* xyzfile {a.charge} {a.mult} {dft_guess}\n"
            )
        run(f"{a.name}_ts.inp", f"{a.name}_ts.out")
        if not terminated_ok(f"{a.name}_ts.out"):
            clean()
            _save(res, "unresolved", "TS_FAILED")
            print(json.dumps(res, indent=2))
            return
        vals = _final_imag_values(f"{a.name}_ts.out")
        res["ts_imag_cm-1"] = min(vals) if vals else None
        res["ts_imag_all"] = vals
        # v0: do NOT early-out on multi-imag / soft-mode windows; continue to IRC
        # and let policy/acceptance decide. Record imags for Reflect.
        ts_xyz = f"{a.name}_ts.xyz"
        a.hess = f"{a.name}_ts.hess"
        # v0: no FUSED geometry reject table

    with open(f"{a.name}_irc.inp", "w") as f:
        f.write(
            "! r2SCAN-3c IRC TightSCF CPCM(water)\n"
            f'%irc MaxIter 100 InitHess read Hess_Filename "{a.hess}" end\n'
            f"%maxcore 4000\n%pal nprocs {a.nprocs} end\n"
            f"* xyzfile {a.charge} {a.mult} {ts_xyz}\n"
        )
    run(f"{a.name}_irc.inp", f"{a.name}_irc.out")
    fpath, bpath = f"{a.name}_irc_IRC_F.xyz", f"{a.name}_irc_IRC_B.xyz"
    if not (os.path.exists(fpath) and os.path.exists(bpath)):
        clean()
        _save(res, "unresolved", "IRC_FAILED")
        print(json.dumps(res, indent=2))
        return

    cls = _EM.classify_double_ended(
        fpath,
        bpath,
        a.reactant,
        a.product,
        a.coproduct,
        spectators=(a.spectators.split(",") if a.spectators else None),
    )
    res["endpoint_match"] = cls["endpoint_match"]

    adj = _VW.adjudicate_with_policy(
        f"{a.name}_ts.out",
        fpath,
        bpath,
        a.reactant,
        a.product,
        name=a.name,
        coproduct=a.coproduct,
    )
    res["water_detail"] = adj.get("water_detail")
    res["policy_pass"] = adj.get("pass")
    clean()
    _save(res, adj["status"], adj.get("detail"))
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
