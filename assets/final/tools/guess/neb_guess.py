#!/usr/bin/env python3
"""Generate TS guess structures using ORCA NEB-TS with xTB.

Unlike linear interpolation (auto_guess.py), NEB-TS optimizes a chain of images
along the minimum energy path, producing a much higher-quality TS guess —
especially for isomerization reactions where the reaction path is non-linear.

Usage:
    python resources/neb_guess.py --step-dir validation/step_dir
    python resources/neb_guess.py --step-dir validation/step_dir --round 1 --nimages 12
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

WS = Path(__file__).resolve().parents[1]
# Repository root: tools/<group>/<file>.py -> two levels up.
REPO = Path(__file__).resolve().parents[2]
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

PYTHON = sys.executable or _CP.PYBIN
XTB_BIN = shutil.which("xtb") or _CP.XTB_BIN
ORCA_CMD = os.environ.get(
    "ORCA_CMD",
    (_CP.ORCA_DIR + '/orca'),
)

sys.path.insert(0, str(REPO / "tools" / "guess"))
sys.path.insert(0, str(REPO / "tools" / "geometry"))

from auto_guess import (

    read_xyz,
    write_xyz,
    smiles_to_xyz_xtb,
    _element_nearest_neighbor_map,
    reorder_product,
)


def _repo_rel(p) -> str:
    """Path relative to the repository root, or the path itself if it lies outside.

    Reporting a path must not be able to fail: this was `relative_to(WS)`, which assumed QM
    scratch sat under tools/ and raised once it moved to runs/ — discarding guesses that had
    already been built.
    """
    from pathlib import Path as _P
    try:
        return str(_P(p).resolve().relative_to(_P(__file__).resolve().parents[2]))
    except ValueError:
        return str(p)



def render_neb_ts_input(
    charge: int,
    multiplicity: int,
    reactant_ref: str,
    product_ref: str,
    nprocs: int,
    nimages: int = 8,
    free_end: bool = True,
) -> str:
    # Free_End lets the endpoint images relax during the band optimization. It is the safer choice
    # when the endpoints are independently generated, and the wrong one when they are already a
    # matched pair, which is how the deposits ran NEB.
    fe = "  Free_End true\n" if free_end else ""
    return (
        "! NEB-TS XTB2\n\n"
        f"%pal nprocs {nprocs} end\n\n"
        f"%xtb NPROCS {nprocs} end\n\n"
        "%neb\n"
        f"  NImages {nimages}\n"
        f'  Product "{product_ref}"\n'
        f"{fe}"
        "end\n\n"
        f"* xyzfile {charge} {multiplicity} {reactant_ref} *\n"
    )


def run_neb_ts(
    step_dir: Path,
    reactant_xyz: Path,
    product_xyz: Path,
    round_idx: int = 0,
    charge: int = 0,
    multiplicity: int = 1,
    nprocs: int = 4,
    nimages: int = 8,
    timeout: int = 3600,
    free_end: bool = True,
) -> Path | None:
    """Run ORCA NEB-TS and return path to the optimized TS xyz, or None."""
    neb_dir = step_dir / f"round_{round_idx}" / "neb_ts_run"
    neb_dir.mkdir(parents=True, exist_ok=True)

    r_dst = neb_dir / "reactant.xyz"
    p_dst = neb_dir / "product.xyz"
    shutil.copy2(reactant_xyz, r_dst)
    shutil.copy2(product_xyz, p_dst)

    inp_text = render_neb_ts_input(
        charge, multiplicity, "reactant.xyz", "product.xyz", nprocs, nimages, free_end,
    )
    inp_path = neb_dir / "neb_ts.inp"
    inp_path.write_text(inp_text)

    orca_parts = shlex.split(ORCA_CMD)
    if orca_parts and not Path(orca_parts[0]).is_absolute():
        orca_parts[0] = str(Path(orca_parts[0]).resolve())

    out_path = neb_dir / "neb_ts.out"
    print(f"  running ORCA NEB-TS (nprocs={nprocs}, nimages={nimages}, timeout={timeout}s) ...")

    try:
        with out_path.open("w") as fh:
            subprocess.run(
                [*orca_parts, "neb_ts.inp"],
                cwd=neb_dir,
                stdout=fh,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
    except subprocess.TimeoutExpired:
        print(f"  NEB-TS timed out after {timeout}s")

    # Look for the optimized TS
    ts_xyz = neb_dir / "neb_ts.xyz"
    if ts_xyz.exists():
        print(f"  NEB-TS converged → {ts_xyz}")
        return ts_xyz

    # Fallback: extract highest-energy image from trajectory
    for fallback_name in [
        "neb_ts_NEB-CI_converged.xyz",
        "neb_ts_MEP_trj.xyz",
        "neb_ts_NEB_trj.xyz",
    ]:
        trj = neb_dir / fallback_name
        if trj.exists():
            print(f"  TS opt did not converge; extracting highest-energy image from {fallback_name}")
            return _extract_highest_image(trj, neb_dir)

    print("  NEB-TS produced no output")
    return None


def _extract_highest_image(trj_xyz: Path, output_dir: Path) -> Path | None:
    """Extract the highest-energy frame from a multi-frame XYZ trajectory."""
    text = trj_xyz.read_text().strip()
    if not text:
        return None

    lines = text.splitlines()
    frames: list[tuple[float | None, list[str]]] = []
    i = 0
    while i < len(lines):
        try:
            n = int(lines[i].strip())
        except (ValueError, IndexError):
            break
        comment = lines[i + 1] if i + 1 < len(lines) else ""
        frame_lines = lines[i : i + 2 + n]

        energy = None
        for tok in comment.replace(",", " ").split():
            try:
                val = float(tok)
                if energy is None or abs(val) > 1e-3:
                    energy = val
            except ValueError:
                continue
        frames.append((energy, frame_lines))
        i += 2 + n

    if not frames:
        return None

    valid = [(e, f) for e, f in frames if e is not None]
    best = max(valid, key=lambda x: x[0]) if valid else frames[len(frames) // 2]

    out = output_dir / "neb_ts_highest_image.xyz"
    out.write_text("\n".join(best[1]) + "\n")
    e_str = f"{best[0]:.6f}" if best[0] is not None else "unknown"
    print(f"  extracted highest-energy image (E={e_str}) → {out.name}")
    return out


def process_step(
    step_dir: Path,
    round_idx: int = 0,
    nprocs: int = 4,
    nimages: int = 8,
    timeout: int = 3600,
) -> dict:
    """Generate a TS guess via NEB-TS for one step. Returns manifest dict."""
    step_dir = step_dir.resolve()
    reactant_xyz = step_dir / "reactant.xyz"
    route_json = step_dir / "yarp_route.json"

    if not reactant_xyz.exists():
        raise FileNotFoundError(f"Missing {reactant_xyz}")
    if not route_json.exists():
        raise FileNotFoundError(f"Missing {route_json}")

    route = json.loads(route_json.read_text())
    r_smi = route["reactant_smiles"]
    p_balanced_smi = route["product_balanced_smiles"]

    r_syms, r_coords = read_xyz(reactant_xyz)
    n_atoms = len(r_syms)

    product_xyz = step_dir / "product_neb.xyz"
    print(f"  generating product geometry: {p_balanced_smi}")
    smiles_to_xyz_xtb(p_balanced_smi, product_xyz)
    p_syms, p_coords = read_xyz(product_xyz)

    if len(p_syms) != n_atoms:
        raise ValueError(
            f"Atom count mismatch: reactant={n_atoms}, product_balanced={len(p_syms)}. "
            f"Cannot run NEB."
        )

    print(f"  atom-mapping for NEB: {r_smi} → {p_balanced_smi}")
    full_map = _element_nearest_neighbor_map(r_syms, r_coords, p_syms, p_coords)
    p_syms_reord, p_coords_reord = reorder_product(p_syms, p_coords, full_map)

    for i, (rs, ps) in enumerate(zip(r_syms, p_syms_reord)):
        if rs != ps:
            raise ValueError(f"Symbol mismatch at atom {i}: reactant={rs}, product={ps}")

    product_reord_xyz = step_dir / "product_neb_reordered.xyz"
    write_xyz(
        product_reord_xyz, p_syms_reord, p_coords_reord,
        f"Reordered product for NEB: {p_balanced_smi}",
    )

    ts_xyz = run_neb_ts(
        step_dir, reactant_xyz, product_reord_xyz,
        round_idx=round_idx, nprocs=nprocs, nimages=nimages, timeout=timeout,
    )

    if ts_xyz is None:
        raise RuntimeError("NEB-TS failed to produce a TS guess")

    round_dir = step_dir / f"round_{round_idx}"
    guess_id = "neb_ts"
    guess_dir = round_dir / guess_id
    guess_xyz = guess_dir / "guess.xyz"
    guess_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ts_xyz, guess_xyz)

    guesses = [{
        "guess_id": guess_id,
        "xyz_path": str(guess_xyz.relative_to(step_dir)),
        "mechanism": "neb_ts",
        "stage": "neb_ts_optimized",
        "generator_notes": f"ORCA NEB-TS with xTB (nimages={nimages})",
    }]

    manifest = {
        "workdir": _repo_rel(step_dir),
        "round": round_idx,
        "reactant_smiles": r_smi,
        "product_smiles": p_balanced_smi,
        "charge": 0,
        "multiplicity": 1,
        "guesses": guesses,
    }

    manifest_path = step_dir / f"auto_guess_manifest.round_{round_idx}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"  wrote manifest: {manifest_path}")
    return manifest


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--step-dir", type=Path, required=True,
                    help="Step directory (must contain reactant.xyz and yarp_route.json)")
    ap.add_argument("--round", type=int, default=0, help="Round index")
    ap.add_argument("--nprocs", type=int, default=4, help="ORCA processes")
    ap.add_argument("--nimages", type=int, default=8, help="NEB images")
    ap.add_argument("--timeout", type=int, default=3600, help="Timeout in seconds")
    args = ap.parse_args()

    step_dir = args.step_dir if args.step_dir.is_absolute() else WS / args.step_dir
    process_step(step_dir, args.round, args.nprocs, args.nimages, args.timeout)


if __name__ == "__main__":
    main()
