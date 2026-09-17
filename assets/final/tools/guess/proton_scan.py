#!/usr/bin/env python3
"""Single-coordinate DFT relaxed scan driving a forming bond B(a,b) from d0->d1.
Per-point constrained Opt (DEFGRID3), chained geometries. For 1,3-H shifts /
proton transfers. Args: wd start.xyz a b d0 d1 [npts]"""
import os, re, subprocess, sys, json
sys.path.insert(0,'/root/OpenAgentHarness/templates/path-validator-workspace/resources')
from auto_guess import read_xyz, write_xyz
from pathlib import Path
ORCA="/root/orca_6_1_1_linux_x86-64_shared_openmpi418_nodmrg/orca"
wd=Path(sys.argv[1]); start=Path(sys.argv[2])
a,b=int(sys.argv[3]),int(sys.argv[4]); d0,d1=float(sys.argv[5]),float(sys.argv[6])
npts=int(sys.argv[7]) if len(sys.argv)>7 else 12
wd.mkdir(parents=True,exist_ok=True)
DISTS=[round(d0+i*(d1-d0)/(npts-1),3) for i in range(npts)]
def spe(o):
    v=[float(m.group(1)) for m in re.finditer(r'FINAL SINGLE POINT ENERGY\s+([-\d.]+)',open(o).read())]
    return v[-1] if v else None
cur=start
for i,d in enumerate(DISTS):
    dd=wd/f"p{i:02d}";dd.mkdir(exist_ok=True)
    s,c=read_xyz(cur);write_xyz(dd/"s.xyz",s,c,f"d={d}")
    (dd/"c.inp").write_text("! r2SCAN-3c CPCM(water) Opt NoPop DEFGRID3\n"
        f"%geom Constraints {{ B {a} {b} {d} C }} end end\n"
        "%maxcore 4000\n%pal nprocs 8 end\n* xyzfile 0 1 s.xyz *\n")
    with open(dd/"c.out","w") as f:
        subprocess.run([ORCA,"c.inp"],cwd=str(dd),stdout=f,stderr=subprocess.STDOUT)
    e=spe(dd/"c.out");o=dd/"c.xyz"
    print(f"p{i:02d} d={d} E={e}",flush=True)
    if o.exists():cur=o
es=[(d,spe(wd/f"p{i:02d}/c.out") if (wd/f"p{i:02d}/c.out").exists() else None) for i,d in enumerate(DISTS)]
Emin=min(e for _,e in es if e)
rel=[round((e-Emin)*627.5,1) if e else None for _,e in es]
pk=max(range(len(es)),key=lambda i:(es[i][1] or -1e9))
print("MEP kcal:",rel);print("peak idx",pk,"-> p%02d/c.xyz"%pk,"peak",rel[pk])
json.dump({"dists":[d for d,_ in es],"E":[e for _,e in es],"peak":pk},open(wd/"scan.json","w"),indent=2)
