#!/usr/bin/env python3
"""TS guesses for concerted hydride+proton isomerizations (aldose↔ketose and close
kin) via a GFN2 constrained 2D scan.

This is a minimal rebuild of the missing scan2d.py named by the skill
`strict-pathway-validation`. Scope is deliberately narrower than the lost tool:
GFN2 xTB dual-distance scan only, then hand the highest-energy points to the
existing DFT gate (strict_validate.py / soft_mode_cleanup.py). It does not
reproduce the ORCA DEFGRID3 relaxed 2D surface that the repro_runs/*/dft_scan2d
directories hold, and it is not wired into validate_candidate.

Driving coordinates follow the skill ladder: form hydride C→C *and* form proton
O→O (two different H's). Atom indices are 1-based (xtb xcontrol convention).

  process_step(step_dir, round_idx=0, n_guesses=9) -> manifest dict
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

from constrained_scan_guess import PYTHON, WS, XTB_BIN, read_xyz, write_xyz
from dry_proton_guess import run_constrained_opt_pairs

MAP_TOOL = WS / "resources" / "tools" / "map_reaction_atoms.py"
XH_BOND_MAX = 1.35


def identify_hydride_proton(
    reactant_smiles: str,
    product_smiles: str,
    reactant_xyz: Path,
) -> dict:
    """Locate the two migrating H's from the atom map's hydrogen_count_changes.

    Expects exactly one C that loses H, one C that gains H (hydride C→C), and
    one O that loses H, one O that gains H (proton O→O). Falls back to
    geometry (donor H closest to the acceptor) within each X–H shell.
    """
    with __import__("tempfile").NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        json_out = f.name
    try:
        subprocess.run(
            [PYTHON, str(MAP_TOOL), reactant_smiles, product_smiles,
             "--reactant-xyz", str(reactant_xyz),
             "--json-out", json_out, "--max-mappings", "1"],
            check=True, capture_output=True, text=True, timeout=120,
        )
        result = json.loads(Path(json_out).read_text())
    finally:
        Path(json_out).unlink(missing_ok=True)

    mapping = result["mappings"][0]
    hc = mapping.get("hydrogen_count_changes") or []
    c_lose = [r["reactant_atom"] for r in hc if r["symbol"] == "C" and r["delta"] == -1]
    c_gain = [r["reactant_atom"] for r in hc if r["symbol"] == "C" and r["delta"] == 1]
    o_lose = [r["reactant_atom"] for r in hc if r["symbol"] == "O" and r["delta"] == -1]
    o_gain = [r["reactant_atom"] for r in hc if r["symbol"] == "O" and r["delta"] == 1]
    if not (len(c_lose) == 1 and len(c_gain) == 1 and len(o_lose) == 1 and len(o_gain) == 1):
        raise ValueError(
            "expected one C→C hydride and one O→O proton; got "
            f"C_lose={c_lose} C_gain={c_gain} O_lose={o_lose} O_gain={o_gain}"
        )

    syms, coords = read_xyz(reactant_xyz)
    c_don, c_acc = c_lose[0], c_gain[0]
    o_don, o_acc = o_lose[0], o_gain[0]

    def bonded_h(owner_1b: int) -> list[int]:
        o = owner_1b - 1
        out = []
        for i, s in enumerate(syms):
            if s != "H":
                continue
            if float(np.linalg.norm(coords[i] - coords[o])) < XH_BOND_MAX:
                out.append(i + 1)
        return out

    hs_c = bonded_h(c_don)
    hs_o = bonded_h(o_don)
    if not hs_c or not hs_o:
        raise ValueError(f"no H on donor C{c_don} / O{o_don}: Hs_C={hs_c} Hs_O={hs_o}")

    def closest(hs: list[int], target_1b: int) -> int:
        t = coords[target_1b - 1]
        return min(hs, key=lambda h: float(np.linalg.norm(coords[h - 1] - t)))

    h_hyd = closest(hs_c, c_acc)
    h_prot = closest(hs_o, o_acc)
    d_ha = float(np.linalg.norm(coords[h_hyd - 1] - coords[c_acc - 1]))
    d_oa = float(np.linalg.norm(coords[h_prot - 1] - coords[o_acc - 1]))
    return {
        "c_donor": c_don, "c_acceptor": c_acc, "h_hydride": h_hyd,
        "o_donor": o_don, "o_acceptor": o_acc, "h_proton": h_prot,
        "d_h_c_acc": d_ha, "d_h_o_acc": d_oa,
    }


def grid_values(d0: float, d_end: float, n: int) -> list[float]:
    """Inclusive linear grid from the reactant distance toward the bonded value."""
    return [float(x) for x in np.linspace(d0, d_end, n)]


def process_step(step_dir: Path, round_idx: int = 0, n_guesses: int = 9,
                 n_hyd: int = 5, n_prot: int = 5) -> dict:
    step_dir = Path(step_dir)
    route_json = step_dir / "yarp_route.json"
    reactant_xyz = step_dir / "reactant.xyz"
    if not route_json.exists():
        raise FileNotFoundError(f"Missing {route_json}")
    if not reactant_xyz.exists():
        raise FileNotFoundError(f"Missing {reactant_xyz}")

    route = json.loads(route_json.read_text())
    r_smi = route["reactant_smiles"]
    p_smi = route.get("product_main_smiles", route["product_balanced_smiles"].split(".")[0])

    print(f"  identifying hydride+proton shift: {r_smi} -> {p_smi}")
    info = identify_hydride_proton(r_smi, p_smi, reactant_xyz)
    print(
        f"  hydride H{info['h_hydride']}: C{info['c_donor']} -> C{info['c_acceptor']} "
        f"(H...C_acc={info['d_h_c_acc']:.2f} A); "
        f"proton H{info['h_proton']}: O{info['o_donor']} -> O{info['o_acceptor']} "
        f"(H...O_acc={info['d_h_o_acc']:.2f} A)"
    )

    # End targets sit a little short of equilibrium X–H so the peak is not stuck in the
    # product well; FF's deposited DFT scan drove O–H down to 1.00 A similarly.
    hyd_grid = grid_values(info["d_h_c_acc"], 1.15, n_hyd)
    prot_grid = grid_values(info["d_h_o_acc"], 1.05, n_prot)
    print(f"  2D GFN2 grid {n_hyd}x{n_prot} "
          f"(H-C: {hyd_grid[0]:.2f}->{hyd_grid[-1]:.2f}; "
          f"H-O: {prot_grid[0]:.2f}->{prot_grid[-1]:.2f})")

    round_dir = step_dir / f"round_{round_idx}"
    round_dir.mkdir(parents=True, exist_ok=True)
    scored: list[dict] = []
    for dh in hyd_grid:
        for dp in prot_grid:
            tag = f"hc_{dh:.2f}_ho_{dp:.2f}"
            work = round_dir / tag
            # Skip the pure reactant corner: both distances at the starting values does
            # not advance either transfer and just remakes the reactant.
            if abs(dh - info["d_h_c_acc"]) < 0.02 and abs(dp - info["d_h_o_acc"]) < 0.02:
                continue
            constraints = [
                (info["h_hydride"], info["c_acceptor"], dh),
                (info["h_proton"], info["o_acceptor"], dp),
            ]
            energy, opt_xyz = run_constrained_opt_pairs(reactant_xyz, constraints, work)
            if energy is None or opt_xyz is None:
                print(f"    {tag}: FAILED")
                continue
            guess = work / "guess.xyz"
            shutil.copy(opt_xyz, guess)
            print(f"    {tag}: E={energy:.6f} Eh")
            scored.append({
                "guess_id": tag,
                "xyz_path": str(guess.relative_to(step_dir)),
                "mechanism": "scan2d_gfn2",
                "stage": tag,
                "energy_Eh": energy,
                "generator_notes": (
                    f"H{info['h_hydride']}-C{info['c_acceptor']}={dh:.2f}A, "
                    f"H{info['h_proton']}-O{info['o_acceptor']}={dp:.2f}A, "
                    f"E(xTB)={energy:.6f} Eh"
                ),
            })

    if not scored:
        raise RuntimeError("every grid point failed")

    scored.sort(key=lambda g: g["energy_Eh"], reverse=True)
    selected = scored[:n_guesses]
    print(f"  selected {len(selected)} guesses (highest energy)")

    manifest = {
        "workdir": str(step_dir),
        "round": round_idx,
        "reactant_smiles": r_smi,
        "product_smiles": p_smi,
        "charge": 0,
        "multiplicity": 1,
        "guesses": selected,
        "hydride_proton": info,
        "grid": {"h_c": hyd_grid, "h_o": prot_grid},
    }
    out = step_dir / f"scan2d_manifest.round_{round_idx}.json"
    out.write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    print(f"  wrote manifest: {out}")
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--step-dir", required=True)
    ap.add_argument("--round", type=int, default=0)
    ap.add_argument("--n-guesses", type=int, default=9)
    ap.add_argument("--n-hyd", type=int, default=5, help="grid points along forming C–H")
    ap.add_argument("--n-prot", type=int, default=5, help="grid points along forming O–H")
    a = ap.parse_args()
    process_step(Path(a.step_dir), a.round, a.n_guesses, a.n_hyd, a.n_prot)
    return 0


if __name__ == "__main__":
    sys.exit(main())
