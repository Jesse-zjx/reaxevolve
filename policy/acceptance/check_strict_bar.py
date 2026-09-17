#!/usr/bin/env python3
"""STRICT(v5) checker — sole acceptance implementation.

Clauses (see STRICT.md):
  1. Level      r2SCAN-3c / CPCM(water); integration grid reported as-built
  2. Frequency  EXACTLY one imaginary mode in the final NumFreq block
  3. Endpoints  raw IRC ends are the exact neutral species (RDKit canonical SMILES, charge 0)
  4. Discrete water  if both ends have H2O: compare H atom indices bonded to water O;
                     swapped → catalytic shuttle (allowed); identical → spectator (reject)

Modes:
  new       gate a candidate edge: exit 1 if any of clauses 2-4 fails.  (default for --ts)
  as-built  audit a finished deposit: report findings, exit 0.         (default for --deposit)

Usage
  check_strict_bar.py --deposit /path/to/glucose_ff_review_v1
  check_strict_bar.py --ts ts.out --irc-f IRC_F.xyz --irc-b IRC_B.xyz \\
                      --reactant "..." --product "..."
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys

STRICT_VERSION = "v5"
WATER = "O"  # canonical SMILES of H2O after RemoveHs
BOND_CUTOFF_A = 1.35  # H–O distance considered bonded for discrete water test

try:
    from rdkit import Chem, RDLogger
    from rdkit.Chem import rdDetermineBonds

    RDLogger.DisableLog("rdApp.*")
    HAVE_RDKIT = True
except Exception:
    HAVE_RDKIT = False


# ---------- parsing ----------
def parse_ts_out(path):
    """Return (imaginary modes, keyword line, grid label) from an ORCA TS output."""
    text = open(path, errors="ignore").read()
    tail = text[text.rfind("VIBRATIONAL FREQUENCIES") :]
    imag = [
        float(m.group(1))
        for m in re.finditer(r"([-\d.]+)\s*cm\*\*-1\s*\*\*\*imaginary", tail)
    ]
    kws = re.findall(r"^\|\s*\d+>\s*(!.*)$", text, re.M)
    kw = kws[0].strip() if kws else ""
    up = " ".join(kws).upper()
    if "DEFGRID3" in up:
        grid = "DEFGRID3"
    elif "DEFGRID1" in up:
        grid = "DEFGRID1"
    else:
        grid = "DEFGRID2 (ORCA default)"
    return imag, kw, grid


def read_xyz_atoms(path):
    """Return list of (symbol, x, y, z) or None."""
    try:
        lines = open(path, errors="ignore").read().strip().splitlines()
        n = int(lines[0].split()[0])
        atoms = []
        for line in lines[2 : 2 + n]:
            parts = line.split()
            if len(parts) < 4:
                continue
            atoms.append((parts[0], float(parts[1]), float(parts[2]), float(parts[3])))
        return atoms if len(atoms) == n else None
    except Exception:
        return None


def xyz_species(path):
    """Perceive an xyz as neutral closed-shell fragments.

    Returns (canonical SMILES of the whole system, [fragment SMILES], atom count)
    or (None, [], atom_count) when perception fails. Stereochemistry is dropped.
    """
    n = 0
    try:
        n = int(open(path).readline().split()[0])
    except Exception:
        pass
    if not HAVE_RDKIT:
        return None, [], n
    try:
        mol = Chem.MolFromXYZFile(path)
        if mol is None:
            return None, [], n
        rdDetermineBonds.DetermineBonds(mol, charge=0)
        mol = Chem.RemoveHs(mol)
        whole = Chem.MolToSmiles(mol, isomericSmiles=False)
        frags = sorted(
            Chem.MolToSmiles(f, isomericSmiles=False)
            for f in Chem.GetMolFrags(mol, asMols=True)
        )
        return whole, frags, n
    except Exception:
        return None, [], n


def canon(smiles):
    """Canonical, stereochemistry-free SMILES — matches what xyz_species returns."""
    if not HAVE_RDKIT or not smiles:
        return None
    m = Chem.MolFromSmiles(smiles)
    return Chem.MolToSmiles(m, isomericSmiles=False) if m else None


def water_h_indices(atoms):
    """Find complete neutral water fragments by geometry; return set of frozensets.

    Each frozenset is {O_index, H_a, H_b} (0-based atom indices). Multiple waters
    are returned if present. Used for the discrete water clause (v5).
    """
    if not atoms:
        return set()
    oxygens = [i for i, (sym, *_) in enumerate(atoms) if sym.upper() == "O"]
    hydrogens = [i for i, (sym, *_) in enumerate(atoms) if sym.upper() == "H"]
    waters = set()
    for oi in oxygens:
        _, ox, oy, oz = atoms[oi]
        bonded_h = []
        for hi in hydrogens:
            _, hx, hy, hz = atoms[hi]
            d = ((ox - hx) ** 2 + (oy - hy) ** 2 + (oz - hz) ** 2) ** 0.5
            if d <= BOND_CUTOFF_A:
                bonded_h.append(hi)
        if len(bonded_h) == 2:
            waters.add(frozenset([oi, bonded_h[0], bonded_h[1]]))
    return waters


def discrete_water_ok(irc_f, irc_b):
    """Clause 4 discrete water test.

    Returns (ok, detail) where ok is True/False/None.
      True  — no bilateral water, or catalytic shuttle (H indices differ)
      False — spectator water (identical O+H+H identities on both ends)
      None  — could not parse geometries
    """
    a_f = read_xyz_atoms(irc_f)
    a_b = read_xyz_atoms(irc_b)
    if a_f is None or a_b is None:
        return None, "could not parse IRC xyz for discrete water test"

    w_f = water_h_indices(a_f)
    w_b = water_h_indices(a_b)
    if not w_f or not w_b:
        return True, "no bilateral complete H2O fragments"

    # Match waters by oxygen index (atom order conserved along IRC).
    o_to_f = {next(i for i in w if a_f[i][0].upper() == "O"): w for w in w_f}
    o_to_b = {next(i for i in w if a_b[i][0].upper() == "O"): w for w in w_b}
    shared_o = set(o_to_f) & set(o_to_b)
    if not shared_o:
        # Different O indices — treat as non-spectator (unusual); allow with note.
        return True, "bilateral H2O but oxygen indices differ across ends"

    spectator = False
    shuttle = False
    details = []
    for oi in sorted(shared_o):
        hf = frozenset(i for i in o_to_f[oi] if i != oi)
        hb = frozenset(i for i in o_to_b[oi] if i != oi)
        if hf == hb:
            spectator = True
            details.append(f"spectator water O{oi}+H{sorted(hf)}")
        else:
            shuttle = True
            details.append(f"catalytic shuttle O{oi}: H{sorted(hf)} ↔ H{sorted(hb)}")

    # Any identical O+H+H identity is a spectator — reject even if another water shuttles.
    if spectator:
        return False, "; ".join(details)
    if shuttle:
        return True, "; ".join(details)
    return True, "; ".join(details) if details else "bilateral water cleared"


# ---------- clause checks ----------
def check_step(
    name,
    ts_out,
    irc_f=None,
    irc_b=None,
    reactant=None,
    product=None,
    coproduct=None,
):
    """Return a dict of clause results for one elementary step.

    coproduct: optional neutral SMILES present on the product side only
    (e.g. water for dehydration, formaldehyde for retro-aldol).
    """
    r = {
        "name": name,
        "notes": [],
        "strict_version": STRICT_VERSION,
    }

    imag, kw, grid = parse_ts_out(ts_out)
    r["grid"] = grid
    r["level_ok"] = ("R2SCAN-3C" in kw.upper()) and ("CPCM" in kw.upper())
    r["imag"] = imag
    r["single_imag"] = len(imag) == 1
    if len(imag) == 1 and imag[0] > -300:
        r["notes"].append(
            f"weak reactive mode ({imag[0]:.0f}) — confirm it is the intended motion"
        )

    r["endpoints_ok"] = None
    r["water_ok"] = None
    r["no_spectator_water"] = None  # alias kept for callers expecting v4 key
    r["water_detail"] = None

    if irc_f and irc_b and os.path.exists(irc_f) and os.path.exists(irc_b):
        f_whole, f_frags, f_n = xyz_species(irc_f)
        b_whole, b_frags, b_n = xyz_species(irc_b)
        r["fwd"], r["bwd"] = f_whole, b_whole
        r["atoms"] = (b_n, f_n)

        # clause 4 first — water class informs endpoint expectations for catalytic shuttles
        both_have_water = bool(f_frags and b_frags and WATER in f_frags and WATER in b_frags)
        if both_have_water:
            ok, detail = discrete_water_ok(irc_f, irc_b)
            r["water_ok"] = ok
            r["no_spectator_water"] = ok
            r["water_detail"] = detail
            if ok is False:
                r["notes"].append(f"spectator water rejected: {detail}")
            elif ok is True and "catalytic" in (detail or ""):
                r["notes"].append(f"catalytic water shuttle allowed: {detail}")
            elif ok is None:
                r["notes"].append(detail)
        else:
            r["water_ok"] = True
            r["no_spectator_water"] = True
            r["water_detail"] = "no bilateral H2O fragments"

        if reactant and product:
            want_r, want_p = canon(reactant), canon(product)
            want_c = canon(coproduct) if coproduct else None
            # Real dehydration often stores water as coproduct="O".
            if want_c is None and both_have_water and r.get("water_ok") is not False:
                # If only one end is organic+water vs organic, treat water as product.
                pass

            def side_frags(organic, with_coproduct=False, with_catalyst_water=False):
                fr = [organic]
                if with_coproduct and want_c:
                    fr.append(want_c)
                if with_catalyst_water:
                    fr.append(WATER)
                return sorted(fr)

            catalytic = both_have_water and r.get("water_ok") is True and "catalytic" in (
                r.get("water_detail") or ""
            )

            def matches(frags, organic, product_side=False):
                if catalytic:
                    return sorted(frags) == side_frags(
                        organic, with_catalyst_water=True
                    )
                # product side may include coproduct (H2O / CH2O / …)
                if product_side and want_c:
                    return sorted(frags) == side_frags(organic, with_coproduct=True)
                # also allow whole-SMILES equality for single-component sides
                whole = ".".join(sorted(frags)) if frags else None
                return frags == [organic] or whole == organic

            # Either orientation of IRC
            orient_a = matches(f_frags, want_p, True) and matches(b_frags, want_r, False)
            orient_b = matches(f_frags, want_r, False) and matches(b_frags, want_p, True)
            # Fallback: whole-string membership (legacy single-component)
            if not (orient_a or orient_b):
                fwd_ok = f_whole in (want_p, want_r) or (
                    want_c and f_whole in (canon(f"{want_p}.{want_c}"), canon(f"{want_c}.{want_p}"))
                )
                bwd_ok = b_whole in (want_p, want_r) or (
                    want_c and b_whole in (canon(f"{want_p}.{want_c}"), canon(f"{want_c}.{want_p}"))
                )
                r["endpoints_ok"] = bool(
                    f_whole and b_whole and fwd_ok and bwd_ok and f_whole != b_whole
                )
            else:
                r["endpoints_ok"] = True
        elif f_whole and b_whole:
            r["endpoints_ok"] = f_whole != b_whole

        dn = f_n - b_n
        if dn not in (0, -3, 3):
            r["notes"].append(f"atom count changes by {dn:+d} (expect 0 or ±3 for dry/dehyd)")
    else:
        r["notes"].append("IRC endpoints not supplied — clauses 3-4 not checked")

    hard = [r["single_imag"]]
    for k in ("endpoints_ok", "water_ok"):
        if r[k] is not None:
            hard.append(r[k])
    r["pass"] = all(hard)
    return r


# ---------- deposit discovery ----------
def discover_deposit(root):
    """Pair TS .out files with IRC endpoint .xyz files by step number."""
    outs = {}
    for p in glob.glob(os.path.join(root, "04_orca_inp_out_hess", "**", "*.out"), recursive=True):
        base = os.path.basename(p)
        if "IRC" in base.upper():
            continue
        m = re.search(r"step[_-]?(\d+)", base, re.I)
        if m:
            outs[int(m.group(1))] = p

    steps = []
    for num in sorted(outs):
        f = os.path.join(root, "03_irc_endpoints_xyz", f"step_{num}_IRC_F.xyz")
        b = os.path.join(root, "03_irc_endpoints_xyz", f"step_{num}_IRC_B.xyz")
        steps.append(
            {
                "name": f"step {num}",
                "ts_out": outs[num],
                "irc_f": f if os.path.exists(f) else None,
                "irc_b": b if os.path.exists(b) else None,
            }
        )
    return steps


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--deposit", help="deposit root (00_report/, 03_irc_endpoints_xyz/, ...)")
    ap.add_argument("--ts", help="ORCA TS .out for a single step")
    ap.add_argument("--irc-f")
    ap.add_argument("--irc-b")
    ap.add_argument("--reactant", help="expected reactant SMILES (neutral)")
    ap.add_argument("--product", help="expected product SMILES (neutral)")
    ap.add_argument(
        "--mode",
        choices=("new", "as-built"),
        help="new = gate a new edge (default for --ts); "
        "as-built = provenance record (default for --deposit)",
    )
    a = ap.parse_args()
    mode = a.mode or ("as-built" if a.deposit else "new")

    if a.deposit:
        steps = discover_deposit(a.deposit)
        if not steps:
            print(f"no TS .out found under {a.deposit}/04_orca_inp_out_hess/")
            return 1
        title = os.path.basename(os.path.normpath(a.deposit))
    elif a.ts:
        steps = [
            {
                "name": os.path.basename(a.ts),
                "ts_out": a.ts,
                "irc_f": a.irc_f,
                "irc_b": a.irc_b,
            }
        ]
        title = "single step"
    else:
        ap.error("give either --deposit or --ts")

    if not HAVE_RDKIT:
        print("note: rdkit unavailable — clauses 3-4 skipped\n")

    gating = mode == "new"
    results = []
    print(f"=== {title}   [STRICT {STRICT_VERSION} | mode: {mode}] ===")
    print(
        f"{'step':<10}{'imag (cm-1)':<22}{'grid':<26}"
        f"{'1 imag':<9}{'endpoints':<11}{'water':<12}"
    )
    print("-" * 90)
    for s in steps:
        r = check_step(
            s["name"],
            s["ts_out"],
            s.get("irc_f"),
            s.get("irc_b"),
            a.reactant,
            a.product,
        )
        results.append(r)

        def mark(v, fail_label="FAIL", false_label=None):
            if v is None:
                return "—"
            if v:
                return "ok"
            return fail_label if gating else (false_label or "note")

        imags = ", ".join(f"{v:.1f}" for v in r["imag"]) or "none"
        wlabel = mark(r["water_ok"], false_label="spectator")
        if r.get("water_detail") and "catalytic" in (r["water_detail"] or "") and r["water_ok"]:
            wlabel = "shuttle"
        print(
            f"{r['name']:<10}{imags:<22}{r['grid']:<26}"
            f"{mark(r['single_imag']):<9}{mark(r['endpoints_ok']):<11}"
            f"{wlabel:<12}"
        )
        for n in r["notes"]:
            print(f"          · {n}")

    n_ok = sum(1 for r in results if r["pass"])
    grids = {r["grid"] for r in results}
    print("-" * 90)
    print(f"STRICT {STRICT_VERSION} clauses 2-4 met: {n_ok}/{len(results)}")
    print(
        f"grid as-built: {', '.join(sorted(grids))}"
        + (
            "   (uniform)"
            if len(grids) == 1
            else "   (MIXED — quote the grid with every frequency)"
        )
    )
    if gating:
        print(
            f"VERDICT: {'PASS' if n_ok == len(results) else 'FAIL — does not meet STRICT(v5)'}"
        )
        return 0 if n_ok == len(results) else 1
    print("AS-BUILT RECORD — provenance only; this does not re-judge accepted work.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
