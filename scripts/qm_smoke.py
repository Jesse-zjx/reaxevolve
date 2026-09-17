#!/usr/bin/env python3
"""Prove ORCA and xTB actually execute through the migrated path plumbing.

The smoke test one directory over checks that modules import; this one spends real CPU. It runs
the campaign's own level of theory (r2SCAN-3c / CPCM(water) / DEFGRID3) on a molecule small enough
to finish in seconds, and drives xTB through the migrated guess generator rather than calling the
binary directly, so a broken WS-relative path would surface here.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'tools'))
import chem_paths as CP  # noqa: E402
CP.bootstrap()

fails = []


def ok(cond, label, detail=''):
    print('  [%s] %s%s' % ('PASS' if cond else 'FAIL', label, ('  ' + detail) if detail else ''))
    if not cond:
        fails.append(label)


work = tempfile.mkdtemp(prefix='qm_smoke_', dir='/tmp')
print('== 计算目录 %s' % work)

print('\n== 1. xTB：经迁移后的 smi_to_xyz 生成 GFN2 优化几何')
xyz = os.path.join(work, 'meoh.xyz')
r = subprocess.run([CP.PYBIN, os.path.join(CP.RESOURCES, 'smi_to_xyz.py'), 'CO', xyz],
                   capture_output=True, text=True, timeout=300, env=CP.orca_env())
if not os.path.isfile(xyz):
    ok(False, 'smi_to_xyz 产出几何', (r.stderr or r.stdout).strip()[-160:])
else:
    lines = open(xyz).read().split('\n')
    nat = int(lines[0].strip())
    ok(nat == 6, 'CH3OH 原子数为 6', '实得 %d' % nat)

print('\n== 2. ORCA：r2SCAN-3c / CPCM(water) / DEFGRID3 单点')
inp = os.path.join(work, 'sp.inp')
with open(inp, 'w') as f:
    f.write('! r2SCAN-3c CPCM(water) DEFGRID3 SP\n' + '%pal nprocs 2 end\n' +
            '* xyzfile 0 1 %s\n' % (xyz if os.path.isfile(xyz) else 'meoh.xyz'))
if not os.path.isfile(xyz):
    with open(os.path.join(work, 'meoh.xyz'), 'w') as f:
        f.write('6\n\nC 0.00 0.00 0.00\nO 1.42 0.00 0.00\nH -0.36 1.03 0.00\n'
                'H -0.36 -0.51 0.89\nH -0.36 -0.51 -0.89\nH 1.75 0.90 0.00\n')
r = subprocess.run([os.path.join(CP.ORCA_DIR, 'orca'), 'sp.inp'], cwd=work,
                   capture_output=True, text=True, timeout=900, env=CP.orca_env())
m = re.search(r'FINAL SINGLE POINT ENERGY\s+(-?\d+\.\d+)', r.stdout)
ok(m is not None, 'ORCA 收敛并给出总能',
   ('E = %s Eh' % m.group(1)) if m else (r.stdout or r.stderr).strip()[-160:])
ok('CPCM' in r.stdout, 'CPCM(water) 溶剂化已启用')
ok(bool(re.search(r'DefGrid3|DEFGRID3', r.stdout)), 'DEFGRID3 积分格点已启用')

print('\n== 3. ORCA 驱动 xTB：GFN2 优化（campaign 的猜测预筛路径）')
inp2 = os.path.join(work, 'g2.inp')
with open(inp2, 'w') as f:
    f.write('! XTB2 Opt\n' + '%pal nprocs 2 end\n' + '* xyzfile 0 1 %s\n'
            % os.path.basename(xyz if os.path.isfile(xyz) else 'meoh.xyz'))
r = subprocess.run([os.path.join(CP.ORCA_DIR, 'orca'), 'g2.inp'], cwd=work,
                   capture_output=True, text=True, timeout=900, env=CP.orca_env())
ok('HURRAY' in r.stdout or 'OPTIMIZATION RUN DONE' in r.stdout, 'ORCA→otool_xtb 优化完成',
   (r.stdout or r.stderr).strip()[-160:] if 'HURRAY' not in r.stdout else '')

print('\n' + '=' * 60)
if fails:
    print('%d 项未通过: %s' % (len(fails), ', '.join(fails)))
    sys.exit(1)
print('真实 QM 计算在迁移后的路径下跑通')
