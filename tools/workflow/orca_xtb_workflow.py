#!/usr/bin/env python3
"""Run a fixed ORCA+xTB TS-validation workflow for a manifest of TS guesses.

This script executes, for each guess:
1. TS optimization
2. NumFreq
3. IRC
4. IRC forward endpoint optimization
5. IRC backward endpoint optimization
6. Endpoint SMILES matching against reactant/product

Expected workflow failures are recorded into each guess's `validation` block.
Unexpected code/runtime errors are not swallowed and will raise directly.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import shlex
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

from tools.parse_orca_output import parse_with_cclib
from tools.xyz_to_smiles import remove_stereo_from_smiles, remove_stereo_from_xyz


class StepFailure(Exception):
    """Expected workflow failure for a single guess."""

    def __init__(self, step: str, code: str, reason: str):
        super().__init__(reason)
        self.step = step
        self.code = code
        self.reason = reason


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Path to GeneratorOutput manifest JSON.")
    parser.add_argument("--output", help="Path to workflow output JSON.")
    parser.add_argument("--orca-cmd", default=os.environ.get("ORCA_CMD", "orca"))
    parser.add_argument("--n-jobs", type=int, default=1, help="Number of guesses to validate in parallel.")
    parser.add_argument("--nprocs-per-job", type=int, default=2, help="ORCA/xTB processes per job.")
    parser.add_argument("--scratch-root", default="/tmp", help="Parent directory for per-guess scratch workdirs.")
    parser.add_argument("--charge", type=int, default=0, help="Override molecular charge.")
    parser.add_argument("--multiplicity", type=int, default=1, help="Override spin multiplicity.")
    parser.add_argument(
        "--irc-method", default="xtb",
        help="Method for TS refinement, IRC, and endpoint optimisation. "
             "'xtb' (default) uses xTB throughout. A DFT method string like "
             "'r2SCAN-3c' enables Plan C: xTB TS+freq → DFT OptTS → DFT "
             "NumFreq → DFT IRC → DFT endpoint opt.",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def dump_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def relpath_or_abs(path: Path, workdir: Path) -> str:
    try:
        return str(path.resolve().relative_to(workdir.resolve()))
    except ValueError:
        return str(path.resolve())


def build_output_path(manifest: dict[str, Any]) -> Path:
    workdir = Path(manifest["workdir"])
    round_idx = manifest["round"]
    return workdir / f"orca_workflow_output.round_{round_idx}.json"


def make_validation_template() -> dict[str, Any]:
    return {
        "status": "pending",
        "failed_step": None,
        "failure_code": None,
        "failure_reason": None,
        "metrics": {
            "ts_opt_normal_termination": None,
            "numfreq_normal_termination": None,
            "irc_normal_termination": None,
            "imaginary_frequency_count": None,
            "imaginary_frequencies_cm-1": [],
            "endpoint_forward_smiles": None,
            "endpoint_backward_smiles": None,
            "endpoint_match": None,
        },
        "files": {
            "ts_opt": None,
            "numfreq": None,
            "dft_ts_opt": None,
            "dft_numfreq": None,
            "irc": None,
            "endpoint_forward_opt": None,
            "endpoint_backward_opt": None,
        },
    }


def ensure_guess_validation(guess: dict[str, Any]) -> None:
    guess["validation"] = make_validation_template()


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def run_orca(step_dir: Path, input_filename: str, output_filename: str, input_text: str, orca_cmd: str) -> Path:
    step_dir.mkdir(parents=True, exist_ok=True)
    input_path = step_dir / input_filename
    output_path = step_dir / output_filename
    write_text(input_path, input_text)

    # Ensure ORCA command uses absolute path for parallel runs
    orca_parts = shlex.split(orca_cmd)
    if orca_parts and not Path(orca_parts[0]).is_absolute():
        orca_parts[0] = str(Path(orca_parts[0]).resolve())

    command = [*orca_parts, input_filename]
    with output_path.open("w", encoding="utf-8") as handle:
        subprocess.run(
            command,
            cwd=step_dir,
            stdout=handle,
            stderr=subprocess.STDOUT,
            check=False,
        )
    return output_path


def parse_orca_output(path: Path) -> dict[str, Any]:
    return parse_with_cclib(str(path))


def terminated_normally(parsed: dict[str, Any]) -> bool:
    return bool(parsed.get("metadata", {}).get("terminated_normally"))


def opt_converged(parsed: dict[str, Any]) -> bool | None:
    value = parsed.get("opt_status", {}).get("converged")
    if value is None:
        return None
    return bool(value)


def require_normal_job(parsed: dict[str, Any], step: str, code: str, reason: str) -> None:
    if not terminated_normally(parsed):
        raise StepFailure(step, code, reason)


def require_opt_converged(parsed: dict[str, Any], step: str, code: str, reason: str) -> None:
    converged = opt_converged(parsed)
    if converged is False:
        raise StepFailure(step, code, reason)


def render_ts_opt_input(charge: int, multiplicity: int, xyz_ref: str, nprocs: int) -> str:
    return (
        "! XTB OptTS TightOpt\n\n"
        f"%pal nprocs {nprocs} end\n\n"
        f"%xtb NPROCS {nprocs} end\n\n"
        "%geom\n"
        "   Calc_Hess true\n"
        "   Recalc_Hess 5\n"
        "   MaxIter 200\n"
        "end\n\n"
        f"* xyzfile {charge} {multiplicity} {xyz_ref} *\n"
    )


def render_numfreq_input(charge: int, multiplicity: int, xyz_ref: str, nprocs: int) -> str:
    return (
        "! XTB NumFreq\n\n"
        f"%pal nprocs {nprocs} end\n\n"
        f"%xtb NPROCS {nprocs} ACCURACY 1.0 end\n\n"
        f"* xyzfile {charge} {multiplicity} {xyz_ref} *\n"
    )


def render_irc_input(charge: int, multiplicity: int, xyz_ref: str, nprocs: int) -> str:
    return (
        "! XTB IRC\n\n"
        f"%pal nprocs {nprocs} end\n\n"
        f"%xtb NPROCS {nprocs} ACCURACY 1.0 end\n\n"
        "%irc\n"
        "   Direction both\n"
        "   HessMode 0\n"
        "   MaxIter 100\n"
        "end\n\n"
        f"* xyzfile {charge} {multiplicity} {xyz_ref} *\n"
    )


def render_opt_input(charge: int, multiplicity: int, xyz_ref: str, nprocs: int) -> str:
    return (
        "! XTB Opt\n\n"
        f"%pal nprocs {nprocs} end\n\n"
        f"%xtb NPROCS {nprocs} end\n\n"
        f"* xyzfile {charge} {multiplicity} {xyz_ref} *\n"
    )


# ---------------------------------------------------------------------------
# DFT render functions (Plan B: xTB TS opt+freq → DFT IRC+endpoint opt)
# ---------------------------------------------------------------------------

def render_dft_ts_opt_input(
    charge: int, multiplicity: int, xyz_ref: str, nprocs: int,
    method: str = "r2SCAN-3c", hess_file: str | None = None,
) -> str:
    if hess_file:
        hess_block = (
            "  Calc_Hess false\n"
            f"  InHessName \"{hess_file}\"\n"
        )
    else:
        hess_block = "  Calc_Hess true\n"
    return (
        f"! {method} OptTS TightOpt\n\n"
        f"%pal nprocs {nprocs} end\n\n"
        f"%maxcore 3000\n\n"
        "%geom\n"
        f"{hess_block}"
        "  Recalc_Hess 5\n"
        "  MaxIter 200\n"
        "end\n\n"
        f"* xyzfile {charge} {multiplicity} {xyz_ref} *\n"
    )


def render_dft_numfreq_input(
    charge: int, multiplicity: int, xyz_ref: str, nprocs: int,
    method: str = "r2SCAN-3c",
) -> str:
    return (
        f"! {method} NumFreq\n\n"
        f"%pal nprocs {nprocs} end\n\n"
        f"%maxcore 3000\n\n"
        f"* xyzfile {charge} {multiplicity} {xyz_ref} *\n"
    )


def render_dft_irc_input(
    charge: int, multiplicity: int, xyz_ref: str, nprocs: int,
    method: str = "r2SCAN-3c", hess_file: str | None = None,
) -> str:
    hess_block = ""
    if hess_file:
        hess_block = f"  InitHess read\n  Hess_Filename \"{hess_file}\"\n"
    return (
        f"! {method} IRC\n\n"
        f"%pal nprocs {nprocs} end\n\n"
        f"%maxcore 3000\n\n"
        "%irc\n"
        "  Direction both\n"
        "  HessMode 0\n"
        f"{hess_block}"
        "  MaxIter 80\n"
        "end\n\n"
        f"* xyzfile {charge} {multiplicity} {xyz_ref} *\n"
    )


def render_dft_opt_input(
    charge: int, multiplicity: int, xyz_ref: str, nprocs: int,
    method: str = "r2SCAN-3c",
) -> str:
    return (
        f"! {method} Opt\n\n"
        f"%pal nprocs {nprocs} end\n\n"
        f"%maxcore 3000\n\n"
        f"* xyzfile {charge} {multiplicity} {xyz_ref} *\n"
    )


def prepare_guess_xyz(source_xyz: Path, guess_dir: Path) -> Path:
    target_xyz = guess_dir / "guess.xyz"
    guess_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_xyz, target_xyz)
    return target_xyz


def create_scratch_guess_dir(scratch_root: Path, round_idx: int, guess_id: str) -> Path:
    scratch_root.mkdir(parents=True, exist_ok=True)
    safe_guess_id = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in guess_id)
    prefix = f"reactionagent_round_{round_idx}_{safe_guess_id}_"
    return Path(tempfile.mkdtemp(prefix=prefix, dir=scratch_root))


def remap_guess_path(path: Path, scratch_guess_dir: Path, published_guess_dir: Path) -> Path:
    return published_guess_dir / path.resolve().relative_to(scratch_guess_dir.resolve())


def reset_published_guess_dir(guess_dir: Path) -> None:
    generated_entries = (
        "guess.xyz",
        "ts_opt",
        "numfreq",
        "irc",
        "endpoint_forward_opt",
        "endpoint_backward_opt",
    )
    guess_dir.mkdir(parents=True, exist_ok=True)
    for name in generated_entries:
        target = guess_dir / name
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()


def sync_guess_dir(scratch_guess_dir: Path, published_guess_dir: Path) -> None:
    reset_published_guess_dir(published_guess_dir)
    for child in scratch_guess_dir.iterdir():
        destination = published_guess_dir / child.name
        if child.is_dir():
            shutil.copytree(child, destination)
        else:
            shutil.copy2(child, destination)


def normalize_expected_smiles(manifest: dict[str, Any]) -> list[str]:
    return sorted(
        [
            remove_stereo_from_smiles(manifest["reactant_smiles"]),
            remove_stereo_from_smiles(manifest["product_smiles"]),
        ]
    )


def _fragments_formula(smi: str) -> list[str]:
    """Return sorted list of molecular formulas for each '.'-separated fragment.
    Used as a coarse "isomeric form" comparator (handles zwitterions, ring-open
    tautomers, proton-shifted resonance forms — anything with the same atoms)."""
    try:
        from rdkit.Chem import rdMolDescriptors
        from rdkit import Chem
        out = []
        for p in (smi or "").split("."):
            m = Chem.MolFromSmiles(p)
            if m is None:
                return []
            out.append(rdMolDescriptors.CalcMolFormula(m))
        return sorted(out)
    except Exception:
        return []


def _is_isomeric_form(observed: str, expected: str) -> bool:
    """True iff `observed` has the same multi-fragment molecular formula as
    `expected` (heavy atom & hydrogen counts identical). Catches xTB-IRC
    artifacts where one endpoint slides into a ring-opened zwitterion / tautomer
    of the expected species while the TS itself is still the right reaction."""
    fa, fb = _fragments_formula(observed), _fragments_formula(expected)
    return bool(fa) and fa == fb


def _strip_water(smi: str) -> str:
    """Remove water fragments (O, [H]O[H]) from a dot-separated SMILES.
    For dehydration endpoints where the IRC gives product.H2O."""
    from rdkit import Chem
    frags = smi.split(".")
    water_smis = {"O", "[H]O[H]"}
    non_water = [f for f in frags if f not in water_smis]
    return ".".join(sorted(non_water)) if non_water else smi


def _inchi_connectivity(smi: str) -> str | None:
    """Return the InChI connectivity skeleton (formula + /c layer) for a SMILES.
    This is the same for tautomers and proton-shifted zwitterions."""
    from rdkit import Chem
    from rdkit.Chem.inchi import MolToInchi
    try:
        mol = Chem.MolFromSmiles(smi)
        if mol is None:
            return None
        inchi = MolToInchi(mol)
        if not inchi:
            return None
        return inchi.rsplit("/h", 1)[0]
    except Exception:
        return None


def _is_tautomer_match(smi: str, ref: str) -> bool:
    """True if smi and ref share the same InChI connectivity (tautomer/zwitterion)."""
    ca = _inchi_connectivity(smi)
    cb = _inchi_connectivity(ref)
    return bool(ca) and ca == cb


def _normalize_endpoint(smi: str, ref: str) -> str:
    """Try to match an endpoint SMILES against a reference by stripping water
    and/or checking tautomer/zwitterion equivalence via InChI connectivity."""
    if smi == ref:
        return smi
    stripped = _strip_water(smi)
    if stripped == ref:
        return stripped
    # Under the user's exact-SMILES bar, do NOT collapse tautomers/zwitterions
    # onto the reference; only exact (optionally water-stripped) matches count.
    if os.environ.get("EXACT_SMILES_ONLY", "1") == "1":
        return smi
    if _is_tautomer_match(stripped, ref):
        return ref
    if _is_tautomer_match(smi, ref):
        return ref
    return smi

def classify_endpoint_match(
    forward: str,
    backward: str,
    reactant: str,
    product: str,
) -> tuple[str, str]:
    """Return (match_kind, summary) where match_kind is one of:
      - 'strict'                 : both endpoints exact-match expected
      - 'product_match'          : at least one endpoint EXACTLY matches the
                                   expected product; the other side is any
                                   reasonable form (strict reactant / isomeric
                                   form / open-chain tautomer / zwitterion).
      - 'mismatch'               : neither endpoint exact-matches the expected
                                   product → reject.
    For dehydration reactions, endpoint SMILES may contain water fragments
    (e.g. 'O.product_smi'); these are stripped for comparison.
    """
    R = remove_stereo_from_smiles(reactant)
    P = remove_stereo_from_smiles(product)
    forward = remove_stereo_from_smiles(forward)
    backward = remove_stereo_from_smiles(backward)

    fwd_norm = _normalize_endpoint(forward, P)
    bwd_norm = _normalize_endpoint(backward, P)
    fwd_norm_r = _normalize_endpoint(forward, R)
    bwd_norm_r = _normalize_endpoint(backward, R)

    # Strict: both endpoints exact-match expected (water-stripped).
    obs_sorted = sorted([fwd_norm if fwd_norm == P else fwd_norm_r,
                         bwd_norm if bwd_norm == P else bwd_norm_r])
    exp_sorted = sorted([R, P])
    if obs_sorted == exp_sorted:
        return "strict", "both endpoints exact-match expected"

    # Also try raw comparison.
    if sorted([forward, backward]) == exp_sorted:
        return "strict", "both endpoints exact-match expected"

    # User's bar: EXACT neutral SMILES double-end matching ONLY.  When
    # EXACT_SMILES_ONLY is set (default), do NOT accept InChI-connectivity
    # (tautomer/zwitterion) matches or one-sided product matches as passing.
    if os.environ.get("EXACT_SMILES_ONLY", "1") == "1":
        return "mismatch", (
            f"exact-SMILES-only: endpoints do not both exact-match expected. "
            f"fwd={forward}, bwd={backward}, expected R={R} P={P}"
        )

    # Fallback strict: use InChI connectivity to handle canonicalization artifacts
    # (e.g. allenes C=C=C getting converted to charged forms by RDKit).
    fwd_s = _strip_water(forward)
    bwd_s = _strip_water(backward)
    if ((_is_tautomer_match(fwd_s, R) and _is_tautomer_match(bwd_s, P)) or
        (_is_tautomer_match(fwd_s, P) and _is_tautomer_match(bwd_s, R))):
        return "strict", "both endpoints match expected (InChI connectivity)"

    # Product-match: at least one observed endpoint == expected product.
    p_match = (fwd_norm == P or bwd_norm == P or forward == P or backward == P)
    if p_match:
        if fwd_norm == P or forward == P:
            other = backward
            other_norm = bwd_norm_r
        else:
            other = forward
            other_norm = fwd_norm_r
        if other_norm == R or other == R:
            other_kind = "strict_reactant"
        elif _is_isomeric_form(other, R):
            other_kind = "isomer_of_reactant"
        else:
            other_kind = "unrelated"
        return "product_match", f"one endpoint exact-matches product; other={other_kind} ({other})"

    return "mismatch", (
        f"no endpoint exact-matches expected product. "
        f"fwd={forward}, bwd={backward}, expected_P={P}"
    )


def record_step_file(
    validation: dict[str, Any],
    key: str,
    workdir: Path,
    published_guess_dir: Path,
    scratch_guess_dir: Path,
    step_dir: Path,
    input_path: Path,
    out_path: Path,
    *,
    traj_xyz: Path | None = None,
    final_xyz: Path | None = None,
    full_trj_xyz: Path | None = None,
    forward_endpoint_xyz: Path | None = None,
    backward_endpoint_xyz: Path | None = None,
    smiles: str | None = None,
) -> None:
    published_step_dir = remap_guess_path(step_dir, scratch_guess_dir, published_guess_dir)
    payload: dict[str, Any] = {
        "workdir": relpath_or_abs(published_step_dir, workdir),
        "input": relpath_or_abs(remap_guess_path(input_path, scratch_guess_dir, published_guess_dir), workdir),
        "out": relpath_or_abs(remap_guess_path(out_path, scratch_guess_dir, published_guess_dir), workdir),
    }
    if traj_xyz is not None:
        payload["traj_xyz"] = (
            relpath_or_abs(remap_guess_path(traj_xyz, scratch_guess_dir, published_guess_dir), workdir)
            if traj_xyz.exists()
            else None
        )
    if final_xyz is not None:
        payload["final_xyz"] = (
            relpath_or_abs(remap_guess_path(final_xyz, scratch_guess_dir, published_guess_dir), workdir)
            if final_xyz.exists()
            else None
        )
    if full_trj_xyz is not None:
        payload["full_trj_xyz"] = (
            relpath_or_abs(remap_guess_path(full_trj_xyz, scratch_guess_dir, published_guess_dir), workdir)
            if full_trj_xyz.exists()
            else None
        )
    if forward_endpoint_xyz is not None:
        payload["forward_endpoint_xyz"] = (
            relpath_or_abs(remap_guess_path(forward_endpoint_xyz, scratch_guess_dir, published_guess_dir), workdir)
            if forward_endpoint_xyz.exists()
            else None
        )
    if backward_endpoint_xyz is not None:
        payload["backward_endpoint_xyz"] = (
            relpath_or_abs(remap_guess_path(backward_endpoint_xyz, scratch_guess_dir, published_guess_dir), workdir)
            if backward_endpoint_xyz.exists()
            else None
        )
    if smiles is not None:
        payload["smiles"] = smiles
    validation["files"][key] = payload


def resolve_charge_multiplicity(manifest: dict[str, Any], args: argparse.Namespace) -> tuple[int, int]:
    charge = args.charge if args.charge is not None else manifest.get("charge", 0)
    multiplicity = args.multiplicity if args.multiplicity is not None else manifest.get("multiplicity", 1)
    return int(charge), int(multiplicity)


def run_single_guess(guess: dict[str, Any], manifest: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    guess = copy.deepcopy(guess)
    ensure_guess_validation(guess)

    validation = guess["validation"]
    validation["status"] = "running"

    workdir = Path(manifest["workdir"]).resolve()
    round_idx = manifest["round"]
    guess_id = guess["guess_id"]
    published_guess_dir = workdir / f"round_{round_idx}" / guess_id
    scratch_guess_dir = create_scratch_guess_dir(Path(args.scratch_root).resolve(), round_idx, guess_id)
    source_xyz = Path(guess["xyz_path"])
    if not source_xyz.is_absolute():
        source_xyz = (workdir / source_xyz).resolve()

    charge, multiplicity = resolve_charge_multiplicity(manifest, args)
    expected_smiles = normalize_expected_smiles(manifest)

    try:
        prepare_guess_xyz(source_xyz, scratch_guess_dir)

        guess_dir = scratch_guess_dir
        ts_opt_dir = guess_dir / "ts_opt"
        ts_opt_out = run_orca(
            ts_opt_dir,
            "ts_opt.inp",
            "ts_opt.out",
            render_ts_opt_input(charge, multiplicity, "../guess.xyz", args.nprocs_per_job),
            args.orca_cmd,
        )
        ts_opt_input = ts_opt_dir / "ts_opt.inp"
        ts_opt_trj = ts_opt_dir / "ts_opt_trj.xyz"
        ts_opt_xyz = ts_opt_dir / "ts_opt.xyz"
        record_step_file(
            validation,
            "ts_opt",
            workdir,
            published_guess_dir,
            scratch_guess_dir,
            ts_opt_dir,
            ts_opt_input,
            ts_opt_out,
            traj_xyz=ts_opt_trj,
            final_xyz=ts_opt_xyz,
        )
        ts_opt_parsed = parse_orca_output(ts_opt_out)
        validation["metrics"]["ts_opt_normal_termination"] = terminated_normally(ts_opt_parsed)
        ts_energy_data = ts_opt_parsed.get("energy", {})
        if ts_energy_data.get("final_energy_hartree") is not None:
            validation["metrics"]["ts_energy_hartree"] = ts_energy_data["final_energy_hartree"]
        require_normal_job(
            ts_opt_parsed,
            "ts_opt",
            "ts_opt_abnormal_termination",
            "TS optimization did not terminate normally.",
        )
        require_opt_converged(
            ts_opt_parsed,
            "ts_opt",
            "unknown_failure",
            "TS optimization terminated but did not converge.",
        )
        if not ts_opt_xyz.exists():
            raise StepFailure("ts_opt", "ts_opt_no_output", "TS optimization finished without ts_opt.xyz.")

        numfreq_dir = guess_dir / "numfreq"
        numfreq_out = run_orca(
            numfreq_dir,
            "ts_freq.inp",
            "ts_freq.out",
            render_numfreq_input(charge, multiplicity, "../ts_opt/ts_opt.xyz", args.nprocs_per_job),
            args.orca_cmd,
        )
        numfreq_input = numfreq_dir / "ts_freq.inp"
        record_step_file(
            validation,
            "numfreq",
            workdir,
            published_guess_dir,
            scratch_guess_dir,
            numfreq_dir,
            numfreq_input,
            numfreq_out,
        )
        numfreq_parsed = parse_orca_output(numfreq_out)
        validation["metrics"]["numfreq_normal_termination"] = terminated_normally(numfreq_parsed)
        require_normal_job(
            numfreq_parsed,
            "numfreq",
            "numfreq_abnormal_termination",
            "NumFreq did not terminate normally.",
        )
        imag_count = numfreq_parsed.get("freqs", {}).get("n_imaginary")
        imag_values = numfreq_parsed.get("imag_freqs", {}).get("imaginary_freqs_cm-1", [])
        if imag_count is None:
            raise RuntimeError(f"Failed to parse imaginary frequency count from {numfreq_out}")
        validation["metrics"]["imaginary_frequency_count"] = imag_count
        validation["metrics"]["imaginary_frequencies_cm-1"] = imag_values
        if imag_count == 0:
            raise StepFailure("numfreq", "numfreq_zero_imaginary", "NumFreq found zero imaginary frequencies.")
        if imag_count != 1:
            raise StepFailure(
                "numfreq",
                "numfreq_multiple_imaginary",
                f"NumFreq found {imag_count} imaginary frequencies.",
            )

        use_dft_irc = args.irc_method.lower() != "xtb"
        validation["metrics"]["irc_method"] = args.irc_method

        # The geometry used as input for IRC (may be upgraded to DFT TS below)
        irc_ts_xyz_ref = "../ts_opt/ts_opt.xyz"

        # ---- Plan C: DFT OptTS + DFT NumFreq when DFT IRC is requested ----
        if use_dft_irc:
            dft_ts_dir = guess_dir / "dft_ts_opt"
            xtb_hess = guess_dir / "numfreq" / "ts_freq.hess"
            dft_ts_hess_ref = "../numfreq/ts_freq.hess" if xtb_hess.exists() else None
            dft_ts_out = run_orca(
                dft_ts_dir,
                "dft_ts_opt.inp",
                "dft_ts_opt.out",
                render_dft_ts_opt_input(
                    charge, multiplicity, "../ts_opt/ts_opt.xyz",
                    args.nprocs_per_job, method=args.irc_method,
                    hess_file=dft_ts_hess_ref,
                ),
                args.orca_cmd,
            )
            dft_ts_input = dft_ts_dir / "dft_ts_opt.inp"
            dft_ts_xyz = dft_ts_dir / "dft_ts_opt.xyz"
            dft_ts_trj = dft_ts_dir / "dft_ts_opt_trj.xyz"
            record_step_file(
                validation, "dft_ts_opt", workdir, published_guess_dir,
                scratch_guess_dir, dft_ts_dir, dft_ts_input, dft_ts_out,
                traj_xyz=dft_ts_trj, final_xyz=dft_ts_xyz,
            )
            dft_ts_parsed = parse_orca_output(dft_ts_out)
            validation["metrics"]["dft_ts_opt_normal_termination"] = terminated_normally(dft_ts_parsed)
            require_normal_job(
                dft_ts_parsed, "dft_ts_opt", "dft_ts_opt_abnormal_termination",
                "DFT TS optimization did not terminate normally.",
            )
            require_opt_converged(
                dft_ts_parsed, "dft_ts_opt", "dft_ts_opt_not_converged",
                "DFT TS optimization terminated but did not converge.",
            )
            if not dft_ts_xyz.exists():
                raise StepFailure("dft_ts_opt", "dft_ts_opt_no_output",
                                  "DFT TS optimization finished without output xyz.")

            dft_nf_dir = guess_dir / "dft_numfreq"
            dft_nf_out = run_orca(
                dft_nf_dir,
                "dft_freq.inp",
                "dft_freq.out",
                render_dft_numfreq_input(
                    charge, multiplicity, "../dft_ts_opt/dft_ts_opt.xyz",
                    args.nprocs_per_job, method=args.irc_method,
                ),
                args.orca_cmd,
            )
            dft_nf_input = dft_nf_dir / "dft_freq.inp"
            record_step_file(
                validation, "dft_numfreq", workdir, published_guess_dir,
                scratch_guess_dir, dft_nf_dir, dft_nf_input, dft_nf_out,
            )
            dft_nf_parsed = parse_orca_output(dft_nf_out)
            validation["metrics"]["dft_numfreq_normal_termination"] = terminated_normally(dft_nf_parsed)
            require_normal_job(
                dft_nf_parsed, "dft_numfreq", "dft_numfreq_abnormal_termination",
                "DFT NumFreq did not terminate normally.",
            )
            dft_imag_count = dft_nf_parsed.get("freqs", {}).get("n_imaginary")
            dft_imag_values = dft_nf_parsed.get("imag_freqs", {}).get("imaginary_freqs_cm-1", [])
            validation["metrics"]["dft_imaginary_frequency_count"] = dft_imag_count
            validation["metrics"]["dft_imaginary_frequencies_cm-1"] = dft_imag_values
            if dft_imag_count == 0:
                raise StepFailure("dft_numfreq", "dft_numfreq_zero_imaginary",
                                  "DFT NumFreq found zero imaginary frequencies — not a TS at DFT level.")
            if dft_imag_count is not None and dft_imag_count > 1:
                sorted_imag = sorted(dft_imag_values, key=abs, reverse=True)
                secondary_imag = sorted_imag[1] if len(sorted_imag) > 1 else 0.0
                if abs(secondary_imag) > 100.0:
                    raise StepFailure(
                        "dft_numfreq", "dft_numfreq_multiple_imaginary",
                        f"DFT NumFreq found {dft_imag_count} imaginary frequencies: "
                        f"{dft_imag_values}. Secondary mode too large ({secondary_imag:.1f} cm-1).",
                    )

            dft_ts_energy = dft_nf_parsed.get("energy", {}).get("final_energy_hartree")
            if dft_ts_energy is not None:
                validation["metrics"]["dft_ts_energy_hartree"] = dft_ts_energy

            irc_ts_xyz_ref = "../dft_ts_opt/dft_ts_opt.xyz"

        irc_dir = guess_dir / "irc"
        if use_dft_irc:
            dft_hess_file = "../dft_numfreq/dft_freq.hess"
            dft_hess_path = guess_dir / "dft_numfreq" / "dft_freq.hess"
            if not dft_hess_path.exists():
                dft_hess_file = None
            irc_input_text = render_dft_irc_input(
                charge, multiplicity, irc_ts_xyz_ref,
                args.nprocs_per_job, method=args.irc_method,
                hess_file=dft_hess_file,
            )
        else:
            irc_input_text = render_irc_input(
                charge, multiplicity, irc_ts_xyz_ref, args.nprocs_per_job,
            )
        irc_out = run_orca(
            irc_dir,
            "irc.inp",
            "irc.out",
            irc_input_text,
            args.orca_cmd,
        )
        irc_input = irc_dir / "irc.inp"
        irc_full_trj = irc_dir / "irc_IRC_Full_trj.xyz"
        irc_forward_xyz = irc_dir / "irc_IRC_F.xyz"
        irc_backward_xyz = irc_dir / "irc_IRC_B.xyz"
        record_step_file(
            validation,
            "irc",
            workdir,
            published_guess_dir,
            scratch_guess_dir,
            irc_dir,
            irc_input,
            irc_out,
            full_trj_xyz=irc_full_trj,
            forward_endpoint_xyz=irc_forward_xyz,
            backward_endpoint_xyz=irc_backward_xyz,
        )
        irc_parsed = parse_orca_output(irc_out)
        validation["metrics"]["irc_normal_termination"] = terminated_normally(irc_parsed)
        require_normal_job(
            irc_parsed,
            "irc",
            "irc_abnormal_termination",
            "IRC did not terminate normally.",
        )
        if not irc_forward_xyz.exists() or not irc_backward_xyz.exists():
            raise StepFailure("irc", "unknown_failure", "IRC finished without both endpoint xyz files.")

        endpoint_forward_dir = guess_dir / "endpoint_forward_opt"
        if use_dft_irc:
            fwd_opt_text = render_dft_opt_input(
                charge, multiplicity, "../irc/irc_IRC_F.xyz",
                args.nprocs_per_job, method=args.irc_method,
            )
        else:
            fwd_opt_text = render_opt_input(
                charge, multiplicity, "../irc/irc_IRC_F.xyz", args.nprocs_per_job,
            )
        endpoint_forward_out = run_orca(
            endpoint_forward_dir,
            "opt.inp",
            "opt.out",
            fwd_opt_text,
            args.orca_cmd,
        )
        endpoint_forward_input = endpoint_forward_dir / "opt.inp"
        endpoint_forward_xyz = endpoint_forward_dir / "opt.xyz"
        endpoint_forward_trj = endpoint_forward_dir / "opt_trj.xyz"
        record_step_file(
            validation,
            "endpoint_forward_opt",
            workdir,
            published_guess_dir,
            scratch_guess_dir,
            endpoint_forward_dir,
            endpoint_forward_input,
            endpoint_forward_out,
            traj_xyz=endpoint_forward_trj,
            final_xyz=endpoint_forward_xyz,
        )
        endpoint_forward_parsed = parse_orca_output(endpoint_forward_out)
        fwd_opt_ok = (terminated_normally(endpoint_forward_parsed)
                      and endpoint_forward_parsed.get("geometry_converged", False))
        if not fwd_opt_ok:
            print(f"  [WARN] Forward endpoint opt did not converge; using IRC endpoint geometry.")
            irc_fwd_xyz = guess_dir / "irc" / "irc_IRC_F.xyz"
            if irc_fwd_xyz.exists():
                shutil.copy(irc_fwd_xyz, endpoint_forward_xyz)
            elif not endpoint_forward_xyz.exists():
                raise StepFailure("endpoint_opt", "endpoint_forward_opt_failed",
                                  "Forward endpoint opt.xyz is missing and IRC endpoint unavailable.")

        endpoint_backward_dir = guess_dir / "endpoint_backward_opt"
        if use_dft_irc:
            bwd_opt_text = render_dft_opt_input(
                charge, multiplicity, "../irc/irc_IRC_B.xyz",
                args.nprocs_per_job, method=args.irc_method,
            )
        else:
            bwd_opt_text = render_opt_input(
                charge, multiplicity, "../irc/irc_IRC_B.xyz", args.nprocs_per_job,
            )
        endpoint_backward_out = run_orca(
            endpoint_backward_dir,
            "opt.inp",
            "opt.out",
            bwd_opt_text,
            args.orca_cmd,
        )
        endpoint_backward_input = endpoint_backward_dir / "opt.inp"
        endpoint_backward_xyz = endpoint_backward_dir / "opt.xyz"
        endpoint_backward_trj = endpoint_backward_dir / "opt_trj.xyz"
        record_step_file(
            validation,
            "endpoint_backward_opt",
            workdir,
            published_guess_dir,
            scratch_guess_dir,
            endpoint_backward_dir,
            endpoint_backward_input,
            endpoint_backward_out,
            traj_xyz=endpoint_backward_trj,
            final_xyz=endpoint_backward_xyz,
        )
        endpoint_backward_parsed = parse_orca_output(endpoint_backward_out)
        bwd_opt_ok = (terminated_normally(endpoint_backward_parsed)
                      and endpoint_backward_parsed.get("geometry_converged", False))
        if not bwd_opt_ok:
            print(f"  [WARN] Backward endpoint opt did not converge; using IRC endpoint geometry.")
            irc_bwd_xyz = guess_dir / "irc" / "irc_IRC_B.xyz"
            if irc_bwd_xyz.exists():
                shutil.copy(irc_bwd_xyz, endpoint_backward_xyz)
            elif not endpoint_backward_xyz.exists():
                raise StepFailure("endpoint_opt", "endpoint_backward_opt_failed",
                                  "Backward endpoint opt.xyz is missing and IRC endpoint unavailable.")

        def _extract_xyz_energy(xyz_path):
            """Extract energy from ORCA XYZ comment line (format: '... E value')."""
            try:
                with open(xyz_path) as f:
                    _ = f.readline()
                    comment = f.readline()
                import re as _re
                m = _re.search(r'E\s+(-?\d+\.\d+)', comment)
                return float(m.group(1)) if m else None
            except Exception:
                return None

        fwd_energy_data = endpoint_forward_parsed.get("energy", {})
        bwd_energy_data = endpoint_backward_parsed.get("energy", {})
        fwd_e_val = fwd_energy_data.get("final_energy_hartree")
        bwd_e_val = bwd_energy_data.get("final_energy_hartree")
        if not fwd_opt_ok or fwd_e_val is None:
            fwd_e_val = _extract_xyz_energy(endpoint_forward_xyz)
        if not bwd_opt_ok or bwd_e_val is None:
            bwd_e_val = _extract_xyz_energy(endpoint_backward_xyz)
        if fwd_e_val is not None:
            validation["metrics"]["endpoint_forward_energy_hartree"] = fwd_e_val
        if bwd_e_val is not None:
            validation["metrics"]["endpoint_backward_energy_hartree"] = bwd_e_val

        # Use DFT TS energy when available (Plan C); fall back to xTB only
        # when IRC is also xTB — never mix theory levels for barriers.
        ts_e = validation["metrics"].get("ts_energy_hartree")
        fwd_e = validation["metrics"].get("endpoint_forward_energy_hartree")
        bwd_e = validation["metrics"].get("endpoint_backward_energy_hartree")
        if use_dft_irc:
            ts_e = validation["metrics"].get("dft_ts_energy_hartree")
        if ts_e is not None and fwd_e is not None:
            validation["metrics"]["barrier_forward_kcal"] = round((ts_e - fwd_e) * 627.509, 2)
        if ts_e is not None and bwd_e is not None:
            validation["metrics"]["barrier_backward_kcal"] = round((ts_e - bwd_e) * 627.509, 2)
        if fwd_e is not None and bwd_e is not None:
            validation["metrics"]["reaction_energy_kcal"] = round((fwd_e - bwd_e) * 627.509, 2)

        forward_smiles = remove_stereo_from_xyz(str(endpoint_forward_xyz))
        backward_smiles = remove_stereo_from_xyz(str(endpoint_backward_xyz))
        validation["metrics"]["endpoint_forward_smiles"] = forward_smiles
        validation["metrics"]["endpoint_backward_smiles"] = backward_smiles
        validation["files"]["endpoint_forward_opt"]["smiles"] = forward_smiles
        validation["files"]["endpoint_backward_opt"]["smiles"] = backward_smiles

        # Handle cases where SMILES conversion failed
        if forward_smiles is None or backward_smiles is None:
            raise StepFailure(
                "endpoint_match",
                "endpoint_smiles_mismatch",
                f"SMILES conversion failed: forward={forward_smiles}, backward={backward_smiles}",
            )

        observed_smiles = sorted([forward_smiles, backward_smiles])
        strict_only = os.environ.get("ENDPOINT_MATCH_STRICT", "1") == "1"
        match_kind, match_summary = classify_endpoint_match(
            forward_smiles,
            backward_smiles,
            manifest["reactant_smiles"],
            manifest["product_smiles"],
        )
        validation["metrics"]["endpoint_match"] = match_kind == "strict"
        validation["metrics"]["endpoint_match_kind"] = match_kind
        validation["metrics"]["endpoint_match_summary"] = match_summary

        # Imag-freq guard: require a real reactive mode for lenient acceptance.
        imag = validation["metrics"].get("imaginary_frequencies_cm-1") or []
        max_imag_mag = max((abs(v) for v in imag), default=0.0)
        lenient_imag_ok = max_imag_mag >= 200.0

        accepted = match_kind == "strict" or (
            not strict_only
            and match_kind == "product_match"
            and lenient_imag_ok
        )

        if not accepted:
            raise StepFailure(
                "endpoint_match",
                "endpoint_smiles_mismatch",
                (
                    f"Endpoint SMILES mismatch: kind={match_kind} ({match_summary}); "
                    f"observed={observed_smiles}, expected={expected_smiles}, "
                    f"max|imag|={max_imag_mag:.1f}cm-1, strict_only={strict_only}"
                ),
            )

        validation["status"] = "success"
        validation["failed_step"] = None
        validation["failure_code"] = None
        validation["failure_reason"] = None
        return guess

    except StepFailure as exc:
        validation["status"] = "failed"
        validation["failed_step"] = exc.step
        validation["failure_code"] = exc.code
        validation["failure_reason"] = exc.reason
        return guess
    finally:
        if scratch_guess_dir.exists() and any(scratch_guess_dir.iterdir()):
            sync_guess_dir(scratch_guess_dir, published_guess_dir)
        shutil.rmtree(scratch_guess_dir, ignore_errors=True)


def run_workflow(manifest: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    guesses = manifest["guesses"]
    results: list[dict[str, Any]] = [None] * len(guesses)

    with ThreadPoolExecutor(max_workers=args.n_jobs) as executor:
        future_to_index = {
            executor.submit(run_single_guess, guess, manifest, args): index
            for index, guess in enumerate(guesses)
        }
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            results[index] = future.result()

    output = copy.deepcopy(manifest)
    output["guesses"] = results
    successful_guess_ids = [
        guess["guess_id"]
        for guess in results
        if guess["validation"]["status"] == "success"
    ]
    output["successful_guess_ids"] = successful_guess_ids
    output["if_find_ts"] = bool(successful_guess_ids)
    return output


def main() -> None:
    args = parse_args()
    input_path = Path(args.input).resolve()
    manifest = load_json(input_path)
    output = run_workflow(manifest, args)
    output_path = Path(args.output).resolve() if args.output else build_output_path(manifest)
    dump_json(output_path, output)
    print(output_path)


if __name__ == "__main__":
    main()
