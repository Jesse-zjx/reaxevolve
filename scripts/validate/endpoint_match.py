#!/usr/bin/env python3
"""Sole endpoint-matching implementation (neutral canonical SMILES multisets).

Used by QM drivers and by STRICT(v5) adjudication. Do not duplicate elsewhere.
"""
from __future__ import annotations

import os
import tempfile

import numpy as np
from rdkit import Chem
from rdkit.Chem import rdDetermineBonds

COV = {"H": 0.31, "C": 0.76, "O": 0.66, "N": 0.71}


def read_xyz(path):
    lines = open(path).read().splitlines()
    n = int(lines[0].split()[0])
    sym = [ln.split()[0] for ln in lines[2 : 2 + n]]
    xyz = np.array([[float(v) for v in ln.split()[1:4]] for ln in lines[2 : 2 + n]])
    return sym, xyz


def atom_fragments(sym, xyz, scale=1.3):
    """Split all atoms (incl H) into connected fragments; return list of (syms, coords)."""
    n = len(sym)
    adj = {i: set() for i in range(n)}
    for i in range(n):
        for j in range(i + 1, n):
            if np.linalg.norm(xyz[i] - xyz[j]) < scale * (
                COV.get(sym[i], 0.77) + COV.get(sym[j], 0.77)
            ):
                adj[i].add(j)
                adj[j].add(i)
    seen = set()
    frags = []
    for s0 in range(n):
        if s0 in seen:
            continue
        st = [s0]
        comp = []
        while st:
            a = st.pop()
            if a in seen:
                continue
            seen.add(a)
            comp.append(a)
            st.extend(adj[a] - seen)
        frags.append(sorted(comp))
    return [([sym[i] for i in c], xyz[c]) for c in frags]


def frag_canon(syms, coords):
    """Neutral canonical SMILES (no stereo) of one fragment; None if perception fails."""
    with tempfile.NamedTemporaryFile("w", suffix=".xyz", delete=False) as f:
        f.write(f"{len(syms)}\n\n")
        for s, c in zip(syms, coords):
            f.write(f"{s} {c[0]:.6f} {c[1]:.6f} {c[2]:.6f}\n")
        tmp = f.name
    try:
        m = Chem.MolFromXYZFile(tmp)
        rdDetermineBonds.DetermineBonds(m, charge=0)
        smi = Chem.MolToSmiles(Chem.RemoveHs(Chem.Mol(m), sanitize=False))
        return Chem.CanonSmiles(smi, useChiral=0)
    except Exception:
        return None
    finally:
        os.unlink(tmp)


def canon(smi):
    try:
        return Chem.CanonSmiles(smi, useChiral=0)
    except Exception:
        return smi


def endpoint_matches(irc_xyz, expected_smis):
    """Multiset of neutral canonical SMILES of IRC fragments must equal expected.

    Charged/zwitterionic endpoints fail DetermineBonds(charge=0) and are rejected.
    Returns (ok, got, exp).
    """
    sym, xyz = read_xyz(irc_xyz)
    # Sort with a total order. frag_canon returns None for a fragment RDKit cannot perceive —
    # dissociated, radical, or otherwise mangled — and comparing None against anything raises,
    # so a plain sorted() crashed here before the `None not in got` guard below could run. The
    # crash was not hypothetical: a naive interpolation guess in the bar-resolution probe reached
    # an IRC endpoint with two unperceivable fragments and took down the validator, which in the
    # loop means the attempt yields no verdict at all rather than a rejection.
    #
    # This cannot change any accept/reject decision. For endpoints whose fragments are all
    # perceivable the ordering is unchanged, and an unperceivable fragment was already specified
    # as a rejection by the guard and by the docstring above — it simply became reachable.
    got = sorted(
        (frag_canon(s, c) for s, c in atom_fragments(sym, xyz)),
        key=lambda s: (s is None, s or ""),
    )
    exp = sorted(canon(s) for s in expected_smis)
    return (None not in got) and (got == exp), got, exp


def classify_double_ended(fpath, bpath, reactant, product, coproduct=None, spectators=None):
    """Classify F/B endpoints vs expected R/P (+ optional coproduct/spectators).

    Returns dict with endpoint_match flags and a coarse label in
    {double_ended, one_sided, mismatch} — not a STRICT verdict.
    """
    spect = list(spectators or [])
    prod_side = [product] + ([coproduct] if coproduct else []) + spect
    react_side = [reactant] + spect
    fF_R, *_ = endpoint_matches(fpath, react_side)
    fF_P, *_ = endpoint_matches(fpath, prod_side)
    fB_R, *_ = endpoint_matches(bpath, react_side)
    fB_P, *_ = endpoint_matches(bpath, prod_side)
    strict_pair = (fF_R and fB_P) or (fF_P and fB_R)
    one = fF_R or fF_P or fB_R or fB_P
    return {
        "endpoint_match": {
            "F_isReactant": fF_R,
            "F_isProduct": fF_P,
            "B_isReactant": fB_R,
            "B_isProduct": fB_P,
        },
        "double_ended": bool(strict_pair),
        "one_sided": bool(one and not strict_pair),
        "label": "double_ended" if strict_pair else ("one_sided" if one else "mismatch"),
    }
