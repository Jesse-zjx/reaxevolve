#!/usr/bin/env python3
"""Generate a chemically-reasonable .xyz for a SMILES via RDKit ETKDG +
xTB GFN2 optimization. Used to bootstrap step_0/reactant.xyz for paths
that start at a seed (e.g. fructofuranose) instead of glucose.

Usage:
    python smi_to_xyz.py "<smiles>" out.xyz [--name NAME]
"""
from __future__ import annotations
import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from rdkit import Chem
from rdkit.Chem import AllChem

import sys as _sys, os as _os
_here = _os.path.dirname(_os.path.abspath(__file__))
_pkg = _here
while _pkg != '/':
    if _os.path.isfile(_os.path.join(_pkg, 'tools', 'chem_paths.py')):
        _sys.path.insert(0, _os.path.join(_pkg, 'tools'))
        _sys.path.insert(0, _os.path.join(_pkg, 'scripts', 'lib'))
        break
    if _os.path.isfile(_os.path.join(_pkg, 'chem_paths.py')) and _os.path.basename(_pkg) == 'tools':
        _sys.path.insert(0, _pkg)
        _sys.path.insert(0, _os.path.join(_os.path.dirname(_pkg), 'scripts', 'lib'))
        break
    _pkg = _os.path.dirname(_pkg)
import chem_paths as _CP
_CP.bootstrap()

XTB = _CP.XTB_BIN


def smi_to_3d(smi: str) -> Chem.Mol:
    mol = Chem.MolFromSmiles(smi)
    if mol is None:
        raise ValueError(f"invalid SMILES: {smi}")
    mol = Chem.AddHs(mol)
    # ETKDG embed; if it fails (rare for sugars/furans), random coords fallback
    if AllChem.EmbedMolecule(mol, AllChem.ETKDGv3()) != 0:
        AllChem.EmbedMolecule(mol, useRandomCoords=True)
    AllChem.MMFFOptimizeMolecule(mol, maxIters=400)
    return mol


def mol_to_xyz_block(mol: Chem.Mol, comment: str) -> str:
    """Write XYZ in the project's format: <natoms>\n<n_heavy> <smiles>\n<coords>"""
    coords = mol.GetConformer().GetPositions()
    n = mol.GetNumAtoms()
    n_heavy = sum(1 for a in mol.GetAtoms() if a.GetAtomicNum() > 1)
    lines = [str(n), f"{n_heavy} {comment}"]
    for atom, xyz in zip(mol.GetAtoms(), coords):
        lines.append(f"{atom.GetSymbol():2s} {xyz[0]:>15.9f} {xyz[1]:>15.9f} {xyz[2]:>15.9f}")
    return "\n".join(lines) + "\n"


def xtb_opt(xyz_text: str, name: str = "tmp") -> str:
    """Run xTB GFN2 optimization, return optimized xyz."""
    with tempfile.TemporaryDirectory() as td:
        td_p = Path(td)
        inp = td_p / "inp.xyz"
        inp.write_text(xyz_text)
        env = os.environ.copy()
        env.setdefault("OMP_NUM_THREADS", "2")
        env.setdefault("MKL_NUM_THREADS", "2")
        if not XTB or not os.path.isfile(str(XTB)):
            print("[warn] xtb not available; returning unoptimized xyz", file=sys.stderr)
            return xyz_text
        try:
            subprocess.run(
                [XTB, str(inp), "--gfn", "2", "--opt", "normal", "--namespace", name],
                cwd=td_p, env=env, check=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except (subprocess.CalledProcessError, FileNotFoundError, OSError) as e:
            print(f"[warn] xtb opt failed ({e}); returning unoptimized xyz",
                  file=sys.stderr)
            return xyz_text
        opt = td_p / f"{name}.xtbopt.xyz"
        if not opt.exists():
            opt = td_p / "xtbopt.xyz"
        if not opt.exists():
            print("[warn] no xtbopt.xyz produced; returning unoptimized xyz",
                  file=sys.stderr)
            return xyz_text
        return opt.read_text()


def fix_xyz_header(xyz: str, smi: str) -> str:
    """Replace the comment line with `<n_heavy> <smiles>` matching project convention."""
    lines = xyz.splitlines()
    if len(lines) < 2:
        return xyz
    mol = Chem.MolFromSmiles(smi)
    n_heavy = mol.GetNumHeavyAtoms() if mol else 0
    lines[1] = f"{n_heavy} {smi}"
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("smiles")
    ap.add_argument("out", help="output .xyz path")
    ap.add_argument("--name", default="mol")
    ap.add_argument("--no-xtb", action="store_true",
                    help="skip xTB opt (RDKit-MMFF only)")
    args = ap.parse_args()

    mol = smi_to_3d(args.smiles)
    raw = mol_to_xyz_block(mol, args.smiles)
    if args.no_xtb:
        final = raw
    else:
        opt = xtb_opt(raw, name=args.name)
        final = fix_xyz_header(opt, args.smiles)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(final)
    print(f"[OK] wrote {out}  ({len(final.splitlines())-2} atoms)")


if __name__ == "__main__":
    main()
