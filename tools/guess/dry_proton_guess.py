#!/usr/bin/env python3
"""Dry (water-free) TS guesses for proton-transfer steps: keto-enol tautomerization and
enolization/ketonization, i.e. steps where one H moves and the skeleton does not change.
Aldose<->ketose isomerization is NOT in scope: it needs a concerted hydride shift plus a
proton shift, which is a 2D coordinate -- use scan2d.py (original ORCA DFT 2D scan, restored from OpenAgentHarness) or
scan2d_guess.py (GFN2 grid rebuild); see skill `strict-pathway-validation`).

Why dry: across the three accepted deposits, 5 of the 6 proton-transfer steps were
done without any explicit water, including all four in glucose_ff_review_v1
(-2042.5, -2032.5, -1630.0, -2137.8 cm-1; the manifest labels step 5 "enediol->ketose (dry)").
Only glucose_haa_review_v1 step 4 is water-mediated
(-920.1 cm-1). A relayed water is a spectator on both IRC ends of an isomerization, so
it cannot satisfy the no-catalytic-water clause; the dry saddle can, and empirically
also gives a much stiffer reactive mode. Use water_relay_guess.py only as a fallback.

Mechanics mirror constrained_scan_guess.py: GFN2-xTB constrained optimizations along a
driven coordinate, geometries ranked by energy, highest = most TS-like. Atom indices are
1-based throughout (xtb xcontrol convention).

  process_step(step_dir, round_idx=0, n_guesses=9) -> manifest dict
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

from constrained_scan_guess import (
    PYTHON,
    WS,
    XTB_BIN,
    read_xyz,
    run_constrained_opt,
    write_xyz,
)

MAP_TOOL = WS / "resources" / "tools" / "map_reaction_atoms.py"

# A covalent X-H bond is well under this; used to collect the donor's hydrogens.
XH_BOND_MAX = 1.35


def run_constrained_opt_pairs(
    reactant_xyz: Path,
    constraints: list[tuple[int, int, float]],
    work_dir: Path,
) -> tuple[float | None, Path | None]:
    """GFN2 constrained opt holding an arbitrary set of interatomic distances.

    constrained_scan_guess.run_constrained_opt hardwires its second constraint to
    (h_idx, o_idx), which cannot express the donor-H / H-acceptor pair a concerted
    proton transfer needs, so the xcontrol file is written directly here.
    Indices are 1-based; returns (energy_Eh, optimized_xyz) or (None, None).
    """
    import shutil

    work_dir.mkdir(parents=True, exist_ok=True)
    inp_xyz = work_dir / "input.xyz"
    shutil.copy(reactant_xyz, inp_xyz)

    lines = ["$constrain", "  force constant=1.0"]
    lines += [f"  distance: {i}, {j}, {d:.4f}" for i, j, d in constraints]
    lines.append("$end")
    (work_dir / "xcontrol.inp").write_text("\n".join(lines) + "\n")

    try:
        r = subprocess.run(
            [XTB_BIN, str(inp_xyz), "--opt", "normal", "--gfn", "2",
             "--chrg", "0", "--input", str(work_dir / "xcontrol.inp")],
            cwd=str(work_dir), capture_output=True, text=True, timeout=300,
        )
    except Exception as e:
        print(f"    xTB constrained opt failed: {e}", file=sys.stderr)
        return None, None

    opt_xyz = work_dir / "xtbopt.xyz"
    if not opt_xyz.exists():
        return None, None
    energy = None
    for line in r.stdout.splitlines():
        if "TOTAL ENERGY" in line:
            energy = float(line.split()[-3])
    return energy, opt_xyz


def identify_proton_shift(
    reactant_smiles: str,
    product_smiles: str,
    reactant_xyz: Path,
) -> dict:
    """Locate the migrating hydrogen for a proton-transfer step.

    Returns {donor_idx, acceptor_idx, h_idx, donor_sym, acceptor_sym} (all 1-based).
    Raises ValueError when the step does not look like a single proton transfer.
    """
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        json_out = f.name
    try:
        subprocess.run(
            [PYTHON, str(MAP_TOOL), reactant_smiles, product_smiles,
             "--reactant-xyz", str(reactant_xyz),
             "--json-out", json_out, "--max-mappings", "1"],
            capture_output=True, text=True, check=True,
        )
        result = json.loads(Path(json_out).read_text())
    finally:
        Path(json_out).unlink(missing_ok=True)

    if not result.get("mappings"):
        raise ValueError("no atom mapping found")

    h_changes = result["mappings"][0].get("hydrogen_count_changes", [])
    donors = [c for c in h_changes if c["delta"] < 0]
    acceptors = [c for c in h_changes if c["delta"] > 0]
    if len(donors) != 1 or len(acceptors) != 1:
        raise ValueError(
            f"not a single proton transfer: {len(donors)} donor(s), "
            f"{len(acceptors)} acceptor(s) in {h_changes}"
        )

    donor_idx = int(donors[0]["reactant_atom"])
    acceptor_idx = int(acceptors[0]["reactant_atom"])

    syms, coords = read_xyz(reactant_xyz)
    d_pos, a_pos = coords[donor_idx - 1], coords[acceptor_idx - 1]

    # Of the hydrogens on the donor, the migrating one is the one already leaning
    # toward the acceptor.
    cands = [
        (np.linalg.norm(coords[i] - a_pos), i + 1)
        for i, s in enumerate(syms)
        if s == "H" and np.linalg.norm(coords[i] - d_pos) <= XH_BOND_MAX
    ]
    if not cands:
        raise ValueError(f"no hydrogen bonded to donor atom {donor_idx}")
    cands.sort()
    h_idx = cands[0][1]

    return {
        "donor_idx": donor_idx,
        "acceptor_idx": acceptor_idx,
        "h_idx": h_idx,
        "donor_sym": syms[donor_idx - 1],
        "acceptor_sym": syms[acceptor_idx - 1],
    }


def process_step(step_dir: Path, round_idx: int = 0, n_guesses: int = 9) -> dict:
    """Generate dry proton-transfer TS guesses for one step directory."""
    step_dir = Path(step_dir)
    route_json = step_dir / "yarp_route.json"
    reactant_xyz = step_dir / "reactant.xyz"
    if not route_json.exists():
        raise FileNotFoundError(f"Missing {route_json}")
    if not reactant_xyz.exists():
        raise FileNotFoundError(f"Missing {reactant_xyz}")

    route = json.loads(route_json.read_text())
    r_smi = route["reactant_smiles"]
    p_balanced_smi = route["product_balanced_smiles"]
    p_main_smi = route.get("product_main_smiles", p_balanced_smi.split(".")[0])

    print(f"  identifying proton shift: {r_smi} -> {p_main_smi}")
    info = identify_proton_shift(r_smi, p_main_smi, reactant_xyz)
    d_i, a_i, h_i = info["donor_idx"], info["acceptor_idx"], info["h_idx"]

    syms, coords = read_xyz(reactant_xyz)
    d_ha = float(np.linalg.norm(coords[h_i - 1] - coords[a_i - 1]))
    d_dh = float(np.linalg.norm(coords[h_i - 1] - coords[d_i - 1]))
    print(f"  migrating H{h_i}: {info['donor_sym']}{d_i}-H={d_dh:.2f} A, "
          f"H...{info['acceptor_sym']}{a_i}={d_ha:.2f} A")

    # Drive the forming H...acceptor bond in; the donor-H bond is left free so the
    # scan finds its own barrier rather than being forced through a chosen geometry.
    offset = round_idx * 0.05
    forming = [1.05, 1.15, 1.25, 1.35, 1.50, 1.70, 1.90]
    forming = [round(d + offset, 3) for d in forming if d + offset < d_ha]

    round_dir = step_dir / f"round_{round_idx}"
    scan = []

    print(f"  running H->acceptor scan ({len(forming)} points) ...")
    for d in forming:
        tag = f"ha_{d:.2f}"
        energy, opt_xyz = run_constrained_opt(
            reactant_xyz, h_i, a_i, d, work_dir=round_dir / tag,
        )
        if energy is None:
            print(f"    d(H-A)={d:.2f}A: FAILED")
            continue
        print(f"    d(H-A)={d:.2f}A: E={energy:.6f} Eh")
        scan.append({
            "tag": tag, "energy": energy, "xyz_path": opt_xyz,
            "mechanism": "dry_proton_scan",
            "notes": f"H{h_i}-{info['acceptor_sym']}{a_i}={d:.2f}A",
        })

    # Concerted set: stretch donor-H while the acceptor bond forms. This carries the
    # stiff 1,2-H shifts (aldose<->ketose) where a single driven coordinate slides
    # back to the reactant instead of climbing. The grid deliberately spans early to
    # late: these shifts are strongly asynchronous, e.g. the accepted HMF step-2
    # saddle sits at d(O-H)=1.48, d(H-C)=1.90 with the acceptor bond barely formed,
    # so a grid clustered around a half-transferred H would miss it.
    dual = [
        (1.15, 1.90), (1.25, 1.75), (1.35, 1.60), (1.45, 1.45),
        (1.30, 1.35), (1.35, 1.30), (1.45, 1.20), (1.55, 1.15),
    ]
    dual = [(round(dh + offset, 3), round(ha + offset, 3)) for dh, ha in dual]
    print(f"  running concerted D-H / H-A scan ({len(dual)} points) ...")
    for d_dh_t, d_ha_t in dual:
        tag = f"dual_{d_dh_t:.2f}_{d_ha_t:.2f}"
        energy, opt_xyz = run_constrained_opt_pairs(
            reactant_xyz,
            [(d_i, h_i, d_dh_t), (h_i, a_i, d_ha_t)],
            work_dir=round_dir / tag,
        )
        if energy is None:
            print(f"    d(D-H)={d_dh_t:.2f} d(H-A)={d_ha_t:.2f}: FAILED")
            continue
        print(f"    d(D-H)={d_dh_t:.2f} d(H-A)={d_ha_t:.2f}: E={energy:.6f} Eh")
        scan.append({
            "tag": tag, "energy": energy, "xyz_path": opt_xyz,
            "mechanism": "dry_proton_concerted",
            "notes": f"D{d_i}-H{h_i}={d_dh_t:.2f}A, H{h_i}-A{a_i}={d_ha_t:.2f}A",
        })

    if not scan:
        raise RuntimeError("all constrained optimizations failed")

    scan.sort(key=lambda x: x["energy"], reverse=True)
    selected = scan[:n_guesses]
    print(f"  selected {len(selected)} guesses (highest energy)")

    guesses = []
    for sr in selected:
        if not (sr["xyz_path"] and sr["xyz_path"].exists()):
            continue
        guess_xyz = round_dir / sr["tag"] / "guess.xyz"
        opt_syms, opt_coords = read_xyz(sr["xyz_path"])
        write_xyz(guess_xyz, opt_syms, opt_coords,
                  f"{sr['mechanism']} {sr['notes']} E(xTB)={sr['energy']:.6f} Eh")
        guesses.append({
            "guess_id": sr["tag"],
            "xyz_path": str(guess_xyz.relative_to(step_dir)),
            "mechanism": sr["mechanism"],
            "stage": sr["tag"],
            "generator_notes": f"{sr['notes']}, E(xTB)={sr['energy']:.6f} Eh",
        })

    manifest = {
        "workdir": str(step_dir),
        "round": round_idx,
        "reactant_smiles": r_smi,
        "product_smiles": p_balanced_smi,
        "charge": 0,
        "multiplicity": 1,
        "guesses": guesses,
        "proton_shift": info,
    }
    manifest_path = step_dir / f"dry_proton_manifest.round_{round_idx}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"  wrote manifest: {manifest_path}")
    return manifest


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--step-dir", type=Path, required=True)
    ap.add_argument("--round", type=int, default=0)
    ap.add_argument("--n-guesses", type=int, default=9)
    args = ap.parse_args()
    step_dir = args.step_dir if args.step_dir.is_absolute() else WS / args.step_dir
    process_step(step_dir, args.round, args.n_guesses)


if __name__ == "__main__":
    sys.exit(main())
