#!/usr/bin/env python3
"""Fully automated TS validation driver — no LLM agent needed.

For each pending step in path_queue.json:
  1. Run prepare_step.py (ensure reactant.xyz + sidecar files exist)
  2. Run auto_guess.py (generate TS guess structures via interpolation)
  3. Run orca_xtb_workflow.py (TS opt + freq + IRC + endpoint match)
  4. Parse results: if any guess succeeded, mark step success + copy product.xyz;
     otherwise mark step failed after max_rounds.
  5. Advance to next step or next path.

Usage:
    python resources/auto_validate_driver.py                 # run all pending
    python resources/auto_validate_driver.py --max-rounds 3  # at most 3 rounds per step
    python resources/auto_validate_driver.py --dry-run        # print plan only
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

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
ORCA_CMD = os.environ.get(
    "ORCA_CMD",
    (_CP.ORCA_DIR + '/orca'),
)
QUEUE_PATH = WS / "validation" / "path_queue.json"


def load_queue():
    return json.loads(QUEUE_PATH.read_text())


def save_queue(queue):
    QUEUE_PATH.write_text(json.dumps(queue, indent=2, ensure_ascii=False))


def run_prepare(path_id: int | None = None):
    """Run prepare_step.py to set up the step directory."""
    cmd = [PYTHON, str(WS / "resources" / "prepare_step.py")]
    if path_id is not None:
        cmd += ["--path", str(path_id)]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(WS))
    print(r.stdout)
    if r.stderr:
        print(r.stderr, file=sys.stderr)
    return r.returncode == 0


# Guess-generator routing by reaction kind.  Floppy steps (ring open/close,
# isomerization, tautomerization, enolization) get a MEP-quality NEB-CI guess
# plus interpolation fillers; bond-breaking steps additionally get a constrained
# scan along the breaking/forming bond.  Pure linear interpolation alone cannot
# crack these and fragments or hits the wrong endpoint.
SCAN_KINDS = {"dehydration", "ring_opening", "ring_closure", "dehydration_aromatization"}
NEB_KINDS = {
    "ring_opening", "ring_closure", "isomerization", "enolization",
    "tautomerization", "keto_enol", "rearrangement", "dehydration",
}
# Formal proton-transfer steps: the neutral-concerted path needs an explicit
# water proton-relay, otherwise the IRC ends on an oxocarbenium/zwitterion and
# fails exact neutral-SMILES matching.  Water-relay NEB is the PRIMARY guess.
WATER_RELAY_KINDS = {
    "ring_opening", "ring_closure", "isomerization", "enolization",
    "tautomerization", "keto_enol",
}


def _run_generator(script_name: str, step_dir: Path, round_idx: int,
                   n_guesses: int, extra_env: dict, timeout: int = 4200) -> list | None:
    """Run one guess generator script and return its guesses list (or None)."""
    script = str(WS / "resources" / script_name)
    cmd = [PYTHON, script, "--step-dir", str(step_dir),
           "--round", str(round_idx), "--n-guesses", str(n_guesses)]
    if script_name == "neb_guess.py":
        # neb_guess uses --nprocs/--nimages, not --n-guesses
        cmd = [PYTHON, script, "--step-dir", str(step_dir),
               "--round", str(round_idx), "--nprocs", "8", "--nimages", "10"]
    if script_name == "water_relay_guess.py":
        # 1 water on even rounds, 2 waters on odd rounds (longer relay)
        n_w = 1 + (round_idx % 2)
        cmd = [PYTHON, script, "--step-dir", str(step_dir),
               "--round", str(round_idx), "--n-waters", str(n_w),
               "--nprocs", "8", "--nimages", "10"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(WS),
                           env=extra_env, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"    {script_name} timed out ({timeout}s)")
        return None
    if r.stdout:
        print(r.stdout[-1500:])
    if r.stderr:
        for ln in r.stderr.splitlines()[-5:]:
            print(f"    stderr: {ln}", file=sys.stderr)
    if r.returncode != 0:
        print(f"    {script_name} failed (rc={r.returncode})")
        return None
    mp = step_dir / f"auto_guess_manifest.round_{round_idx}.json"
    if not mp.exists():
        return None
    try:
        return json.loads(mp.read_text()).get("guesses", [])
    except Exception:
        return None


def run_auto_guess(step_dir: Path, round_idx: int, n_guesses: int = 9,
                   reaction_kind: str = "unknown") -> dict | None:
    """Build a COMBINED guess manifest: NEB-CI (MEP) + constrained scan +
    interpolation fillers, chosen by reaction kind.  Each generator writes
    guesses into distinct round_<r>/<guess_id>/ subfolders so they never
    collide; we merge their guess lists into the final round manifest.
    """
    env = os.environ.copy()
    env["PATH"] = (_CP.XTB_DIR + ':') + env.get("PATH", "")

    merged: list = []
    seen_ids: set[str] = set()

    def add(guesses):
        if not guesses:
            return
        for g in guesses:
            gid = g.get("guess_id")
            if gid and gid not in seen_ids:
                seen_ids.add(gid)
                merged.append(g)

    plan = []
    if reaction_kind in WATER_RELAY_KINDS:
        plan.append(("water_relay_guess.py", 1))          # primary for proton transfers
    if reaction_kind in NEB_KINDS and reaction_kind not in WATER_RELAY_KINDS:
        plan.append(("neb_guess.py", 1))                  # dry NEB (e.g. dehydration)
    if reaction_kind in SCAN_KINDS:
        plan.append(("constrained_scan_guess.py", n_guesses))
    # interpolation fillers always (cheap, sometimes the winner)
    plan.append(("auto_guess.py", n_guesses))

    print(f"  combined guess plan for '{reaction_kind}': "
          f"{', '.join(s for s, _ in plan)}")
    for script_name, ng in plan:
        print(f"  -> {script_name}")
        add(_run_generator(script_name, step_dir, round_idx, ng, env))

    if not merged:
        return None

    # Cap total guesses to keep per-round cost bounded; NEB first (already
    # ordered), then scan (energy-ranked), then interpolation fillers.
    MAX_GUESSES = 12
    if len(merged) > MAX_GUESSES:
        merged = merged[:MAX_GUESSES]

    manifest = {
        "workdir": str(step_dir.relative_to(WS)),
        "round": round_idx,
        "reactant_smiles": (step_dir / "reactant_smiles.txt").read_text().strip()
        if (step_dir / "reactant_smiles.txt").exists() else "",
        "product_smiles": (step_dir / "product_balanced_smiles.txt").read_text().strip()
        if (step_dir / "product_balanced_smiles.txt").exists() else "",
        "charge": 0,
        "multiplicity": 1,
        "guesses": merged,
    }
    manifest_path = step_dir / f"auto_guess_manifest.round_{round_idx}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"  combined manifest: {len(merged)} guesses")
    return manifest


def run_orca_workflow(manifest_path: Path, n_jobs: int = 9) -> dict | None:
    """Run orca_xtb_workflow.py and return the output."""
    output_path = manifest_path.parent / manifest_path.name.replace(
        "auto_guess_manifest", "orca_workflow_output"
    )
    cmd = [
        PYTHON, str(WS / "resources" / "orca_xtb_workflow.py"),
        "--input", str(manifest_path),
        "--output", str(output_path),
        "--orca-cmd", ORCA_CMD,
        "--n-jobs", str(n_jobs),
        "--nprocs-per-job", "1",
    ]
    print(f"  running ORCA workflow ({n_jobs} parallel jobs) ...")
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(WS), timeout=7200)
    print(r.stdout)
    if r.stderr:
        for line in r.stderr.splitlines()[-10:]:
            print(f"  stderr: {line}", file=sys.stderr)
    if output_path.exists():
        return json.loads(output_path.read_text())
    return None


def extract_product_xyz(workflow_output: dict, step_dir: Path) -> Path | None:
    """From a successful guess, extract the forward IRC endpoint as product.xyz."""
    for guess in workflow_output.get("guesses", []):
        v = guess.get("validation", {})
        if v.get("status") != "success":
            continue

        match_kind = v.get("metrics", {}).get("endpoint_match_kind", "strict")
        fwd_smi = v.get("metrics", {}).get("endpoint_forward_smiles", "")
        bwd_smi = v.get("metrics", {}).get("endpoint_backward_smiles", "")

        # Determine which endpoint is the product.
        # Need to compare with expected product SMILES.
        from tools.xyz_to_smiles import remove_stereo_from_smiles
        expected_p = remove_stereo_from_smiles(workflow_output["product_smiles"].split(".")[0])

        fwd_clean = remove_stereo_from_smiles(fwd_smi) if fwd_smi else ""
        bwd_clean = remove_stereo_from_smiles(bwd_smi) if bwd_smi else ""

        # Find the endpoint that matches the main product
        fwd_files = v.get("files", {}).get("endpoint_forward_opt", {})
        bwd_files = v.get("files", {}).get("endpoint_backward_opt", {})

        product_xyz_rel = None
        product_note = ""

        if fwd_clean == expected_p and fwd_files.get("final_xyz"):
            product_xyz_rel = fwd_files["final_xyz"]
            product_note = f"forward IRC endpoint (exact match product)"
        elif bwd_clean == expected_p and bwd_files.get("final_xyz"):
            product_xyz_rel = bwd_files["final_xyz"]
            product_note = f"backward IRC endpoint (exact match product)"
        elif fwd_files.get("final_xyz"):
            product_xyz_rel = fwd_files["final_xyz"]
            product_note = f"forward IRC endpoint (best match, kind={match_kind})"
        elif bwd_files.get("final_xyz"):
            product_xyz_rel = bwd_files["final_xyz"]
            product_note = f"backward IRC endpoint (fallback)"

        if product_xyz_rel:
            src = WS / product_xyz_rel
            if not src.exists():
                src = step_dir / product_xyz_rel
            if src.exists():
                # For multi-fragment products (dehydration), extract main product only
                dst = step_dir / "product.xyz"
                _extract_main_product(src, dst, expected_p, product_note)
                return dst

    return None


def _extract_main_product(src: Path, dst: Path, expected_main_smi: str, note: str):
    """Extract the main organic product from the IRC endpoint XYZ.

    For dehydration products, the IRC endpoint contains both the organic
    product and H₂O in one XYZ. We strip the water fragment so the next
    step gets a clean reactant geometry.
    """
    lines = src.read_text().strip().splitlines()
    n = int(lines[0].strip())
    atom_lines = lines[2:2 + n]

    # Parse atoms
    symbols = []
    coords = []
    for line in atom_lines:
        parts = line.split()
        symbols.append(parts[0])
        coords.append([float(x) for x in parts[1:4]])

    import numpy as np
    coords_arr = np.array(coords)

    # Try to detect and remove water fragment(s)
    # Water = one O + two H, all within bonding distance of each other,
    # and isolated (not bonded to the organic fragment)
    stripped_indices = _strip_water_fragments(symbols, coords_arr)

    if stripped_indices and len(stripped_indices) < n:
        out_syms = [symbols[i] for i in stripped_indices]
        out_coords = coords_arr[stripped_indices]
        out_lines = [str(len(out_syms)), f"Main product (water stripped) from {note}"]
        for sym, (x, y, z) in zip(out_syms, out_coords):
            out_lines.append(f"{sym:2s} {x:16.10f} {y:16.10f} {z:16.10f}")
        dst.write_text("\n".join(out_lines) + "\n")
        return

    # Water stripping failed (H-bonded?). Check if atom count suggests
    # extra fragments by comparing to expected_main_smi formula.
    from rdkit import Chem
    mol = Chem.MolFromSmiles(expected_main_smi)
    if mol is not None:
        expected_n = mol.GetNumAtoms()  # includes implicit H
        mol_h = Chem.AddHs(mol)
        expected_n_with_h = mol_h.GetNumAtoms()
        if n > expected_n_with_h:
            # Product XYZ has more atoms than expected → regenerate from SMILES
            print(f"    product.xyz has {n} atoms but expected {expected_n_with_h} "
                  f"for {expected_main_smi} — regenerating from SMILES")
            smi_to_xyz_script = WS / "resources" / "smi_to_xyz.py"
            if smi_to_xyz_script.exists():
                import subprocess as sp
                r = sp.run(
                    [sys.executable, str(smi_to_xyz_script),
                     expected_main_smi, str(dst)],
                    capture_output=True, text=True,
                )
                if r.returncode == 0 and dst.exists():
                    return
                print(f"    smi_to_xyz.py failed (rc={r.returncode}), keeping original")

    out_lines = [str(n), f"Main product from {note}"]
    out_lines.extend(atom_lines)
    dst.write_text("\n".join(out_lines) + "\n")


def _strip_water_fragments(
    symbols: list[str], coords: "np.ndarray"
) -> list[int] | None:
    """Identify and remove isolated H₂O fragments from an XYZ structure.
    Returns indices of atoms to KEEP, or None if no water found.
    """
    import numpy as np
    n = len(symbols)

    # Build connectivity graph (bond if distance < 1.8 Å for heavy, < 1.3 Å for O-H)
    bond_cutoffs = {
        ("C", "C"): 1.7, ("C", "O"): 1.7, ("C", "N"): 1.7,
        ("O", "O"): 1.6, ("O", "H"): 1.3, ("C", "H"): 1.3,
        ("N", "H"): 1.3, ("H", "H"): 1.0,
    }

    def cutoff(s1, s2):
        key = tuple(sorted([s1, s2]))
        return bond_cutoffs.get(key, 1.7)

    adjacency: dict[int, set[int]] = {i: set() for i in range(n)}
    for i in range(n):
        for j in range(i + 1, n):
            d = np.linalg.norm(coords[i] - coords[j])
            if d < cutoff(symbols[i], symbols[j]):
                adjacency[i].add(j)
                adjacency[j].add(i)

    # Find connected components via BFS
    visited = set()
    components: list[set[int]] = []
    for start in range(n):
        if start in visited:
            continue
        comp = set()
        queue = [start]
        while queue:
            node = queue.pop()
            if node in comp:
                continue
            comp.add(node)
            for nb in adjacency[node]:
                if nb not in comp:
                    queue.append(nb)
        visited |= comp
        components.append(comp)

    if len(components) <= 1:
        return None

    # Identify water components: exactly {O, H, H}
    water_indices: set[int] = set()
    for comp in components:
        comp_syms = sorted(symbols[i] for i in comp)
        if comp_syms == ["H", "H", "O"]:
            water_indices |= comp

    if not water_indices:
        return None

    keep = [i for i in range(n) if i not in water_indices]
    return keep


def process_one_step(path_entry: dict, step_entry: dict, max_rounds: int, n_guesses: int) -> str:
    """Process a single step. Returns 'success', 'failed', or 'error'."""
    pid = path_entry["path_id"]
    sidx = step_entry["step_index"]
    step_dir = WS / "validation" / f"path_{pid}" / f"step_{sidx}"
    ts_iso = datetime.datetime.now().isoformat(timespec="seconds")

    current_round = step_entry.get("rounds_attempted", 0)
    if current_round >= max_rounds:
        return "exhausted"

    print(f"\n  --- round {current_round} ---")

    # Generate guesses
    reaction_kind = step_entry.get("reaction_kind", "unknown")
    manifest = run_auto_guess(step_dir, current_round, n_guesses, reaction_kind)
    if manifest is None:
        step_entry["notes"] = (step_entry.get("notes") or "") + f" [auto_validate {ts_iso}: guess generation failed]"
        return "error"

    manifest_path = step_dir / f"auto_guess_manifest.round_{current_round}.json"

    # Run ORCA workflow — parallelize across all combined guesses
    n_manifest = len(manifest.get("guesses", [])) or n_guesses
    try:
        output = run_orca_workflow(manifest_path, n_jobs=min(n_manifest, 12))
    except subprocess.TimeoutExpired:
        print(f"  ORCA workflow timed out (2h)")
        step_entry["notes"] = (step_entry.get("notes") or "") + f" [auto_validate {ts_iso}: ORCA timeout round {current_round}]"
        step_entry["rounds_attempted"] = current_round + 1
        return "timeout"

    if output is None:
        step_entry["notes"] = (step_entry.get("notes") or "") + f" [auto_validate {ts_iso}: ORCA workflow produced no output]"
        step_entry["rounds_attempted"] = current_round + 1
        return "error"

    step_entry["rounds_attempted"] = current_round + 1

    # Check results
    successes = [g for g in output.get("guesses", []) if g.get("validation", {}).get("status") == "success"]

    if successes:
        best = successes[0]
        v = best["validation"]
        m = v.get("metrics", {})
        imag = m.get("imaginary_frequencies_cm-1", [])
        max_imag = min(imag) if imag else 0

        product_xyz = extract_product_xyz(output, step_dir)

        step_entry["status"] = "success"
        step_entry["ts_validated"] = {
            "guess_id": best["guess_id"],
            "ts_xyz": str((step_dir / best.get("xyz_path", "")).relative_to(WS)) if best.get("xyz_path") else None,
            "imag_freq_cm-1": max_imag,
            "irc_forward_smiles": m.get("endpoint_forward_smiles"),
            "irc_backward_smiles": m.get("endpoint_backward_smiles"),
            "endpoint_match_kind": m.get("endpoint_match_kind", "strict"),
            "note": f"Auto-validated via interpolation guess at round {current_round}",
        }
        if product_xyz and product_xyz.exists():
            step_entry["product_xyz"] = str(product_xyz.relative_to(WS))
        step_entry["notes"] = (step_entry.get("notes") or "") + (
            f" [auto_validate {ts_iso}: SUCCESS round {current_round}, "
            f"guess={best['guess_id']}, imag={max_imag:.1f}cm-1, "
            f"match_kind={m.get('endpoint_match_kind','?')}]"
        )
        return "success"
    else:
        # Summarize failures
        failures = {}
        for g in output.get("guesses", []):
            v = g.get("validation", {})
            code = v.get("failure_code", "unknown")
            failures[code] = failures.get(code, 0) + 1
        summary = ", ".join(f"{k}={v}" for k, v in sorted(failures.items()))
        step_entry["notes"] = (step_entry.get("notes") or "") + (
            f" [auto_validate {ts_iso}: round {current_round} failed ({summary})]"
        )
        return "round_failed"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-rounds", type=int, default=3, help="Max rounds per step before marking failed")
    ap.add_argument("--n-guesses", type=int, default=9, help="Guesses per round")
    ap.add_argument("--dry-run", action="store_true", help="Print plan, don't execute")
    ap.add_argument("--path", type=int, default=None, help="Process only this path_id")
    args = ap.parse_args()

    queue = load_queue()
    total_successes = 0
    total_failures = 0

    for path_entry in queue:
        if args.path is not None and path_entry["path_id"] != args.path:
            continue
        if path_entry["status"] not in ("pending",):
            continue

        pid = path_entry["path_id"]
        steps = path_entry["steps"]
        cs = path_entry["current_step"]

        while cs < len(steps):
            step = steps[cs]

            if step["status"] in ("success", "skipped"):
                cs += 1
                path_entry["current_step"] = cs
                save_queue(queue)
                continue

            print(f"\n{'='*70}")
            print(f"Path {pid} step {step['step_index']} "
                  f"({step.get('reaction_kind', '?')}: "
                  f"{step['reactant_smiles']} → {step.get('product_balanced_smiles', '?')})")
            print(f"{'='*70}")

            if args.dry_run:
                print(f"  [DRY RUN] would process this step")
                break

            # Prepare step directory
            run_prepare(pid)

            # Try rounds until success or exhausted
            result = "round_failed"
            while step.get("rounds_attempted", 0) < args.max_rounds and result == "round_failed":
                result = process_one_step(path_entry, step, args.max_rounds, args.n_guesses)
                save_queue(queue)

            if result == "success":
                total_successes += 1
                print(f"\n  ✓ Path {pid} step {step['step_index']} SUCCEEDED")
                cs += 1
                path_entry["current_step"] = cs
                save_queue(queue)
            else:
                total_failures += 1
                step["status"] = "failed"
                # Do NOT abort the whole path: each step's reactant is rebuilt
                # from SMILES by prepare_step, so steps are independent.  Keep
                # going to learn which steps clear the strict bar.
                cs += 1
                path_entry["current_step"] = cs
                save_queue(queue)
                print(f"\n  ✗ Path {pid} step {step['step_index']} FAILED after {step.get('rounds_attempted', 0)} rounds — continuing to next step")

        if cs >= len(steps):
            n_ok = sum(1 for s in steps if s["status"] in ("success", "skipped"))
            path_entry["status"] = "success" if n_ok == len(steps) else "partial"
            save_queue(queue)
            print(f"\n  ★ Path {pid} done: {n_ok}/{len(steps)} steps validated "
                  f"(status={path_entry['status']})")

    print(f"\n{'='*70}")
    print(f"DONE: {total_successes} steps succeeded, {total_failures} steps failed")
    print(f"{'='*70}")

    # Final queue summary
    queue = load_queue()
    for p in queue:
        n_done = sum(1 for s in p["steps"] if s["status"] in ("success", "skipped"))
        print(f"  Path {p['path_id']:>2}: {p['status']:<8s}  ({n_done}/{len(p['steps'])} done)")


if __name__ == "__main__":
    main()
