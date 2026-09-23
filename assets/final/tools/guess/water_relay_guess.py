#!/usr/bin/env python3
"""Generate TS guesses for concerted *neutral* proton-transfer steps using an
explicit water proton-relay, then NEB-CI.

Prefer dry guesses for new edges
--------------------------------
STRICT(v5) *allows* catalytic proton shuttles when the discrete water test shows
exchanged H indices on the IRC ends (see policy/acceptance/STRICT.md). This
generator is therefore not barred by acceptance policy.

It is still usually the wrong first choice: dry intramolecular shifts need not
collapse to a zwitterion. Atom-mapped asynchronous scans give clean dry 1,2-/1,3-H
migrations (HMF s2 -1449.8, FF s2 -2042.5, FF s3 -2032.5, FF s5 -1630.0,
FF s8 -2137.8). `validate_candidate.py` / the guess ladder tries dry generators
first and falls back here only if they yield no guess.

Retained also because `glucose_haa_review_v1` step 4 is a genuine water-mediated
tautomerization (-920.1, H4↔H9 shuttle) accepted under v5.

Original rationale (historical)
-------------------------------
Many glucose->HMF elementary steps (ring open/close, aldose<->ketose
isomerization, enolization, vinylogous tautomerization) are formally
intramolecular proton shifts.  Dry intramolecular paths were believed to run through
strained 3-/4-membered TSs that collapse to oxocarbenium/zwitterion endpoints under
GFN2/DFT, so the raw IRC endpoints do NOT exact-match the neutral reactant and
product.  Inserting one explicit water as a proton shuttle gives a low,
*neutral-concerted* path whose IRC ends are the exact neutral R and P (the
water returns as a spectator and is stripped at endpoint matching).

Strategy
--------
1. Atom-map reactant -> product (map_reaction_atoms.py) to find the heavy atom
   that LOSES an H (donor) and the one that GAINS an H (acceptor).
2. Place one (optionally two) explicit water molecule(s) bridging the donor H
   and the acceptor; xTB-optimize the reactant.H2O complex.
3. Build the product organic from SMILES, add the SAME number of waters near
   the mapped donor/acceptor, xTB-optimize the product.H2O complex.
4. Element-nearest-neighbor map reactant-complex -> product-complex, reorder.
5. ORCA NEB-CI between the two complexes -> TS guess.

The emitted manifest uses the *organic* product SMILES (no water), so
orca_xtb_workflow's endpoint matching strips the catalytic water and still
demands an exact neutral-SMILES double-end match.

Usage:
    python resources/water_relay_guess.py --step-dir validation/path_200/step_1
    python resources/water_relay_guess.py --step-dir DIR --round 1 --n-waters 1
"""
from __future__ import annotations

import argparse
import json
import os
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

sys.path.insert(0, str(REPO / "tools" / "guess"))
sys.path.insert(0, str(REPO / "tools" / "geometry"))

from auto_guess import (  # noqa: E402
    read_xyz, write_xyz, smiles_to_xyz_xtb,
    _element_nearest_neighbor_map, reorder_product,
)
from neb_guess import run_neb_ts  # noqa: E402




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

# ---------------------------------------------------------------------------
# Donor / acceptor detection
# ---------------------------------------------------------------------------

def _map_h_changes(reactant_smiles, product_balanced_smiles, reactant_xyz):
    """Return (donor_heavy_1based, acceptor_heavy_1based) from atom mapping, or
    (None, None) if it could not be determined."""
    script = REPO / "tools" / "geometry" / "map_reaction_atoms.py"
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        jout = f.name
    try:
        subprocess.run(
            [PYTHON, str(script), reactant_smiles, product_balanced_smiles,
             "--reactant-xyz", str(reactant_xyz), "--json-out", jout,
             "--max-mappings", "1"],
            capture_output=True, text=True, check=True, timeout=300,
        )
        res = json.loads(Path(jout).read_text())
    except Exception as e:
        print(f"  atom-mapping failed: {e}")
        return None, None
    finally:
        Path(jout).unlink(missing_ok=True)

    if not res.get("mappings"):
        return None, None
    hcs = res["mappings"][0].get("hydrogen_count_changes", [])
    donors = sorted([h for h in hcs if h["delta"] < 0], key=lambda x: x["delta"])
    acceptors = sorted([h for h in hcs if h["delta"] > 0], key=lambda x: -x["delta"])
    donor = donors[0]["reactant_atom"] if donors else None
    acceptor = acceptors[0]["reactant_atom"] if acceptors else None
    return donor, acceptor


def _heuristic_donor_acceptor(syms, coords):
    """Fallback: acceptor = carbonyl O (C=O), donor = nearest O-H or C-H.
    Returns (donor_heavy_1based, acceptor_heavy_1based)."""
    n = len(syms)
    # carbonyl O: O with a single C neighbor at ~1.2 A
    accept = None
    for i in range(n):
        if syms[i] != "O":
            continue
        nbrs = [j for j in range(n) if j != i and
                np.linalg.norm(coords[i] - coords[j]) < 1.35]
        if len(nbrs) == 1 and syms[nbrs[0]] == "C":
            accept = i + 1
            break
    if accept is None:  # any O
        accept = next((i + 1 for i in range(n) if syms[i] == "O"), 1)
    # donor: hydroxyl O nearest to acceptor
    apos = coords[accept - 1]
    best, bestd = None, 1e9
    for i in range(n):
        if syms[i] != "O" or (i + 1) == accept:
            continue
        has_h = any(syms[j] == "H" and np.linalg.norm(coords[i] - coords[j]) < 1.2
                    for j in range(n))
        if not has_h:
            continue
        d = np.linalg.norm(coords[i] - apos)
        if d < bestd:
            bestd, best = d, i + 1
    return best, accept


def _attached_h(heavy_1based, syms, coords, near_pos=None):
    """Return index (1-based) of an H bonded to heavy atom; if near_pos given,
    the one closest to near_pos."""
    hi = heavy_1based - 1
    hs = [j for j in range(len(syms)) if syms[j] == "H"
          and np.linalg.norm(coords[hi] - coords[j]) < 1.3]
    if not hs:
        return None
    if near_pos is not None:
        hs.sort(key=lambda j: np.linalg.norm(coords[j] - near_pos))
    return hs[0] + 1


# ---------------------------------------------------------------------------
# Water placement
# ---------------------------------------------------------------------------

def _add_one_water(syms, coords, donor_h_pos, acceptor_pos):
    """Place a rigid water bridging donor_h_pos and acceptor_pos; return new
    (syms, coords) with O,H,H appended.  Chooses a clash-free O position by
    sampling around the bridge midpoint."""
    centroid = coords.mean(axis=0)
    bridge = 0.5 * (donor_h_pos + acceptor_pos)
    best_o, best_score = None, 1e18
    rng = np.random.default_rng(0)
    for _ in range(400):
        # sample direction away from centroid plus jitter
        out = bridge - centroid
        if np.linalg.norm(out) < 1e-3:
            out = rng.normal(size=3)
        out = out / np.linalg.norm(out)
        jitter = rng.normal(scale=0.6, size=3)
        cand = bridge + out * rng.uniform(0.8, 2.2) + jitter
        dmin = min(np.linalg.norm(cand - coords[k]) for k in range(len(syms)))
        if dmin < 2.3:
            continue
        # want O reasonably close to both bridge partners for a relay
        score = (abs(np.linalg.norm(cand - acceptor_pos) - 2.8)
                 + abs(np.linalg.norm(cand - donor_h_pos) - 1.8)
                 - 0.1 * dmin)
        if score < best_score:
            best_score, best_o = score, cand
    if best_o is None:
        best_o = bridge + (bridge - centroid) / (np.linalg.norm(bridge - centroid) + 1e-9) * 3.0

    o = best_o
    # H1 points toward acceptor (water donates to acceptor)
    d1 = acceptor_pos - o
    d1 = d1 / (np.linalg.norm(d1) + 1e-9)
    h1 = o + 0.97 * d1
    # H2 ~104.5 deg from H1, in plane with donor_h
    ref = donor_h_pos - o
    ref = ref - np.dot(ref, d1) * d1
    if np.linalg.norm(ref) < 1e-3:
        ref = np.cross(d1, np.array([0.0, 0.0, 1.0]))
        if np.linalg.norm(ref) < 1e-3:
            ref = np.cross(d1, np.array([0.0, 1.0, 0.0]))
    ref = ref / (np.linalg.norm(ref) + 1e-9)
    ang = np.deg2rad(104.5)
    d2 = np.cos(ang) * d1 + np.sin(ang) * ref
    h2 = o + 0.97 * d2

    new_syms = list(syms) + ["O", "H", "H"]
    new_coords = np.vstack([coords, o, h1, h2])
    return new_syms, new_coords


def _xtb_opt(syms, coords, workdir: Path, charge=0):
    workdir.mkdir(parents=True, exist_ok=True)
    inp = workdir / "in.xyz"
    write_xyz(inp, syms, coords, "complex")
    try:
        subprocess.run(
            [XTB_BIN, str(inp), "--opt", "normal", "--gfn", "2",
             "--alpb", "water", "--chrg", str(charge)],
            cwd=str(workdir), capture_output=True, text=True, timeout=600,
        )
    except Exception as e:
        print(f"  xtb opt failed: {e}")
        return None
    out = workdir / "xtbopt.xyz"
    if not out.exists():
        return None
    return read_xyz(out)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

# ORCA rewrites OMP_NUM_THREADS from its own %pal value before it launches otool_xtb, so a fixed
# default here silently ignores whatever core budget the caller is running under.
DEFAULT_NPROCS = int(os.environ.get('NPROCS', '8'))


def process_step(step_dir: Path, round_idx=0, n_waters=1, nprocs=DEFAULT_NPROCS,
                 nimages=10, timeout=3600) -> dict:
    step_dir = step_dir.resolve()
    reactant_xyz = step_dir / "reactant.xyz"
    route = json.loads((step_dir / "yarp_route.json").read_text())
    r_smi = route["reactant_smiles"]
    p_main = route.get("product_main_smiles") or route["product_balanced_smiles"].split(".")[0]
    p_balanced = route["product_balanced_smiles"]

    r_syms, r_coords = read_xyz(reactant_xyz)

    donor, acceptor = _map_h_changes(r_smi, p_balanced, reactant_xyz)
    if donor is None or acceptor is None:
        print("  using heuristic donor/acceptor")
        donor, acceptor = _heuristic_donor_acceptor(r_syms, r_coords)
    if donor is None or acceptor is None:
        raise RuntimeError("could not determine donor/acceptor for water relay")
    acc_pos = r_coords[acceptor - 1]
    dh = _attached_h(donor, r_syms, r_coords, near_pos=acc_pos)
    if dh is None:
        # donor may be a carbon losing H; pick any H on donor
        dh = _attached_h(donor, r_syms, r_coords)
    if dh is None:
        raise RuntimeError(f"no H on donor atom {donor}")
    print(f"  relay: donor heavy={donor} (H{dh}) -> acceptor heavy={acceptor}")

    # Build reactant complex with water(s)
    rc_syms, rc_coords = r_syms, r_coords
    for _ in range(n_waters):
        rc_syms, rc_coords = _add_one_water(
            rc_syms, rc_coords, rc_coords[dh - 1], rc_coords[acceptor - 1])
    opt = _xtb_opt(rc_syms, rc_coords, step_dir / f"round_{round_idx}" / "wr_react")
    if opt is None:
        raise RuntimeError("reactant complex xtb opt failed")
    rc_syms, rc_coords = opt

    # Build product complex with same number of waters
    prod_xyz = step_dir / "product_wr_organic.xyz"
    smiles_to_xyz_xtb(p_main, prod_xyz)
    p_syms, p_coords = read_xyz(prod_xyz)
    # place waters near the most carbonyl-like / hydroxyl region of product
    pdonor, pacceptor = _heuristic_donor_acceptor(p_syms, p_coords)
    if pacceptor is None:
        pacceptor = 1
    pacc_pos = p_coords[pacceptor - 1]
    pdh = _attached_h(pdonor, p_syms, p_coords, near_pos=pacc_pos) if pdonor else None
    pc_syms, pc_coords = p_syms, p_coords
    for _ in range(n_waters):
        anchor_h = pc_coords[(pdh - 1)] if pdh else pacc_pos + np.array([1.5, 0, 0])
        pc_syms, pc_coords = _add_one_water(
            pc_syms, pc_coords, anchor_h, pc_coords[pacceptor - 1])
    opt = _xtb_opt(pc_syms, pc_coords, step_dir / f"round_{round_idx}" / "wr_prod")
    if opt is None:
        raise RuntimeError("product complex xtb opt failed")
    pc_syms, pc_coords = opt

    if len(rc_syms) != len(pc_syms):
        raise RuntimeError(
            f"atom count mismatch rc={len(rc_syms)} pc={len(pc_syms)}")

    # Map and reorder product complex to reactant complex ordering
    full_map = _element_nearest_neighbor_map(rc_syms, rc_coords, pc_syms, pc_coords)
    pc_syms_r, pc_coords_r = reorder_product(pc_syms, pc_coords, full_map)
    for i, (a, b) in enumerate(zip(rc_syms, pc_syms_r)):
        if a != b:
            raise RuntimeError(f"symbol mismatch at {i}: {a} vs {b}")

    round_dir = step_dir / f"round_{round_idx}"
    rc_path = round_dir / "wr_reactant.xyz"
    pc_path = round_dir / "wr_product_reordered.xyz"
    write_xyz(rc_path, rc_syms, rc_coords, "reactant+water complex")
    write_xyz(pc_path, pc_syms_r, pc_coords_r, "product+water complex (reordered)")

    ts_xyz = run_neb_ts(step_dir, rc_path, pc_path, round_idx=round_idx,
                        nprocs=nprocs, nimages=nimages, timeout=timeout)
    if ts_xyz is None:
        raise RuntimeError("NEB-TS (water relay) produced no TS")

    guess_id = f"water_relay_{n_waters}w"
    gdir = round_dir / guess_id
    gdir.mkdir(parents=True, exist_ok=True)
    gxyz = gdir / "guess.xyz"
    shutil.copy2(ts_xyz, gxyz)

    manifest = {
        "workdir": _repo_rel(step_dir),
        "round": round_idx,
        "reactant_smiles": r_smi,
        # organic product only -> endpoint matching strips catalytic water
        "product_smiles": p_main,
        "charge": 0,
        "multiplicity": 1,
        "guesses": [{
            "guess_id": guess_id,
            "xyz_path": str(gxyz.relative_to(step_dir)),
            "mechanism": "water_proton_relay_neb",
            "stage": "neb_ci",
            "generator_notes": f"{n_waters} explicit water relay, NEB-CI nimages={nimages}",
        }],
    }
    mp = step_dir / f"auto_guess_manifest.round_{round_idx}.json"
    mp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"  wrote water-relay manifest: {_repo_rel(mp)}")
    return manifest


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--step-dir", type=Path, required=True)
    ap.add_argument("--round", type=int, default=0)
    ap.add_argument("--n-waters", type=int, default=1)
    ap.add_argument("--n-guesses", type=int, default=1)  # accepted, ignored
    ap.add_argument("--nprocs", type=int, default=DEFAULT_NPROCS)
    ap.add_argument("--nimages", type=int, default=10)
    ap.add_argument("--timeout", type=int, default=3600)
    args = ap.parse_args()
    step_dir = args.step_dir if args.step_dir.is_absolute() else WS / args.step_dir
    process_step(step_dir, args.round, args.n_waters, args.nprocs,
                 args.nimages, args.timeout)


if __name__ == "__main__":
    main()
