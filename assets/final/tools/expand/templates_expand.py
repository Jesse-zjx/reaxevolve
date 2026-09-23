#!/usr/bin/env python3
"""Reaction-template-driven frontier expander (replacement for low-yield YARP
enumeration). Given a species SMILES, enumerate chemically-valid NEUTRAL candidate
products via aqueous biomass-valorization reaction templates, tag reaction_kind, dedupe vs the
graph, score toward targets, and emit a validation queue.

Templates (RDKit reaction SMARTS on explicit-H mol + graph-based ring close/open):
  - dehydration (beta-elimination, -H2O, form C=C)
  - keto<->enol / aldose<->ketose tautomerization (1,2-H shift)
  - retro-aldol (C-C cleavage beta to a carbonyl -> two fragments)
  - ring close / open (hemiketal/hemiacetal: a -OH and a C=O at 1,4/1,5 form/break a 5/6 ring)
Each candidate then goes to strict TS/IRC validation via the method ladder.
"""
import sys, json, itertools, collections
from rdkit import Chem
from rdkit.Chem import AllChem, rdMolDescriptors as desc
from rdkit import RDLogger
RDLogger.DisableLog('rdApp.*')

# Sub-journal-scale target set for aqueous / hydrothermal biomass valorization.
# All are classic glucose/xylose-derived products reachable by the current template set
# (dehydration, keto<->enol tautomerization, retro-aldol C-C cleavage, ring close/open).
TARGETS = {
    'HMF': 'O=Cc1ccc(CO)o1',            # 5-hydroxymethylfurfural
    'FF': 'O=Cc1ccco1',                 # furfural
    'HAA': 'O=CCO',                     # glycolaldehyde
    'furan': 'c1ccoc1',
    '5-MF': 'Cc1ccc(C=O)o1',           # 5-methylfurfural
    'furfuryl_alcohol': 'OCc1ccco1',
    'glyceraldehyde': 'O=CC(O)CO',
    'DHA': 'OCC(=O)CO',                 # dihydroxyacetone
    'pyruvaldehyde': 'CC(=O)C=O',      # methylglyoxal
    'glyoxal': 'O=CC=O',
    'erythrose': 'O=CC(O)C(O)CO',
    'acetol': 'CC(=O)CO',              # hydroxyacetone
}

# RDKit reaction SMARTS (run on AddHs mol). Products kept neutral.
RXN = {
    'dehydration': '[O;H1:3][C:1][C:2][#1:4]>>[C:1]=[C:2].[O:3][#1:4]',
    'keto_to_enol': '[C:1](=[O:2])[C:3][#1:4]>>[C:1]([O:2][#1:4])=[C:3]',
    'enol_to_keto': '[C:1]([O;H1:2])=[C:3]>>[C:1](=[O:2])[C:3][#1]',
    'retro_aldol': '[C:1](=[O:2])[C:3][C:4][O:5][#1:6]>>[C:1](=[O:2])[C:3][#1:6].[C:4]=[O:5]',
}


def canon(s):
    m = Chem.MolFromSmiles(s)
    if not m:
        return None
    Chem.RemoveStereochemistry(m)
    return Chem.MolToSmiles(m)


_BAD = [Chem.MolFromSmarts(p) for p in (
    '[*]=[*]=[*]',      # cumulene / allene / ketene / CO2-like
    '[OX2]-[OX2]',       # peroxide
    '[#6]#[#6]',         # alkyne (implausible in this chemistry)
)]


def neutral_ok(s):
    m = Chem.MolFromSmiles(s)
    if not m:
        return False
    if any(a.GetFormalCharge() != 0 for a in m.GetAtoms()):
        return False
    for f in s.split('.'):
        mf = Chem.MolFromSmiles(f)
        if mf is None:
            return False
        if any(mf.HasSubstructMatch(b) for b in _BAD):
            return False
    return True


def run_smarts(smi):
    out = []
    mol = Chem.AddHs(Chem.MolFromSmiles(smi))
    for kind, sma in RXN.items():
        rxn = AllChem.ReactionFromSmarts(sma)
        try:
            prods = rxn.RunReactants((mol,))
        except Exception:
            continue
        for ps in prods:
            frags = []
            ok = True
            for p in ps:
                try:
                    Chem.SanitizeMol(p)
                    frags.append(Chem.MolToSmiles(Chem.RemoveHs(p)))
                except Exception:
                    ok = False
            if not ok:
                continue
            # main organic product = largest non-water fragment(s)
            allfrags = []
            for f in frags:
                allfrags += f.split('.')
            org = [f for f in allfrags if canon(f) != canon('O')]
            water = any(canon(f) == canon('O') for f in allfrags)
            if not org:
                continue
            # for retro_aldol keep both organic fragments; else main = the changed organic
            prod = canon('.'.join(org))
            if prod and neutral_ok(prod):
                out.append((prod, kind, 'O' if water else None))
    return out


def ring_close_open(smi):
    """Graph-based hemiketal ring close (OH + C=O at 1,4 or 1,5 -> 5/6 ring) and
    ring open (reverse). Returns (product_smiles, kind, coproduct)."""
    out = []
    m = Chem.MolFromSmiles(smi)
    if not m:
        return out
    mh = Chem.RWMol(m)
    # --- ring CLOSE: carbonyl C + hydroxyl O separated by 3-4 bonds -> form C-O ring
    carbonylC = [a.GetIdx() for a in m.GetAtoms() if a.GetSymbol() == 'C'
                 and any(b.GetBondType() == Chem.BondType.DOUBLE and
                         b.GetOtherAtom(a).GetSymbol() == 'O' for b in a.GetBonds())]
    hydroxylO = [a.GetIdx() for a in m.GetAtoms() if a.GetSymbol() == 'O'
                 and a.GetTotalNumHs() == 1 and a.GetDegree() == 1]
    from rdkit.Chem import rdmolops
    dm = rdmolops.GetDistanceMatrix(m)
    for cC in carbonylC:
        for oO in hydroxylO:
            d = int(dm[cC][oO])
            if d in (3, 4):  # forms 5- or 6-membered O-ring
                rw = Chem.RWMol(m)
                # carbonyl O of cC -> becomes OH; new bond cC-oO; oO loses its H (now ether)
                # find carbonyl O
                cO = None
                for b in m.GetAtomWithIdx(cC).GetBonds():
                    o = b.GetOtherAtom(m.GetAtomWithIdx(cC))
                    if o.GetSymbol() == 'O' and b.GetBondType() == Chem.BondType.DOUBLE:
                        cO = o.GetIdx()
                if cO is None:
                    continue
                try:
                    rw.GetBondBetweenAtoms(cC, cO).SetBondType(Chem.BondType.SINGLE)
                    rw.GetAtomWithIdx(cO).SetNumExplicitHs(1)
                    rw.AddBond(cC, oO, Chem.BondType.SINGLE)
                    rw.GetAtomWithIdx(oO).SetNumExplicitHs(0)
                    p = rw.GetMol(); Chem.SanitizeMol(p)
                    ps = canon(Chem.MolToSmiles(p))
                    if ps and neutral_ok(ps) and ps != canon(smi):
                        out.append((ps, 'ring_closure', None))
                except Exception:
                    pass
    # --- ring OPEN: a ring C bonded to ring O and bearing an OH (hemiketal) -> open to C=O
    for a in m.GetAtoms():
        if a.GetSymbol() != 'C' or not a.IsInRing():
            continue
        ringO = [n for n in a.GetNeighbors() if n.GetSymbol() == 'O' and n.IsInRing()]
        ohO = [n for n in a.GetNeighbors() if n.GetSymbol() == 'O' and not n.IsInRing()
               and n.GetTotalNumHs() == 1]
        if ringO and ohO:
            rw = Chem.RWMol(m)
            try:
                rw.RemoveBond(a.GetIdx(), ringO[0].GetIdx())
                rw.GetBondBetweenAtoms(a.GetIdx(), ohO[0].GetIdx()).SetBondType(Chem.BondType.DOUBLE)
                rw.GetAtomWithIdx(ohO[0].GetIdx()).SetNumExplicitHs(0)
                rw.GetAtomWithIdx(ringO[0].GetIdx()).SetNumExplicitHs(1)
                p = rw.GetMol(); Chem.SanitizeMol(p)
                ps = canon(Chem.MolToSmiles(p))
                if ps and neutral_ok(ps) and ps != canon(smi):
                    out.append((ps, 'ring_opening', None))
            except Exception:
                pass
    return out


def formula(s):
    m = Chem.MolFromSmiles(s)
    return desc.CalcMolFormula(m) if m else '?'


_ENOL = Chem.MolFromSmarts('[OX2H][#6X3]=[#6]')          # C=C-OH (enol)
_VIC_OH = Chem.MolFromSmarts('[OX2H][#6][#6][OX2H]')      # vicinal diol (relay partner)
_CARBONYL = Chem.MolFromSmarts('[CX3]=[OX1]')
_FURAN = Chem.MolFromSmarts('c1ccco1')
_RING_HEMIKETAL = Chem.MolFromSmarts('[#6;R]([OX2;R])[OX2H]')  # ring C bonded to ring-O and an OH


def target_dist(prod):
    m = Chem.MolFromSmiles(prod)
    if not m:
        return -1
    sc = 0.0
    if m.HasSubstructMatch(_FURAN):
        sc += 1.5
    nC = sum(1 for a in m.GetAtoms() if a.GetSymbol() == 'C')
    if nC <= 3:
        sc += 1.5
    for t, ts in TARGETS.items():
        if canon(prod) == canon(ts):
            sc += 10
    return sc


def motif_score(rsmi, psmi, kind, cop):
    """Prioritize PROVEN strict-able motifs (strict-edge-criterion), deprioritize
    the hard sub-types that keep failing (aromatization of not-fully-formed rings)."""
    r = Chem.MolFromSmiles(rsmi); p = Chem.MolFromSmiles(psmi)
    if r is None or p is None:
        return -99
    s = 0.0
    if kind in ('keto_to_enol', 'enol_to_keto', 'tautomerization', 'isomerization'):
        s += 4.0                                   # direct 1,2/1,3 H-shift: highest proven yield
    elif kind == 'dehydration':
        if r.HasSubstructMatch(_ENOL):
            s += 3.0                               # beta-elimination FROM an enol (proven)
        else:
            # Phase-2 (2026-08): non-enol dehydrations dominate dehydration/no_match.
            # Skill ts-validation-strategy requires E1cb-like start from the enol; keep the
            # candidate enumerable but push it below enol dehydrations in the QM budget.
            s -= 4.0
        if r.HasSubstructMatch(_VIC_OH):
            s += 1.5                               # vicinal-OH relay available
        if p.HasSubstructMatch(_FURAN) and not r.HasSubstructMatch(_FURAN):
            s -= 2.0                               # ring-aromatization step: hard, keeps failing
    elif kind in ('ring_closure', 'ring_opening'):
        if r.HasSubstructMatch(_RING_HEMIKETAL) or p.HasSubstructMatch(_RING_HEMIKETAL):
            s += 2.5                               # hemiketal with vicinal-OH relay (proven)
        else:
            s += 0.5
    elif kind == 'retro_aldol':
        s += 2.5                                   # C-C cleavage -> small fragments: fast DFT + lights up small targets
    # size preference: smaller reactants converge MUCH faster at DFT (throughput) and
    # small carbonyl/enol fragments ARE targets -> favor them on ties.
    nHeavy = sum(1 for a in r.GetAtoms() if a.GetSymbol() != 'H')
    s -= 0.18 * nHeavy
    return round(s + 0.3 * target_dist(psmi), 2)


NOVELTY_WEIGHT = 2.0   # novelty-search term: push exploration into unexplored chemical space

def expand(frontier, known_edges):
    """frontier: list of SMILES. known_edges: set of (R,P) canon to dedupe."""
    try:
        import diversity as DIV
    except Exception:
        DIV = None
    known_species = set(canon(s) for s in frontier if canon(s))
    cands = []
    seen = set()
    for r in frontier:
        rc = canon(r)
        prods = run_smarts(rc) + ring_close_open(rc)
        for prod, kind, cop in prods:
            pc = canon(prod)
            if not pc or pc == rc:
                continue
            key = (rc, pc)
            if key in known_edges or key in seen:
                continue
            seen.add(key)
            base = motif_score(rc, pc, kind, cop)
            nov = DIV.novelty(pc, known_species) if DIV else 0.0
            cands.append({'reactant': rc, 'product': pc, 'coproduct': cop,
                          'reaction_kind': kind, 'formula_R': formula(rc),
                          'formula_P': formula(pc), 'motif_score': round(base, 2),
                          'novelty': round(nov, 3),
                          'score': round(base + NOVELTY_WEIGHT * nov, 2)})
    cands.sort(key=lambda c: -c['score'])
    return cands


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

if __name__ == '__main__':
    # This module is a library: `expand(frontier, known_edges)`.
    #
    # It used to double as a script that computed its own frontier and wrote its own
    # candidate_queue.json. That was a second write path into Graph Memory, in a different
    # format, bypassing the atom-conservation gate — so a direct run could leave the queue
    # in a shape the loop does not read. Frontier selection and landing now belong to
    # loop/explore_templates.py, which goes through scripts/graph/add_hypothesis.py.
    print(__doc__.strip())
    print()
    print('This is a library, not an entry point. To enumerate and land candidates:')
    print('    python loop/explore_templates.py --top 24 [--dry-run]')
    print()
    print('To inspect the enumeration without writing anything:')
    print('    python -c "import sys; sys.path[:0]=[\'tools/expand\',\'tools/screen\'];'
          ' import templates_expand as T;'
          ' print(len(T.expand([T.canon(\'O=CC(O)C(O)C(O)C(O)CO\')], set())))"')
    raise SystemExit(2)
