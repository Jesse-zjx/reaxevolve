#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
from collections import Counter
from itertools import islice

import networkx as nx
from rdkit import Chem
from rdkit.Chem import AllChem, Draw, rdDetermineBonds, rdFMCS


def build_parser():
    parser = argparse.ArgumentParser(
        description="Enumerate and score heavy-atom mappings between reactant and product SMILES."
    )
    parser.add_argument("reactant_smiles", help="Reactant SMILES")
    parser.add_argument("product_smiles", help="Product SMILES")
    parser.add_argument(
        "--reactant-xyz",
        help="Optional reactant XYZ file. If provided, reactant atom-map numbers are reassigned to match this file's 1-based atom indices.",
    )
    parser.add_argument(
        "--max-mappings",
        type=int,
        default=10,
        help="Maximum number of mappings to report (default: 10)",
    )
    parser.add_argument(
        "--beam-width",
        type=int,
        default=200,
        help="Beam width used when extending MCS seeds (default: 200)",
    )
    parser.add_argument(
        "--max-seed-matches",
        type=int,
        default=200,
        help="Maximum number of MCS matches to examine per molecule (default: 200)",
    )
    parser.add_argument(
        "--json-out",
        help=(
            "Optional path to write mapping records as JSON. "
            "By default writes only the top-ranked record; use --all-mapped "
            "to write all reported mappings. Each record includes "
            "mapped_reaction_smiles, formed_bonds, broken_bonds, "
            "bond_order_changes, and hydrogen_count_changes."
        ),
    )
    parser.add_argument(
        "--all-mapped",
        action="store_true",
        help="Print all mapped reaction SMILES instead of only the top-ranked one",
    )
    parser.add_argument(
        "--draw",
        nargs="?",
        const="mapped_reaction.png",
        help=(
            "Optionally draw the top-ranked mapped reaction. "
            "If no path is provided, writes ./mapped_reaction.png"
        ),
    )
    parser.add_argument(
        "--draw-all",
        nargs="?",
        const="mapped_reactions",
        help=(
            "Optionally draw all reported mapped reactions to a directory. "
            "If no directory is provided, writes ./mapped_reactions/"
        ),
    )
    return parser


def parse_smiles(smiles):
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Failed to parse SMILES: {smiles}")
    Chem.AssignStereochemistry(mol, cleanIt=True, force=True)
    return mol


def parse_xyz_with_connectivity(path):
    mol = Chem.MolFromXYZFile(str(path))
    if mol is None:
        raise ValueError(f"Failed to parse XYZ file: {path}")
    rdDetermineBonds.DetermineConnectivity(mol)
    return mol


def heavy_atom_indices(mol):
    return [atom.GetIdx() for atom in mol.GetAtoms() if atom.GetAtomicNum() > 1]


def build_connectivity_graph(mol, atom_indices):
    graph = nx.Graph()
    allowed = set(atom_indices)
    pos_by_orig = {orig_idx: pos for pos, orig_idx in enumerate(atom_indices)}

    for pos, orig_idx in enumerate(atom_indices):
        atom = mol.GetAtomWithIdx(orig_idx)
        neighbors = [
            nbr for nbr in atom.GetNeighbors()
            if nbr.GetIdx() in allowed
        ]
        neighbor_counts = Counter(nbr.GetAtomicNum() for nbr in neighbors)
        graph.add_node(
            pos,
            atomic_num=atom.GetAtomicNum(),
            degree=len(neighbors),
            neighbor_counts=tuple(sorted(neighbor_counts.items())),
        )

    for bond in mol.GetBonds():
        a = bond.GetBeginAtomIdx()
        b = bond.GetEndAtomIdx()
        if a not in pos_by_orig or b not in pos_by_orig:
            continue
        graph.add_edge(pos_by_orig[a], pos_by_orig[b])
    return graph


def graph_isomorphic_mappings(graph_a, graph_b, max_candidates):
    node_match = lambda a, b: (
        a["atomic_num"] == b["atomic_num"]
        and a["degree"] == b["degree"]
        and a["neighbor_counts"] == b["neighbor_counts"]
    )
    gm = nx.algorithms.isomorphism.GraphMatcher(graph_a, graph_b, node_match=node_match)
    if not gm.is_isomorphic():
        return []

    candidates = []
    seen = set()
    for mapping in islice(gm.isomorphisms_iter(), max_candidates):
        sig = mapping_signature(mapping)
        if sig in seen:
            continue
        seen.add(sig)
        candidates.append(mapping)
    return candidates


def infer_reactant_xyz_labels(mol_r, reactant_xyz_path):
    xyz_mol = parse_xyz_with_connectivity(reactant_xyz_path)
    reactant_with_h = Chem.AddHs(Chem.Mol(mol_r))

    if xyz_mol.GetNumAtoms() == reactant_with_h.GetNumAtoms():
        reactant_atom_indices = list(range(reactant_with_h.GetNumAtoms()))
        xyz_atom_indices = list(range(xyz_mol.GetNumAtoms()))
        graph_reactant = build_connectivity_graph(reactant_with_h, reactant_atom_indices)
        graph_xyz = build_connectivity_graph(xyz_mol, xyz_atom_indices)
        mappings = graph_isomorphic_mappings(graph_reactant, graph_xyz, max_candidates=20)
        if not mappings:
            raise ValueError(
                "Reactant XYZ connectivity does not match the reactant SMILES with explicit hydrogens."
            )
        smiles_to_xyz = mappings[0]
        return {
            atom_idx: smiles_to_xyz[atom_idx] + 1
            for atom_idx in heavy_atom_indices(mol_r)
        }

    heavy_r = heavy_atom_indices(mol_r)
    heavy_xyz = heavy_atom_indices(xyz_mol)
    if len(heavy_r) != len(heavy_xyz):
        raise ValueError(
            "Reactant XYZ atom count does not match the reactant SMILES, even after ignoring hydrogens."
        )

    graph_reactant = build_connectivity_graph(mol_r, heavy_r)
    graph_xyz = build_connectivity_graph(xyz_mol, heavy_xyz)
    mappings = graph_isomorphic_mappings(graph_reactant, graph_xyz, max_candidates=20)
    if not mappings:
        raise ValueError(
            "Reactant XYZ heavy-atom connectivity does not match the reactant SMILES."
        )

    pos_to_orig_r = {pos: orig for pos, orig in enumerate(heavy_r)}
    pos_to_orig_xyz = {pos: orig for pos, orig in enumerate(heavy_xyz)}
    return {
        pos_to_orig_r[r_pos]: pos_to_orig_xyz[xyz_pos] + 1
        for r_pos, xyz_pos in mappings[0].items()
    }


def heavy_atom_features(mol, atom_idx):
    atom = mol.GetAtomWithIdx(atom_idx)
    heavy_neighbors = [
        nbr for nbr in atom.GetNeighbors()
        if nbr.GetAtomicNum() > 1
    ]
    neighbor_counts = Counter(nbr.GetAtomicNum() for nbr in heavy_neighbors)
    return {
        "atomic_num": atom.GetAtomicNum(),
        "symbol": atom.GetSymbol(),
        "formal_charge": atom.GetFormalCharge(),
        "is_aromatic": atom.GetIsAromatic(),
        "chiral_tag": str(atom.GetChiralTag()),
        "degree": len(heavy_neighbors),
        "total_valence": atom.GetTotalValence(),
        "total_hs": atom.GetTotalNumHs(),
        "neighbor_counts": tuple(sorted(neighbor_counts.items())),
    }


def build_heavy_graph(mol, heavy_idxs):
    graph = nx.Graph()
    pos_by_orig = {orig_idx: pos for pos, orig_idx in enumerate(heavy_idxs)}
    for pos, orig_idx in enumerate(heavy_idxs):
        feat = heavy_atom_features(mol, orig_idx)
        graph.add_node(pos, **feat)
    for bond in mol.GetBonds():
        a = bond.GetBeginAtomIdx()
        b = bond.GetEndAtomIdx()
        if a not in pos_by_orig or b not in pos_by_orig:
            continue
        graph.add_edge(
            pos_by_orig[a],
            pos_by_orig[b],
            order=bond_order_value(bond),
            is_aromatic=bond.GetIsAromatic(),
        )
    return graph


def bond_order_value(bond):
    if bond is None:
        return None
    if bond.GetIsAromatic():
        return 1.5
    return float(bond.GetBondTypeAsDouble())


def node_similarity(node_a, node_b):
    if node_a["atomic_num"] != node_b["atomic_num"]:
        return -1e9

    score = 20.0
    if node_a["formal_charge"] == node_b["formal_charge"]:
        score += 2.0
    else:
        score -= 2.5 * abs(node_a["formal_charge"] - node_b["formal_charge"])

    if node_a["is_aromatic"] == node_b["is_aromatic"]:
        score += 1.0
    else:
        score -= 1.0

    score -= 1.2 * abs(node_a["degree"] - node_b["degree"])
    score -= 0.6 * abs(node_a["total_valence"] - node_b["total_valence"])
    score -= 0.8 * abs(node_a["total_hs"] - node_b["total_hs"])

    if node_a["chiral_tag"] == node_b["chiral_tag"]:
        score += 0.5

    counter_a = Counter(dict(node_a["neighbor_counts"]))
    counter_b = Counter(dict(node_b["neighbor_counts"]))
    overlap = sum((counter_a & counter_b).values())
    total = sum((counter_a | counter_b).values())
    if total:
        score += 3.0 * overlap / total

    return score


def bond_similarity(edge_a, edge_b):
    if edge_a is None and edge_b is None:
        return 0.0
    if edge_a is None:
        return -6.0
    if edge_b is None:
        return -6.0

    score = 5.0
    if edge_a["is_aromatic"] == edge_b["is_aromatic"]:
        score += 0.5
    order_delta = abs(edge_a["order"] - edge_b["order"])
    score -= 2.0 * order_delta
    return score


def score_mapping(graph_r, graph_p, mapping):
    score = 0.0
    for r_pos, p_pos in mapping.items():
        score += node_similarity(graph_r.nodes[r_pos], graph_p.nodes[p_pos])

    n = len(mapping)
    for r_i in range(n):
        p_i = mapping[r_i]
        for r_j in range(r_i + 1, n):
            p_j = mapping[r_j]
            edge_r = graph_r.get_edge_data(r_i, r_j)
            edge_p = graph_p.get_edge_data(p_i, p_j)
            score += bond_similarity(edge_r, edge_p)
    return score


def mapping_signature(mapping):
    return tuple(mapping[i] for i in sorted(mapping))


def graph_isomorphic_candidates(graph_r, graph_p, max_candidates):
    node_match = lambda a, b: a["atomic_num"] == b["atomic_num"]
    gm = nx.algorithms.isomorphism.GraphMatcher(graph_r, graph_p, node_match=node_match)
    if not gm.is_isomorphic():
        return []

    candidates = []
    seen = set()
    for mapping in islice(gm.isomorphisms_iter(), max_candidates):
        sig = mapping_signature(mapping)
        if sig in seen:
            continue
        seen.add(sig)
        candidates.append(mapping)
    return candidates


def find_mcs_seeds(mol_r, mol_p, pos_by_orig_r, pos_by_orig_p, max_seed_matches):
    params = rdFMCS.MCSParameters()
    params.AtomTyper = rdFMCS.AtomCompare.CompareElements
    params.BondTyper = rdFMCS.BondCompare.CompareAny
    params.MaximizeBonds = True
    params.AtomCompareParameters.CompleteRingsOnly = False
    params.AtomCompareParameters.RingMatchesRingOnly = False
    params.AtomCompareParameters.MatchValences = False
    params.Timeout = 10

    result = rdFMCS.FindMCS([mol_r, mol_p], params)
    if not result.smartsString:
        return [dict()]

    query = Chem.MolFromSmarts(result.smartsString)
    react_matches = mol_r.GetSubstructMatches(query, uniquify=False, maxMatches=max_seed_matches)
    prod_matches = mol_p.GetSubstructMatches(query, uniquify=False, maxMatches=max_seed_matches)

    seeds = []
    seen = set()
    for react_match in react_matches:
        for prod_match in prod_matches:
            seed = {}
            for react_orig, prod_orig in zip(react_match, prod_match):
                if react_orig not in pos_by_orig_r or prod_orig not in pos_by_orig_p:
                    continue
                seed[pos_by_orig_r[react_orig]] = pos_by_orig_p[prod_orig]
            sig = mapping_signature(seed)
            if sig in seen:
                continue
            seen.add(sig)
            seeds.append(seed)
    return seeds or [dict()]


def best_candidate_products(graph_p, graph_r, react_pos, used_products):
    react_node = graph_r.nodes[react_pos]
    candidates = []
    for prod_pos, prod_node in graph_p.nodes(data=True):
        if prod_pos in used_products:
            continue
        if react_node["atomic_num"] != prod_node["atomic_num"]:
            continue
        score = node_similarity(react_node, prod_node)
        candidates.append((score, prod_pos))
    candidates.sort(reverse=True)
    return [prod_pos for _, prod_pos in candidates]


def select_next_reactant(mapping, graph_r, graph_p):
    used_products = set(mapping.values())
    remaining = [pos for pos in graph_r.nodes if pos not in mapping]
    ranked = []
    for react_pos in remaining:
        candidates = best_candidate_products(graph_p, graph_r, react_pos, used_products)
        ranked.append((
            len(candidates),
            -graph_r.nodes[react_pos]["degree"],
            react_pos,
            candidates,
        ))
    ranked.sort()
    _, _, react_pos, candidates = ranked[0]
    return react_pos, candidates


def incremental_score(graph_r, graph_p, partial_mapping, react_pos, prod_pos):
    score = node_similarity(graph_r.nodes[react_pos], graph_p.nodes[prod_pos])
    for mapped_r, mapped_p in partial_mapping.items():
        edge_r = graph_r.get_edge_data(react_pos, mapped_r)
        edge_p = graph_p.get_edge_data(prod_pos, mapped_p)
        score += bond_similarity(edge_r, edge_p)
    return score


def extend_seed_mapping(seed, graph_r, graph_p, beam_width, max_complete):
    initial_score = 0.0
    for react_pos, prod_pos in seed.items():
        initial_score += node_similarity(graph_r.nodes[react_pos], graph_p.nodes[prod_pos])
    states = [(initial_score, dict(seed))]

    while states and len(states[0][1]) < graph_r.number_of_nodes():
        next_states = []
        for partial_score, partial_mapping in states:
            react_pos, candidates = select_next_reactant(partial_mapping, graph_r, graph_p)
            used_products = set(partial_mapping.values())
            for prod_pos in candidates:
                if prod_pos in used_products:
                    continue
                delta = incremental_score(graph_r, graph_p, partial_mapping, react_pos, prod_pos)
                new_mapping = dict(partial_mapping)
                new_mapping[react_pos] = prod_pos
                next_states.append((partial_score + delta, new_mapping))
        next_states.sort(key=lambda item: item[0], reverse=True)
        deduped = []
        seen = set()
        for score, mapping in next_states:
            sig = mapping_signature(mapping)
            if sig in seen:
                continue
            seen.add(sig)
            deduped.append((score, mapping))
            if len(deduped) >= beam_width:
                break
        states = deduped

    completed = []
    seen = set()
    for _, mapping in states:
        if len(mapping) != graph_r.number_of_nodes():
            continue
        sig = mapping_signature(mapping)
        if sig in seen:
            continue
        seen.add(sig)
        completed.append(mapping)
        if len(completed) >= max_complete:
            break
    return completed


def reactant_atom_label(atom_idx, reactant_labels=None):
    if reactant_labels is None:
        return atom_idx + 1
    return reactant_labels[atom_idx]


def format_bond_label(atom_a, symbol_a, atom_b, symbol_b):
    left = (atom_a, symbol_a)
    right = (atom_b, symbol_b)
    if right[0] < left[0]:
        left, right = right, left
    return f"{left[1]}{left[0]}-{right[1]}{right[0]}"


def format_hydrogen_change(atom_label, symbol, delta):
    sign = "+" if delta > 0 else ""
    return f"{symbol}{atom_label}:{sign}{delta}H"


def bond_changes(mol_r, mol_p, heavy_r, heavy_p, mapping, reactant_labels=None):
    pos_to_orig_r = {pos: orig for pos, orig in enumerate(heavy_r)}
    pos_to_orig_p = {pos: orig for pos, orig in enumerate(heavy_p)}

    formed = []
    broken = []
    changed = []
    hydrogen_delta = []

    n = len(mapping)
    for r_i in range(n):
        p_i = mapping[r_i]
        atom_r = mol_r.GetAtomWithIdx(pos_to_orig_r[r_i])
        atom_p = mol_p.GetAtomWithIdx(pos_to_orig_p[p_i])
        h_r = atom_r.GetTotalNumHs()
        h_p = atom_p.GetTotalNumHs()
        if h_r != h_p:
            hydrogen_delta.append(
                format_hydrogen_change(
                    reactant_atom_label(pos_to_orig_r[r_i], reactant_labels),
                    atom_r.GetSymbol(),
                    h_p - h_r,
                )
            )

    for r_i in range(n):
        p_i = mapping[r_i]
        for r_j in range(r_i + 1, n):
            p_j = mapping[r_j]
            bond_r = mol_r.GetBondBetweenAtoms(pos_to_orig_r[r_i], pos_to_orig_r[r_j])
            bond_p = mol_p.GetBondBetweenAtoms(pos_to_orig_p[p_i], pos_to_orig_p[p_j])
            order_r = bond_order_value(bond_r)
            order_p = bond_order_value(bond_p)
            atom_label_i = reactant_atom_label(pos_to_orig_r[r_i], reactant_labels)
            atom_label_j = reactant_atom_label(pos_to_orig_r[r_j], reactant_labels)
            symbol_i = mol_r.GetAtomWithIdx(pos_to_orig_r[r_i]).GetSymbol()
            symbol_j = mol_r.GetAtomWithIdx(pos_to_orig_r[r_j]).GetSymbol()
            bond_label = format_bond_label(atom_label_i, symbol_i, atom_label_j, symbol_j)

            if bond_r is not None and bond_p is None:
                broken.append(bond_label)
            elif bond_r is None and bond_p is not None:
                formed.append(bond_label)
            elif bond_r is not None and bond_p is not None and abs(order_r - order_p) > 1e-6:
                changed.append({
                    "bond": bond_label,
                    "reactant_order": order_r,
                    "product_order": order_p,
                })

    return formed, broken, changed, hydrogen_delta


def as_mapping_records(
    mol_r,
    mol_p,
    heavy_r,
    heavy_p,
    graph_r,
    graph_p,
    mappings,
    reactant_labels=None,
):
    records = []
    pos_to_orig_r = {pos: orig for pos, orig in enumerate(heavy_r)}
    pos_to_orig_p = {pos: orig for pos, orig in enumerate(heavy_p)}

    for rank, mapping in enumerate(mappings, start=1):
        score = score_mapping(graph_r, graph_p, mapping)
        formed, broken, changed, hydrogen_delta = bond_changes(
            mol_r,
            mol_p,
            heavy_r,
            heavy_p,
            mapping,
            reactant_labels=reactant_labels,
        )
        mapping_r2p = {
            str(reactant_atom_label(pos_to_orig_r[r_pos], reactant_labels)): pos_to_orig_p[p_pos] + 1
            for r_pos, p_pos in sorted(mapping.items())
        }
        mapping_p2r = {
            str(pos_to_orig_p[p_pos] + 1): reactant_atom_label(pos_to_orig_r[r_pos], reactant_labels)
            for r_pos, p_pos in sorted(mapping.items())
        }
        records.append({
            "rank": rank,
            "score": score,
            "reactant_to_product": mapping_r2p,
            "product_to_reactant": mapping_p2r,
            "formed_bonds": formed,
            "broken_bonds": broken,
            "bond_order_changes": changed,
            "hydrogen_count_changes": hydrogen_delta,
            "mapped_reaction_smiles": mapped_reaction_smiles(
                mol_r,
                mol_p,
                pos_to_orig_r,
                pos_to_orig_p,
                mapping,
                reactant_labels=reactant_labels,
            ),
        })
    return records


def dedupe_and_rank_mappings(graph_r, graph_p, mapping_candidates, max_mappings):
    scored = []
    seen = set()
    for mapping in mapping_candidates:
        sig = mapping_signature(mapping)
        if sig in seen:
            continue
        seen.add(sig)
        scored.append((score_mapping(graph_r, graph_p, mapping), mapping))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [mapping for _, mapping in scored[:max_mappings]]


def ensure_same_heavy_formula(mol_r, mol_p, heavy_r, heavy_p):
    counts_r = Counter(mol_r.GetAtomWithIdx(idx).GetAtomicNum() for idx in heavy_r)
    counts_p = Counter(mol_p.GetAtomWithIdx(idx).GetAtomicNum() for idx in heavy_p)
    if counts_r != counts_p:
        raise ValueError(
            "Reactant and product heavy-atom compositions differ: "
            f"{dict(counts_r)} vs {dict(counts_p)}"
        )


def mapped_side_smiles(mol, atom_map_numbers):
    mapped = Chem.Mol(mol)
    for atom in mapped.GetAtoms():
        atom.SetAtomMapNum(atom_map_numbers.get(atom.GetIdx(), 0))
    return Chem.MolToSmiles(mapped, canonical=False)


def mapped_reaction_smiles(mol_r, mol_p, pos_to_orig_r, pos_to_orig_p, mapping, reactant_labels=None):
    react_maps = {
        pos_to_orig_r[r_pos]: reactant_atom_label(pos_to_orig_r[r_pos], reactant_labels)
        for r_pos in mapping
    }
    prod_maps = {
        pos_to_orig_p[p_pos]: reactant_atom_label(pos_to_orig_r[r_pos], reactant_labels)
        for r_pos, p_pos in mapping.items()
    }
    react_smiles = mapped_side_smiles(mol_r, react_maps)
    prod_smiles = mapped_side_smiles(mol_p, prod_maps)
    return react_smiles + ">>" + prod_smiles


def draw_reaction(mapped_rxn_smiles, output_path):
    ext = Path(output_path).suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg"}:
        raise ValueError("--draw currently supports .png/.jpg/.jpeg output")
    reaction = AllChem.ReactionFromSmarts(mapped_rxn_smiles, useSmiles=True)
    if reaction is None:
        raise ValueError("Failed to build reaction object from mapped reaction SMILES")
    image = Draw.ReactionToImage(reaction, subImgSize=(500, 250))
    image.save(output_path)


def draw_all_reactions(records, output_dir):
    output_dir = Path(output_dir)
    if output_dir.exists() and not output_dir.is_dir():
        raise ValueError(f"--draw-all expects a directory path, got file: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    output_paths = []
    for record in records:
        output_path = output_dir / f"mapping_{record['rank']:03d}.png"
        draw_reaction(record["mapped_reaction_smiles"], output_path)
        output_paths.append(output_path)
    return output_paths


def compact_mapping_records(records):
    fields = [
        "mapped_reaction_smiles",
        "formed_bonds",
        "broken_bonds",
        "bond_order_changes",
        "hydrogen_count_changes",
    ]
    return [
        {field: record[field] for field in fields}
        for record in records
    ]


def main():
    args = build_parser().parse_args()

    mol_r = parse_smiles(args.reactant_smiles)
    mol_p = parse_smiles(args.product_smiles)
    reactant_labels = None
    if args.reactant_xyz:
        reactant_labels = infer_reactant_xyz_labels(mol_r, args.reactant_xyz)
    heavy_r = heavy_atom_indices(mol_r)
    heavy_p = heavy_atom_indices(mol_p)
    ensure_same_heavy_formula(mol_r, mol_p, heavy_r, heavy_p)
    pos_by_orig_r = {orig: pos for pos, orig in enumerate(heavy_r)}
    pos_by_orig_p = {orig: pos for pos, orig in enumerate(heavy_p)}

    graph_r = build_heavy_graph(mol_r, heavy_r)
    graph_p = build_heavy_graph(mol_p, heavy_p)

    mapping_candidates = graph_isomorphic_candidates(
        graph_r,
        graph_p,
        max_candidates=max(args.max_mappings * 50, 200),
    )

    if not mapping_candidates:
        seeds = find_mcs_seeds(
            mol_r,
            mol_p,
            pos_by_orig_r,
            pos_by_orig_p,
            args.max_seed_matches,
        )
        completed = []
        for seed in seeds:
            completed.extend(
                extend_seed_mapping(
                    seed,
                    graph_r,
                    graph_p,
                    beam_width=args.beam_width,
                    max_complete=max(args.max_mappings * 10, 50),
                )
            )
        mapping_candidates = completed

    best_mappings = dedupe_and_rank_mappings(
        graph_r,
        graph_p,
        mapping_candidates,
        max_mappings=args.max_mappings,
    )

    records = as_mapping_records(
        mol_r,
        mol_p,
        heavy_r,
        heavy_p,
        graph_r,
        graph_p,
        best_mappings,
        reactant_labels=reactant_labels,
    )

    result = {
        "reactant_smiles": args.reactant_smiles,
        "product_smiles": args.product_smiles,
        "reactant_xyz": args.reactant_xyz,
        "reactant_atom_labels_source": "reactant_xyz" if reactant_labels else "reactant_smiles",
        "reactant_heavy_atoms": len(heavy_r),
        "product_heavy_atoms": len(heavy_p),
        "mappings": records,
    }
    if reactant_labels:
        result["reactant_smiles_to_xyz"] = {
            str(atom_idx + 1): reactant_labels[atom_idx]
            for atom_idx in sorted(reactant_labels)
        }

    if not records:
        raise SystemExit("No mappings found.")

    if args.all_mapped:
        for record in records:
            print(record["mapped_reaction_smiles"])
    else:
        print(records[0]["mapped_reaction_smiles"])

    if args.draw:
        draw_reaction(records[0]["mapped_reaction_smiles"], args.draw)
        print(f"Wrote {args.draw}")

    if args.draw_all:
        output_paths = draw_all_reactions(records, args.draw_all)
        print(f"Wrote {len(output_paths)} mapped reaction drawings to {args.draw_all}")

    if args.json_out:
        json_records = records if args.all_mapped else records[:1]
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump(compact_mapping_records(json_records), handle, indent=2, sort_keys=False)
        print(f"Wrote {args.json_out}")


if __name__ == "__main__":
    main()
