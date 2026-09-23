#!/usr/bin/env python3
"""Generate TS guess structures by linear interpolation between reactant and
product geometries.

This is the reaction-agnostic fallback: it needs only the two endpoint SMILES and
makes no mechanistic assumption. When the reaction kind is known, a targeted method
(constrained C-O/beta-H scan, dry proton scan, 2D concerted scan, anomeric scan)
gives a far better guess -- see skill `strict-pathway-validation` for the ladder.

Workflow per step:
  1. Parse reactant.xyz (already exists).
  2. Generate product_balanced.xyz via RDKit ETKDG + xTB opt (balanced = main
     product + coproducts like H₂O, so atom count equals reactant).
  3. Atom-map reactant → product using the existing map_reaction_atoms tool
     (heavy-atom graph matching + MCS).
  4. Build a full-atom (incl. H) mapping by extending the heavy-atom map with
     a nearest-neighbor greedy assignment of hydrogens.
  5. Reorder product atoms to match reactant ordering.
  6. Linear-interpolation at several fractions (0.25 … 0.75) → TS guesses.
  7. Optionally: xTB single-point on each interpolated structure to pick the
     highest-energy ones.
  8. Write guess.xyz files + manifest JSON compatible with orca_xtb_workflow.py.

Usage:
    python resources/auto_guess.py --step-dir validation/path_2/step_1
    python resources/auto_guess.py --step-dir validation/path_2/step_1 --round 1
    python resources/auto_guess.py --all-pending   # iterate all pending steps
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

import numpy as np

WS = Path(__file__).resolve().parents[1]
# Repository root: tools/guess/auto_guess.py -> two levels up.
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

_CP.bootstrap()

PYTHON = sys.executable or _CP.PYBIN
XTB_BIN = shutil.which("xtb") or _CP.XTB_BIN

sys.path.insert(0, str(REPO / "tools" / "guess"))
sys.path.insert(0, str(REPO / "tools" / "geometry"))


# ---------------------------------------------------------------------------
# XYZ I/O
# ---------------------------------------------------------------------------

def read_xyz(path: Path) -> tuple[list[str], np.ndarray]:
    """Return (symbols, coords[N,3])."""
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
# Product geometry generation
# ---------------------------------------------------------------------------

def smiles_to_xyz_xtb(smiles: str, out_xyz: Path) -> None:
    """SMILES → ETKDGv3 + MMFF → xTB GFN2 opt → .xyz"""
    from rdkit import Chem
    from rdkit.Chem import AllChem

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Cannot parse SMILES: {smiles!r}")
    mol = Chem.AddHs(mol)
    params = AllChem.ETKDGv3()
    params.randomSeed = 42
    if AllChem.EmbedMolecule(mol, params) != 0:
        params.useRandomCoords = True
        if AllChem.EmbedMolecule(mol, params) != 0:
            raise ValueError(f"Cannot embed SMILES: {smiles!r}")
    try:
        AllChem.MMFFOptimizeMolecule(mol, maxIters=2000)
    except Exception:
        AllChem.UFFOptimizeMolecule(mol, maxIters=2000)

    conf = mol.GetConformer()
    syms = [a.GetSymbol() for a in mol.GetAtoms()]
    coords = np.array([[conf.GetAtomPosition(i).x,
                         conf.GetAtomPosition(i).y,
                         conf.GetAtomPosition(i).z] for i in range(mol.GetNumAtoms())])
    write_xyz(out_xyz, syms, coords, f"ETKDG embed of {smiles}")

    if Path(XTB_BIN).exists():
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "in.xyz"
            shutil.copy(out_xyz, inp)
            try:
                subprocess.run(
                    [XTB_BIN, str(inp), "--opt", "normal", "--gfn", "2", "--chrg", "0"],
                    cwd=td, capture_output=True, timeout=600, check=True,
                )
                opt = Path(td) / "xtbopt.xyz"
                if opt.exists():
                    shutil.copy(opt, out_xyz)
            except Exception as e:
                print(f"  (xTB opt failed, keeping MMFF: {e})", file=sys.stderr)


# ---------------------------------------------------------------------------
# Atom mapping: heavy-atom map → extend to all atoms (incl H)
# ---------------------------------------------------------------------------

def heavy_atom_map(reactant_smiles: str, product_smiles: str, reactant_xyz: Path) -> dict:
    """Call map_reaction_atoms.py and return the JSON result."""
    script = REPO / "tools" / "geometry" / "map_reaction_atoms.py"
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        json_out = f.name
    try:
        subprocess.run(
            [PYTHON, str(script),
             reactant_smiles, product_smiles,
             "--reactant-xyz", str(reactant_xyz),
             "--json-out", json_out,
             "--max-mappings", "1"],
            capture_output=True, text=True, check=True,
        )
        return json.loads(Path(json_out).read_text())
    finally:
        Path(json_out).unlink(missing_ok=True)


def extend_mapping_to_hydrogens(
    r_syms: list[str],
    r_coords: np.ndarray,
    p_syms: list[str],
    p_coords: np.ndarray,
    heavy_map: dict[int, int],
) -> dict[int, int]:
    """Extend a heavy-atom map (0-based r_idx → 0-based p_idx) to include
    hydrogens via greedy nearest-heavy-atom + distance assignment."""
    full_map = dict(heavy_map)

    r_h_indices = [i for i, s in enumerate(r_syms) if s == "H"]
    p_h_indices = [i for i, s in enumerate(p_syms) if s == "H"]

    if len(r_h_indices) != len(p_h_indices):
        raise ValueError(
            f"H count mismatch: reactant has {len(r_h_indices)}, product has {len(p_h_indices)}"
        )

    r_heavy_set = set(heavy_map.keys())
    p_heavy_set = set(heavy_map.values())

    def nearest_heavy(coords, h_idx, heavy_set, syms):
        """Return the nearest heavy atom index to hydrogen h_idx."""
        dists = np.linalg.norm(coords[list(heavy_set)] - coords[h_idx], axis=1)
        sorted_heavy = sorted(heavy_set, key=lambda x: np.linalg.norm(coords[x] - coords[h_idx]))
        return sorted_heavy[0]

    r_h_by_heavy: dict[int, list[int]] = {}
    for h_i in r_h_indices:
        parent = nearest_heavy(r_coords, h_i, r_heavy_set, r_syms)
        r_h_by_heavy.setdefault(parent, []).append(h_i)

    p_h_by_heavy: dict[int, list[int]] = {}
    for h_i in p_h_indices:
        parent = nearest_heavy(p_coords, h_i, p_heavy_set, p_syms)
        p_h_by_heavy.setdefault(parent, []).append(h_i)

    used_p = set()
    unmatched_r: list[int] = []

    for r_heavy, r_hs in r_h_by_heavy.items():
        p_heavy = heavy_map[r_heavy]
        p_hs = p_h_by_heavy.get(p_heavy, [])
        p_hs_avail = [h for h in p_hs if h not in used_p]

        for r_h in r_hs:
            if p_hs_avail:
                best = min(p_hs_avail, key=lambda ph: np.linalg.norm(p_coords[ph] - r_coords[r_h]))
                full_map[r_h] = best
                used_p.add(best)
                p_hs_avail.remove(best)
            else:
                unmatched_r.append(r_h)

    remaining_p = [h for h in p_h_indices if h not in used_p]
    for r_h in unmatched_r:
        if remaining_p:
            best = min(remaining_p, key=lambda ph: np.linalg.norm(p_coords[ph] - r_coords[r_h]))
            full_map[r_h] = best
            used_p.add(best)
            remaining_p.remove(best)

    return full_map


def reorder_product(
    p_syms: list[str],
    p_coords: np.ndarray,
    full_map: dict[int, int],
) -> tuple[list[str], np.ndarray]:
    """Reorder product atoms so index i in output corresponds to reactant atom i."""
    n = len(p_syms)
    new_syms = [""] * n
    new_coords = np.zeros_like(p_coords)
    for r_i, p_i in full_map.items():
        new_syms[r_i] = p_syms[p_i]
        new_coords[r_i] = p_coords[p_i]
    return new_syms, new_coords


# ---------------------------------------------------------------------------
# Interpolation
# ---------------------------------------------------------------------------

def interpolate(
    r_coords: np.ndarray,
    p_coords: np.ndarray,
    fractions: list[float],
) -> list[np.ndarray]:
    """Linear interpolation in Cartesian space."""
    return [r_coords + f * (p_coords - r_coords) for f in fractions]


# ---------------------------------------------------------------------------
# xTB single-point energy ranking (optional)
# ---------------------------------------------------------------------------

def xtb_energy(symbols: list[str], coords: np.ndarray) -> float | None:
    """Return xTB GFN2 single-point energy (Hartree), or None on failure."""
    if not Path(XTB_BIN).exists():
        return None
    with tempfile.TemporaryDirectory() as td:
        xyz = Path(td) / "mol.xyz"
        write_xyz(xyz, symbols, coords, "SP")
        try:
            r = subprocess.run(
                [XTB_BIN, str(xyz), "--sp", "--gfn", "2", "--chrg", "0"],
                cwd=td, capture_output=True, text=True, timeout=120,
            )
            for line in r.stdout.splitlines():
                if "TOTAL ENERGY" in line:
                    return float(line.split()[-3])
        except Exception:
            pass
    return None


# ---------------------------------------------------------------------------
# Main entry: process one step
# ---------------------------------------------------------------------------

def process_step(step_dir: Path, round_idx: int = 0, n_guesses: int = 9,
                 fractions: list[float] | None = None) -> dict:
    """Generate TS guesses for one step. Returns manifest dict."""
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

    # Generate product geometry (balanced = same heavy-atom count as reactant)
    product_bal_xyz = step_dir / "product_balanced_interp.xyz"
    print(f"  generating product_balanced geometry: {p_balanced_smi}")
    smiles_to_xyz_xtb(p_balanced_smi, product_bal_xyz)
    p_syms, p_coords = read_xyz(product_bal_xyz)

    if len(p_syms) != n_atoms:
        raise ValueError(
            f"Atom count mismatch: reactant={n_atoms}, product_balanced={len(p_syms)}. "
            f"Cannot interpolate."
        )

    # Heavy-atom mapping
    print(f"  atom-mapping: {r_smi} → {p_balanced_smi}")

    # Use balanced product SMILES for mapping (same heavy-atom formula as reactant).
    # map_reaction_atoms requires same heavy-atom count, which is only true for
    # the balanced product (main product + coproducts like H₂O).
    try:
        map_result = heavy_atom_map(r_smi, p_balanced_smi, reactant_xyz)
        if map_result and map_result.get("mappings"):
            print(f"  got {len(map_result['mappings'][0]['reactant_to_product'])} heavy-atom pairs from map_reaction_atoms")
    except subprocess.CalledProcessError as e:
        print(f"  WARNING: heavy-atom mapping failed: {e.stderr[:300] if e.stderr else '(no stderr)'}")
        map_result = None
    except Exception as e:
        print(f"  WARNING: heavy-atom mapping failed: {e}")
        map_result = None

    # Element-wise nearest-neighbor mapping (works even when mapping tool fails).
    print(f"  building full atom map via element-grouped nearest-neighbor")
    full_map = _element_nearest_neighbor_map(r_syms, r_coords, p_syms, p_coords)
    p_syms_reord, p_coords_reord = reorder_product(p_syms, p_coords, full_map)

    # Sanity: symbols must match after reordering
    for i, (rs, ps) in enumerate(zip(r_syms, p_syms_reord)):
        if rs != ps:
            raise ValueError(f"Symbol mismatch at atom {i}: reactant={rs}, product={ps}")

    # Interpolation fractions — shift slightly per round for diversity
    if fractions is None:
        base = [0.2, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.8]
        offset = round_idx * 0.025
        fractions = [min(0.95, max(0.05, f + offset)) for f in base]

    interp_coords = interpolate(r_coords, p_coords_reord, fractions)

    # xTB energy ranking
    print(f"  ranking {len(interp_coords)} interpolated structures by xTB energy ...")
    energies = []
    for i, coords in enumerate(interp_coords):
        e = xtb_energy(r_syms, coords)
        energies.append(e)
        tag = f"{e:.6f} Eh" if e is not None else "FAILED"
        print(f"    f={fractions[i]:.2f}: {tag}")

    # Sort by energy (highest = most TS-like), keep top n_guesses
    ranked = sorted(
        [(f, c, e) for f, c, e in zip(fractions, interp_coords, energies) if e is not None],
        key=lambda x: x[2],
        reverse=True,
    )
    if not ranked:
        print("  WARNING: all xTB single-points failed, using middle fractions")
        mid = len(interp_coords) // 2
        start = max(0, mid - n_guesses // 2)
        ranked = [(fractions[i], interp_coords[i], None) for i in range(start, min(start + n_guesses, len(interp_coords)))]

    selected = ranked[:n_guesses]
    print(f"  selected {len(selected)} guesses (highest energy)")

    # Write guess files
    round_dir = step_dir / f"round_{round_idx}"
    guesses = []
    for idx, (frac, coords, energy) in enumerate(selected):
        guess_id = f"interp_{frac:.2f}"
        guess_dir = round_dir / guess_id
        guess_xyz = guess_dir / "guess.xyz"
        comment = f"Linear interpolation f={frac:.2f}"
        if energy is not None:
            comment += f" E(xTB)={energy:.6f} Eh"
        write_xyz(guess_xyz, r_syms, coords, comment)
        guesses.append({
            "guess_id": guess_id,
            "xyz_path": str(guess_xyz.relative_to(step_dir)),
            "mechanism": "linear_interpolation",
            "stage": f"f={frac:.2f}",
            "generator_notes": comment,
        })

    # Build manifest. `workdir` is informational, so express it relative to the repository root
    # when possible and fall back to the path itself. It used to be taken relative to this
    # file's parent directory, which only resolved while scratch lived under tools/ — under the
    # current layout (runs/) that raised and lost a set of guesses that had already been built.
    try:
        workdir = str(step_dir.relative_to(REPO))
    except ValueError:
        workdir = str(step_dir)
    manifest = {
        "workdir": workdir,
        "round": round_idx,
        "reactant_smiles": r_smi,
        "product_smiles": p_balanced_smi,
        "charge": 0,
        "multiplicity": 1,
        "guesses": guesses,
    }

    manifest_path = step_dir / f"auto_guess_manifest.round_{round_idx}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"  wrote manifest: {_repo_rel(manifest_path)}")
    return manifest


def _element_nearest_neighbor_map(
    r_syms: list[str],
    r_coords: np.ndarray,
    p_syms: list[str],
    p_coords: np.ndarray,
) -> dict[int, int]:
    """Build a full-atom map by grouping atoms by element and doing greedy
    nearest-neighbor assignment within each group. This handles cases where
    the reactant and product xyz have different atom orderings."""
    from scipy.optimize import linear_sum_assignment

    r_by_elem: dict[str, list[int]] = {}
    for i, s in enumerate(r_syms):
        r_by_elem.setdefault(s, []).append(i)

    p_by_elem: dict[str, list[int]] = {}
    for i, s in enumerate(p_syms):
        p_by_elem.setdefault(s, []).append(i)

    full_map = {}
    for elem in r_by_elem:
        r_idxs = r_by_elem[elem]
        p_idxs = p_by_elem.get(elem, [])
        if len(r_idxs) != len(p_idxs):
            raise ValueError(f"Element {elem} count mismatch: reactant={len(r_idxs)}, product={len(p_idxs)}")

        if len(r_idxs) == 1:
            full_map[r_idxs[0]] = p_idxs[0]
            continue

        # Build cost matrix (Euclidean distance)
        cost = np.zeros((len(r_idxs), len(p_idxs)))
        for i, ri in enumerate(r_idxs):
            for j, pj in enumerate(p_idxs):
                cost[i, j] = np.linalg.norm(r_coords[ri] - p_coords[pj])

        row_ind, col_ind = linear_sum_assignment(cost)
        for i, j in zip(row_ind, col_ind):
            full_map[r_idxs[i]] = p_idxs[j]

    return full_map


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--step-dir", type=Path, help="Single step directory to process")
    ap.add_argument("--round", type=int, default=None, help="Round index (auto-detect if omitted)")
    ap.add_argument("--n-guesses", type=int, default=9, help="Number of TS guesses to generate")
    ap.add_argument("--all-pending", action="store_true", help="Process all pending steps in path_queue.json")
    args = ap.parse_args()

    if args.all_pending:
        queue = json.loads((WS / "validation" / "path_queue.json").read_text())
        for path in queue:
            if path["status"] != "pending":
                continue
            cs = path["current_step"]
            if cs >= len(path["steps"]):
                continue
            step = path["steps"][cs]
            step_dir = WS / "validation" / f"path_{path['path_id']}" / f"step_{step['step_index']}"
            round_idx = args.round if args.round is not None else step.get("rounds_attempted", 0)
            print(f"\n{'='*60}")
            print(f"Path {path['path_id']} step {step['step_index']} (round {round_idx})")
            print(f"  {step['reactant_smiles']} → {step.get('product_balanced_smiles', '?')}")
            print(f"{'='*60}")
            try:
                process_step(step_dir, round_idx, args.n_guesses)
            except Exception as e:
                print(f"  ERROR: {e}")
    elif args.step_dir:
        step_dir = args.step_dir if args.step_dir.is_absolute() else WS / args.step_dir
        round_idx = args.round if args.round is not None else 0
        process_step(step_dir, round_idx, args.n_guesses)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
