#!/usr/bin/env python3
"""Clear spurious soft imaginary modes off an otherwise good transition state.

OptTS often lands on a geometry that carries the reaction's own stiff imaginary mode plus a handful
of small ones from loose hydroxyl rotations. The screening bar in strict_validate.py tolerates those,
but the deposit bar requires exactly one imaginary mode, so such a step cannot be deposited as it
stands. The remedy the three accepted deposits used is to step off the flat directions and let a
tighter optimization settle into the true saddle:

    displace the geometry along each spurious mode by +/- amp, re-run OptTS with VeryTightSCF and a
    Hessian recalculated every few cycles, and keep whichever result has one imaginary mode left.

Reads an ORCA .hess, writes the displaced geometries, and optionally runs the follow-up OptTS.

    soft_mode_cleanup.py --hess step_ts.hess --out cleanup/
    soft_mode_cleanup.py --hess step_ts.hess --out cleanup/ --run --nprocs 8 \
        --active-atoms "3 4 12"
"""
import argparse
import os
import re
import subprocess
import sys

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

ORCA = os.environ.get('ORCA_DIR', _CP.ORCA_DIR)
BOHR = 0.529177210903


def read_hess(path):
    """(symbols, coords in Angstrom, frequencies in cm-1, normal modes as columns)."""
    text = open(path).read()

    def block(name):
        m = re.search(r'\$%s\s*\n(.*?)(?=\n\$)' % name, text, re.S)
        if not m:
            raise ValueError('%s has no $%s block' % (path, name))
        # ORCA puts comment lines describing the next section ahead of its marker
        return '\n'.join(ln for ln in m.group(1).split('\n') if not ln.lstrip().startswith('#'))

    lines = block('atoms').strip().split('\n')
    syms, xyz = [], []
    for ln in lines[1:]:
        p = ln.split()
        if len(p) >= 5:
            syms.append(p[0])
            xyz.append([float(v) * BOHR for v in p[2:5]])

    fl = block('vibrational_frequencies').strip().split('\n')
    freqs = [float(ln.split()[1]) for ln in fl[1:] if len(ln.split()) == 2]

    # column-blocked matrix: a header row of mode indices, then one row per coordinate
    nl = block('normal_modes').strip().split('\n')
    n = int(nl[0].split()[0])
    modes = np.zeros((n, n))
    row, cols = None, []
    for ln in nl[1:]:
        p = ln.split()
        if not p:
            continue
        if all(v.lstrip('-').isdigit() for v in p):
            cols = [int(v) for v in p]
            continue
        row = int(p[0])
        for k, v in enumerate(p[1:]):
            modes[row, cols[k]] = float(v)
    return syms, np.array(xyz), freqs, modes


def spurious(freqs, floor):
    """Indices of imaginary modes other than the stiff one the reaction itself needs."""
    imag = [i for i, f in enumerate(freqs) if f < -1.0]
    if not imag:
        return [], None
    main = min(imag, key=lambda i: freqs[i])
    if freqs[main] > floor:
        return [], None           # nothing here looks like a reaction coordinate
    return [i for i in imag if i != main], main


def write_xyz(path, syms, coords, comment=''):
    with open(path, 'w') as f:
        f.write('%d\n%s\n' % (len(syms), comment))
        for s, c in zip(syms, coords):
            f.write('%-3s %14.8f %14.8f %14.8f\n' % (s, c[0], c[1], c[2]))


CLASH = 0.85     # Angstrom; below this two atoms are on top of each other


def min_dist(coords):
    d = np.linalg.norm(coords[:, None, :] - coords[None, :, :], axis=-1)
    np.fill_diagonal(d, np.inf)
    return d.min()


def displaced(syms, xyz, modes, idx, amp):
    """Geometry stepped along one normal mode, both ways, at an amplitude that stays physical.

    The softer the mode the further a fixed step travels, and a full step along the flattest ones
    drives atoms through each other. Halve until the geometry is something ORCA can start from.
    """
    v = modes[:, idx].reshape(-1, 3)
    norm = np.linalg.norm(v)
    if norm < 1e-8:
        return [], amp
    v = v / norm
    for _ in range(4):
        out = [xyz + s * amp * v for s in (1.0, -1.0)]
        if all(min_dist(g) >= CLASH for g in out):
            return out, amp
        amp /= 2.0
    return [], amp


def opt_input(xyz_name, nprocs, active=None):
    """OptTS tuned to push a residual soft mode positive rather than to explore.

    Convergence thresholds are named the way ORCA 6 spells them. `TolG`/`TolD` are rejected
    outright by the input scanner ("Unknown identifier in GEOM block"), and the run dies in under a
    second -- which this script used to report as "no displacement gave a single imaginary mode",
    i.e. a tool defect wearing the costume of a chemical result.
    """
    aa = ''
    if active:
        # space-separated inside the braces, as in strict_validate.py; commas are not parsed
        aa = ('  TS_Active_Atoms {%s} end\n  TS_Active_Atoms_Factor 1.5\n'
              % ' '.join(active.replace(',', ' ').split()))
    return ('! r2SCAN-3c OptTS NumFreq VeryTightSCF DEFGRID3 CPCM(water)\n'
            '%%geom Calc_Hess true Recalc_Hess 3 MaxIter 150\n'
            '  TolE 1e-7\n  TolRMSG 1e-5\n  TolMaxG 3e-5\n  TolRMSD 5e-4\n  TolMaxD 1e-3\n'
            '%s'
            'end\n'
            '%%maxcore 4000\n%%pal nprocs %d end\n* xyzfile 0 1 %s *\n'
            % (aa, nprocs, xyz_name))


def why_failed(out_path):
    """The ORCA complaint that stopped the run, for outputs that never reached a frequency block."""
    if not os.path.exists(out_path):
        return 'no output file written'
    t = open(out_path, errors='ignore').read()
    for pat in (r'Unknown identifier in \w+ block.*?:\s*\n?.*?Last token\s*:\s*(\S+)',
                r'ORCA finished by error termination[^\n]*',
                r'aborting the run[^\n]*',
                r'Error\s*:[^\n]*'):
        m = re.search(pat, t, re.S)
        if m:
            return ' '.join(m.group(0).split())[:200]
    return None


def imag_of(out_path):
    """Imaginary frequencies in the last frequency block of an ORCA output."""
    if not os.path.exists(out_path):
        return None
    t = open(out_path, errors='ignore').read()
    if 'VIBRATIONAL FREQUENCIES' not in t:
        return None
    tail = t.split('VIBRATIONAL FREQUENCIES')[-1]
    return [float(x) for x in re.findall(
        r'^\s+\d+:\s+(-\d+\.\d+) cm\*\*-1\s+\*\*\*imaginary', tail, re.M)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--hess', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--amp', type=float, default=0.7,
                    help='displacement along each spurious mode, Angstrom')
    ap.add_argument('--tiny', type=float, default=-60.0,
                    help='modes above this are left to the tight re-optimization instead of being '
                         'displaced along: a step along the flattest directions distorts the '
                         'molecule more than it resolves')
    ap.add_argument('--main-floor', type=float, default=-300.0,
                    help='the stiffest imaginary mode must be below this to count as the reaction '
                         'coordinate; otherwise there is nothing worth cleaning up')
    ap.add_argument('--run', action='store_true', help='also run the follow-up OptTS')
    ap.add_argument('--nprocs', type=int, default=8)
    ap.add_argument('--active-atoms', default=None)
    ap.add_argument('--timeout', type=int, default=21600)
    a = ap.parse_args()

    syms, xyz, freqs, modes = read_hess(a.hess)
    soft, main = spurious(freqs, a.main_floor)
    if main is None:
        print('no dominant imaginary mode below %.0f cm-1; nothing to clean' % a.main_floor)
        return 1
    print('reaction mode %.2f cm-1; spurious %s'
          % (freqs[main], [round(freqs[i], 1) for i in soft] or 'none'))
    if not soft:
        print('already a single imaginary mode')
        return 0

    os.makedirs(a.out, exist_ok=True)
    cands = []
    # A residual of only a few tens of wavenumbers is usually grid noise on a flat direction rather
    # than a real downhill channel, and the tighter optimization alone pushes it positive; the
    # deposits' HAA step 2 was cleaned that way. Try that before spending cycles on displacements.
    write_xyz(os.path.join(a.out, 'tight.xyz'), syms, xyz, 'undisplaced, tight re-optimization')
    cands.append('tight.xyz')
    for i in soft:
        if freqs[i] > a.tiny:
            continue
        gs, used = displaced(syms, xyz, modes, i, a.amp)
        for k, g in enumerate(gs):
            name = 'disp_m%d_%s.xyz' % (i, '+-'[k])
            write_xyz(os.path.join(a.out, name), syms, g,
                      'displaced %+.2f A along %.1f cm-1' % ((1, -1)[k] * used, freqs[i]))
            cands.append(name)
        if not gs:
            print('  mode %.1f cm-1: no physical displacement, leaving it to the tight re-opt'
                  % freqs[i])
    print('wrote %d candidate geometries' % len(cands))
    if not a.run:
        return 0

    crashed = []
    for name in cands:
        stem = name[:-4]
        inp = os.path.join(a.out, stem + '.inp')
        open(inp, 'w').write(opt_input(name, a.nprocs, a.active_atoms))
        print('running %s ...' % stem, flush=True)
        try:
            subprocess.run([ORCA + '/orca', stem + '.inp'], cwd=a.out, timeout=a.timeout,
                           stdout=open(os.path.join(a.out, stem + '.out'), 'w'),
                           stderr=subprocess.STDOUT)
        except subprocess.TimeoutExpired:
            print('  timed out')
            continue
        op = os.path.join(a.out, stem + '.out')
        im = imag_of(op)
        if im is None:
            # No frequency block at all: the run never got that far. Reporting this as "no imaginary
            # modes" is how a broken input turns into a false chemical negative, so name it instead.
            print('  RUN FAILED (no frequency block): %s' % (why_failed(op) or 'see ' + op))
            crashed.append(stem)
            continue
        print('  imaginary: %s' % im)
        if len(im) == 1:
            print('CLEAN: %s -> %.2f cm-1' % (stem, im[0]))
            print('geometry: %s' % os.path.join(a.out, stem + '.xyz'))
            return 0
    if crashed and len(crashed) == len(cands):
        print('every candidate run failed before producing frequencies -- this is a tool/input '
              'problem, not a result about the saddle')
        return 2
    print('no displacement gave a single imaginary mode')
    return 1


if __name__ == '__main__':
    sys.exit(main())
