#!/usr/bin/env python3
"""Prepare a step directory for the path-validator agent.

Usage:
    python resources/prepare_step.py            # auto-find active step
    python resources/prepare_step.py --path N   # force prepare path N's current_step
    python resources/prepare_step.py --status   # just print status, no FS changes

For the active (path, step):
1. Create validation/path_<id>/step_<idx>/ dir
2. Copy reactant.xyz from
   - structures/glucose.xyz                   if step.idx == 0
   - validation/path_<id>/step_<idx-1>/product.xyz   otherwise
3. Write reactant_smiles.txt, target_product_smiles.txt
4. Write yarp_route.json (zwitterion/radical hints for TS guess seeding)
5. Verify reactant.xyz canonical SMILES matches step.reactant_smiles
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
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

PYTHON = _CP.PYBIN
QUEUE_PATH = ROOT / "validation" / "path_queue.json"
META_PATH = ROOT / "validation" / "meta.json"
GLUCOSE_XYZ = ROOT / "structures" / "glucose.xyz"
STRUCT_DIR = ROOT / "structures"
XYZ_TO_SMI = ROOT / "resources" / "tools" / "xyz_to_smiles.py"
SMI_TO_XYZ = ROOT / "resources" / "smi_to_xyz.py"


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in (name or "").strip().lower()).strip("_") or "seed"


def starting_structure(path: dict) -> Path:
    """Return the xyz file for step 0 of `path`. For glucose-starting paths
    this is structures/glucose.xyz; for seed-starting paths we look for / build
    structures/<slug>.xyz on demand."""
    if path.get("starts_at_glucose", True):
        return GLUCOSE_XYZ
    seed_name = path.get("starts_at_seed_name") or ""
    smi = path["steps"][0]["reactant_smiles"]
    slug = _slug(seed_name) if seed_name else f"seed_p{path['path_id']}"
    out = STRUCT_DIR / f"{slug}.xyz"
    if not out.exists():
        print(f"  [prepare] building {out.relative_to(ROOT)} for {smi!r} ...")
        subprocess.run(
            [PYTHON, str(SMI_TO_XYZ), smi, str(out), "--name", slug],
            check=True,
        )
    return out


def canon_smiles(smi: str) -> str:
    """Canonicalize SMILES with RDKit (strip stereo)."""
    try:
        from rdkit import Chem
        m = Chem.MolFromSmiles(smi)
        if m is None:
            return smi
        Chem.RemoveStereochemistry(m)
        return Chem.MolToSmiles(m)
    except Exception:
        return smi


def xyz_to_smi(xyz_path: Path) -> str | None:
    if not xyz_path.exists():
        return None
    try:
        out = subprocess.check_output(
            [PYTHON, str(XYZ_TO_SMI), str(xyz_path)], text=True, stderr=subprocess.STDOUT
        )
        # xyz_to_smiles.py prints exactly one line: the canonical SMILES (which may legitimately
        # contain '=' for double bonds). Take the last non-empty non-comment line, ignoring
        # RDKit log lines that start with a [HH:MM:SS] timestamp.
        for line in reversed(out.splitlines()):
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("["):
                continue
            return line.split()[0]
    except Exception as e:
        print(f"  [xyz_to_smiles error] {e}", file=sys.stderr)
    return None


def load_state():
    queue = json.loads(QUEUE_PATH.read_text())
    meta = json.loads(META_PATH.read_text())
    return queue, meta


def save_state(queue, meta):
    QUEUE_PATH.write_text(json.dumps(queue, indent=2))
    META_PATH.write_text(json.dumps(meta, indent=2))


def find_active(queue):
    for p in queue:
        if p["status"] == "pending":
            if p["current_step"] >= len(p["steps"]):
                continue
            step = p["steps"][p["current_step"]]
            return p, step
    return None, None


def prepare(path: dict, step: dict, meta: dict, *, dry_run=False) -> dict:
    pid = path["path_id"]
    sidx = step["step_index"]
    step_dir = ROOT / "validation" / f"path_{pid}" / f"step_{sidx}"
    # Backwards compat: support both old single product_smiles and new split fields.
    prod_main = step.get("product_main_smiles") or step.get("product_smiles")
    prod_balanced = step.get("product_balanced_smiles") or prod_main
    coproduct = step.get("coproduct")
    report = {
        "path_id": pid,
        "step_index": sidx,
        "step_dir": str(step_dir.relative_to(ROOT)),
        "reactant_smiles_expected": step["reactant_smiles"],
        "product_main_smiles": prod_main,
        "product_balanced_smiles": prod_balanced,
        "coproduct": coproduct,
        "actions": [],
    }
    if dry_run:
        return report

    step_dir.mkdir(parents=True, exist_ok=True)

    # Reactant XYZ source
    dst = step_dir / "reactant.xyz"
    src = None
    if sidx == 0:
        src = starting_structure(path)
    else:
        prev = path["steps"][sidx - 1]
        # Prefer the chained product geometry from the previous step when the
        # previous step succeeded; otherwise (independent per-step survey) build
        # the reactant geometry from this step's own SMILES.
        if prev["status"] in ("success", "skipped") and prev.get("product_xyz"):
            src = ROOT / prev["product_xyz"]

    if src is None or not src.exists():
        # Build reactant.xyz from this step's reactant SMILES (independent mode).
        print(f"  [prepare] building reactant.xyz from SMILES {step['reactant_smiles']!r}")
        r = subprocess.run(
            [PYTHON, str(SMI_TO_XYZ), step["reactant_smiles"], str(dst)],
            capture_output=True, text=True,
        )
        if not dst.exists():
            report["error"] = (
                f"could not build reactant.xyz from SMILES "
                f"{step['reactant_smiles']!r}: {r.stderr[-300:]}"
            )
            return report
        report["actions"].append("built reactant.xyz from SMILES (independent mode)")
        src = dst
    if not dst.exists() or dst.read_bytes() != src.read_bytes():
        shutil.copy(src, dst)
        report["actions"].append(f"copied reactant.xyz from {src.relative_to(ROOT)}")

    # SMILES sidecar files
    (step_dir / "reactant_smiles.txt").write_text(step["reactant_smiles"] + "\n")
    (step_dir / "product_main_smiles.txt").write_text(prod_main + "\n")
    (step_dir / "product_balanced_smiles.txt").write_text(prod_balanced + "\n")
    if coproduct:
        (step_dir / "coproduct_smiles.txt").write_text(coproduct + "\n")
    report["actions"].append(
        "wrote reactant_smiles.txt + product_main_smiles.txt + "
        "product_balanced_smiles.txt"
        + (" + coproduct_smiles.txt" if coproduct else "")
    )

    yarp_payload = {
        "reactant_smiles": step["reactant_smiles"],
        "product_main_smiles": prod_main,
        "product_balanced_smiles": prod_balanced,
        "coproduct": coproduct,
        "route_through": step.get("yarp_route_through", []),
        "comment": (
            "Use product_balanced_smiles for the map-atoms action (it includes coproducts "
            "like H2O so heavy-atom counts balance). Use product_main_smiles when comparing "
            "the next step's reactant SMILES."
        ),
    }
    (step_dir / "yarp_route.json").write_text(json.dumps(yarp_payload, indent=2))
    report["actions"].append(
        f"wrote yarp_route.json ({len(step.get('yarp_route_through', []))} hints, "
        f"coproduct={coproduct!r})"
    )

    # Verify reactant SMILES
    actual = xyz_to_smi(dst)
    if actual:
        actual_c = canon_smiles(actual)
        expected_c = canon_smiles(step["reactant_smiles"])
        report["reactant_smiles_actual"] = actual
        report["smiles_match"] = (actual_c == expected_c)
        if not report["smiles_match"]:
            report["warning"] = (
                f"reactant.xyz canon SMILES != expected\n"
                f"  expected: {expected_c}\n"
                f"  actual  : {actual_c}"
            )
    else:
        report["warning"] = "could not derive SMILES from reactant.xyz"

    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", type=int, default=None, help="force prepare this path (else auto)")
    ap.add_argument("--status", action="store_true", help="print status only, no FS changes")
    ap.add_argument("--all-pending", action="store_true",
                    help="prepare current_step for *every* pending path (useful one-shot bootstrap)")
    args = ap.parse_args()

    queue, meta = load_state()

    if args.status:
        for p in queue:
            tag = "✓" if p["status"] == "success" else ("✗" if p["status"] == "failed" else "·")
            print(
                f"{tag} Path {p['path_id']}: {p['status']:8s}  "
                f"step {p['current_step']}/{len(p['steps'])}"
            )
            if p["status"] == "pending" and p["current_step"] < len(p["steps"]):
                s = p["steps"][p["current_step"]]
                pb = s.get("product_balanced_smiles") or s.get("product_smiles")
                cop = s.get("coproduct")
                cop_tag = f"  + {cop}" if cop else ""
                print(
                    f"    next: {s['reactant_smiles']!r}\n"
                    f"       → {pb!r}{cop_tag}"
                )
        return

    if args.all_pending:
        targets = []
        for p in queue:
            if p["status"] == "pending" and p["current_step"] < len(p["steps"]):
                targets.append((p, p["steps"][p["current_step"]]))
    elif args.path is not None:
        target = next((p for p in queue if p["path_id"] == args.path), None)
        if not target:
            sys.exit(f"path {args.path} not found")
        if target["current_step"] >= len(target["steps"]):
            sys.exit(f"path {args.path} has no current_step ({target['status']})")
        targets = [(target, target["steps"][target["current_step"]])]
    else:
        path, step = find_active(queue)
        if not path:
            print("No pending paths.")
            return
        targets = [(path, step)]

    for path, step in targets:
        rpt = prepare(path, step, meta)
        print(json.dumps(rpt, indent=2, ensure_ascii=False))
        print()


if __name__ == "__main__":
    main()
