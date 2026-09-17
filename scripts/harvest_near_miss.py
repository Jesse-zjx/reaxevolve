#!/usr/bin/env python3
"""Raise STRICT count by cleaning near-miss saddles that already have a dominant mode.

Takes NOT_CLEAN_TS records whose Hessian is still on disk, runs soft_mode_cleanup to push
residual soft imaginaries positive, then re-validates (OptTS is skipped when the cleaned
geometry already carries a single imaginary; IRC + endpoint match decide STRICT).

  harvest_near_miss.py                 # the three pre-selected near-misses
  harvest_near_miss.py --only g2_K_M   # one of them
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
_d = HERE
while _d != '/' and not os.path.isfile(os.path.join(_d, 'tools', 'chem_paths.py')):
    _d = os.path.dirname(_d)
sys.path.insert(0, os.path.join(_d, 'tools'))
import chem_paths as CP  # noqa: E402

PY = CP.PYBIN
CLEANUP = os.path.join(CP.RESOURCES, 'soft_mode_cleanup.py')
VALIDATE = os.path.join(CP.RESOURCES, 'strict_validate.py')
OUT_ROOT = os.path.join(CP.VALIDATION, 'harvest_near_miss')

# Pre-selected: dominant imag + soft contaminant(s), hess still present, modes matched to file.
TARGETS = [
    {
        'id': 'dehyd_698',
        'hess': ('tools/qm-workspace/validation/dispatch_runs/'
                 'OeCCeOCeCCOCO__OeCCeOCeCCeCO/OeCCeOCeCCOCO__OeCCeOCeCCeCO_g1_ts.hess'),
        'reactant': 'O=CC(=O)C=CC(O)CO',
        'product': 'O=CC(=O)C=CC=CO',
        'coproduct': 'O',
        'kind': 'dehydration',
        'modes': [-698.37, -285.11],
    },
    {
        'id': 'dehyd_316',
        'hess': ('tools/qm-workspace/validation/dispatch_runs/'
                 'OeCCOeCCOCOCO__CeCOCOCeCOCeO/OeCCOeCCOCOCO__CeCOCOCeCOCeO_g0_ts.hess'),
        'reactant': 'O=CC(O)=CC(O)C(O)CO',
        'product': 'C=C(O)C(O)C=C(O)C=O',
        'coproduct': 'O',
        'kind': 'dehydration',
        'modes': [-316.75, -214.59],
    },
    {
        'id': 'g2_K_M',
        'hess': 'tools/qm-workspace/validation/cpcm_chain/g2_K_M/g2_K_M_ts.hess',
        'reactant': 'OC=C1C=CC(O)(CO)O1',
        'product': 'O=CC1(O)C=CC(CO)O1',
        'coproduct': None,
        'kind': 'isomerization',
        'modes': [-401.53, -264.76],
    },
]


def log(msg):
    print(msg, flush=True)


def run(cmd, cwd=None, env=None):
    log('  $ ' + ' '.join(cmd))
    return subprocess.run(cmd, cwd=cwd, env=env or CP.orca_env(),
                          capture_output=False, text=True)


def find_clean_xyz(clean_dir):
    """Geometry declared CLEAN by soft_mode_cleanup (single imag after OptTS)."""
    # Prefer the stem that the script printed as CLEAN; fall back to any *ts.xyz with one imag.
    for name in ('tight.xyz',):
        p = os.path.join(clean_dir, name)
        if os.path.isfile(p.replace('.xyz', '.out')):
            # after --run, OptTS writes stem.xyz next to stem.out
            opt = os.path.join(clean_dir, 'tight.xyz')
            # ORCA OptTS writes tight.xyz as the optimized geometry when inp references it
            pass
    # soft_mode_cleanup prints "geometry: .../stem.xyz" for the winner; the OptTS result is stem.xyz
    # (same name as the guess — ORCA overwrites) or stem_trj; look for outs with one imag.
    sys.path.insert(0, CP.RESOURCES)
    from soft_mode_cleanup import imag_of  # noqa: E402
    for out in sorted(glob.glob(os.path.join(clean_dir, '*.out'))):
        im = imag_of(out)
        if im is not None and len(im) == 1:
            stem = out[:-4]
            for cand in (stem + '.xyz', os.path.join(clean_dir, os.path.basename(stem) + '.xyz')):
                if os.path.isfile(cand) and os.path.getsize(cand) > 0:
                    return cand, im[0]
    return None, None


def harvest_one(t, nprocs):
    hess = t['hess'] if os.path.isabs(t['hess']) else os.path.join(CP.PACKAGE, t['hess'])
    if not os.path.isfile(hess):
        log('[%s] missing hess: %s' % (t['id'], hess))
        return {'id': t['id'], 'status': 'NO_HESS'}
    wd = os.path.join(OUT_ROOT, t['id'])
    clean_dir = os.path.join(wd, 'cleanup')
    os.makedirs(wd, exist_ok=True)
    log('==== [%s] %s -> %s (+%s) ====' % (t['id'], t['reactant'], t['product'], t['coproduct']))
    log('  modes were %s' % t['modes'])

    # 1) soft-mode cleanup OptTS
    r = run([PY, CLEANUP, '--hess', hess, '--out', clean_dir,
             '--amp', '0.7', '--nprocs', str(nprocs), '--run'])
    if r.returncode not in (0,):
        # exit 0 = CLEAN found; exit 1 = nothing to clean / no single-imag; exit 2 = all crashed
        log('[%s] cleanup exit %s' % (t['id'], r.returncode))

    xyz, imag = find_clean_xyz(clean_dir)
    if not xyz:
        # Maybe already single-imag (cleanup returned 0 without running)? Use original ts xyz.
        src_xyz = hess.replace('.hess', '.xyz')
        if os.path.isfile(src_xyz):
            log('[%s] no cleaned geometry; will not re-validate the dirty saddle' % t['id'])
        return {'id': t['id'], 'status': 'CLEANUP_FAILED', 'cleanup_dir': clean_dir}

    log('[%s] cleaned geometry %s  imag=%.2f' % (t['id'], xyz, imag))

    # 2) strict_validate from the cleaned TS (re-OptTS + IRC + endpoints)
    val_dir = os.path.join(wd, 'validate')
    os.makedirs(val_dir, exist_ok=True)
    guess = os.path.join(val_dir, 'guess.xyz')
    shutil.copy2(xyz, guess)
    cmd = [PY, VALIDATE, '--name', t['id'] + '_clean', '--guess', guess,
           '--reactant', t['reactant'], '--product', t['product'],
           '--nprocs', str(nprocs), '--workdir', os.path.abspath(val_dir)]
    if t['coproduct']:
        cmd += ['--coproduct', t['coproduct']]
    env = CP.orca_env(EXACT_SMILES_ONLY='1', NPROCS=str(nprocs))
    r = run(cmd, env=env)

    # Read the cache the validator just wrote
    cache_path = os.path.join(val_dir, 'strict_cache.json')
    status = 'NO_CACHE'
    imag_final = None
    if os.path.isfile(cache_path):
        blob = json.load(open(cache_path))
        for rec in blob.values():
            if isinstance(rec, dict):
                status = rec.get('status', status)
                imag_final = rec.get('ts_imag_cm-1')
    result = {'id': t['id'], 'status': status, 'ts_imag_cm-1': imag_final,
              'reactant': t['reactant'], 'product': t['product'],
              'coproduct': t['coproduct'], 'kind': t['kind'],
              'workdir': val_dir, 'time': time.strftime('%Y-%m-%d %H:%M')}
    log('[%s] RESULT %s  imag=%s' % (t['id'], status, imag_final))
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', default=None, help='run a single target id')
    ap.add_argument('--nprocs', type=int, default=int(os.environ.get('NPROCS', '4')))
    a = ap.parse_args()
    os.makedirs(OUT_ROOT, exist_ok=True)
    targets = [t for t in TARGETS if a.only is None or t['id'] == a.only]
    if not targets:
        sys.exit('no targets match --only %r' % a.only)
    results = []
    for t in targets:
        results.append(harvest_one(t, a.nprocs))
    summary = os.path.join(OUT_ROOT, 'summary.jsonl')
    with open(summary, 'a') as fh:
        for r in results:
            fh.write(json.dumps(r, ensure_ascii=False) + '\n')
    n_strict = sum(1 for r in results if str(r.get('status', '')).startswith('STRICT'))
    log('done: %d/%d STRICT  (summary %s)' % (n_strict, len(results), summary))
    return 0 if n_strict else 1


if __name__ == '__main__':
    sys.exit(main())
