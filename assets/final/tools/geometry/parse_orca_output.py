#!/usr/bin/env python
"""Parse ORCA output files into compact agent-friendly summaries.

Usage:
    # List available keywords for a file
    python tools/parse_orca_output.py <orca_output_file>

    # Query specific keywords (markdown output)
    python tools/parse_orca_output.py <orca_output_file> <keyword1> [keyword2] ...

    # Query with JSON output
    python tools/parse_orca_output.py <orca_output_file> energy freqs --format json

    # Quiet mode: return just the value (for scripting)
    python tools/parse_orca_output.py <orca_output_file> imag_freq_count --quiet
    python tools/parse_orca_output.py <orca_output_file> final_energy --quiet --format json

    # Choose table format for tabular keywords
    python tools/parse_orca_output.py <orca_output_file> opt_all_steps --format csv

Output Formats:
    markdown    - Human-readable with headers (default)
    csv         - Comma-separated values for tabular data
    json        - Structured JSON for automation
    --quiet     - Minimal output: just the requested value(s)

Keywords:
    basic            - natoms, charge, multiplicity, nelectrons
    job_state        - whether the job appears finished from termination keywords
    trj_files        - matching trajectory xyz filenames for this output
    energy           - SCF energies, final energy
    thermo           - enthalpy, freeenergy, entropy, zpve, temperature, pressure
    opt_status       - optimization converged or not
    opt_convergence  - final convergence values vs thresholds
    opt_all_steps    - compact table of convergence criteria for all optimization steps
    masses           - atomic masses
    freqs            - vibrational frequencies, imaginary count
    imag_freqs       - only imaginary frequencies (if any)
    ir_intensities   - IR intensities for each mode
    irc_summary      - compact IRC path summary table
    all              - everything above

Sub-keywords (single-value queries):
    final_energy, energy_final              - final SCF energy in Hartree
    final_energy_eV                         - final SCF energy in eV
    optimization_converged, opt_converged   - boolean: optimization status
    opt_cycles                              - number of optimization steps
    imag_freq_count                         - number of imaginary frequencies
    imag_freqs_values                       - list of imaginary frequency values
"""

import json
import io
import math
import re
import sys
from pathlib import Path

try:
    import cclib
except ImportError:  # pragma: no cover - exercised in external agent environments
    cclib = None


HARTREE_TO_EV = 27.211386245988

KEYWORD_DESCRIPTIONS = {
    "basic": "natoms, charge, multiplicity, nelectrons",
    "job_state": "whether the job appears finished from termination keywords",
    "trj_files": "matching trajectory xyz filenames for this output",
    "energy": "SCF energies, final energy",
    "thermo": "enthalpy, freeenergy, entropy, zpve, temperature, pressure",
    "opt_status": "optimization converged or not",
    "opt_convergence": "final convergence values vs thresholds",
    "opt_all_steps": "compact table of convergence criteria for all optimization steps",
    "masses": "atomic masses",
    "freqs": "vibrational frequencies, imaginary count",
    "imag_freqs": "only imaginary frequencies (if any)",
    "ir_intensities": "IR intensities for each mode",
    "irc_summary": "compact IRC path summary table",
}

SUBKEYWORD_ALIASES = {
    "natoms": ("basic", "natoms"),
    "charge": ("basic", "charge"),
    "multiplicity": ("basic", "multiplicity"),
    "nelectrons": ("basic", "nelectrons"),
    "final_energy": ("energy", "final_energy_hartree"),
    "energy_final": ("energy", "final_energy_hartree"),
    "final_energy_eV": ("energy", "final_energy_eV"),
    "optimization_converged": ("opt_status", "converged"),
    "opt_converged": ("opt_status", "converged"),
    "opt_cycles": ("opt_all_steps", "n_steps"),
    "imag_freq_count": ("freqs", "n_imaginary"),
    "imag_freqs_values": ("imag_freqs", "imaginary_freqs_cm-1"),
}

KEYWORD_ALIASES = {
    "frequencies": "freqs",
    "frequency": "freqs",
    "imaginary_frequencies": "imag_freqs",
    "convergence": "opt_convergence",
    "trajectory_files": "trj_files",
}

SUPPORTED_KEYWORDS = list(KEYWORD_DESCRIPTIONS.keys())


def parse_irc_summary(filepath: str) -> dict:
    """Parse IRC PATH SUMMARY from ORCA output."""
    path = Path(filepath)
    if not path.exists():
        return {}

    text = path.read_text(errors="replace")
    if "IRC PATH SUMMARY" not in text:
        return {}

    lines = text.splitlines()
    summary_start = None
    for i, line in enumerate(lines):
        if "IRC PATH SUMMARY" in line:
            summary_start = i + 1
            break

    if summary_start is None:
        return {}

    points = []
    i = summary_start
    while i < len(lines):
        line = lines[i]
        match = re.match(
            r"\s+(\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(\d+\.\d+)\s+(\d+\.\d+)",
            line,
        )
        if match:
            points.append(
                {
                    "step": int(match.group(1)),
                    "energy_hartree": float(match.group(2)),
                    "dE_kcal_mol": float(match.group(3)),
                    "max_gradient": float(match.group(4)),
                    "rms_gradient": float(match.group(5)),
                    "is_ts": "<= TS" in line,
                }
            )
        elif points and line.strip().startswith("---"):
            break
        elif points and not line.strip():
            break
        i += 1

    if not points:
        return {}

    ts_point = None
    ts_index = None
    for idx, point in enumerate(points):
        if point["is_ts"]:
            ts_point = point
            ts_index = idx
            break

    if ts_index is not None:
        side_a = points[:ts_index]
        side_b = points[ts_index + 1 :]
    else:
        side_a = []
        side_b = points

    barriers = {}
    if ts_point is not None:
        ts_energy = ts_point["energy_hartree"]
        if side_a:
            e_min_a = min(point["energy_hartree"] for point in side_a)
            barriers["barrier_side_a_kcal_mol"] = (ts_energy - e_min_a) * 627.509
        if side_b:
            e_min_b = min(point["energy_hartree"] for point in side_b)
            barriers["barrier_side_b_kcal_mol"] = (ts_energy - e_min_b) * 627.509

    forward_converged = False
    backward_converged = False
    in_forward = False
    in_backward = False
    for line in lines:
        if "FORWARD IRC" in line and "BACKWARD" not in line:
            in_forward = True
            in_backward = False
        elif "BACKWARD IRC" in line and "FORWARD" not in line:
            in_forward = False
            in_backward = True
        elif "MAXIMUM NUMBER OF ITERATIONS REACHED" in line:
            if in_forward:
                forward_converged = False
            elif in_backward:
                backward_converged = False
        elif "THE IRC HAS CONVERGED" in line:
            if in_forward:
                forward_converged = True
            elif in_backward:
                backward_converged = True

    result = {
        "n_points": len(points),
        "ts_point": ts_point,
        "n_side_a": len(side_a),
        "n_side_b": len(side_b),
        "forward_converged": forward_converged,
        "backward_converged": backward_converged,
        "points": points,
    }
    if barriers:
        result["barriers"] = barriers
    return result


def dedupe_lines(lines: list[str]) -> list[str]:
    """Remove duplicate non-empty lines while preserving order."""
    deduped = []
    seen = set()
    for line in lines:
        normalized = line.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def ccread_with_messages(filepath: str):
    """Run cclib once and capture parser log messages instead of printing to stderr."""
    if cclib is None:
        return None, [], "cclib is not installed"

    log_buffer = io.StringIO()
    try:
        data = cclib.io.ccread(str(filepath), logstream=log_buffer)
    except Exception as exc:
        messages = dedupe_lines(log_buffer.getvalue().splitlines())
        return None, messages, str(exc)

    messages = dedupe_lines(log_buffer.getvalue().splitlines())
    return data, messages, None


def detect_calc_type(filepath: str, data=None) -> str:
    """Detect calculation type from parsed metadata with text fallback."""
    if data and hasattr(data, "metadata") and data.metadata:
        keywords = [keyword.upper() for keyword in data.metadata.get("keywords", [])]
        if "IRC" in keywords:
            return "irc"
        if "OPTTS" in keywords or "TS" in keywords:
            return "optts"
        if any("OPT" in keyword for keyword in keywords):
            return "opt"
        if "NUMFREQ" in keywords:
            return "numfreq"
        if "FREQ" in keywords:
            return "freq"

    text = Path(filepath).read_text(errors="replace")
    if "IRC PATH SUMMARY" in text:
        return "irc"
    if re.search(r"^\s*VIBRATIONAL FREQUENCIES\s*$", text, re.MULTILINE):
        return "numfreq"
    if "Geometry Optimization Run" in text:
        return "opt"
    return "unknown"


def parse_text_metadata(text: str) -> dict:
    """Parse lightweight metadata directly from ORCA text output."""
    metadata = {}

    version_match = re.search(r"Program Version\s+([0-9][^\s]*)", text)
    if version_match:
        metadata["orca_version"] = version_match.group(1)

    keyword_match = re.search(r"^\|\s+\d+>\s+!\s+(.+)$", text, re.MULTILINE)
    if keyword_match:
        metadata["keywords"] = keyword_match.group(1).split()

    warnings = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("WARNING:"):
            message = line.split("WARNING:", 1)[1].strip()
            j = i + 1
            while j < len(lines) and lines[j].lstrip().startswith("===>"):
                detail = lines[j].split(":", 1)[-1].strip()
                if detail:
                    message = f"{message}: {detail}"
                j += 1
            warnings.append(message)
            i = j
            continue
        i += 1
    if warnings:
        metadata["warnings"] = warnings

    wall_time_match = re.search(
        r"TOTAL RUN TIME:\s+(\d+)\s+days\s+(\d+)\s+hours\s+(\d+)\s+minutes\s+(\d+)\s+seconds\s+(\d+)\s+msec",
        text,
    )
    if wall_time_match:
        days, hours, minutes, seconds, millis = map(int, wall_time_match.groups())
        total_seconds = days * 86400 + hours * 3600 + minutes * 60 + seconds + millis / 1000.0
        metadata["wall_time"] = f"{total_seconds:.3f} s"

    metadata["terminated_normally"] = "****ORCA TERMINATED NORMALLY****" in text
    return metadata


def parse_text_job_state(text: str) -> dict:
    """Infer whether a job has finished from termination keywords in the output text."""
    lowered = text.lower()

    if "ORCA TERMINATED NORMALLY".lower() in lowered:
        return {
            "state": "ORCA TERMINATED NORMALLY"
        }

    terminated_keywords = [
        "terminated",
    ]
    matched = [keyword for keyword in terminated_keywords if keyword in lowered]
    finished = bool(matched)
    return {
        "state": "finished" if finished else "running_or_incomplete",
    }


def find_trj_files(filepath: str) -> dict:
    """Find trajectory xyz files associated with an ORCA output file."""
    path = Path(filepath)
    if not path.exists():
        return {}

    candidates = sorted(
        candidate.name
        for candidate in path.parent.glob(f"{path.stem}*trj*.xyz")
        if candidate.is_file()
    )
    if not candidates:
        return {}

    return {"trj_files": candidates}


def parse_text_basic(text: str, calc_type: str) -> dict:
    """Parse basic fields directly from text when cclib is unavailable or incomplete."""
    basic = {"calc_type": calc_type}

    charge_match = re.search(r"Total Charge\s+Charge\s+\.\.\.\.\s+(-?\d+)", text)
    if charge_match:
        basic["charge"] = int(charge_match.group(1))

    mult_match = re.search(r"Multiplicity\s+Mult\s+\.\.\.\.\s+(\d+)", text)
    if mult_match:
        basic["multiplicity"] = int(mult_match.group(1))

    electron_match = re.search(r"Number of Electrons\s+NEL\s+\.\.\.\.\s+(\d+)", text)
    if electron_match:
        basic["nelectrons"] = int(electron_match.group(1))

    natoms_match = re.search(r"Number of atoms\s+\.\.\.\.\s+(\d+)", text)
    if natoms_match:
        basic["natoms"] = int(natoms_match.group(1))

    return basic


def parse_text_energy(text: str) -> dict:
    """Parse final single point energies from ORCA text."""
    matches = re.findall(r"FINAL SINGLE POINT ENERGY\s+(-?\d+\.\d+)", text)
    if not matches:
        return {}

    energies_h = [float(value) for value in matches]
    final_h = energies_h[-1]
    return {
        "scfenergies_hartree": energies_h,
        "final_energy_hartree": final_h,
        "scfenergies_eV": [value * HARTREE_TO_EV for value in energies_h],
        "final_energy_eV": final_h * HARTREE_TO_EV,
        "n_scf_cycles": len(energies_h),
    }


def parse_text_thermo(text: str) -> dict:
    """Parse thermochemistry values from ORCA text."""
    thermo = {}

    patterns = {
        "enthalpy_hartree": r"Total enthalpy\s+\.\.\.\s+(-?\d+\.\d+)\s+Eh",
        "freeenergy_hartree": r"Final Gibbs free energy\s+\.\.\.\s+(-?\d+\.\d+)\s+Eh",
        "entropy_correction_hartree": r"Total entropy correction\s+\.\.\.\s+(-?\d+\.\d+)\s+Eh",
        "zpve_hartree": r"Non-thermal \(ZPE\) correction\s+\.\.\.\s+(-?\d+\.\d+)\s+Eh",
        "temperature_K": r"Temperature\s+\.\.\.\s+([0-9.]+)\s+K",
        "pressure_atm": r"Pressure\s+\.\.\.\s+([0-9.]+)\s+atm",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, text)
        if match:
            thermo[key] = float(match.group(1))

    if "enthalpy_hartree" in thermo:
        thermo["enthalpy_eV"] = thermo["enthalpy_hartree"] * HARTREE_TO_EV
    if "freeenergy_hartree" in thermo:
        thermo["freeenergy_eV"] = thermo["freeenergy_hartree"] * HARTREE_TO_EV
    if "zpve_hartree" in thermo:
        thermo["zpve_eV"] = thermo["zpve_hartree"] * HARTREE_TO_EV
    if "entropy_correction_hartree" in thermo:
        thermo["entropy_eV_per_K"] = thermo["entropy_correction_hartree"] * HARTREE_TO_EV

    return thermo


def parse_text_opt_status(text: str) -> dict:
    """Parse optimization convergence status from ORCA text."""
    if "THE OPTIMIZATION HAS CONVERGED" in text:
        return {"converged": True}
    if "The optimization did not converge but reached the maximum number of" in text:
        return {"converged": False}
    if "The optimization has not yet converged" in text:
        return {"converged": False}
    return {}


def parse_text_opt_tables(text: str) -> tuple[dict, dict]:
    """Parse geometry convergence tables from ORCA text."""
    blocks = []
    lines = text.splitlines()
    pattern = re.compile(
        r"^\s*(Energy change|RMS gradient|MAX gradient|RMS step|MAX step)\s+"
        r"(-?\d+(?:\.\d+)?(?:[Ee][+-]?\d+)?)\s+"
        r"(-?\d+(?:\.\d+)?(?:[Ee][+-]?\d+)?)\s+"
        r"(YES|NO)\s*$"
    )
    label_map = {
        "Energy change": "energy_change",
        "MAX gradient": "max_gradient",
        "RMS gradient": "rms_gradient",
        "MAX step": "max_displacement",
        "RMS step": "rms_displacement",
    }

    idx = 0
    while idx < len(lines):
        if "Geometry convergence" not in lines[idx]:
            idx += 1
            continue
        criteria = {}
        j = idx + 1
        while j < len(lines):
            match = pattern.match(lines[j])
            if match:
                label, value, threshold, converged = match.groups()
                criteria[label_map[label]] = {
                    "value": float(value),
                    "threshold": float(threshold),
                    "met": converged == "YES",
                }
            elif criteria and (not lines[j].strip() or "Max(Bonds)" in lines[j] or "--------" in lines[j]):
                break
            j += 1
        if criteria:
            blocks.append(criteria)
        idx = j

    if not blocks:
        return {}, {}

    ordered_labels = [
        "energy_change",
        "max_gradient",
        "rms_gradient",
        "max_displacement",
        "rms_displacement",
    ]
    last = blocks[-1]
    opt_convergence = {"criteria": [], "n_met": 0, "n_total": 0}
    for label in ordered_labels:
        item = last.get(label)
        if item is None:
            continue
        opt_convergence["criteria"].append(
            {
                "name": label,
                "value": item["value"],
                "threshold": item["threshold"],
                "met": item["met"],
            }
        )
        opt_convergence["n_total"] += 1
        if item["met"]:
            opt_convergence["n_met"] += 1

    opt_all_steps = {
        "n_steps": len(blocks),
        "thresholds": {
            label: blocks[-1][label]["threshold"] for label in ordered_labels if label in blocks[-1]
        },
        "steps": [],
    }
    for step_idx, block in enumerate(blocks, start=1):
        row = {"step": step_idx, "n_met": 0, "n_total": 0}
        for label in ordered_labels:
            item = block.get(label)
            if item is None:
                continue
            row[label] = item["value"]
            row["n_total"] += 1
            if item["met"]:
                row["n_met"] += 1
        opt_all_steps["steps"].append(row)

    return opt_convergence, opt_all_steps


def parse_text_freqs(text: str) -> tuple[dict, dict]:
    """Parse vibrational frequencies from ORCA text."""
    freqs = {}
    imag_freqs = {}

    values = [
        float(match.group(1))
        for match in re.finditer(
            r"^\s*\d+:\s+(-?\d+\.\d+)\s+cm\*\*-1(?:\s+\*\*\*imaginary mode\*\*\*)?\s*$",
            text,
            re.MULTILINE,
        )
    ]
    if values:
        imag_values = [value for value in values if value < 0]
        freqs = {
            "vibfreqs_cm-1": values,
            "n_freqs": len(values),
            "n_imaginary": len(imag_values),
        }
        imag_freqs = {
            "imaginary_freqs_cm-1": imag_values,
            # "n_imaginary": len(imag_values),
        }
        return freqs, imag_freqs

    count_matches = re.findall(r"found\s+(\d+)\s+significant imaginary frequenc(?:y|ies)", text)
    if count_matches:
        count = int(count_matches[-1])
        freqs = {
            "n_freqs": None,
            "error": "Use shell tool instead."
        }
        imag_freqs = {
            "imaginary_freqs_cm-1": [],
            "error": "Use shell tool instead."
        }

    return freqs, imag_freqs


def merge_missing(target: dict, fallback: dict) -> dict:
    """Fill missing top-level keys in a parsed section from fallback values."""
    for key, value in fallback.items():
        if key not in target or target[key] in (None, [], {}, ""):
            target[key] = value
    return target


def parse_with_cclib(filepath: str) -> dict:
    """Parse ORCA output file using cclib plus custom IRC parsing."""
    path = Path(filepath)
    if not path.exists():
        return {"error": f"File not found: {filepath}"}

    text = path.read_text(errors="replace")
    data, parser_messages, parse_error = ccread_with_messages(path)
    calc_type = detect_calc_type(filepath, data)
    result = {}
    text_metadata = parse_text_metadata(text)
    text_job_state = parse_text_job_state(text)
    text_trj_files = find_trj_files(filepath)
    text_basic = parse_text_basic(text, calc_type)
    text_energy = parse_text_energy(text)
    text_thermo = parse_text_thermo(text)
    text_opt_status = parse_text_opt_status(text)
    text_opt_convergence, text_opt_all_steps = parse_text_opt_tables(text)
    text_freqs, text_imag_freqs = parse_text_freqs(text)

    if parse_error is not None and cclib is None and not any(
        [
            text_basic,
            text_energy,
            text_thermo,
            text_opt_status,
            text_opt_convergence,
            text_freqs,
            text_metadata,
        ]
    ):
        return {"error": f"cclib parse error: {parse_error}"}

    def has_attr(attr):
        return hasattr(data, attr) and getattr(data, attr) is not None

    basic = dict(text_basic)
    if data is not None and has_attr("natom"):
        basic["natoms"] = int(data.natom)
    if data is not None and has_attr("charge"):
        basic["charge"] = int(data.charge)
    if data is not None and has_attr("mult"):
        basic["multiplicity"] = int(data.mult)
    if data is not None and has_attr("nelectrons"):
        basic["nelectrons"] = int(data.nelectrons)
    result["basic"] = basic
    result["job_state"] = text_job_state
    result["trj_files"] = text_trj_files

    energy = dict(text_energy)
    if data is not None and has_attr("scfenergies"):
        energy["scfenergies_eV"] = data.scfenergies.tolist()
        energy["final_energy_eV"] = float(data.scfenergies[-1])
        energy["n_scf_cycles"] = len(data.scfenergies)
        energy.setdefault("final_energy_hartree", float(data.scfenergies[-1]) / HARTREE_TO_EV)
    result["energy"] = energy

    thermo = dict(text_thermo)
    if data is not None and has_attr("enthalpy"):
        thermo["enthalpy_eV"] = float(data.enthalpy)
    if data is not None and has_attr("freeenergy"):
        thermo["freeenergy_eV"] = float(data.freeenergy)
    if data is not None and has_attr("entropy"):
        thermo["entropy_eV_per_K"] = float(data.entropy)
    if data is not None and has_attr("zpve"):
        thermo["zpve_eV"] = float(data.zpve)
    if data is not None and has_attr("temperature"):
        thermo["temperature_K"] = float(data.temperature)
    if data is not None and has_attr("pressure"):
        thermo["pressure_atm"] = float(data.pressure)
    result["thermo"] = thermo

    opt_status = dict(text_opt_status)
    if data is not None and has_attr("optdone"):
        opt_status["converged"] = bool(data.optdone)
    result["opt_status"] = opt_status

    opt_convergence = dict(text_opt_convergence)
    if data is not None and has_attr("geovalues") and has_attr("geotargets"):
        labels = [
            "energy_change",
            "max_gradient",
            "rms_gradient",
            "max_displacement",
            "rms_displacement",
        ]
        values = data.geovalues[-1].tolist()
        targets = data.geotargets.tolist()
        criteria = []
        for i, label in enumerate(labels):
            if i < len(values) and i < len(targets):
                met = abs(values[i]) < targets[i] if label == "energy_change" else values[i] < targets[i]
                criteria.append(
                    {
                        "name": label,
                        "value": values[i],
                        "threshold": targets[i],
                        "met": bool(met),
                    }
                )
        opt_convergence["criteria"] = criteria
        opt_convergence["n_met"] = sum(1 for item in criteria if item["met"])
        opt_convergence["n_total"] = len(criteria)
    result["opt_convergence"] = opt_convergence

    opt_all_steps = dict(text_opt_all_steps)
    if data is not None and has_attr("geovalues") and has_attr("geotargets"):
        labels = [
            "energy_change",
            "max_gradient",
            "rms_gradient",
            "max_displacement",
            "rms_displacement",
        ]
        targets = data.geotargets.tolist()
        steps = []
        for step_idx, values in enumerate(data.geovalues, start=1):
            values_list = values.tolist() if hasattr(values, "tolist") else list(values)
            row = {
                "step": step_idx,
                "n_met": 0,
                "n_total": 0,
            }
            for i, label in enumerate(labels):
                if i < len(values_list) and i < len(targets):
                    row[label] = values_list[i]
                    row["n_total"] += 1
                    met = abs(values_list[i]) < targets[i] if label == "energy_change" else values_list[i] < targets[i]
                    if met:
                        row["n_met"] += 1
            steps.append(row)

        opt_all_steps["n_steps"] = len(steps)
        opt_all_steps["thresholds"] = {label: targets[i] for i, label in enumerate(labels) if i < len(targets)}
        opt_all_steps["steps"] = steps
    result["opt_all_steps"] = opt_all_steps

    masses = {}
    if data is not None and has_attr("atommasses"):
        masses["atommasses"] = data.atommasses.tolist()
    result["masses"] = masses

    freqs = dict(text_freqs)
    if data is not None and has_attr("vibfreqs"):
        freqs["vibfreqs_cm-1"] = data.vibfreqs.tolist()
        freqs["n_freqs"] = len(data.vibfreqs)
        freqs["n_imaginary"] = int(sum(1 for freq in data.vibfreqs if freq < 0))
    result["freqs"] = freqs

    imag_freqs = dict(text_imag_freqs)
    if data is not None and has_attr("vibfreqs"):
        values = [float(freq) for freq in data.vibfreqs if freq < 0]
        imag_freqs["imaginary_freqs_cm-1"] = values
        # imag_freqs["n_imaginary"] = len(values)
    result["imag_freqs"] = imag_freqs

    ir_intensities = {}
    if data is not None and has_attr("vibirs"):
        ir_intensities["ir_intensities"] = data.vibirs.tolist()
    result["ir_intensities"] = ir_intensities

    gradients = {}
    if data is not None and has_attr("grads"):
        gradients["shape"] = list(data.grads.shape)
    result["gradients"] = gradients

    metadata = dict(text_metadata)
    if data is not None and has_attr("metadata"):
        md = data.metadata
        merge_missing(
            metadata,
            {
                "orca_version": md.get("package_version", "N/A"),
                "keywords": md.get("keywords", []),
                "warnings": md.get("warnings", []),
                "wall_time": str(md.get("wall_time", "N/A")),
            },
        )
    metadata["terminated_normally"] = text_metadata.get("terminated_normally", False)
    if parse_error is not None:
        parser_messages = [*parser_messages, f"cclib fallback: {parse_error}"]
    if parser_messages:
        metadata["parser_messages"] = parser_messages
    result["metadata"] = metadata

    irc_data = parse_irc_summary(filepath)
    if irc_data:
        result["irc_summary"] = irc_data

    return result


def format_scalar(value) -> str:
    """Format scalar values compactly for text tables."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        return f"{value:.10g}"
    return str(value)


def render_table(headers: list[str], rows: list[list], table_format: str) -> str:
    """Render a compact markdown or CSV table."""
    str_rows = [[format_scalar(cell) for cell in row] for row in rows]

    if table_format == "csv":
        lines = [",".join(headers)]
        lines.extend(",".join(row) for row in str_rows)
        return "\n".join(lines)

    widths = [len(header) for header in headers]
    for row in str_rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))

    header_line = "| " + " | ".join(headers[idx].ljust(widths[idx]) for idx in range(len(headers))) + " |"
    separator_line = "| " + " | ".join("-" * widths[idx] for idx in range(len(headers))) + " |"
    body_lines = [
        "| " + " | ".join(row[idx].ljust(widths[idx]) for idx in range(len(headers))) + " |"
        for row in str_rows
    ]
    return "\n".join([header_line, separator_line, *body_lines])


def render_opt_all_steps(data: dict, table_format: str) -> str:
    """Render opt_all_steps as a compact summary plus table."""
    if not data:
        return "not available"

    steps = data.get("steps", [])
    thresholds = data.get("thresholds", {})
    summary_lines = [f"n_steps: {data.get('n_steps', len(steps))}"]
    if steps:
        final_step = steps[-1]
        summary_lines.append(f"final_step: {final_step['step']}")
        summary_lines.append(f"final_met: {final_step['n_met']}/{final_step['n_total']}")
    if thresholds:
        threshold_text = ", ".join(f"{key}<{format_scalar(value)}" for key, value in thresholds.items())
        summary_lines.append(f"thresholds: {threshold_text}")

    headers = [
        "step",
        "n_met",
        # "n_total",
        "energy_change",
        "max_gradient",
        "rms_gradient",
        "max_displacement",
        "rms_displacement",
    ]
    rows = [
        [
            step.get("step"),
            step.get("n_met"),
            # step.get("n_total"),
            step.get("energy_change"),
            step.get("max_gradient"),
            step.get("rms_gradient"),
            step.get("max_displacement"),
            step.get("rms_displacement"),
        ]
        for step in steps
    ]
    return "\n".join([*summary_lines, "", render_table(headers, rows, table_format)])


def render_irc_summary(data: dict, table_format: str) -> str:
    """Render irc_summary as a compact summary plus table."""
    if not data:
        return "not available"

    ts_point = data.get("ts_point") or {}
    summary_lines = [
        f"n_points: {data.get('n_points', 0)}",
        f"ts_step: {ts_point.get('step', 'N/A')}",
        f"n_side_a: {data.get('n_side_a', 0)}",
        f"n_side_b: {data.get('n_side_b', 0)}",
        f"forward_converged: {format_scalar(data.get('forward_converged'))}",
        f"backward_converged: {format_scalar(data.get('backward_converged'))}",
    ]

    barriers = data.get("barriers", {})
    if barriers:
        barrier_text = ", ".join(f"{key}={format_scalar(value)}" for key, value in barriers.items())
        summary_lines.append(f"barriers: {barrier_text}")

    headers = [
        "step",
        "side",
        # "is_ts",
        # "energy_hartree",
        "dE_kcal_mol",
        "max_gradient",
        "rms_gradient",
    ]
    rows = []
    ts_step = ts_point.get("step")
    for point in data.get("points", []):
        if point.get("is_ts"):
            side = "ts"
        elif ts_step is not None and point["step"] < ts_step:
            side = "a"
        elif ts_step is not None and point["step"] > ts_step:
            side = "b"
        else:
            side = "unknown"
        rows.append(
            [
                point.get("step"),
                side,
                # point.get("is_ts"),
                # point.get("energy_hartree"),
                point.get("dE_kcal_mol"),
                point.get("max_gradient"),
                point.get("rms_gradient"),
            ]
        )

    return "\n".join([*summary_lines, "", render_table(headers, rows, table_format)])


def render_json_block(data: dict, compact: bool = False) -> str:
    """Render normal keyword payloads as pretty JSON."""
    if compact:
        return json.dumps(data, separators=(',', ':'), allow_nan=True)
    return json.dumps(data, indent=2, allow_nan=True)


def render_keyword_section(keyword: str, value: dict, table_format: str, compact: bool = False) -> str:
    """Render a single keyword block."""
    if table_format == "json":
        return render_json_block(value, compact=compact)

    if not compact:
        header = f"## {keyword}"
        if keyword == "opt_all_steps":
            return f"{header}\n{render_opt_all_steps(value, table_format)}"
        if keyword == "irc_summary":
            return f"{header}\n{render_irc_summary(value, table_format)}"
        return f"{header}\n{render_json_block(value, compact=False)}"
    else:
        # Compact mode for --quiet
        return render_json_block(value, compact=True)


def has_content(value) -> bool:
    """Check whether a parsed payload has meaningful content."""
    if isinstance(value, dict):
        return any(has_content(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return len(value) > 0
    return value is not None


def get_available_keywords(result: dict) -> list[str]:
    """Return non-empty supported keywords in canonical order."""
    available = []
    for keyword in SUPPORTED_KEYWORDS:
        value = result.get(keyword)
        if isinstance(value, dict) and has_content(value):
            available.append(keyword)
    return available


def parse_cli_args(argv: list[str]) -> tuple[str, list[str], str, bool]:
    """Parse CLI arguments."""
    if len(argv) < 2:
        print(__doc__)
        sys.exit(1)

    if argv[1] in {"-h", "--help"}:
        print(__doc__)
        sys.exit(0)

    filepath = argv[1]
    requested = []
    table_format = "markdown"
    quiet_mode = False
    idx = 2
    while idx < len(argv):
        arg = argv[idx]
        if arg == "--format":
            if idx + 1 >= len(argv):
                print("error: --format requires a value: markdown, csv, or json")
                sys.exit(1)
            table_format = argv[idx + 1].strip().lower()
            idx += 2
            continue
        if arg.startswith("--format="):
            table_format = arg.split("=", 1)[1].strip().lower()
            idx += 1
            continue
        if arg == "--quiet":
            quiet_mode = True
            idx += 1
            continue
        if arg.startswith("--"):
            print(f"error: unknown option: {arg}")
            sys.exit(1)
        requested.append(arg)
        idx += 1

    if table_format not in {"markdown", "csv", "json"}:
        print(f"error: unsupported table format: {table_format}")
        sys.exit(1)

    return filepath, requested, table_format, quiet_mode


def render_available_keywords(filepath: str, available: list[str]) -> str:
    """Render a compact list of available keywords."""
    lines = [f"file: {filepath}", "available_keywords:"]
    for keyword in available:
        lines.append(f"- {keyword}: {KEYWORD_DESCRIPTIONS[keyword]}")
    lines.append("")
    lines.append(f"usage: python tools/parse_orca_output.py {filepath} <keyword1> [keyword2 ...]")
    lines.append("table_formats: --format markdown|csv")

    return "\n".join(lines)


def main():
    filepath, requested, table_format, quiet_mode = parse_cli_args(sys.argv)
    result = parse_with_cclib(filepath)

    if "error" in result:
        print(json.dumps({"error": result["error"]}, indent=2))
        sys.exit(1)

    available = get_available_keywords(result)

    if not requested:
        if quiet_mode:
            print(json.dumps({"error": "--quiet requires keyword(s) to query"}))
            sys.exit(1)
        print(render_available_keywords(filepath, available))
        return


    if "all" in requested:
        requested = available

    # In quiet mode with single keyword, output just the value
    if quiet_mode and len(requested) == 1:
        raw_keyword = requested[0]
        keyword = KEYWORD_ALIASES.get(raw_keyword, raw_keyword)

        if keyword in SUBKEYWORD_ALIASES:
            parent, child = SUBKEYWORD_ALIASES[keyword]
            parent_value = result.get(parent, {})
            if isinstance(parent_value, dict) and child in parent_value:
                value = parent_value[child]
                if table_format == "json":
                    print(json.dumps(value, allow_nan=True))
                else:
                    print(value)
            else:
                print(json.dumps({"error": f"Keyword not available: {raw_keyword}"}))
                sys.exit(1)
        elif keyword in result and available:
            value = result[keyword]
            if table_format == "json":
                print(json.dumps(value, allow_nan=True))
            else:
                print(value)
        else:
            print(json.dumps({"error": f"Unknown or unavailable keyword: {raw_keyword}"}))
            sys.exit(1)
        return

    # Multi-keyword or regular output
    if table_format == "json":
        output_dict = {"file": filepath}
        for raw_keyword in requested:
            keyword = KEYWORD_ALIASES.get(raw_keyword, raw_keyword)
            if keyword in SUBKEYWORD_ALIASES:
                parent, child = SUBKEYWORD_ALIASES[keyword]
                parent_value = result.get(parent, {})
                if isinstance(parent_value, dict) and child in parent_value:
                    output_dict[raw_keyword] = parent_value[child]
                else:
                    output_dict[raw_keyword] = {"error": f"Keyword not available for this file: {raw_keyword}"}
            elif keyword in result and available:
                output_dict[raw_keyword] = result[keyword]
            else:
                output_dict[raw_keyword] = {"error": f"Unknown keyword: {raw_keyword}"}
        print(json.dumps(output_dict, indent=2, allow_nan=True))
        return

    sections = [f"file: {filepath}"]
    for raw_keyword in requested:
        keyword = KEYWORD_ALIASES.get(raw_keyword, raw_keyword)
        if keyword in SUBKEYWORD_ALIASES:
            parent, child = SUBKEYWORD_ALIASES[keyword]
            parent_value = result.get(parent, {})
            if isinstance(parent_value, dict) and child in parent_value:
                sections.append(render_keyword_section(raw_keyword, parent_value[child], table_format))
            else:
                sections.append(
                    f"## {raw_keyword}\n"
                    f"{json.dumps({'error': f'Keyword not available for this file: {raw_keyword}'}, indent=2)}"
                )
            continue
        if keyword not in KEYWORD_DESCRIPTIONS:
            sections.append(f"## {raw_keyword}\n{json.dumps({'error': f'Unknown keyword: {raw_keyword}'}, indent=2)}")
            continue
        if keyword not in available:
            sections.append(
                f"## {raw_keyword}\n"
                f"{json.dumps({'error': f'Keyword not available for this file: {raw_keyword}'}, indent=2)}"
            )
            continue
        sections.append(render_keyword_section(raw_keyword, result[keyword], table_format))

    print("\n\n".join(sections))


if __name__ == "__main__":
    main()
