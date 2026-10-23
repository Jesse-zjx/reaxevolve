#!/usr/bin/env python3
"""Validation dispatcher: take candidate edges (from candidate_queue.json) and, by
reaction_kind, generate TS guesses with the right method, run strict_validate
(EXACT_SMILES_ONLY), and record results to dispatch_cache.json (ingested by
build_reaction_network.py).

Method ladder by reaction_kind:
  dehydration / aromatization        -> constrained_scan_guess (C-O +/- beta-H scan)
  retro_aldol                        -> C-C + beta-OH-proton dual scan
  ring_closure / ring_opening        -> anomeric C-O + proton dual scan
  keto_to_enol / enol_to_keto / tautomerization / enolization -> dry_proton_guess, falling
      back to the deprecated water relay only if the dry scan yields nothing
  isomerization (aldose<->ketose)    -> 2D concerted hydride + proton scan: two H's move, so
      the single-H proton scan cannot describe it

Usage:
  validate_candidate.py --top 8                 # top-N from candidate_queue.json
  validate_candidate.py --kinds retro_aldol,dehydration --top 6
  validate_candidate.py --edge "R>>P" --kind dehydration --coproduct O
"""
import os, sys, json, argparse, subprocess, shutil, time, glob, re
from pathlib import Path as P
import numpy as np
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

ROOT = _CP.ROOT
RN = _CP.RN
# workdir MUST live under the path-validator-workspace: constrained_scan_guess /
# water_relay_guess compute WS-relative paths internally and fail otherwise. Override with
# DISPATCH_WORK to run against a clean tree -- a run that reuses an old edge directory can pick
# up its leftover ORCA outputs, which silently turns a from-scratch check into a replay.
# Concurrent dispatchers need one DISPATCH_WORK each: the edge directory is named after the
# reactant/product SMILES, so two workers given the same step share it and ORCA dies reading
# files the other has overwritten.
WORK = os.environ.get('DISPATCH_WORK', os.path.join(ROOT, 'validation', 'dispatch_runs'))
if not os.path.abspath(WORK).startswith(os.path.abspath(ROOT)):
    sys.exit('DISPATCH_WORK must be under %s (guess generators resolve WS-relative paths)' % ROOT)
os.makedirs(WORK, exist_ok=True)
sys.path.insert(0, os.path.join(ROOT, 'resources'))
from auto_guess import read_xyz, write_xyz
import constrained_scan_guess as CSG
import dry_proton_guess as DPG
import water_relay_guess as WR
import neb_guess as NEB
sys.path.insert(0, RN)
import active_learning_ts as AL

ENDO_THRESH_KCAL = 60.0   # GFN2 reaction ΔE above this => prune (very endothermic, hopeless)

OD = _CP.ORCA_DIR
XTB = _CP.XTB_BIN
PYBIN = _CP.PYBIN
SV = os.path.join(ROOT, 'resources/strict_validate.py')
SMI2XYZ = os.path.join(ROOT, 'resources/smi_to_xyz.py')
ENV = dict(os.environ, PATH=(_CP.XTB_DIR + ':') + OD + ':' + os.environ.get('PATH', ''),
           LD_LIBRARY_PATH=OD + ':' + os.environ.get('LD_LIBRARY_PATH', ''), ORCA_CMD=OD + '/orca',
           EXACT_SMILES_ONLY='1',
           # xtb defaults to one OpenMP thread per core, which is pure contention for the small
           # constrained opts in the scans and starves the ORCA job when dispatchers run in
           # parallel. Inherit an explicit setting if the caller made one.
           OMP_NUM_THREADS=os.environ.get('OMP_NUM_THREADS', '1'))
CACHE = os.environ.get('DISPATCH_CACHE', os.path.join(_CP.GRAPH, 'dispatch_cache.json'))
DISC = os.environ.get('DISCOVERED_CACHE', os.path.join(_CP.GRAPH, 'discovered_cache.json'))  # IRC-connected real edges


def log(*a):
    m = ' '.join(str(x) for x in a); print(m, flush=True)
    open(os.path.join(WORK, 'dispatch.log'), 'a').write(time.strftime('[%H:%M:%S] ') + m + '\n')


def bonds(s, c):
    n = len(s); adj = {i: set() for i in range(n)}
    for i in range(n):
        for j in range(i + 1, n):
            d = np.linalg.norm(c[i] - c[j]); cut = 1.3 if 'H' in (s[i], s[j]) else 1.8
            if d < cut: adj[i].add(j); adj[j].add(i)
    return adj


def build_reactant(R, wd):
    rx = os.path.join(wd, 'reactant.xyz')
    subprocess.run([PYBIN, SMI2XYZ, R, rx], env=ENV, capture_output=True)
    return rx if os.path.exists(rx) else None


def gfn2_energy(xyz, wd):
    """GFN2 single-point energy (Eh) for cheap pruning; None on failure."""
    os.makedirs(wd, exist_ok=True); shutil.copy(xyz, os.path.join(wd, 'sp.xyz'))
    try:
        subprocess.run([XTB, 'sp.xyz', '--gfn', '2', '--alpb', 'water', '--sp'], cwd=wd,
                       stdout=open(os.path.join(wd, 'sp.log'), 'w'), stderr=subprocess.STDOUT, env=ENV, timeout=200)
    except Exception:
        return None
    e = None
    for ln in open(os.path.join(wd, 'sp.log')):
        if 'TOTAL ENERGY' in ln:
            try: e = float(ln.split()[-3])
            except: pass
    return e


def gfn2_opt_energy_smi(smi, wd):
    """Build from SMILES + GFN2 opt, return energy (Eh). Separate fragment => no clash."""
    os.makedirs(wd, exist_ok=True)
    x = os.path.join(wd, 'm.xyz')
    subprocess.run([PYBIN, SMI2XYZ, smi, x], env=ENV, capture_output=True)
    if not os.path.exists(x):
        return None
    try:
        subprocess.run([XTB, 'm.xyz', '--opt', 'loose', '--gfn', '2', '--alpb', 'water'], cwd=wd,
                       stdout=open(os.path.join(wd, 'o.log'), 'w'), stderr=subprocess.STDOUT, env=ENV, timeout=300)
    except Exception:
        return None
    e = None
    for ln in open(os.path.join(wd, 'o.log')):
        if 'TOTAL ENERGY' in ln:
            try: e = float(ln.split()[-3])
            except: pass
    return e


def rxn_dE_gfn2(rx, Pbal, wd):
    """GFN2 reaction ΔE (kcal/mol). Product side = SEPARATELY optimized fragments
    summed (so fragmentations aren't penalized by supermolecule clash)."""
    wdR = os.path.join(wd, 'opt_R'); os.makedirs(wdR, exist_ok=True)
    shutil.copy(rx, os.path.join(wdR, 'm.xyz'))
    try:
        subprocess.run([XTB, 'm.xyz', '--opt', 'loose', '--gfn', '2', '--alpb', 'water'], cwd=wdR,
                       stdout=open(os.path.join(wdR, 'o.log'), 'w'), stderr=subprocess.STDOUT, env=ENV, timeout=300)
    except Exception:
        return None
    er = None
    for ln in open(os.path.join(wdR, 'o.log')):
        if 'TOTAL ENERGY' in ln:
            try: er = float(ln.split()[-3])
            except: pass
    if er is None:
        return None
    ep = 0.0
    for i, frag in enumerate(Pbal.split('.')):
        e = gfn2_opt_energy_smi(frag, os.path.join(wd, 'sp_P%d' % i))
        if e is None:
            return None
        ep += e
    return (ep - er) * 627.509


def write_route(wd, R, Pmain, Pbal, cop):
    json.dump({'reactant_smiles': R, 'product_main_smiles': Pmain,
               'product_balanced_smiles': Pbal, 'coproduct': cop},
              open(os.path.join(wd, 'yarp_route.json'), 'w'))


def xtb_constr(rx, i, j, k, l, dij, dkl, wd):
    """constrained opt: distance i-j = dij, and (if k,l given) k-l = dkl. 1-based out."""
    os.makedirs(wd, exist_ok=True); shutil.copy(rx, os.path.join(wd, 'in.xyz'))
    lines = ['$constrain', ' force constant=1.0', ' distance: %d,%d,%.3f' % (i + 1, j + 1, dij)]
    if k is not None:
        lines.append(' distance: %d,%d,%.3f' % (k + 1, l + 1, dkl))
    lines.append('$end')
    open(os.path.join(wd, 'xc.inp'), 'w').write('\n'.join(lines) + '\n')
    try:
        subprocess.run([XTB, 'in.xyz', '--opt', 'normal', '--gfn', '2', '--alpb', 'water', '--input', 'xc.inp'],
                       cwd=wd, stdout=open(os.path.join(wd, 'o.log'), 'w'), stderr=subprocess.STDOUT, env=ENV, timeout=400)
    except Exception:
        return None, None
    o = os.path.join(wd, 'xtbopt.xyz')
    if not os.path.exists(o): return None, None
    e = None
    for ln in open(os.path.join(wd, 'o.log')):
        if 'TOTAL ENERGY' in ln:
            try: e = float(ln.split()[-3])
            except: pass
    return e, o


# Reactive atoms of the candidate in progress, 0-based, handed to ORCA as TS_Active_Atoms. The
# generators already know which atoms they drove; without passing them on, OptTS on a floppy
# polyol spends its cycles among peripheral hydroxyl torsions. 10 of the 20 deposited TS were
# optimized with TS_Active_Atoms set, so this follows the protocol rather than departing from it.
ACTIVE = []


# Shortest distance each contact type reaches in a real sugar TS. Guesses are ranked by GFN2
# energy on the premise that the highest-energy structure is the most TS-like, but a clashed
# interpolation always wins that ranking, so it monopolises the DFT budget and ORCA aborts on it
# in PROPINT. Screen the geometry before the energy gets a vote.
CLASH_FLOOR = {('C', 'C'): 1.30, ('C', 'H'): 0.95, ('C', 'O'): 1.15,
               ('H', 'H'): 1.05, ('H', 'O'): 0.85, ('O', 'O'): 1.25}


def geom_sane(xyz):
    try:
        s, c = read_xyz(P(xyz))
    except Exception:
        return False
    for i in range(len(s)):
        for j in range(i + 1, len(s)):
            floor = CLASH_FLOOR.get(tuple(sorted((s[i], s[j]))))
            if floor and np.linalg.norm(c[i] - c[j]) < floor:
                return False
    return True


# ---- per-kind guess generators: return list of guess xyz paths ----

def guesses_dehydration(wd, R, Pmain, cop):
    global ACTIVE
    write_route(wd, R, Pmain, Pmain + ('.O' if cop == 'O' else ''), cop or 'O')
    try:
        man = CSG.process_step(P(wd), round_idx=0, n_guesses=9)
    except Exception as e:
        log('  CSG failed', e); return []
    bb = man.get('breaking_bond') or {}
    ACTIVE = [bb[k] - 1 for k in ('c_idx', 'o_idx', 'h_idx') if bb.get(k)]
    return [os.path.join(wd, g['xyz_path']) for g in man.get('guesses', [])]


def guesses_tautomer(wd, R, Pmain, force_water=False):
    """Dry proton transfer first; a relayed water only if the dry scan yields nothing.

    A relay water is a spectator on both IRC ends of an isomerization, so it cannot
    satisfy the no-catalytic-water clause. The dry route is also what the accepted
    deposits actually did: 5 of their 6 proton-transfer steps are dry, including all
    four in glucose_ff_review_v1. glucose_haa_review_v1 step 4 is the one accepted
    water-mediated case, which is why the fallback is kept rather than deleted.

    Returns (guess_paths, used_water) so the caller knows whether to allow a spectator.
    """
    global ACTIVE
    write_route(wd, R, Pmain, Pmain, None)
    try:
        if force_water:
            raise RuntimeError('--force-water: skipping the dry scan')
        man = DPG.process_step(P(wd), round_idx=0, n_guesses=9)
        out = [os.path.join(wd, g['xyz_path']) for g in man.get('guesses', [])]
        if out:
            ps = man.get('proton_shift') or {}
            ACTIVE = [ps[k] - 1 for k in ('donor_idx', 'acceptor_idx', 'h_idx') if ps.get(k)]
            return out, False
        log('  dry proton scan produced no guesses')
    except Exception as e:
        log('  dry proton scan failed', e)

    log('  falling back to water relay (spectator H2O — will not meet the bar as a new edge)')
    out = []
    for nw in (1, 2):
        try:
            # ORCA overwrites the inherited OMP_NUM_THREADS with its own %pal value before calling
            # otool_xtb, so a hardcoded 8 here escapes the campaign's core budget entirely: six
            # concurrent relay jobs at NPROCS=5 were measured driving the load to 101 on 32 cores.
            man = WR.process_step(P(wd), round_idx=nw - 1, n_waters=nw, nprocs=int(NPROCS),
                                  nimages=10, timeout=2000)
            out += [os.path.join(wd, g['xyz_path']) for g in man.get('guesses', [])]
        except Exception as e:
            log('  WR nw=%d failed' % nw, e)
    return out, bool(out)


def _dual_scan(rx, sites, grid, wd, tag):
    global ACTIVE, DRIVE2
    if sites:
        ACTIVE = sorted(set(sites[0]))
        DRIVE2 = sites[0]        # (a, b, h, acc): the heavy-atom bond and the proton it moves with
    s, c = read_xyz(P(rx)); outs = []
    for ti, (a, b, h, acc) in enumerate(sites[:2]):
        cand = []
        for (d1, d2) in grid:
            e, o = xtb_constr(rx, a, b, h, acc, d1, d2, os.path.join(wd, '%s_t%d_%.1f_%.1f' % (tag, ti, d1, d2)))
            if e is not None: cand.append((e, o))
        cand.sort(reverse=True)
        outs += [o for _, o in cand[:3]]
    return outs


def guesses_retroaldol(wd, R):
    rx = os.path.join(wd, 'reactant.xyz'); s, c = read_xyz(P(rx)); adj = bonds(s, c)
    sites = []
    for i in range(len(s)):
        if s[i] != 'C': continue
        cO = [j for j in adj[i] if s[j] == 'O' and np.linalg.norm(c[i] - c[j]) < 1.30]
        if not cO: continue
        for ca in adj[i]:
            if s[ca] != 'C': continue
            for cb in adj[ca]:
                if s[cb] != 'C' or cb == i: continue
                for o in adj[cb]:
                    if s[o] == 'O':
                        hs = [h for h in adj[o] if s[h] == 'H']
                        if hs:
                            sites.append((ca, cb, hs[0], cO[0]))  # stretch Ca-Cb, drive bOH-H -> carbonyl O
    grid = [(1.9, 1.5), (2.1, 1.3), (2.1, 1.1), (2.3, 1.2), (2.5, 1.1)]
    return _dual_scan(rx, sites, grid, wd, 'ra')


def guesses_iso(wd, R):
    """aldose<->ketose: a concerted 1,2-hydride C->C shift *plus* an O->O proton shift.

    Two hydrogens move, so the single-H scan in dry_proton_guess cannot describe this step;
    drive the forming C-H and the forming O-H together, as scan2d.py does for the deposited
    isomerizations (FF s1 -434.65, FF s6 -766.50, HAA s1 -474.15). The motif is geometric and
    direction-agnostic: a carbonyl C=O next to a carbon carrying both a hydrogen (the hydride)
    and a hydroxyl (the proton source).
    """
    rx = os.path.join(wd, 'reactant.xyz'); s, c = read_xyz(P(rx)); adj = bonds(s, c)
    sites = []
    for cc in range(len(s)):
        if s[cc] != 'C': continue
        co = [j for j in adj[cc] if s[j] == 'O' and np.linalg.norm(c[cc] - c[j]) < 1.30]
        if not co: continue
        oc = co[0]
        for ca in adj[cc]:
            if s[ca] != 'C': continue
            hyd = [h for h in adj[ca] if s[h] == 'H']
            ohO = [o for o in adj[ca] if s[o] == 'O' and any(s[x] == 'H' for x in adj[o])]
            if not (hyd and ohO): continue
            h_hyd = min(hyd, key=lambda h: np.linalg.norm(c[h] - c[cc]))
            hp = [x for x in adj[ohO[0]] if s[x] == 'H']
            h_pro = min(hp, key=lambda h: np.linalg.norm(c[h] - c[oc]))
            sites.append((cc, h_hyd, h_pro, oc))  # form Cc-H(hydride) and Oc-H(proton)
    # _dual_scan only scans the first two sites, so put the best-oriented first: a hydroxyl
    # already leaning toward the carbonyl O needs far less work from the constrained relaxation.
    sites.sort(key=lambda t: np.linalg.norm(c[t[3]] - c[t[2]]))
    # spans the col: the saddle sits near a half-formed hydride with the proton further along
    grid = [(1.60, 1.45), (1.45, 1.30), (1.35, 1.15), (1.30, 1.05), (1.15, 1.05)]
    return _dual_scan(rx, sites, grid, wd, 'iso')


def product_ring_size(Pmain):
    """Size of the ring the product carries, or None if it has none or more than one."""
    from rdkit import Chem
    m = Chem.MolFromSmiles(Pmain)
    if m is None:
        return None
    rings = m.GetRingInfo().AtomRings()
    return len(rings[0]) if len(rings) == 1 else None


def _ring_size_if_closed(adj, c_idx, o_idx):
    """Atoms in the ring that forming a c_idx-o_idx bond would create."""
    seen = {c_idx: 0}
    queue = [c_idx]
    while queue:
        u = queue.pop(0)
        for v in adj[u]:
            if v not in seen:
                seen[v] = seen[u] + 1
                if v == o_idx:
                    return seen[v] + 1          # bonds along the chain, plus the new one
                queue.append(v)
    return None


def guesses_ring(wd, R, opening, Pmain=None):
    rx = os.path.join(wd, 'reactant.xyz'); s, c = read_xyz(P(rx)); adj = bonds(s, c)
    sites = []
    if opening:
        # anomeric ring C bonded to ring-O + a hydroxyl O: stretch C-ringO, drive C-OH proton -> ringO
        for i in range(len(s)):
            if s[i] != 'C': continue
            ringO = [j for j in adj[i] if s[j] == 'O' and len([x for x in adj[j] if s[x] == 'C']) == 2]
            ohO = [j for j in adj[i] if s[j] == 'O' and any(s[x] == 'H' for x in adj[j])]
            if ringO and ohO:
                h = [x for x in adj[ohO[0]] if s[x] == 'H'][0]
                sites.append((i, ringO[0], h, ringO[0]))  # C-ringO stretch + OH proton -> ringO
        grid = [(2.0, 1.4), (2.1, 1.2), (2.3, 1.1), (2.3, 1.3), (2.5, 1.1)]
    else:
        # closing: carbonyl C + distal hydroxyl O at graph dist 3-4: shrink C...O, drive OH proton -> carbonyl O
        from rdkit import Chem
        from rdkit.Chem import rdmolops
        # use geometry distance proxy: pick carbonylC + hydroxylO 2.5-4 A apart
        carbonylC = [i for i in range(len(s)) if s[i] == 'C' and any(s[j] == 'O' and np.linalg.norm(c[i] - c[j]) < 1.30 for j in adj[i])]
        for cC in carbonylC:
            cO = [j for j in adj[cC] if s[j] == 'O' and np.linalg.norm(c[cC] - c[j]) < 1.30][0]
            for o in range(len(s)):
                if s[o] != 'O' or o in adj[cC]: continue
                if not any(s[x] == 'H' for x in adj[o]): continue
                d = np.linalg.norm(c[cC] - c[o])
                # an extended chain conformer holds the two ends that close the ring well past the
                # window a formed bond would sit in, so accept partners the pre-organization step
                # can still bring together
                if 2.3 < d < 6.5:
                    h = [x for x in adj[o] if s[x] == 'H'][0]
                    sites.append((cC, o, h, cO))  # shrink cC-o, drive o's H -> carbonyl O
        # Which oxygen closes the ring is set by the product, not by which one happens to be nearest
        # in this conformer. Picking the nearest gave HMF step 4 a six-membered ring where the product
        # has a five-membered one, and drove FF step 10 to a species with no ring at all.
        want = product_ring_size(Pmain) if Pmain else None
        if want:
            keep = [t for t in sites if _ring_size_if_closed(adj, t[0], t[1]) == want]
            if keep:
                sites = keep
            else:
                log('  no candidate pair closes a %d-ring; keeping all %d by distance'
                    % (want, len(sites)))
        sites.sort(key=lambda t: np.linalg.norm(c[t[0]] - c[t[1]]))
        grid = [(1.9, 1.4), (1.7, 1.3), (2.1, 1.3), (1.8, 1.2), (2.0, 1.5)]
    return _dual_scan(rx, sites, grid, wd, 'ring')


DEHY = {'dehydration', 'aromatization', 'dehydration_aromatization'}
TAUT = {'keto_to_enol', 'enol_to_keto', 'tautomerization', 'enolization', 'ketonization'}
# aldose<->ketose moves two hydrogens; routing it to the single-H proton scan (as 'isomerization'
# in TAUT used to do) cannot reach its saddle.
ISO = {'isomerization', 'aldose_ketose', 'ketose_aldose'}


NPROCS = os.environ.get('NPROCS', '8')
DFT_TIMEOUT = int(os.environ.get('DFT_TIMEOUT', '5400'))  # per-guess wall-clock cap (s): avoid a stuck OptTS hogging a worker
NEB_TIMEOUT = int(os.environ.get('NEB_TIMEOUT', '3600'))  # NEB runs at GFN2, so this is generous


PRERELAX = os.environ.get('DFT_PRERELAX', '0') == '1'


def dft_prerelax(guess, wd, tag):
    """Relax a guess at DFT with the reactive atoms frozen in place.

    The guess generators scan at GFN2, so a guess arrives with its spectator hydroxyls sitting at
    xTB geometry and OptTS spends most of its cycles dragging them onto the DFT surface: the
    deposited steps, whose guesses came from DFT-level scans, converged in 1-10 cycles where the
    same steps from an xTB guess take 30-55 and run out of wall clock. Freezing the reactive core
    keeps the saddle character the scan found while the rest of the molecule relaxes.
    Returns the relaxed geometry, or the original guess if the relaxation does not finish.
    """
    if not ACTIVE:
        return guess
    d = os.path.join(wd, 'prerelax_' + tag)
    os.makedirs(d, exist_ok=True)
    shutil.copy(guess, os.path.join(d, 'g.xyz'))
    cons = '\n'.join('    { C %d C }' % i for i in ACTIVE)
    open(os.path.join(d, 'pr.inp'), 'w').write(
        '! r2SCAN-3c Opt TightSCF DEFGRID3 CPCM(water)\n'
        '%geom Constraints\n' + cons + '\n  end\n  MaxIter 60\nend\n'
        '%maxcore 4000\n'
        '%pal nprocs ' + NPROCS + ' end\n'
        '* xyzfile 0 1 g.xyz *\n')
    try:
        subprocess.run([OD + '/orca', 'pr.inp'], cwd=d, env=ENV, timeout=3600,
                       stdout=open(os.path.join(d, 'pr.out'), 'w'), stderr=subprocess.STDOUT)
    except Exception as e:
        log('  prerelax failed:', e); return guess
    out = os.path.join(d, 'pr.xyz')
    if os.path.exists(out):
        log('  prerelaxed at DFT with %d atoms frozen' % len(ACTIVE))
        return out
    return guess


# Kinds whose saddle the single-ended scans never found: proton transfer, C-C fragmentation and
# ring closure all closed 0 of 11 attempts when guessed by driving one coordinate out of the
# reactant. Enable with NEB_GUESS=1.
NEBGUESS = os.environ.get('NEB_GUESS', '0') == '1'
NEB_KINDS = set(TAUT) | {'retro_aldol', 'ring_closure', 'ring_opening'}


def xtb_free_opt(xyz, wd):
    """Plain GFN2/water optimization, used to settle a driven geometry into its basin."""
    os.makedirs(wd, exist_ok=True); shutil.copy(xyz, os.path.join(wd, 'in.xyz'))
    try:
        subprocess.run([XTB, 'in.xyz', '--opt', 'normal', '--gfn', '2', '--alpb', 'water'],
                       cwd=wd, stdout=open(os.path.join(wd, 'o.log'), 'w'),
                       stderr=subprocess.STDOUT, env=ENV, timeout=400)
    except Exception:
        return None
    o = os.path.join(wd, 'xtbopt.xyz')
    return o if os.path.exists(o) else None


def matched_product_endpoint(rx, kind, Pmain, wd):
    """A product geometry in the reactant's own conformation and atom order, for NEB.

    An independently embedded product is a different conformer, not just a different bonding
    pattern: for HMF step 2, 20 of the 21 atoms sat more than 1 A from their reactant positions,
    so the band had to fold the whole molecule and NEB spent its 500 iterations without
    converging. Driving the reactive coordinate out of the reactant geometry instead leaves the
    rest of the molecule where it was, which is what the deposits' hand-built endpoint pairs did.
    Returns None if the relaxed geometry is not the expected product, since a mislabelled endpoint
    would send NEB to the wrong basin.
    """
    if kind in TAUT and len(ACTIVE) == 3:
        don, acc, h = ACTIVE
        _, g = xtb_constr(rx, acc, h, don, h, 0.98, 2.20, os.path.join(wd, 'nebP_drive'))
    else:
        return None
    if not g:
        return None
    o = xtb_free_opt(g, os.path.join(wd, 'nebP_relax'))
    if not o:
        return None
    got, want = stripped_smiles(o), canon(Pmain)
    if got != want:
        log('  NEB product endpoint relaxed to %s, expected %s -> skip NEB' % (got, want))
        return None
    return o


def guesses_neb(wd, rx, kind, Pmain, nimages=8):
    """Double-ended NEB-TS between the reactant and a conformation-matched product.

    A scan drives one coordinate out of the reactant and hopes the rest of the molecule follows;
    NEB optimizes the whole path between the two basins its endpoints define, so the image it
    returns is a maximum of the real MEP rather than of one chosen coordinate. This is how the
    deposits built the steps that resisted scanning here — HMF steps 1 and 2 both came from a
    GFN2 NEB-CI between two explicitly built endpoint geometries.
    """
    prod = matched_product_endpoint(rx, kind, Pmain, wd)
    if prod is None:
        return []
    try:
        ts = NEB.run_neb_ts(P(wd), P(rx), P(prod), round_idx=0, nprocs=int(NPROCS),
                            nimages=nimages, timeout=NEB_TIMEOUT, free_end=False)
    except Exception as e:
        log('  NEB-TS guess failed:', e); return []
    return [str(ts)] if ts else []


DFTSCAN = os.environ.get('DFT_SCAN', '0') == '1'
TAUT2D = os.environ.get('TAUT_2D', '0') == '1'
XFER2D = os.environ.get('XFER_2D', '0') == '1'
DRIVE2 = None    # concerted site (a, b, h, acc) recorded by the two-coordinate generators

# How far to drive the heavy-atom bond, per kind: retro-aldol breaks a C-C, ring closure forms a
# C-O. The proton always ends up on its acceptor at about 1.0 A.
DRIVE_TARGET = {'retro_aldol': 2.50, 'ring_closure': 1.50, 'ring_opening': 2.40}
# Where the heavy-atom axis of the grid begins. Ring closure joins two ends of an extended chain,
# so its partners start several angstroms apart and the sweep has to be brought in first; the bonds
# that retro-aldol and ring opening break are already at their reactant length.
DRIVE_START = {'ring_closure': 2.80}
PREORG_START = 2.40      # H-acceptor distance the 2D grid starts from
RSMI = None              # reactant SMILES of the candidate in flight, for pre-organization checks


def preorg(rx, acc, h, a, b, dab, wd):
    """Constrained GFN2 pre-organization, rejected unless the molecule is still the reactant.

    Rotating the donor into place is meant to be a pure conformational change. On both ring closures
    it was not: pulling the proton to 2.4 A tore it off its hydroxyl and left an allene, and the 35
    grid points were then scanned from a molecule that is not the reactant, which is why their
    endpoints came out as open dienols. Back the target off in stages and scan from the untouched
    reactant rather than scan a different reaction.
    """
    s, c = read_xyz(P(rx))
    e0 = float(np.linalg.norm(c[acc] - c[h]))
    for frac in (1.0, 0.6, 0.3):
        target = PREORG_START + (e0 - PREORG_START) * (1.0 - frac)
        _, g = xtb_constr(rx, acc, h, a, b, target, dab, os.path.join(wd, 'preorg_%.2f' % target))
        if not g:
            continue
        got = stripped_smiles(g)
        if RSMI and got and got == canon(RSMI):
            return g
        log('  pre-organization to %.2f A changed the molecule to %s, backing off'
            % (target, got))
    log('  pre-organization abandoned; scanning from the reactant geometry')
    return None


def clear_scan_points(d, stem):
    """Drop per-point geometries from an earlier scan in this directory.

    A rerun with a different grid overwrites points one by one, so a crash part way through would
    leave the tail behind from the previous grid and scan_points would read the two as one surface.
    """
    for f in glob.glob(os.path.join(d, stem + '.[0-9][0-9][0-9].xyz')):
        os.remove(f)


def scan_points(d, stem):
    """(xyz path, energy) for every converged point of a relaxed scan, in scan order.

    Read from the per-point geometries rather than stem.relaxscanact.dat: ORCA only writes the .dat
    once the whole scan finishes, so one crashed point threw away every DFT optimization before it.
    HAA step 4 lost 11 good points that way to a SHARK temp-file error on the last one.
    """
    out = []
    for f in sorted(glob.glob(os.path.join(d, stem + '.[0-9][0-9][0-9].xyz'))):
        m = re.search(r'E\s+(-?\d+\.\d+)', open(f).readlines()[1])
        if m:
            out.append((f, float(m.group(1))))
    return out


def _scan_peak_2d(pts, n2):
    """Index of the highest point on the easiest way across a 2D relaxed-scan grid.

    Walk from the reactant corner to the product corner by the route whose worst point is as low as
    possible, and return that worst point: on a grid it is the discrete saddle. Taking the lowest
    point of each row and the highest of those, as the deposits' scan2d.py did, assumes the reaction
    coordinate runs along the rows. When both coordinates move together the path is diagonal, and
    row-wise selection returned a point on the grid edge for both ring closure and retro-aldol here.
    """
    import heapq
    n1 = len(pts) // n2
    if n1 < 2:
        return None
    E = [pts[r * n2 + c][1] for r in range(n1) for c in range(n2)]
    at = lambda r, c: r * n2 + c
    best = {at(0, 0): E[at(0, 0)]}                     # lowest bottleneck known for each node
    via = {at(0, 0): at(0, 0)}                         # node that set that bottleneck
    q = [(E[at(0, 0)], at(0, 0), at(0, 0))]
    goal = at(n1 - 1, n2 - 1)
    while q:
        cost, u, peak = heapq.heappop(q)
        if cost > best.get(u, float('inf')):
            continue
        if u == goal:
            return peak
        r, c = divmod(u, n2)
        for nr, nc in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
            if not (0 <= nr < n1 and 0 <= nc < n2):
                continue
            v = at(nr, nc)
            nc_cost = max(cost, E[v])
            if nc_cost < best.get(v, float('inf')):
                best[v] = nc_cost
                via[v] = v if E[v] >= cost else peak
                heapq.heappush(q, (nc_cost, v, via[v]))
    return None


def dft_scan2d(rx, wd, kind, n1=5, n2=7):
    """Chained 2D r2SCAN-3c relaxed scan over the two coordinates a concerted step actually moves.

    Ring closure and retro-aldol change a heavy-atom bond and transfer a proton at the same time,
    which is why _dual_scan drives both at once. Driving them at GFN2 leaves the guess far enough
    from the DFT ridge that OptTS settles on a soft mode instead: 0 of 5 such steps closed. This is
    the recipe the deposits used for their concerted steps (bridge_stepC/iso5b/scan2d.py), and the
    1D form of it is what closed HMF step 2 here.
    """
    if not DRIVE2 or kind not in DRIVE_TARGET:
        return []
    a, b, h, acc = DRIVE2
    s, c = read_xyz(P(rx))
    d = os.path.join(wd, 'dft_scan2d')
    os.makedirs(d, exist_ok=True)
    if len(scan_points(d, 's2')) >= n1 * n2 - 2:   # reuse a scan a previous run already paid for
        pts = scan_points(d, 's2')
        log('  reusing %d grid points from an earlier run' % len(pts))
        idx = _scan_peak_2d(pts, n2)
        return [pts[idx][0]] if idx is not None else []
    start = rx
    e0 = float(np.linalg.norm(c[acc] - c[h])); e1 = 1.00
    d0 = float(np.linalg.norm(c[a] - c[b]))
    ab0 = min(d0, DRIVE_START.get(kind, d0))

    # A hydroxyl often points away from the acceptor in the reactant conformer, leaving the proton
    # 4-5 A off. Sweeping that whole gap in five constrained DFT steps wrenches the molecule around
    # and the grid stops describing the reaction. Rotate the donor into place at GFN2 first, which
    # is pure conformational change, and scan only the transfer itself. The heavy-atom bond is held
    # at its reactant length throughout: these steps are concerted, so an unrestrained approach of
    # the proton already snaps the C-C and leaves the first grid axis with nothing to sweep.
    if e0 > PREORG_START + 0.2 or d0 > ab0 + 0.2:
        g = preorg(rx, acc, h, a, b, ab0, d)
        if g:
            s, c = read_xyz(P(g))
            was_e0, was_d0 = e0, d0
            e0 = float(np.linalg.norm(c[acc] - c[h]))
            d0 = float(np.linalg.norm(c[a] - c[b]))
            start = g
            log('  pre-organized: d(H-acc) %.2f -> %.2f, d(%d-%d) %.2f -> %.2f A'
                % (was_e0, e0, a, b, was_d0, d0))
        else:
            # Clamping the axis to the usual 2.8 A start would leave the first constrained
            # optimization pulling the partners 2 A together in one step: HMF s4 spent 52 cycles on
            # that without converging. Sweep from where the reactant actually is and add rows so the
            # step stays near 0.45 A.
            n1 = max(n1, int(round((d0 - DRIVE_TARGET[kind]) / 0.45)) + 1)
            log('  sweeping the heavy-atom axis from its reactant length %.2f A in %d rows'
                % (d0, n1))
    d1 = DRIVE_TARGET[kind]
    clear_scan_points(d, 's2')
    shutil.copy(start, os.path.join(d, 'r.xyz'))
    # MaxIter is raised because the first point starts from a GFN2 geometry that the pre-organization
    # pulled a long way: at ORCA's default limit it ran out of cycles, and a scan point that fails to
    # converge cannot be stored, which brings the whole scan down with a SHARK error.
    open(os.path.join(d, 's2.inp'), 'w').write(
        '! r2SCAN-3c CPCM(water) Opt NoPop DEFGRID3\n'
        '%%geom MaxIter 100\n  Scan\n    B %d %d = %.3f, %.3f, %d\n'
        '    B %d %d = %.3f, %.3f, %d\n  end\nend\n'
        '%%maxcore 4000\n%%pal nprocs %s end\n* xyzfile 0 1 r.xyz *\n'
        % (a, b, d0, d1, n1, acc, h, e0, e1, n2, NPROCS))
    try:
        subprocess.run([OD + '/orca', 's2.inp'], cwd=d, env=ENV, timeout=DFT_TIMEOUT,
                       stdout=open(os.path.join(d, 's2.out'), 'w'), stderr=subprocess.STDOUT)
    except Exception as e:
        log('  DFT 2D scan failed:', e); return []
    pts = scan_points(d, 's2')
    idx = _scan_peak_2d(pts, n2)
    if idx is None:
        log('  DFT 2D scan gave only %d points, need %d rows' % (len(pts), 2)); return []
    log('  DFT 2D scan col at grid point %d/%d (row %d of %d)'
        % (idx + 1, len(pts), idx // n2 + 1, len(pts) // n2))
    return [pts[idx][0]]


def dft_proton_scan(rx, wd, npts=12):
    """Chained r2SCAN-3c relaxed scan driving the transferring H onto its acceptor.

    Modelled on ff_chain/proton_scan.py, which produced the FF proton-transfer guesses whose OptTS
    then converged in 1-2 cycles. An earlier attempt in this campaign swept only +-0.3 A around the
    GFN2 saddle estimate and its peak landed on the window edge, because the xTB guess already sits
    past the DFT ridge. Sweeping the full range out of the reactant crosses the barrier instead of
    starting beyond it; ORCA chains the points, so the path stays on one conformational branch.
    """
    if len(ACTIVE) != 3:
        return []
    acc, h = ACTIVE[1], ACTIVE[2]
    s, c = read_xyz(P(rx))
    d0 = float(np.linalg.norm(c[acc] - c[h]))
    d1 = 1.15 if s[acc] == 'C' else 1.00
    if d0 - d1 < 0.4:
        log('  reactant already has the proton at %.2f A from the acceptor, skip DFT scan' % d0)
        return []
    d = os.path.join(wd, 'dft_pscan')
    os.makedirs(d, exist_ok=True)
    if len(scan_points(d, 'ps')) >= npts - 2:      # reuse a scan a previous run already paid for
        log('  reusing %d scan points from an earlier run' % len(scan_points(d, 'ps')))
    else:
        clear_scan_points(d, 'ps')
        shutil.copy(rx, os.path.join(d, 'r.xyz'))
        open(os.path.join(d, 'ps.inp'), 'w').write(
            '! r2SCAN-3c CPCM(water) Opt NoPop DEFGRID3\n'
            '%%geom MaxIter 100\n  Scan\n    B %d %d = %.3f, %.3f, %d\n  end\nend\n'
            '%%maxcore 4000\n%%pal nprocs %s end\n* xyzfile 0 1 r.xyz *\n'
            % (acc, h, d0, d1, npts, NPROCS))
        try:
            subprocess.run([OD + '/orca', 'ps.inp'], cwd=d, env=ENV, timeout=DFT_TIMEOUT,
                           stdout=open(os.path.join(d, 'ps.out'), 'w'), stderr=subprocess.STDOUT)
        except Exception as e:
            log('  DFT proton scan failed:', e); return []
    # The profile always falls away steeply just past its peak, because the last constrained point
    # relaxes into the product basin. That is true of the two steps this method reproduced as well as
    # of the ones it missed, so the shape of the drop says nothing about whether the guess is usable
    # and the peak is taken as it stands.
    return _pscan_peak(scan_points(d, 'ps'))


def _pscan_peak(pts):
    """Highest point of a 1D scan, provided the scan actually went over a barrier."""
    if not pts:
        log('  DFT proton scan produced no energies'); return []
    imax = max(range(len(pts)), key=lambda i: pts[i][1])
    if imax in (0, len(pts) - 1):
        log('  DFT proton scan peak on the window edge (point %d/%d) -> not a barrier crossing'
            % (imax + 1, len(pts)))
        return []
    log('  DFT proton scan peak at point %d/%d, %.1f kcal above the reactant end'
        % (imax + 1, len(pts), (pts[imax][1] - pts[0][1]) * 627.5))
    return [pts[imax][0]]


def taut_co_bond(rx):
    """The C-O bond whose order changes during a tautomerization, and where to drive it.

    Enol-to-keto turns the enol C-O into a carbonyl while the proton lands on the far carbon; the
    keto direction does the reverse. That heavy-atom change is what a single proton coordinate
    cannot describe.
    """
    if len(ACTIVE) != 3:
        return None
    s, c = read_xyz(P(rx))
    adj = bonds(s, c)
    for o, target in ((ACTIVE[0], 1.23), (ACTIVE[1], 1.36)):
        if s[o] != 'O':
            continue
        cs = [x for x in adj[o] if s[x] == 'C']
        if len(cs) == 1:
            return cs[0], o, target
    return None


def dft_taut_scan2d(rx, wd, n1=4, n2=7):
    """2D r2SCAN-3c scan over the proton and the C-O bond order of a tautomerization.

    The 1D proton scan closes a tautomerization only when the transfer is loosely coupled to the
    skeleton. Where it is not, the relaxed profile is discontinuous rather than barriered: FF step 8
    fell 58 kcal across 0.06 A even after refinement, because the C=C and C-O rearrange in the same
    motion. Scanning the C-O alongside the proton keeps both branches on one surface.
    """
    co = taut_co_bond(rx)
    if not co:
        return []
    cc, o, co_target = co
    acc, h = ACTIVE[1], ACTIVE[2]
    s, c = read_xyz(P(rx))
    co0 = float(np.linalg.norm(c[cc] - c[o]))
    e0 = float(np.linalg.norm(c[acc] - c[h]))
    e1 = 1.15 if s[acc] == 'C' else 1.00
    if abs(co0 - co_target) < 0.05 or e0 - e1 < 0.4:
        return []
    d = os.path.join(wd, 'dft_taut2d')
    os.makedirs(d, exist_ok=True)
    if len(scan_points(d, 't2')) < n1 * n2 - 2:
        clear_scan_points(d, 't2')
        shutil.copy(rx, os.path.join(d, 'r.xyz'))
        open(os.path.join(d, 't2.inp'), 'w').write(
            '! r2SCAN-3c CPCM(water) Opt NoPop DEFGRID3\n'
            '%%geom MaxIter 100\n  Scan\n    B %d %d = %.3f, %.3f, %d\n'
            '    B %d %d = %.3f, %.3f, %d\n  end\nend\n'
            '%%maxcore 4000\n%%pal nprocs %s end\n* xyzfile 0 1 r.xyz *\n'
            % (cc, o, co0, co_target, n1, acc, h, e0, e1, n2, NPROCS))
        log('  2D tautomer scan: d(C%d-O%d) %.2f -> %.2f, d(H-acc) %.2f -> %.2f A'
            % (cc, o, co0, co_target, e0, e1))
        try:
            subprocess.run([OD + '/orca', 't2.inp'], cwd=d, env=ENV, timeout=DFT_TIMEOUT,
                           stdout=open(os.path.join(d, 't2.out'), 'w'), stderr=subprocess.STDOUT)
        except Exception as e:
            log('  2D tautomer scan failed:', e)
    pts = scan_points(d, 't2')
    idx = _scan_peak_2d(pts, n2)
    if idx is None:
        log('  2D tautomer scan gave only %d points' % len(pts)); return []
    log('  2D tautomer saddle at grid point %d/%d' % (idx + 1, len(pts)))
    return [pts[idx][0]]


def transfer_site(rx):
    """(donor, acceptor, H, heavy-pair-to-hold) of the proton in flight, or None.

    The donor is read off the geometry as the heavy atom the hydrogen is bonded to rather than taken
    from the site tuple. The concerted generators record (a, b, h, acc) with b the hydroxyl oxygen,
    but for the isomerizations b is itself a hydrogen, and trusting it produced a grid that stretched
    an H-H contact from 2.68 to 3.18 A.
    """
    if len(ACTIVE) == 3:
        _, acc, h = ACTIVE
        hold = None
    elif DRIVE2:
        a, b, h, acc = DRIVE2
        hold = (a, b)
    else:
        return None
    s, c = read_xyz(P(rx))
    if s[h] != 'H' or s[acc] == 'H':
        return None
    near = sorted((float(np.linalg.norm(c[h] - c[i])), i)
                  for i, e in enumerate(s) if e != 'H' and i != acc)
    if not near or near[0][0] > 1.30:
        return None
    if hold and (s[hold[0]] == 'H' or s[hold[1]] == 'H'):
        hold = None
    return near[0][1], acc, h, hold


def dft_transfer_scan2d(rx, wd, n1=5, n2=7):
    """2D r2SCAN-3c scan of the donor-H stretch against the acceptor-H approach.

    Every transition state in the three deposits has its proton in flight: FF step 3 sits at
    d(O-H)=1.27 / d(C-H)=1.53, step 6 at 1.26/1.55, step 10 at 1.18/1.35. Not one of the saddles this
    campaign converged to has a bridging hydrogen at all, and the reason is the coordinate: holding
    only the acceptor-H distance never breaks the donor-H bond, so the molecule contorts to bring the
    proton close while keeping it, which is the +71 kcal wall FF step 3 climbed before dropping off a
    cliff to the product. Stretching the donor bond alongside the approach puts the grid on the
    transfer ridge, and the window comes from those deposited geometries instead of being swept in
    from the reactant, where 0.45 A steps skipped over the saddle entirely.

    For ring closure the heavy-atom bond is pinned rather than driven: the deposited step 10 saddle
    still has C-O at 2.51 A, so closing it to 1.50 A as the earlier grid did runs well past the
    saddle into the product basin.
    """
    site = transfer_site(rx)
    if not site:
        return []
    don, acc, h, hold = site
    s, c = read_xyz(P(rx))
    dh0 = float(np.linalg.norm(c[don] - c[h]))
    ah0 = float(np.linalg.norm(c[acc] - c[h]))
    dh1 = dh0 + 0.50                             # donor bond stretched past the deposited 1.27-1.35
    ah1 = 1.20 if s[acc] == 'C' else 1.05
    ah_start = min(ah0, 2.30)                    # 0.18 A steps across the region the saddles sit in
    if ah_start - ah1 < 0.3:
        return []
    d = os.path.join(wd, 'dft_xfer2d')
    os.makedirs(d, exist_ok=True)
    if len(scan_points(d, 'x2')) < n1 * n2 - 2:
        clear_scan_points(d, 'x2')
        shutil.copy(rx, os.path.join(d, 'r.xyz'))
        extra = ''
        if hold:
            a, b = hold
            hd = min(float(np.linalg.norm(c[a] - c[b])), 2.50)
            extra = '  Constraints\n    {B %d %d %.3f C}\n  end\n' % (a, b, hd)
            log('  holding d(%d-%d) at %.2f A while the proton crosses' % (a, b, hd))
        open(os.path.join(d, 'x2.inp'), 'w').write(
            '! r2SCAN-3c CPCM(water) Opt NoPop DEFGRID3\n'
            '%%geom MaxIter 100\n%s  Scan\n    B %d %d = %.3f, %.3f, %d\n'
            '    B %d %d = %.3f, %.3f, %d\n  end\nend\n'
            '%%maxcore 4000\n%%pal nprocs %s end\n* xyzfile 0 1 r.xyz *\n'
            % (extra, don, h, dh0, dh1, n1, acc, h, ah_start, ah1, n2, NPROCS))
        log('  2D transfer scan: d(%s%d-H) %.2f -> %.2f, d(%s%d-H) %.2f -> %.2f A'
            % (s[don], don, dh0, dh1, s[acc], acc, ah_start, ah1))
        try:
            subprocess.run([OD + '/orca', 'x2.inp'], cwd=d, env=ENV, timeout=DFT_TIMEOUT,
                           stdout=open(os.path.join(d, 'x2.out'), 'w'), stderr=subprocess.STDOUT)
        except Exception as e:
            log('  2D transfer scan failed:', e)
    pts = scan_points(d, 'x2')
    idx = _scan_peak_2d(pts, n2)
    if idx is None:
        log('  2D transfer scan gave only %d points' % len(pts)); return []
    log('  2D transfer saddle at grid point %d/%d' % (idx + 1, len(pts)))
    return [pts[idx][0]]


def neb_from_scan(rx, wd, Pmain, subdir, stem, nimages=8):
    """NEB between the reactant and the far end of the chained DFT scan.

    Single-ended scans cannot reach the saddle of a strongly coupled step: at every fixed proton
    position the constrained optimization stays in the electronic structure it started from, so the
    profile climbs to roughly +50 kcal on the enol branch and only drops when the last point flips to
    the keto one. A double-ended search crosses between the branches instead, which is how the
    deposits found HMF steps 1 and 2.

    What blocked NEB earlier in this campaign was the product endpoint: independently embedding the
    product gave a different conformer, and NEB spent its iterations folding the molecule rather than
    crossing the barrier. The scan's last point solves that, since chaining from the reactant leaves
    it in the same conformation, already relaxed at r2SCAN-3c.
    """
    d = os.path.join(wd, subdir)
    pts = scan_points(d, stem)
    if len(pts) < 2:
        return []
    end = pts[-1][0]
    got = stripped_smiles(end)
    want = canon(Pmain)
    if not got or (want and got != want):
        log('  scan endpoint is %s, not the product %s: no NEB from it' % (got, want))
        return []
    try:
        ts = NEB.run_neb_ts(P(d), P(rx), P(end), round_idx=0, nprocs=int(NPROCS),
                            nimages=nimages, timeout=NEB_TIMEOUT, free_end=False)
    except Exception as e:
        log('  NEB from the scan endpoint failed:', e); return []
    if not ts or not os.path.exists(str(ts)):
        log('  NEB from the scan endpoint did not converge')
        return []
    log('  NEB saddle between the reactant and the scan endpoint')
    return [str(ts)]


def ts_mode_bond(kind):
    """The bond whose stretch OptTS should follow, for the kinds that need to be told.

    Eigenvector following from a GFN2-level proton-transfer guess drifts off the transfer ridge and
    converges on a soft heavy-atom saddle: FF step 2 came back at -334 and -27 cm-1 against the
    deposited -2043. Naming the breaking donor-H stretch keeps OptTS on the right mode. Combined
    with a full-range DFT relaxed scan for the guess, this reproduced HMF step 2 and FF step 2.
    """
    if kind in TAUT and len(ACTIVE) == 3:
        return '%d %d' % (ACTIVE[0], ACTIVE[2])     # donor, H
    return None


def validate(name, guess, R, Pmain, cop, wd, spect=None, kind=None):
    cmd = [PYBIN, SV, '--name', name, '--guess', guess, '--reactant', R, '--product', Pmain,
           '--nprocs', NPROCS, '--workdir', wd]
    if cop: cmd += ['--coproduct', cop]
    if spect: cmd += ['--spectators', spect]
    if ACTIVE: cmd += ['--active-atoms', ','.join(str(i) for i in ACTIVE)]
    tmb = ts_mode_bond(kind)
    if tmb: cmd += ['--ts-mode-bond', tmb]
    try:
        subprocess.run(cmd, env=ENV, cwd=wd, timeout=DFT_TIMEOUT)
    except subprocess.TimeoutExpired:
        log('  TIMEOUT (%ds) on %s -> abandon guess' % (DFT_TIMEOUT, name))
        # clean up any orphaned ORCA/mpi children from this guess
        subprocess.run(['pkill', '-9', '-f', name], capture_output=True)
        return None
    cf = os.path.join(wd, 'strict_cache.json')
    if os.path.exists(cf):
        d = json.load(open(cf)); return d[list(d)[-1]]
    return None


def canon(smi):
    """Canonical form matching what stripped_smiles returns, so the two can be compared."""
    from rdkit import Chem
    frags = [f for f in smi.split('.') if f not in ('O', '[H]O[H]')]
    m = Chem.MolFromSmiles('.'.join(frags)) if frags else None
    if m is None:
        return None
    Chem.RemoveStereochemistry(m)
    return Chem.MolToSmiles(m)


def stripped_smiles(xyz):
    """Neutral canonical SMILES of an xyz (water stripped); None if charged/bad."""
    from rdkit import Chem
    try:
        o = subprocess.check_output([PYBIN, os.path.join(ROOT, 'resources/tools/xyz_to_smiles.py'), xyz],
                                    text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return None
    smi = None
    for ln in reversed(o.splitlines()):
        ln = ln.strip()
        if ln and not ln.startswith('['):
            smi = ln.split()[0]; break
    if not smi:
        return None
    frags = [f for f in smi.split('.') if f not in ('O', '[H]O[H]')]
    if not frags:
        return None
    m = Chem.MolFromSmiles('.'.join(frags))
    if m is None or any(a.GetFormalCharge() != 0 for a in m.GetAtoms()):
        return None
    Chem.RemoveStereochemistry(m)
    return Chem.MolToSmiles(m)


def record_discovered(r, p, imag, kind):
    """Record an ACTUAL IRC-connected neutral edge (real chemistry the TS connects),
    regardless of whether it matched the proposed product. Grows the network + seeds."""
    from rdkit import Chem
    try:
        rc = Chem.MolToSmiles(Chem.MolFromSmiles(r)); pc = Chem.MolToSmiles(Chem.MolFromSmiles(p))
    except Exception:
        return
    if rc == pc:
        return
    d = json.load(open(DISC)) if os.path.exists(DISC) else {}
    key = '%s>>%s' % (rc, pc)
    if key not in d:
        d[key] = {'reactant': rc, 'product': pc, 'reaction_kind': kind, 'status': 'qm_real',
                  'ts_imag_cm-1': imag, 'source': 'dispatch_discovered', 'time': time.strftime('%Y-%m-%d %H:%M')}
        json.dump(d, open(DISC, 'w'), indent=2)
        log('  HARVESTED qm-real edge: %s >> %s (imag %s)' % (rc, pc, imag))


def harvest_endpoints(wd, vn, imag, kind):
    """After a validation, read the guess's raw IRC endpoints and record the real
    neutral edge they connect (even on MISMATCH)."""
    import glob
    F = sorted(glob.glob(os.path.join(wd, vn + '*_IRC_F.xyz')))
    B = sorted(glob.glob(os.path.join(wd, vn + '*_IRC_B.xyz')))
    if not F or not B:
        return
    sf = stripped_smiles(F[-1]); sb = stripped_smiles(B[-1])
    if sf and sb and sf != sb:
        record_discovered(sb, sf, imag, kind)


def _parse_hess_modes(hess):
    """Return (freqs list, normal-mode matrix dim x dim) from an ORCA .hess."""
    txt = open(hess).read().splitlines()
    i = txt.index('$vibrational_frequencies'); n = int(txt[i + 1])
    freqs = [float(txt[i + 2 + k].split()[1]) for k in range(n)]
    j = txt.index('$normal_modes'); dim = int(txt[j + 1].split()[0])
    mat = np.zeros((dim, dim)); p = j + 2; col = 0
    while col < dim:
        p += 1
        vals = []
        for r in range(dim):
            parts = txt[p].split(); vals = [float(x) for x in parts[1:]]
            for c, v in enumerate(vals):
                mat[r, col + c] = v
            p += 1
        col += len(vals)
    return freqs, mat


def soft_mode_cleanup(wd, base_name, R, Pmain, cop, spect, kind):
    """If a TS has a dominant strong imaginary + soft imaginary(s), displace along
    the soft mode and re-OptTS to a clean single-imaginary saddle, then re-validate.
    Returns strict_validate result dict or None."""
    ts = os.path.join(wd, base_name + '_ts.xyz'); hs = os.path.join(wd, base_name + '_ts.hess')
    if not (os.path.exists(ts) and os.path.exists(hs)):
        return None
    try:
        freqs, mat = _parse_hess_modes(hs)
    except Exception:
        return None
    negs = [(k, f) for k, f in enumerate(freqs) if f < -1.0]
    if len(negs) < 2:
        return None
    soft = max(negs, key=lambda kf: kf[1])[0]     # negative freq closest to 0
    vec = mat[:, soft].reshape(-1, 3)
    s, c = read_xyz(P(ts))
    for d in (0.6, -0.6):
        gdir = os.path.join(wd, base_name + '_clean_%+.1f' % d); os.makedirs(gdir, exist_ok=True)
        gx = os.path.join(gdir, 'guess.xyz'); write_xyz(P(gx), s, c + d * vec, 'soft-mode displaced')
        r = validate(base_name + '_clean%+d' % int(d * 10), gx, R, Pmain, cop, wd, spect)
        if r:
            harvest_endpoints(wd, base_name + '_clean%+d' % int(d * 10), r.get('ts_imag_cm-1'), kind)
            allmodes = r.get('ts_imag_all') or []
            if r.get('status') == 'STRICT' or len([m for m in allmodes if m < -1] ) == 1:
                return r
    return None


def record(R, Pmain, cop, kind, status, imag, imag_all=None):
    d = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    key = '%s>>%s%s' % (R, Pmain, ('.' + cop) if cop else '')
    d[key] = {'reactant': R, 'product': Pmain, 'coproduct': cop, 'reaction_kind': kind,
              'status': status, 'ts_imag_cm-1': imag, 'time': time.strftime('%Y-%m-%d %H:%M')}
    if imag_all:
        d[key]['ts_imag_all'] = imag_all
        d[key]['n_imag'] = len([m for m in imag_all if m < -1])
    json.dump(d, open(CACHE, 'w'), indent=2)


def run_candidate(cd, cap=4):
    global ACTIVE, RSMI
    ACTIVE = []          # never inherit the previous candidate's reactive atoms in queue mode
    R = cd['reactant']; kind = cd['reaction_kind']
    RSMI = R
    Pfull = cd['product']; cop = cd.get('coproduct')
    frags = Pfull.split('.')
    Pmain = max(frags, key=len); Pco = None
    if len(frags) > 1:
        Pco = '.'.join(f for f in frags if f != Pmain) or None
    coproduct = Pco or cop  # second organic fragment (retro-aldol) or water (dehydration)
    name = ('%s__%s' % (R, Pmain)).replace('/', '_').replace('=', 'e').replace('(', '').replace(')', '').replace('#', 't')[:60]
    wd = os.path.join(WORK, name); os.makedirs(wd, exist_ok=True)
    log('==== [%s] %s -> %s (+%s) ====' % (kind, R, Pmain, coproduct))
    rx = build_reactant(R, wd)
    if not rx:
        record(R, Pmain, coproduct, kind, 'BUILD_FAILED', None); return
    Pbal = Pmain + (('.' + coproduct) if coproduct else '')
    # --- energy-filter pruning: skip hopelessly endothermic candidates (GFN2) ---
    dE = rxn_dE_gfn2(rx, Pbal, wd)
    if dE is not None and dE > ENDO_THRESH_KCAL:
        log('  PRUNED: GFN2 dE_rxn=%.1f kcal > %.0f' % (dE, ENDO_THRESH_KCAL))
        record(R, Pmain, coproduct, kind, 'pruned_endothermic', None); return
    # Written up front rather than inside each generator: guesses_ring, guesses_retroaldol and
    # guesses_iso never wrote it, so NEB had no route file to read for exactly the kinds it is
    # there to serve.
    write_route(wd, R, Pmain, Pbal, coproduct)
    spect = None
    if kind in DEHY:
        gs = guesses_dehydration(wd, R, Pmain, 'O')
    elif kind in TAUT:
        # --spectators O is only correct for the water-relay fallback; asserting it for a
        # dry saddle would let a water-mediated endpoint slip through as if it were clean.
        gs, used_water = guesses_tautomer(wd, R, Pmain, cd.get('force_water'))
        spect = 'O' if used_water else None
    elif kind in ISO:
        gs = guesses_iso(wd, R)
    elif kind == 'retro_aldol':
        gs = guesses_retroaldol(wd, R)
    elif kind in ('ring_closure', 'ring_opening'):
        gs = guesses_ring(wd, R, opening=(kind == 'ring_opening'), Pmain=Pmain)
    else:
        log('  unknown kind, skip'); record(R, Pmain, coproduct, kind, 'SKIP_KIND', None); return
    # --force-water is a control mode: the DFT budget must go to the relayed-water guesses and
    # nothing else. Round 1 of the water controls spent its cap on dry active-learning fillers
    # (and geom_sane dropped the 1w/2w guesses that H-bond tighter than the dry clash floors), so
    # the measured IRC ends were zwitterions of the dry molecule, not water-assisted saddles.
    force_water = bool(cd.get('force_water'))
    neb_first = []
    if force_water:
        log('  force-water: skipping AL / NEB / DFT-scan fillers; validating water-relay guesses only')
    else:
        # --- general active-learning TS sampler (ARplorer-style), kind-agnostic fallback ---
        try:
            gs_al = AL.sample(wd, rx, Pbal, n_out=2)
            if gs_al:
                log('  +%d active-learning guesses' % len(gs_al)); gs = gs + gs_al
        except Exception as e:
            log('  active-learning sampler failed:', e)
        neb_first = guesses_neb(wd, rx, kind, Pmain) if (NEBGUESS and kind in NEB_KINDS) else []
        if neb_first:
            log('  +%d NEB-TS guess(es), tried ahead of the scan points' % len(neb_first))
        if DFTSCAN:
            if kind in TAUT:
                # The scan runs first, since NEB takes its far end as the product endpoint, but the
                # NEB saddle is offered first: it is the one that can cross between the two
                # electronic branches. When NEB does not converge it returns nothing and the 1D
                # peak that closed HMF step 2 and FF step 2 is next in line. TAUT2D adds the enol
                # C-O grid as a last tier.
                g = dft_proton_scan(rx, wd)
                neb_first = neb_from_scan(rx, wd, Pmain, 'dft_pscan', 'ps') + g + neb_first
                if TAUT2D:
                    neb_first += dft_taut_scan2d(rx, wd)
            elif kind in DRIVE_TARGET:
                g = dft_scan2d(rx, wd, kind)
                neb_first = neb_from_scan(rx, wd, Pmain, 'dft_scan2d', 's2') + g + neb_first
        # Ahead of everything above: it is the only grid whose points carry a bridging hydrogen,
        # which every deposited saddle has and none of this campaign's converged saddles did.
        if XFER2D:
            neb_first = dft_transfer_scan2d(rx, wd) + neb_first
    n_raw = len(gs)
    if force_water:
        # Relay geometries sit on H-bonds that trip the dry-molecule clash floors (measured:
        # FF_s5 1w C-C 1.20 A, 2w H-H 0.78 A). Dropping them emptied the pool and left only the
        # dry AL fillers. Keep them, log the flags, and let OptTS decide.
        flagged = [g for g in gs if not geom_sane(g)]
        if flagged:
            log('  force-water: keeping %d geom_sane-flagged water guess(es) of %d'
                % (len(flagged), n_raw))
    else:
        gs = [g for g in gs if geom_sane(g)]
        if len(gs) < n_raw:
            log('  dropped %d clashed guess(es) of %d' % (n_raw - len(gs), n_raw))
    # --- guess pruning: rank by GFN2 energy (highest = most TS-like), keep top cap ---
    scored = []
    for g in gs:
        e = gfn2_energy(g, os.path.join(wd, 'rank_' + os.path.basename(os.path.dirname(g))))
        if e is not None:
            scored.append((e, g))
    scored.sort(reverse=True)
    gs = [g for _, g in scored] or gs
    # A NEB-CI image is a maximum of the real path, so it goes first rather than competing on the
    # GFN2 energy ranking, which rewards whichever scan point happens to sit highest.
    gs = neb_first + [g for g in gs if g not in neb_first]
    log('  %d guesses (dE_rxn=%s), DFT-validating top %d' % (len(gs), ('%.1f' % dE) if dE is not None else '?', cap))
    best = None
    for gi, g in enumerate(gs[:cap]):
        vn = '%s_g%d' % (name, gi)
        if PRERELAX:
            g = dft_prerelax(g, wd, 'g%d' % gi)
        r = validate(vn, g, R, Pmain, coproduct, wd, spect, kind)
        if not r:
            continue
        st = r.get('status'); im = r.get('ts_imag_cm-1'); allm = r.get('ts_imag_all') or []
        log('  guess', gi, '->', st, im)
        harvest_endpoints(wd, vn, im, kind)          # (3) grow network from actual IRC endpoints
        if st == 'STRICT':
            # strict_validate accepts a dominant strong mode alongside small floppy ones,
            # but every step in the three accepted deposits has exactly ONE imaginary mode.
            # Try the existing cleanup to reach that; keep the STRICT verdict either way,
            # and record the mode list so a multi-mode saddle is visible rather than silent.
            nneg = len([m for m in allm if m < -1])
            if nneg >= 2:
                log('  STRICT but %d imaginary modes %s — attempting soft-mode cleanup' % (nneg, allm))
                r2 = soft_mode_cleanup(wd, vn, R, Pmain, coproduct, spect, kind)
                if r2 and r2.get('status') == 'STRICT':
                    a2 = r2.get('ts_imag_all') or []
                    if len([m for m in a2 if m < -1]) == 1:
                        record(R, Pmain, coproduct, kind, 'STRICT', r2.get('ts_imag_cm-1'), a2)
                        log('  STRICT (single mode after cleanup)'); return
            record(R, Pmain, coproduct, kind, 'STRICT', im, allm); log('  STRICT'); return
        # (2) persistence: soft-mode cleanup on a near-miss multi-mode saddle w/ dominant strong mode
        nneg = len([m for m in allm if m < -1])
        if st == 'NOT_CLEAN_TS' and nneg >= 2 and allm and min(allm) < -300:
            log('  escalating: soft-mode cleanup on', vn)
            r2 = soft_mode_cleanup(wd, vn, R, Pmain, coproduct, spect, kind)
            if r2 and r2.get('status') == 'STRICT':
                record(R, Pmain, coproduct, kind, 'STRICT', r2.get('ts_imag_cm-1'),
                       r2.get('ts_imag_all'))
                log('  STRICT (after cleanup)'); return
        if st == 'PARTIAL_MATCH' and best is None:
            best = im
    record(R, Pmain, coproduct, kind, 'PARTIAL_MATCH' if best else 'no_strict', best)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--top', type=int, default=6)
    ap.add_argument('--cap', type=int, default=4, help='max guesses to DFT-validate per candidate')
    ap.add_argument('--kinds', default=None, help='comma list to restrict reaction kinds')
    ap.add_argument('--queue', default=os.path.join(_CP.GRAPH, 'candidate_queue.json'))
    ap.add_argument('--edge'); ap.add_argument('--kind'); ap.add_argument('--coproduct')
    ap.add_argument('--force-water', action='store_true',
                    help='skip the dry scan and use the water relay: the only way to reach the\n'
                         'relay path now that a successful dry scan suppresses the fallback')
    args = ap.parse_args()
    open(os.path.join(WORK, 'dispatch.log'), 'a').write('\n==== dispatch %s ====\n' % time.strftime('%Y-%m-%d %H:%M'))
    if args.edge:
        r, p = args.edge.split('>>')
        run_candidate({'reactant': r, 'product': p, 'reaction_kind': args.kind,
                       'coproduct': args.coproduct, 'force_water': args.force_water}, cap=args.cap)
        return
    cands = json.load(open(args.queue))
    if args.kinds:
        ks = set(args.kinds.split(',')); cands = [c for c in cands if c['reaction_kind'] in ks]
    for cd in cands[:args.top]:
        run_candidate(cd, cap=args.cap)
    log('DISPATCH DONE')


if __name__ == '__main__':
    main()
