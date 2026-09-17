#!/usr/bin/env python3
"""
Query internal coordinates from an XYZ-like structure using ASE.

Examples:
    python inquire.py guess.xyz 1 2
    python inquire.py guess.xyz 1 2 3
    python inquire.py guess.xyz 1 2 3 4
    python inquire.py guess.xyz --bond 1 2 --angle 1 2 3 --dihedral 1 2 3 4
    python inquire.py guess.xyz --reference ref.xyz --bond 1 2 --dihedral 1 2 3 4
    python inquire.py traj.xyz --angle 1 2 3
"""

import argparse
import json
import sys

from ase import io


def wrap_signed_deg(angle):
    return ((angle + 180.0) % 360.0) - 180.0


def build_parser():
    parser = argparse.ArgumentParser(
        description="Query bond distances, angles, and dihedrals from a structure file."
    )
    parser.add_argument("structure", help="Input structure file, e.g. guess.xyz")
    parser.add_argument(
        "indices",
        nargs="*",
        help="Optional single query in 1-based form: I J [K] [L]",
    )
    parser.add_argument(
        "--reference",
        help="Optional reference structure file for direct comparison",
    )
    parser.add_argument(
        "--bond",
        nargs=2,
        action="append",
        metavar=("I", "J"),
        default=[],
        help="Query bond distance between atoms I and J",
    )
    parser.add_argument(
        "--angle",
        nargs=3,
        action="append",
        metavar=("I", "J", "K"),
        default=[],
        help="Query angle I-J-K",
    )
    parser.add_argument(
        "--dihedral",
        nargs=4,
        action="append",
        metavar=("I", "J", "K", "L"),
        default=[],
        help="Query dihedral I-J-K-L",
    )
    parser.add_argument(
        "--zero-based",
        action="store_true",
        help="Interpret input atom indices as 0-based. Default is 1-based.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print results as JSON.",
    )
    return parser


def convert_index(raw, zero_based, natoms):
    idx = int(raw)
    if not zero_based:
        idx -= 1
    if idx < 0 or idx >= natoms:
        raise ValueError(f"Atom index {raw} is out of range for {natoms} atoms")
    return idx


def fmt_index(idx, zero_based):
    return idx if zero_based else idx + 1


def parse_single_query(indices):
    if not indices:
        return []
    if len(indices) == 2:
        return [("bond", indices)]
    if len(indices) == 3:
        return [("angle", indices)]
    if len(indices) == 4:
        return [("dihedral", indices)]
    raise ValueError("Single positional query must contain exactly 2, 3, or 4 indices")


def build_queries(args, natoms):
    raw_queries = []
    raw_queries.extend(("bond", item) for item in args.bond)
    raw_queries.extend(("angle", item) for item in args.angle)
    raw_queries.extend(("dihedral", item) for item in args.dihedral)
    raw_queries.extend(parse_single_query(args.indices))

    if not raw_queries:
        raise ValueError("No query was provided")

    queries = []
    for qtype, raw_indices in raw_queries:
        idxs = tuple(convert_index(x, args.zero_based, natoms) for x in raw_indices)
        if len(set(idxs)) != len(idxs):
            raise ValueError(f"{qtype} query contains duplicated atom indices: {raw_indices}")
        queries.append((qtype, idxs))
    return queries


def bond_value(atoms, idxs):
    i, j = idxs
    return atoms.get_distance(i, j)


def angle_value(atoms, idxs):
    i, j, k = idxs
    return atoms.get_angle(i, j, k)


def dihedral_value(atoms, idxs):
    i, j, k, l = idxs
    return wrap_signed_deg(atoms.get_dihedral(i, j, k, l))


def query_value(atoms, qtype, idxs):
    if qtype == "bond":
        return bond_value(atoms, idxs)
    if qtype == "angle":
        return angle_value(atoms, idxs)
    if qtype == "dihedral":
        return dihedral_value(atoms, idxs)
    raise ValueError(f"Unknown query type: {qtype}")


def delta_value(qtype, value, ref_value):
    if qtype == "dihedral":
        return wrap_signed_deg(value - ref_value)
    return value - ref_value


def format_query_result(atoms, qtype, idxs, value, zero_based, ref_atoms=None, ref_value=None):
    symbols = atoms.get_chemical_symbols()
    labels = " ".join(f"{symbols[i]}{fmt_index(i, zero_based)}" for i in idxs)
    if qtype == "bond":
        line = f"Bond = {value:.5f} ({labels})"
    elif qtype == "angle":
        line = f"Angle = {value:.5f} ({labels})"
    else:
        line = f"Dihedral = {value:.5f} ({labels})"

    if ref_atoms is not None and ref_value is not None:
        delta = delta_value(qtype, value, ref_value)
        line += f" | Ref = {ref_value:.5f} | Delta = {delta:+.5f}"
    return line


def json_record(atoms, qtype, idxs, value, zero_based, ref_atoms=None, ref_value=None):
    symbols = atoms.get_chemical_symbols()
    record = {
        "type": qtype,
        "indices": [fmt_index(i, zero_based) for i in idxs],
        "symbols": [symbols[i] for i in idxs],
        "value": value,
    }
    if ref_atoms is not None and ref_value is not None:
        record["reference_value"] = ref_value
        record["delta"] = delta_value(qtype, value, ref_value)
    return record


def normalize_frames(obj):
    if isinstance(obj, list):
        return obj
    return [obj]


def load_structures(path, label):
    try:
        frames = normalize_frames(io.read(path, index=":"))
    except FileNotFoundError:
        print(f"Error: {label} file '{path}' not found", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Error: Failed to read {label} file '{path}': {exc}", file=sys.stderr)
        sys.exit(1)

    if not frames:
        print(f"Error: {label} file '{path}' contains no structures", file=sys.stderr)
        sys.exit(1)
    return frames


def validate_frames(frames, label):
    natoms = len(frames[0])
    for frame_idx, atoms in enumerate(frames, start=1):
        if len(atoms) != natoms:
            print(
                f"Error: {label} frame {frame_idx} has {len(atoms)} atoms, expected {natoms}",
                file=sys.stderr,
            )
            sys.exit(1)
    return natoms


def reference_frame(ref_frames, frame_idx):
    if len(ref_frames) == 1:
        return ref_frames[0]
    return ref_frames[frame_idx]


def format_frame_result(frame_idx, qtype, value, ref_value=None):
    # if qtype == "bond":
    #     label = "Bond"
    # elif qtype == "angle":
    #     label = "Angle"
    # else:
    #     label = "Dihedral"

    # line = f"{frame_idx + 1}: {label} = {value:.2f}"
    line = f"{frame_idx + 1}: {value:.2f}"
    if ref_value is not None:
        delta = delta_value(qtype, value, ref_value)
        line += f" | Ref = {ref_value:.5f} | Delta = {delta:+.5f}"
    return line


def format_trajectory_header(atoms, qtype, idxs, zero_based, nframes):
    symbols = atoms.get_chemical_symbols()
    labels = " ".join(f"{symbols[i]}{fmt_index(i, zero_based)}" for i in idxs)
    if qtype == "bond":
        label = "Bond"
    elif qtype == "angle":
        label = "Angle"
    else:
        label = "Dihedral"
    return f"{label} trajectory ({labels}) | Frames = {nframes}"


def json_trajectory_record(atoms, qtype, idxs, values, zero_based, ref_values=None):
    symbols = atoms.get_chemical_symbols()
    record = {
        "type": qtype,
        "indices": [fmt_index(i, zero_based) for i in idxs],
        "symbols": [symbols[i] for i in idxs],
        "n_frames": len(values),
        "values": values,
    }
    if ref_values is not None:
        record["reference_values"] = ref_values
        record["deltas"] = [delta_value(qtype, value, ref_value) for value, ref_value in zip(values, ref_values)]
    return record


def main():
    args = build_parser().parse_args()

    frames = load_structures(args.structure, "Structure")
    natoms = validate_frames(frames, "Structure")
    atoms = frames[0]

    ref_frames = None
    if args.reference:
        ref_frames = load_structures(args.reference, "Reference")
        ref_natoms = validate_frames(ref_frames, "Reference")
        if ref_natoms != natoms:
            print("Error: Structure and reference have different atom counts", file=sys.stderr)
            sys.exit(1)
        if len(ref_frames) not in (1, len(frames)):
            print(
                "Error: Reference must contain either one structure or the same number of frames as the input",
                file=sys.stderr,
            )
            sys.exit(1)

    try:
        queries = build_queries(args, natoms)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    results = []
    for query_idx, (qtype, idxs) in enumerate(queries):
        if len(frames) == 1:
            value = query_value(atoms, qtype, idxs)
            ref_atoms = reference_frame(ref_frames, 0) if ref_frames is not None else None
            ref_value = query_value(ref_atoms, qtype, idxs) if ref_atoms is not None else None
            if args.json:
                results.append(json_record(atoms, qtype, idxs, value, args.zero_based, ref_atoms, ref_value))
            else:
                print(format_query_result(atoms, qtype, idxs, value, args.zero_based, ref_atoms, ref_value))
        else:
            values = []
            ref_values = [] if ref_frames is not None else None
            if not args.json:
                if query_idx > 0:
                    print()
                print(format_trajectory_header(atoms, qtype, idxs, args.zero_based, len(frames)))
            for frame_idx, frame_atoms in enumerate(frames):
                value = query_value(frame_atoms, qtype, idxs)
                values.append(value)
                ref_value = None
                if ref_frames is not None:
                    ref_atoms = reference_frame(ref_frames, frame_idx)
                    ref_value = query_value(ref_atoms, qtype, idxs)
                    ref_values.append(ref_value)
                if not args.json:
                    print(format_frame_result(frame_idx, qtype, value, ref_value))
            if args.json:
                results.append(
                    json_trajectory_record(
                        atoms,
                        qtype,
                        idxs,
                        values,
                        args.zero_based,
                        ref_values=ref_values,
                    )
                )

    if args.json:
        json.dump(results, sys.stdout, indent=2)
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
