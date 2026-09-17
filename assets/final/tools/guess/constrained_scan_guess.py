#!/usr/bin/env python3
"""Generate TS guess structures for dehydration reactions via constrained
relaxed surface scan along the breaking C-O bond.

Strategy:
  1. Identify the breaking C-O bond and the migrating β-H using atom mapping
     (map_reaction_atoms.py) and bond-change analysis.
  2. Run xTB constrained optimizations at a series of C-O distances (1.6–3.2 Å).
  3. Optionally add a secondary constraint pulling the β-H toward the departing O.
  4. Rank structures by energy; highest-energy points are TS candidates.
  5. Output guess.xyz files + manifest JSON compatible with orca_xtb_workflow.py.

Usage:
    python resources/constrained_scan_guess.py --step-dir validation/path_2/step_1
    python resources/constrained_scan_guess.py --step-dir validation/path_2/step_1 --round 1
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

WS = Path(__file__).resolve().parents[1]
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

sys.path.insert(0, str(WS / "resources"))
sys.path.insert(0, str(WS / "resources" / "tools"))


# ---------------------------------------------------------------------------
# XYZ I/O (reused from auto_guess.py)
# ---------------------------------------------------------------------------

def read_xyz(path: Path) -> tuple[list[str], np.ndarray]:
    lines = path.read_text().strip().splitlines()
    n = int(lines[0].strip())
    symbols, coords = [], []
    for line in lines[2 : 2 + n]:
        parts = line.split()
        symbols.append(parts[0])
        coords.append([float(x) for x in parts[1:4]])
    return symbols, np.array(coords, dtype=float)


def write_xyz(path: Path, symbols: list[str], coords: np.ndarray, comment: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [str(len(symbols)), comment]
    for sym, (x, y, z) in zip(symbols, coords):
        lines.append(f"{sym:2s} {x:16.10f} {y:16.10f} {z:16.10f}")
    path.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Bond identification via map_reaction_atoms.py
# ---------------------------------------------------------------------------

def identify_breaking_bond(
    reactant_smiles: str,
    product_balanced_smiles: str,
    reactant_xyz: Path,
) -> dict:
    """Identify the breaking C-O bond and migrating β-H for a dehydration step.
    Returns dict with keys: c_idx, o_idx (1-based XYZ indices), beta_h_idx.

    Primary method: map_reaction_atoms.py for precise bond-change analysis.
    Fallback: RDKit-based geometry ranking of all C-OH candidates by β-H proximity.
    """
    syms, coords = read_xyz(reactant_xyz)

    try:
        result = _identify_via_atom_mapping(reactant_smiles, product_balanced_smiles, reactant_xyz)
        h_idx = result.get("beta_h_idx")
        if h_idx is not None:
            ho_dist = np.linalg.norm(coords[h_idx - 1] - coords[result["o_idx"] - 1])
            if ho_dist < 4.0:
                return result
            print(f"  atom-mapping β-H too far ({ho_dist:.1f}Å), trying RDKit fallback")
        else:
            print(f"  atom-mapping found no β-H, trying RDKit fallback")
    except Exception as e:
        print(f"  atom-mapping method failed ({e}), using RDKit fallback")

    return _identify_via_rdkit_fallback(reactant_smiles, product_balanced_smiles, reactant_xyz)


def _identify_via_atom_mapping(
    reactant_smiles: str,
    product_balanced_smiles: str,
    reactant_xyz: Path,
) -> dict:
    """Primary method using map_reaction_atoms.py."""
    script = WS / "resources" / "tools" / "map_reaction_atoms.py"
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        json_out = f.name
    try:
        r = subprocess.run(
            [PYTHON, str(script),
             reactant_smiles, product_balanced_smiles,
             "--reactant-xyz", str(reactant_xyz),
             "--json-out", json_out,
             "--max-mappings", "1"],
            capture_output=True, text=True, check=True,
        )
        result = json.loads(Path(json_out).read_text())
    finally:
        Path(json_out).unlink(missing_ok=True)

    if not result.get("mappings"):
        raise ValueError("No atom mappings found")

    best = result["mappings"][0]
    broken = best.get("broken_bonds", [])
    h_changes = best.get("hydrogen_count_changes", [])

    co_bond = None
    for b in broken:
        syms = b["symbols"]
        if sorted(syms) == ["C", "O"]:
            co_bond = b
            break

    if co_bond is None:
        for b in broken:
            if "O" in b["symbols"]:
                co_bond = b
                break

    if co_bond is None:
        raise ValueError(f"No breaking C-O bond found. Broken bonds: {broken}")

    atoms = co_bond["reactant_atoms"]
    syms = co_bond["symbols"]
    if syms[0] == "C":
        c_idx, o_idx = atoms[0], atoms[1]
    else:
        c_idx, o_idx = atoms[1], atoms[0]

    beta_h_idx = _find_beta_hydrogen(c_idx, o_idx, h_changes, reactant_xyz, best)

    return {
        "c_idx": c_idx,
        "o_idx": o_idx,
        "beta_h_idx": beta_h_idx,
        "broken_bonds": broken,
        "h_changes": h_changes,
        "mapping_result": result,
    }


def _identify_via_rdkit_fallback(
    reactant_smiles: str,
    product_balanced_smiles: str,
    reactant_xyz: Path,
) -> dict:
    """Fallback: enumerate ALL C-OH hydroxyl candidates, simulate removing each
    OH (+ β-H) to form a C=C, and pick the candidate whose simulated product
    best matches the expected product SMILES.
    """
    from rdkit import Chem
    from rdkit.Chem import rdDetermineBonds, AllChem
    from rdkit.DataStructs import TanimotoSimilarity

    syms, coords = read_xyz(reactant_xyz)

    xyz_mol = Chem.MolFromXYZFile(str(reactant_xyz))
    if xyz_mol is None:
        raise ValueError(f"Cannot read {reactant_xyz}")
    rdDetermineBonds.DetermineConnectivity(xyz_mol)
    try:
        rdDetermineBonds.DetermineBondOrders(xyz_mol)
    except Exception:
        pass

    # Parse expected main product
    frags = product_balanced_smiles.split(".")
    p_main = max(frags, key=len)
    target_mol = Chem.MolFromSmiles(p_main)
    target_fp = AllChem.GetMorganFingerprintAsBitVect(target_mol, 2, 1024) if target_mol else None

    # Parse reactant from SMILES for graph manipulation
    r_mol = Chem.MolFromSmiles(reactant_smiles)
    if r_mol is None:
        raise ValueError(f"Cannot parse reactant SMILES: {reactant_smiles}")

    # Collect C-OH candidates from XYZ
    candidates: list[dict] = []
    for bond in xyz_mol.GetBonds():
        a1, a2 = bond.GetBeginAtom(), bond.GetEndAtom()
        i1, i2 = a1.GetIdx(), a2.GetIdx()
        s1, s2 = syms[i1], syms[i2]
        if sorted([s1, s2]) != ["C", "O"]:
            continue
        c_i = i1 if s1 == "C" else i2
        o_i = i1 if s1 == "O" else i2
        o_atom = xyz_mol.GetAtomWithIdx(o_i)
        heavy_nb = sum(1 for nb in o_atom.GetNeighbors() if nb.GetAtomicNum() > 1)
        if heavy_nb != 1:
            continue

        beta_h = _find_beta_h_geometric(c_i + 1, o_i + 1, syms, coords, xyz_mol)
        ho_dist = float("inf")
        if beta_h is not None:
            ho_dist = float(np.linalg.norm(coords[beta_h - 1] - coords[o_i]))
        candidates.append({
            "c_idx": c_i + 1,
            "o_idx": o_i + 1,
            "beta_h_idx": beta_h,
            "ho_dist": ho_dist,
            "product_sim": 0.0,
            "simulated_smi": "",
        })

    if not candidates:
        raise ValueError("No C-OH hydroxyl bonds found in reactant XYZ")

    # For each candidate, simulate dehydration on the SMILES graph
    for cand in candidates:
        if cand["beta_h_idx"] is None:
            continue
        sim_smi = _simulate_dehydration(r_mol, xyz_mol, cand, syms)
        cand["simulated_smi"] = sim_smi or ""
        if sim_smi and target_fp:
            try:
                sim_mol = Chem.MolFromSmiles(sim_smi)
                if sim_mol:
                    sim_fp = AllChem.GetMorganFingerprintAsBitVect(sim_mol, 2, 1024)
                    cand["product_sim"] = TanimotoSimilarity(target_fp, sim_fp)
            except Exception:
                pass

    # Sort: highest product similarity first, then closest β-H as tiebreaker
    candidates.sort(key=lambda x: (-x["product_sim"], x["ho_dist"]))
    best = candidates[0]

    print(f"  RDKit fallback: {len(candidates)} C-OH candidates, "
          f"selected C{best['c_idx']}-O{best['o_idx']} "
          f"(sim={best['product_sim']:.3f}, β-H={best['ho_dist']:.2f}Å)")
    for c in candidates:
        tag = "***" if c is best else "   "
        print(f"    {tag} C{c['c_idx']}-O{c['o_idx']} "
              f"β-H={'H'+str(c['beta_h_idx']) if c['beta_h_idx'] else 'none':>5s} "
              f"H-O={c['ho_dist']:.2f}Å sim={c['product_sim']:.3f} "
              f"→ {c['simulated_smi'][:50]}")

    return {
        "c_idx": best["c_idx"],
        "o_idx": best["o_idx"],
        "beta_h_idx": best["beta_h_idx"],
        "broken_bonds": [],
        "h_changes": [],
        "mapping_result": None,
    }


def _simulate_dehydration(r_mol, xyz_mol, cand: dict, syms: list[str]) -> str | None:
    """Simulate dehydration on the RDKit mol: remove O-H from C, remove H from
    adjacent C (β-carbon), form C=C. Return SMILES of organic product or None.

    We work on xyz_mol (which has correct connectivity from XYZ) to manipulate
    the graph, since SMILES-based r_mol may have different atom numbering.
    """
    from rdkit import Chem

    c_xyz = cand["c_idx"] - 1   # 0-based
    o_xyz = cand["o_idx"] - 1
    h_beta_xyz = cand["beta_h_idx"] - 1 if cand["beta_h_idx"] else None

    if h_beta_xyz is None:
        return None

    # Find the β-carbon (the carbon bonded to c_xyz that has h_beta_xyz as neighbor)
    beta_c_xyz = None
    c_atom = xyz_mol.GetAtomWithIdx(c_xyz)
    for nb in c_atom.GetNeighbors():
        if nb.GetAtomicNum() != 6:
            continue
        nb_idx = nb.GetIdx()
        nb_atom = xyz_mol.GetAtomWithIdx(nb_idx)
        for h_nb in nb_atom.GetNeighbors():
            if h_nb.GetIdx() == h_beta_xyz:
                beta_c_xyz = nb_idx
                break
        if beta_c_xyz is not None:
            break

    if beta_c_xyz is None:
        return None

    # Find H atoms bonded to the leaving O (to remove as water)
    o_atom = xyz_mol.GetAtomWithIdx(o_xyz)
    o_h_atoms = [nb.GetIdx() for nb in o_atom.GetNeighbors() if nb.GetAtomicNum() == 1]

    try:
        rw = Chem.RWMol(xyz_mol)
        remove_indices = sorted(set([o_xyz, h_beta_xyz] + o_h_atoms), reverse=True)
        for idx in remove_indices:
            rw.RemoveAtom(idx)

        # Adjust indices for C-C bond (both may have shifted)
        def adjusted(orig):
            shift = sum(1 for r in remove_indices if r < orig)
            return orig - shift

        new_c = adjusted(c_xyz)
        new_beta_c = adjusted(beta_c_xyz)

        bond = rw.GetBondBetweenAtoms(new_c, new_beta_c)
        if bond:
            bond.SetBondType(Chem.BondType.DOUBLE)

        try:
            Chem.SanitizeMol(rw)
        except Exception:
            pass

        smi = Chem.MolToSmiles(rw)
        return smi
    except Exception:
        return None


def _find_beta_h_geometric(
    c_break: int,  # 1-based
    o_leave: int,  # 1-based
    syms: list[str],
    coords: np.ndarray,
    mol,
) -> int | None:
    """Find β-H purely from geometry: H bonded to a C adjacent to C_break,
    choosing the H closest to O_leave."""
    c_atom = mol.GetAtomWithIdx(c_break - 1)
    o_coord = coords[o_leave - 1]

    # Get carbons bonded to c_break
    neighbor_carbons = []
    for nb in c_atom.GetNeighbors():
        if nb.GetAtomicNum() == 6:
            neighbor_carbons.append(nb.GetIdx())

    # For each neighbor carbon, find its H atoms
    best_h = None
    best_dist = float("inf")
    for nc_idx in neighbor_carbons:
        nc_atom = mol.GetAtomWithIdx(nc_idx)
        for nb in nc_atom.GetNeighbors():
            if nb.GetAtomicNum() == 1:
                h_idx = nb.GetIdx()
                d = np.linalg.norm(coords[h_idx] - o_coord)
                if d < best_dist:
                    best_dist = d
                    best_h = h_idx + 1  # 1-based

    return best_h


def _find_beta_hydrogen(
    c_break_idx: int,
    o_leave_idx: int,
    h_changes: list[dict],
    reactant_xyz: Path,
    mapping: dict,
) -> int | None:
    """Find the H atom that migrates to the departing O during E2 elimination.

    Look for a carbon that:
      1. Is bonded to C_break in the reactant
      2. Loses an H in the product (delta < 0 in hydrogen_count_changes)
    Then pick the H on that carbon closest to O_leave.
    """
    syms, coords = read_xyz(reactant_xyz)
    n = len(syms)

    # Carbons that lose H
    h_losing_carbons = {}
    for hc in h_changes:
        if hc["symbol"] == "C" and hc["delta"] < 0:
            h_losing_carbons[hc["reactant_atom"]] = hc  # 1-based XYZ idx

    if not h_losing_carbons:
        return None

    # Find carbons bonded to C_break (distance < 1.7 Å in the XYZ)
    c_break_coord = coords[c_break_idx - 1]
    bonded_carbons = []
    for i in range(n):
        if syms[i] != "C" or (i + 1) == c_break_idx:
            continue
        d = np.linalg.norm(coords[i] - c_break_coord)
        if d < 1.7:
            bonded_carbons.append(i + 1)  # 1-based

    # Intersect with H-losing carbons
    beta_carbons = [c for c in bonded_carbons if c in h_losing_carbons]
    if not beta_carbons:
        # Fallback: any H-losing carbon
        beta_carbons = list(h_losing_carbons.keys())

    if not beta_carbons:
        return None

    beta_c = beta_carbons[0]  # 1-based
    beta_c_coord = coords[beta_c - 1]

    # Find H atoms bonded to beta_c (distance < 1.2 Å)
    h_candidates = []
    for i in range(n):
        if syms[i] != "H":
            continue
        d = np.linalg.norm(coords[i] - beta_c_coord)
        if d < 1.2:
            h_candidates.append(i + 1)  # 1-based

    if not h_candidates:
        return None

    # Pick the H closest to O_leave (most likely to transfer)
    o_coord = coords[o_leave_idx - 1]
    best_h = min(h_candidates, key=lambda h: np.linalg.norm(coords[h - 1] - o_coord))
    return best_h


# ---------------------------------------------------------------------------
# xTB constrained optimization
# ---------------------------------------------------------------------------

def run_constrained_opt(
    reactant_xyz: Path,
    c_idx: int,
    o_idx: int,
    co_distance: float,
    h_idx: int | None = None,
    ho_distance: float | None = None,
    work_dir: Path | None = None,
) -> tuple[float | None, Path | None]:
    """Run xTB constrained optimization with fixed C-O distance.
    Optionally also constrain H-O distance.
    Returns (energy_Eh, optimized_xyz_path) or (None, None) on failure.
    """
    if work_dir is None:
        work_dir = Path(tempfile.mkdtemp())

    work_dir.mkdir(parents=True, exist_ok=True)
    inp_xyz = work_dir / "input.xyz"
    shutil.copy(reactant_xyz, inp_xyz)

    # Build xcontrol file
    xcontrol = work_dir / "xcontrol.inp"
    lines = ["$constrain", "  force constant=1.0"]
    lines.append(f"  distance: {c_idx}, {o_idx}, {co_distance:.4f}")
    if h_idx is not None and ho_distance is not None:
        lines.append(f"  distance: {h_idx}, {o_idx}, {ho_distance:.4f}")
    lines.append("$end")
    xcontrol.write_text("\n".join(lines) + "\n")

    try:
        r = subprocess.run(
            [XTB_BIN, str(inp_xyz), "--opt", "normal", "--gfn", "2",
             "--chrg", "0", "--input", str(xcontrol)],
            cwd=str(work_dir), capture_output=True, text=True, timeout=300,
        )
        opt_xyz = work_dir / "xtbopt.xyz"
        if not opt_xyz.exists():
            return None, None

        energy = None
        for line in r.stdout.splitlines():
            if "TOTAL ENERGY" in line:
                energy = float(line.split()[-3])

        return energy, opt_xyz

    except (subprocess.TimeoutExpired, Exception) as e:
        print(f"    xTB constrained opt failed: {e}", file=sys.stderr)
        return None, None


# ---------------------------------------------------------------------------
# Main: constrained scan for one step
# ---------------------------------------------------------------------------

def process_step(
    step_dir: Path,
    round_idx: int = 0,
    n_guesses: int = 9,
) -> dict:
    """Generate TS guesses for a dehydration step via constrained C-O scan."""
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
    p_main_smi = route.get("product_main_smiles", p_balanced_smi.split(".")[0])

    syms, coords = read_xyz(reactant_xyz)

    # Step 1: Identify breaking C-O bond and β-H
    print(f"  identifying breaking bond: {r_smi} → {p_balanced_smi}")
    bond_info = identify_breaking_bond(r_smi, p_balanced_smi, reactant_xyz)
    c_idx = bond_info["c_idx"]
    o_idx = bond_info["o_idx"]
    h_idx = bond_info["beta_h_idx"]

    c_sym = syms[c_idx - 1]
    o_sym = syms[o_idx - 1]
    current_co = np.linalg.norm(coords[c_idx - 1] - coords[o_idx - 1])
    print(f"  breaking bond: {c_sym}{c_idx}-{o_sym}{o_idx} (current dist={current_co:.2f} Å)")
    if h_idx:
        h_sym = syms[h_idx - 1]
        current_ho = np.linalg.norm(coords[h_idx - 1] - coords[o_idx - 1])
        print(f"  β-hydrogen: {h_sym}{h_idx} (current H-O dist={current_ho:.2f} Å)")

    # Step 2: Constrained scan — C-O stretch only
    co_distances = [1.6, 1.8, 2.0, 2.2, 2.5, 2.8, 3.2]
    # Shift slightly per round for diversity
    offset = round_idx * 0.1
    co_distances = [d + offset for d in co_distances]

    round_dir = step_dir / f"round_{round_idx}"
    scan_results = []

    print(f"  running C-O scan ({len(co_distances)} points) ...")
    for d_co in co_distances:
        tag = f"co_{d_co:.1f}"
        guess_dir = round_dir / tag
        energy, opt_xyz = run_constrained_opt(
            reactant_xyz, c_idx, o_idx, d_co,
            work_dir=guess_dir,
        )
        if energy is not None:
            print(f"    d(C-O)={d_co:.1f}Å: E={energy:.6f} Eh")
            scan_results.append({
                "tag": tag,
                "co_dist": d_co,
                "ho_dist": None,
                "energy": energy,
                "xyz_path": opt_xyz,
                "mechanism": "constrained_co_scan",
                "notes": f"C{c_idx}-O{o_idx}={d_co:.1f}Å",
            })
        else:
            print(f"    d(C-O)={d_co:.1f}Å: FAILED")

    # Step 3: Dual constraint scan — C-O stretch + H→O approach
    if h_idx:
        dual_configs = [
            (1.8, 1.6),
            (2.0, 1.4),
            (2.0, 1.8),
            (2.2, 1.2),
            (2.2, 1.5),
            (2.5, 1.1),
            (2.5, 1.3),
            (2.8, 1.0),
        ]
        # Shift for diversity in later rounds
        dual_configs = [
            (d_co + offset, max(0.9, d_ho - offset * 0.3))
            for d_co, d_ho in dual_configs
        ]

        print(f"  running dual scan (C-O + H-O, {len(dual_configs)} points) ...")
        for d_co, d_ho in dual_configs:
            tag = f"dual_{d_co:.1f}_{d_ho:.1f}"
            guess_dir = round_dir / tag
            energy, opt_xyz = run_constrained_opt(
                reactant_xyz, c_idx, o_idx, d_co,
                h_idx=h_idx, ho_distance=d_ho,
                work_dir=guess_dir,
            )
            if energy is not None:
                print(f"    d(C-O)={d_co:.1f}Å, d(H-O)={d_ho:.1f}Å: E={energy:.6f} Eh")
                scan_results.append({
                    "tag": tag,
                    "co_dist": d_co,
                    "ho_dist": d_ho,
                    "energy": energy,
                    "xyz_path": opt_xyz,
                    "mechanism": "constrained_dual_scan",
                    "notes": f"C{c_idx}-O{o_idx}={d_co:.1f}Å, H{h_idx}-O{o_idx}={d_ho:.1f}Å",
                })
            else:
                print(f"    d(C-O)={d_co:.1f}Å, d(H-O)={d_ho:.1f}Å: FAILED")

    if not scan_results:
        raise RuntimeError("All constrained optimizations failed")

    # Step 4: Rank by energy (highest = most TS-like)
    scan_results.sort(key=lambda x: x["energy"], reverse=True)
    selected = scan_results[:n_guesses]
    print(f"  selected {len(selected)} guesses (highest energy)")

    # Step 5: Write guess.xyz files + manifest
    guesses = []
    for sr in selected:
        guess_id = sr["tag"]
        guess_dir = round_dir / guess_id
        guess_xyz = guess_dir / "guess.xyz"

        if sr["xyz_path"] and sr["xyz_path"].exists():
            # Copy the optimized structure as guess.xyz
            opt_syms, opt_coords = read_xyz(sr["xyz_path"])
            comment = f"{sr['mechanism']} {sr['notes']} E(xTB)={sr['energy']:.6f} Eh"
            write_xyz(guess_xyz, opt_syms, opt_coords, comment)
        else:
            continue

        guesses.append({
            "guess_id": guess_id,
            "xyz_path": str(guess_xyz.relative_to(step_dir)),
            "mechanism": sr["mechanism"],
            "stage": sr["tag"],
            "generator_notes": f"{sr['notes']}, E(xTB)={sr['energy']:.6f} Eh",
        })

    manifest = {
        "workdir": str(step_dir.relative_to(WS)),
        "round": round_idx,
        "reactant_smiles": r_smi,
        "product_smiles": p_balanced_smi,
        "charge": 0,
        "multiplicity": 1,
        "guesses": guesses,
        "breaking_bond": {
            "c_idx": c_idx,
            "o_idx": o_idx,
            "h_idx": h_idx,
        },
    }

    manifest_path = step_dir / f"auto_guess_manifest.round_{round_idx}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"  wrote manifest: {manifest_path.relative_to(WS)}")
    return manifest


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--step-dir", type=Path, required=True,
                    help="Step directory (e.g. validation/path_2/step_1)")
    ap.add_argument("--round", type=int, default=0, help="Round index")
    ap.add_argument("--n-guesses", type=int, default=9,
                    help="Max number of TS guesses to output")
    args = ap.parse_args()

    step_dir = args.step_dir if args.step_dir.is_absolute() else WS / args.step_dir
    process_step(step_dir, args.round, args.n_guesses)


if __name__ == "__main__":
    main()
