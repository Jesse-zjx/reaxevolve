#!/usr/bin/env python3
import argparse
import sys
from collections import deque
from itertools import combinations
from pathlib import Path

import numpy as np
from ase import io
from ase.neighborlist import NeighborList, natural_cutoffs


BOND_MODES = {"translate-group", "translate-atom", "fixed"}
ANGLE_END_MODES = {"rotate-group", "rotate-atom", "fixed", "translate-group"}
ANGLE_CENTER_MODES = {"translate-group", "translate-atom", "fixed"}
DIHEDRAL_END_MODES = {"rotate-groups", "rotate-group", "rotate-atom", "fixed"}


def build_parser():
    parser = argparse.ArgumentParser(
        description="GaussianView-like internal coordinate builder using ASE.",
        epilog=(
            "Operations are applied in the exact order given on the command line.\n"
            "\n"
            "Bond:\n"
            "  --bond I J VALUE MODE_I MODE_J\n"
            "  MODE = translate-group | translate-atom | fixed\n"
            "\n"
            "Angle:\n"
            "  --angle I J K VALUE MODE_1 MODE_2 MODE_3\n"
            "  MODE_1/MODE_3 = rotate-group | rotate-atom | fixed | translate-group\n"
            "  MODE_2 = translate-group | translate-atom | fixed\n"
            "\n"
            "Dihedral:\n"
            "  --dihedral I J K L VALUE MODE_1 MODE_4\n"
            "  MODE = rotate-groups | rotate-group | rotate-atom | fixed\n"
            "\n"
            "Example:\n"
            "  builder.py in.xyz out.xyz "
            "--bond 1 2 1.80 fixed translate-group "
            "--angle 1 2 3 120 fixed fixed rotate-group "
            "--dihedral 1 2 3 4 -60 fixed rotate-group"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("input_xyz", help="Input XYZ file")
    parser.add_argument("output_xyz", help="Output XYZ file")
    parser.add_argument(
        "--com",
        nargs="?",
        const="",
        help=(
            "Also write a Gaussian .com file. If no path is provided, use the "
            "same basename as output_xyz with a .com suffix."
        ),
    )
    parser.add_argument(
        "--cutoff-mult",
        type=float,
        default=1.0,
        help="Scale factor for ASE natural_cutoffs when inferring connectivity (default: 1.0)",
    )
    parser.add_argument(
        "--zero-based",
        action="store_true",
        help="Interpret atom indices as 0-based. Default is 1-based.",
    )
    parser.add_argument(
        "--print-final",
        action="store_true",
        help="Print the final values of all requested internal coordinates.",
    )
    parser.add_argument(
        "--print-moved-atoms",
        action="store_true",
        help=(
            "After each operation, print the atoms whose coordinates actually "
            "changed. Useful for checking group/fragment selection."
        ),
    )
    parser.add_argument(
        "--movement-tol",
        type=float,
        default=1e-8,
        help=(
            "Distance tolerance in Angstrom for --print-moved-atoms "
            "(default: 1e-8)."
        ),
    )
    parser.add_argument(
        "--short-distance-cutoff",
        type=float,
        default=1.0,
        help=(
            "After writing the output, print all atom pairs closer than this "
            "distance in Angstrom (default: 1.0)."
        ),
    )
    return parser


def convert_index(raw, zero_based, natoms):
    idx = int(raw)
    if not zero_based:
        idx -= 1
    if idx < 0 or idx >= natoms:
        raise ValueError(f"Atom index {raw} is out of range for {natoms} atoms")
    return idx


def format_index(idx, zero_based):
    return idx if zero_based else idx + 1


def normalize_mode(raw):
    return raw.strip().lower()


def wrap_signed_deg(angle):
    return ((angle + 180.0) % 360.0) - 180.0


def wrap_unsigned_deg(angle):
    return angle % 360.0


def interpolate_dihedral(current_deg, target_deg, frac):
    diff = wrap_signed_deg(target_deg - current_deg)
    return wrap_signed_deg(current_deg + diff * frac)


def build_adjacency(atoms, cutoff_mult):
    cutoffs = natural_cutoffs(atoms, mult=cutoff_mult)
    nl = NeighborList(cutoffs, self_interaction=False, bothways=True)
    nl.update(atoms)
    return {i: sorted(nl.get_neighbors(i)[0].tolist()) for i in range(len(atoms))}


def connected_component(adjacency, start, blocked_edges=None):
    blocked_edges = blocked_edges or set()
    seen = set()
    queue = deque([start])
    while queue:
        node = queue.popleft()
        if node in seen:
            continue
        seen.add(node)
        for nbr in adjacency[node]:
            if (node, nbr) in blocked_edges or (nbr, node) in blocked_edges:
                continue
            if nbr not in seen:
                queue.append(nbr)
    return sorted(seen)


def side_group(adjacency, atom, other_atom):
    if other_atom in adjacency[atom]:
        return connected_component(adjacency, atom, blocked_edges={(atom, other_atom)})
    return connected_component(adjacency, atom)


def shortest_path(adjacency, start, end):
    queue = deque([(start, [start])])
    seen = {start}
    while queue:
        node, path = queue.popleft()
        if node == end:
            return path
        for nbr in adjacency[node]:
            if nbr in seen:
                continue
            seen.add(nbr)
            queue.append((nbr, path + [nbr]))
    return None


def terminal_group_toward_center(adjacency, atom, center):
    path = shortest_path(adjacency, atom, center)
    if path and len(path) >= 2:
        return connected_component(adjacency, atom, blocked_edges={(path[0], path[1])})
    return connected_component(adjacency, atom)


def bond_selection(adjacency, atom, other_atom, mode):
    if mode == "translate-atom":
        return [atom]
    if mode == "translate-group":
        # For bonded pairs, move the side obtained by cutting the target bond.
        #
        # For non-bonded pairs:
        # - if the two atoms are in different connected components (typical
        #   intermolecular approach / fragment docking), move the full fragment;
        # - if they are already in the same connected component, translating the
        #   whole component would move both atoms together and leave the target
        #   distance unchanged, so fall back to moving only the requested atom.
        if other_atom not in adjacency[atom]:
            component = connected_component(adjacency, atom)
            if other_atom in component:
                return [atom]
            return component
        return side_group(adjacency, atom, other_atom)
    return side_group(adjacency, atom, other_atom)

def center_group_for_angle(adjacency, i, j, k):
    blocked = set()
    for terminal in (i, k):
        path = shortest_path(adjacency, j, terminal)
        if path and len(path) >= 2:
            blocked.add((path[0], path[1]))
    return connected_component(adjacency, j, blocked_edges=blocked)


def torsion_side_group(adjacency, atom, anchor):
    return side_group(adjacency, atom, anchor)


def vector_norm(vec):
    return float(np.linalg.norm(vec))


def unit_vector(vec):
    norm = vector_norm(vec)
    if norm < 1e-12:
        raise ValueError("Encountered zero-length vector")
    return vec / norm


def translate_indices(atoms, indices, displacement):
    if not indices:
        return
    positions = atoms.get_positions()
    positions[np.array(sorted(set(indices)), dtype=int)] += displacement
    atoms.set_positions(positions)


def translate_terminal_to_angle(atoms, selection, i, j, k, target, side):
    trial = atoms.copy()
    if side == "1":
        trial.set_angle(k, j, i, target, indices=[i])
        displacement = trial.positions[i] - atoms.positions[i]
    elif side == "3":
        trial.set_angle(i, j, k, target, indices=[k])
        displacement = trial.positions[k] - atoms.positions[k]
    else:
        raise ValueError(f"Unknown angle terminal side: {side}")
    translate_indices(atoms, selection, displacement)


def angle_center_bisector_step(atoms, indices, i, j, k, step_deg):
    if abs(step_deg) < 1e-12:
        return
    u_i = unit_vector(atoms.positions[i] - atoms.positions[j])
    u_k = unit_vector(atoms.positions[k] - atoms.positions[j])
    bisector = u_i + u_k
    if vector_norm(bisector) < 1e-12:
        bisector = u_i - u_k
    displacement = bisector * np.tan(np.radians(step_deg)) * vector_norm(bisector)
    translate_indices(atoms, indices, displacement)


def angle_translation_gradient(atoms, indices, i, j, k, eps=1e-4):
    grad = np.zeros(3, dtype=float)
    for axis in range(3):
        step = np.zeros(3, dtype=float)
        step[axis] = eps
        plus = atoms.copy()
        minus = atoms.copy()
        translate_indices(plus, indices, step)
        translate_indices(minus, indices, -step)
        grad[axis] = (plus.get_angle(i, j, k) - minus.get_angle(i, j, k)) / (2.0 * eps)
    return grad


def solve_angle_by_translation(atoms, indices, i, j, k, target, max_iter=40, tol=1e-5):
    for _ in range(max_iter):
        current = atoms.get_angle(i, j, k)
        err = target - current
        if abs(err) < tol:
            return

        grad = angle_translation_gradient(atoms, indices, i, j, k)
        grad_norm = vector_norm(grad)
        if grad_norm < 1e-8:
            raise ValueError("Angle translation mode is locally ineffective for this geometry")

        direction = grad / grad_norm
        step = max(-0.75, min(0.75, err / grad_norm))
        trial = atoms.copy()
        translate_indices(trial, indices, direction * step)
        trial_err = target - trial.get_angle(i, j, k)

        if abs(trial_err) >= abs(err):
            improved = False
            for shrink in (0.5, 0.25, 0.1, 0.05, 0.02):
                trial = atoms.copy()
                translate_indices(trial, indices, direction * step * shrink)
                trial_err = target - trial.get_angle(i, j, k)
                if abs(trial_err) < abs(err):
                    step *= shrink
                    improved = True
                    break
            if not improved:
                raise ValueError("Failed to improve angle using translation mode")

        translate_indices(atoms, indices, direction * step)

    final_err = abs(target - atoms.get_angle(i, j, k))
    if final_err >= tol:
        raise ValueError(f"Angle translation solver did not converge (remaining error {final_err:.4e} deg)")


def get_dihedral_signed(atoms, i, j, k, l):
    return wrap_signed_deg(atoms.get_dihedral(i, j, k, l))


def set_dihedral_one_side(atoms, i, j, k, l, target_deg, selection, side):
    target_unsigned = wrap_unsigned_deg(target_deg)
    if side == "right":
        atoms.set_dihedral(i, j, k, l, target_unsigned, indices=selection)
    elif side == "left":
        atoms.set_dihedral(l, k, j, i, target_unsigned, indices=selection)
    else:
        raise ValueError(f"Unknown dihedral side: {side}")


def rotation_matrix(axis, angle_deg):
    axis = unit_vector(axis)
    x, y, z = axis
    angle = np.radians(angle_deg)
    c = np.cos(angle)
    s = np.sin(angle)
    one_c = 1.0 - c
    return np.array(
        [
            [c + x * x * one_c, x * y * one_c - z * s, x * z * one_c + y * s],
            [y * x * one_c + z * s, c + y * y * one_c, y * z * one_c - x * s],
            [z * x * one_c - y * s, z * y * one_c + x * s, c + z * z * one_c],
        ]
    )


def rotate_indices_around_axis(atoms, indices, point, axis, angle_deg):
    if not indices:
        return
    rot = rotation_matrix(axis, angle_deg)
    positions = atoms.get_positions()
    unique = np.array(sorted(set(indices)), dtype=int)
    positions[unique] = (positions[unique] - point) @ rot.T + point
    atoms.set_positions(positions)


def best_axis_rotation_for_normal(atoms, atom, point, axis, normal, target_component):
    original = atoms.positions[atom].copy()

    def component(angle_deg):
        rot = rotation_matrix(axis, angle_deg)
        rotated = (original - point) @ rot.T + point
        return float(np.dot(rotated - point, normal))

    candidates = []
    last_angle = 0.0
    last_value = component(last_angle) - target_component
    for angle in np.linspace(1.0, 360.0, 720):
        value = component(angle) - target_component
        if abs(value) < 1e-10:
            candidates.append(angle)
        elif value * last_value < 0.0:
            lo, hi = last_angle, angle
            for _ in range(50):
                mid = (lo + hi) / 2.0
                mid_value = component(mid) - target_component
                if mid_value * (component(lo) - target_component) <= 0.0:
                    hi = mid
                else:
                    lo = mid
            candidates.append((lo + hi) / 2.0)
        last_angle = angle
        last_value = value

    if not candidates:
        return None
    return min(candidates, key=lambda value: abs(wrap_signed_deg(value)))


def planar_normal_from_atoms(atoms):
    positions = atoms.get_positions()
    centered = positions - positions.mean(axis=0)
    _, _, vh = np.linalg.svd(centered, full_matrices=False)
    return unit_vector(vh[-1])


def mirror_terminal_sibling_groups(atoms, before, adjacency, j, k, selected_atom):
    selected_group = set(side_group(adjacency, selected_atom, k))
    if len(selected_group) != 1:
        return
    sibling_groups = []
    for nbr in adjacency[k]:
        if nbr == j or nbr in selected_group:
            continue
        group = side_group(adjacency, nbr, k)
        if len(group) == 1:
            sibling_groups.append(group)
    if not sibling_groups:
        return

    point = before.positions[k]
    axis = before.positions[k] - before.positions[j]
    normal = planar_normal_from_atoms(before)
    selected_component = float(np.dot(atoms.positions[selected_atom] - point, normal))
    for group in sibling_groups:
        angle = best_axis_rotation_for_normal(
            before,
            group[0],
            point,
            axis,
            normal,
            -selected_component,
        )
        if angle is not None:
            rotate_indices_around_axis(atoms, group, point, axis, angle)


def parse_operations(tokens, zero_based, natoms):
    ops = []
    i = 0
    while i < len(tokens):
        flag = tokens[i]
        if flag == "--bond":
            if i + 5 >= len(tokens):
                raise ValueError("--bond requires I J VALUE MODE_I MODE_J")
            a = convert_index(tokens[i + 1], zero_based, natoms)
            b = convert_index(tokens[i + 2], zero_based, natoms)
            if a == b:
                raise ValueError("Bond atoms must be different")
            value = float(tokens[i + 3])
            mode_a = normalize_mode(tokens[i + 4])
            mode_b = normalize_mode(tokens[i + 5])
            if mode_a not in BOND_MODES or mode_b not in BOND_MODES:
                raise ValueError("Invalid bond mode")
            ops.append(("bond", (a, b, value, mode_a, mode_b)))
            i += 6
        elif flag == "--angle":
            if i + 7 >= len(tokens):
                raise ValueError("--angle requires I J K VALUE MODE_1 MODE_2 MODE_3")
            a = convert_index(tokens[i + 1], zero_based, natoms)
            b = convert_index(tokens[i + 2], zero_based, natoms)
            c = convert_index(tokens[i + 3], zero_based, natoms)
            if len({a, b, c}) != 3:
                raise ValueError("Angle atoms must be distinct")
            value = float(tokens[i + 4])
            mode_a = normalize_mode(tokens[i + 5])
            mode_b = normalize_mode(tokens[i + 6])
            mode_c = normalize_mode(tokens[i + 7])
            if mode_a not in ANGLE_END_MODES or mode_c not in ANGLE_END_MODES or mode_b not in ANGLE_CENTER_MODES:
                raise ValueError("Invalid angle mode")
            if not (0.0 <= value <= 180.0):
                raise ValueError("Angle must be within [0, 180]")
            ops.append(("angle", (a, b, c, value, mode_a, mode_b, mode_c)))
            i += 8
        elif flag == "--dihedral":
            if i + 7 >= len(tokens):
                raise ValueError("--dihedral requires I J K L VALUE MODE_1 MODE_4")
            a = convert_index(tokens[i + 1], zero_based, natoms)
            b = convert_index(tokens[i + 2], zero_based, natoms)
            c = convert_index(tokens[i + 3], zero_based, natoms)
            d = convert_index(tokens[i + 4], zero_based, natoms)
            if len({a, b, c, d}) != 4:
                raise ValueError("Dihedral atoms must be distinct")
            value = float(tokens[i + 5])
            mode_a = normalize_mode(tokens[i + 6])
            mode_d = normalize_mode(tokens[i + 7])
            if mode_a not in DIHEDRAL_END_MODES or mode_d not in DIHEDRAL_END_MODES:
                raise ValueError("Invalid dihedral mode")
            if not (-180.0 <= value <= 180.0):
                raise ValueError("Dihedral must be within [-180, 180]")
            ops.append(("dihedral", (a, b, c, d, value, mode_a, mode_d)))
            i += 8
        else:
            raise ValueError(f"Unknown trailing argument: {flag}")
    return ops


def apply_bond(atoms, adjacency, i, j, target, mode_i, mode_j):
    current = atoms.get_distance(i, j)
    delta = target - current
    if abs(delta) < 1e-12:
        return

    u = unit_vector(atoms.positions[j] - atoms.positions[i])
    sel_i = bond_selection(adjacency, i, j, mode_i)
    sel_j = bond_selection(adjacency, j, i, mode_j)

    active = []
    if mode_i != "fixed":
        active.append(("i", sel_i))
    if mode_j != "fixed":
        active.append(("j", sel_j))
    if not active:
        raise ValueError("Bond operation has no movable side")

    weight = 1.0 / len(active)
    for side, selection in active:
        if side == "i":
            translate_indices(atoms, selection, -u * delta * weight)
        else:
            translate_indices(atoms, selection, u * delta * weight)


def angle_selection(adjacency, atom, center, mode):
    if mode == "rotate-atom":
        return [atom]
    if mode in {"rotate-group", "translate-group"}:
        return terminal_group_toward_center(adjacency, atom, center)
    raise ValueError(f"Unsupported terminal angle mode: {mode}")


def apply_angle_contributor(atoms, adjacency, i, j, k, target, contributor, exact=True):
    which, mode = contributor
    if which == "1":
        selection = angle_selection(adjacency, i, j, mode)
        if mode.startswith("rotate"):
            atoms.set_angle(k, j, i, target, indices=selection)
        elif mode == "translate-group":
            translate_terminal_to_angle(atoms, selection, i, j, k, target, side="1")
        else:
            solve_angle_by_translation(atoms, selection, i, j, k, target)
    elif which == "2":
        selection = [j] if mode == "translate-atom" else center_group_for_angle(adjacency, i, j, k)
        if exact:
            solve_angle_by_translation(atoms, selection, i, j, k, target)
        else:
            angle_center_bisector_step(atoms, selection, i, j, k, target - atoms.get_angle(i, j, k))
    elif which == "3":
        selection = angle_selection(adjacency, k, j, mode)
        if mode.startswith("rotate"):
            atoms.set_angle(i, j, k, target, indices=selection)
        elif mode == "translate-group":
            translate_terminal_to_angle(atoms, selection, i, j, k, target, side="3")
        else:
            solve_angle_by_translation(atoms, selection, i, j, k, target)
    else:
        raise ValueError(f"Unknown angle contributor: {which}")


def apply_angle(atoms, adjacency, i, j, k, target, mode_i, mode_j, mode_k):
    contributors = []
    if mode_i != "fixed":
        contributors.append(("1", mode_i))
    if mode_j != "fixed":
        contributors.append(("2", mode_j))
    if mode_k != "fixed":
        contributors.append(("3", mode_k))
    if not contributors:
        raise ValueError("Angle operation has no movable atom/group")

    current = atoms.get_angle(i, j, k)
    for idx, contributor in enumerate(contributors, start=1):
        frac = idx / len(contributors)
        intermediate_target = current + (target - current) * frac
        use_exact = True
        if contributor[0] == "2" and idx != len(contributors):
            use_exact = not (mode_j == "translate-atom" or mode_i == "fixed" or mode_k == "fixed")
        apply_angle_contributor(
            atoms,
            adjacency,
            i,
            j,
            k,
            intermediate_target,
            contributor,
            exact=use_exact,
        )


def apply_dihedral_contributor(atoms, adjacency, i, j, k, l, target, contributor, one_sided=False):
    which, mode = contributor
    before = atoms.copy()
    if which == "1":
        if mode == "rotate-atom":
            selection = [i]
        elif mode == "rotate-groups":
            selection = connected_component(adjacency, j, blocked_edges={(j, k)})
        else:
            selection = torsion_side_group(adjacency, i, j)
        set_dihedral_one_side(atoms, i, j, k, l, target, selection, side="left")
    elif which == "4":
        if mode == "rotate-atom":
            selection = [l]
        elif mode == "rotate-groups" and one_sided and k in adjacency[l] and len(adjacency[l]) == 1:
            selection = side_group(adjacency, l, k)
        elif mode == "rotate-groups":
            selection = connected_component(adjacency, k, blocked_edges={(j, k)})
        else:
            selection = torsion_side_group(adjacency, l, k)
        set_dihedral_one_side(atoms, i, j, k, l, target, selection, side="right")
        if mode == "rotate-groups" and one_sided and k in adjacency[l] and len(adjacency[l]) == 1:
            mirror_terminal_sibling_groups(atoms, before, adjacency, j, k, l)
    else:
        raise ValueError(f"Unknown dihedral contributor: {which}")


def apply_dihedral(atoms, adjacency, i, j, k, l, target, mode_i, mode_l):
    contributors = []
    if mode_i != "fixed":
        contributors.append(("1", mode_i))
    if mode_l != "fixed":
        contributors.append(("4", mode_l))
    if not contributors:
        raise ValueError("Dihedral operation has no movable side")

    current = get_dihedral_signed(atoms, i, j, k, l)
    for idx, contributor in enumerate(contributors, start=1):
        frac = idx / len(contributors)
        intermediate_target = interpolate_dihedral(current, target, frac)
        apply_dihedral_contributor(
            atoms,
            adjacency,
            i,
            j,
            k,
            l,
            intermediate_target,
            contributor,
            one_sided=(len(contributors) == 1),
        )


def format_atom_label(atoms, idx, zero_based):
    return f"{atoms.symbols[idx]}{format_index(idx, zero_based)}"


def format_atom_labels(atoms, indices, zero_based):
    if not indices:
        return "none"
    return ",".join(format_atom_label(atoms, idx, zero_based) for idx in indices)


def operation_label(atoms, op_type, values, zero_based):
    if op_type == "bond":
        i, j, target, mode_i, mode_j = values
        return (
            f"bond {format_atom_label(atoms, i, zero_based)}-"
            f"{format_atom_label(atoms, j, zero_based)} target={target:.6f} "
            f"modes={mode_i}/{mode_j}"
        )
    if op_type == "angle":
        i, j, k, target, mode_i, mode_j, mode_k = values
        return (
            f"angle {format_atom_label(atoms, i, zero_based)}-"
            f"{format_atom_label(atoms, j, zero_based)}-"
            f"{format_atom_label(atoms, k, zero_based)} target={target:.6f} "
            f"modes={mode_i}/{mode_j}/{mode_k}"
        )

    i, j, k, l, target, mode_i, mode_l = values
    return (
        f"dihedral {format_atom_label(atoms, i, zero_based)}-"
        f"{format_atom_label(atoms, j, zero_based)}-"
        f"{format_atom_label(atoms, k, zero_based)}-"
        f"{format_atom_label(atoms, l, zero_based)} target={target:.6f} "
        f"modes={mode_i}/{mode_l}"
    )


def moved_atom_indices(before_positions, after_positions, tol):
    displacements = np.linalg.norm(after_positions - before_positions, axis=1)
    return [idx for idx, displacement in enumerate(displacements) if displacement > tol], displacements


def print_moved_atoms(atoms, op_number, op_type, values, before_positions, zero_based, tol):
    moved, displacements = moved_atom_indices(before_positions, atoms.get_positions(), tol)
    max_displacement = float(displacements.max()) if len(displacements) else 0.0
    print(
        # f"moved_atoms op={op_number} "
        # f"{operation_label(atoms, op_type, values, zero_based)} "
        # f"count={len(moved)} max_displacement={max_displacement:.6f} "
        # f"atoms={format_atom_labels(atoms, moved, zero_based)}"
        f"moved_atoms {format_atom_labels(atoms, moved, zero_based)}"
    )


def print_final_values(atoms, operations, zero_based):
    for op_type, values in operations:
        if op_type == "bond":
            i, j, _, _, _ = values
            print(
                f"bond {format_index(i, zero_based)} {format_index(j, zero_based)} "
                f"{atoms.get_distance(i, j):.6f}"
            )
        elif op_type == "angle":
            i, j, k, _, _, _, _ = values
            print(
                f"angle {format_index(i, zero_based)} {format_index(j, zero_based)} "
                f"{format_index(k, zero_based)} {atoms.get_angle(i, j, k):.6f}"
            )
        else:
            i, j, k, l, _, _, _ = values
            print(
                f"dihedral {format_index(i, zero_based)} {format_index(j, zero_based)} "
                f"{format_index(k, zero_based)} {format_index(l, zero_based)} "
                f"{get_dihedral_signed(atoms, i, j, k, l):.6f}"
            )


def print_short_distance_pairs(atoms, cutoff, zero_based):
    symbols = atoms.get_chemical_symbols()
    positions = atoms.get_positions()
    found = False
    for i, j in combinations(range(len(atoms)), 2):
        distance = vector_norm(positions[i] - positions[j])
        if distance < cutoff:
            found = True
            print(
                f"Dangerouts Distantance "
                f"{symbols[i]}{format_index(i, zero_based)}-"
                f"{symbols[j]}{format_index(j, zero_based)} d={distance:.3f}"
            )
    if not found:
        print(f"short_distance_pairs_lt_{cutoff:.3f}=none")


def resolve_com_path(output_xyz, com_arg):
    if com_arg is None:
        return None
    if com_arg == "":
        return str(Path(output_xyz).with_suffix(".com"))
    return com_arg


def write_gaussian_com(atoms, path):
    lines = [
        "#N b3lyp/6-31g(d,p) sp",
        "",
        "TS",
        "",
        "0 1",
    ]
    symbols = atoms.get_chemical_symbols()
    for symbol, (x, y, z) in zip(symbols, atoms.get_positions()):
        lines.append(f"{symbol:<2} {x:16.12f} {y:16.12f} {z:16.12f}")
    lines.append("")
    Path(path).write_text("\n".join(lines))


def main():
    parser = build_parser()
    args, trailing = parser.parse_known_args(sys.argv[1:])
    atoms = io.read(args.input_xyz)
    adjacency = build_adjacency(atoms, args.cutoff_mult)
    operations = parse_operations(trailing, args.zero_based, len(atoms))

    if not operations:
        raise SystemExit("No operations were provided")

    for op_number, (op_type, values) in enumerate(operations, start=1):
        before_positions = atoms.get_positions().copy()
        if op_type == "bond":
            apply_bond(atoms, adjacency, *values)
        elif op_type == "angle":
            apply_angle(atoms, adjacency, *values)
        else:
            apply_dihedral(atoms, adjacency, *values)
        # if args.print_moved_atoms:
        print_moved_atoms(
            atoms,
            op_number,
            op_type,
            values,
            before_positions,
            args.zero_based,
            args.movement_tol,
        )

    io.write(args.output_xyz, atoms, format="xyz")
    com_path = resolve_com_path(args.output_xyz, args.com)
    if com_path is not None:
        write_gaussian_com(atoms, com_path)
    if args.print_final:
        print_final_values(atoms, operations, args.zero_based)
    print_short_distance_pairs(atoms, args.short_distance_cutoff, args.zero_based)
    print(f"Wrote {args.output_xyz}")
    if com_path is not None:
        print(f"Wrote {com_path}")


if __name__ == "__main__":
    main()
