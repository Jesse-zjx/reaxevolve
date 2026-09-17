#!/usr/bin/env python3
"""2D relaxed scan for the concerted aldose<->ketose isomerization: constrain TWO
forming bonds simultaneously (hydride C2-H11 and proton O3-H10), relax the rest
(DEFGRID3). Locate the col as the TS guess."""
import os, re, subprocess, sys, json
import numpy as np
sys.path.insert(0,'/root/OpenAgentHarness/templates/path-validator-workspace/resources')
from auto_guess import read_xyz, write_xyz
from pathlib import Path
ORCA="/root/orca_6_1_1_linux_x86-64_shared_openmpi418_nodmrg/orca"
wd=Path(sys.argv[1]); start=Path(sys.argv[2])
C2,H11,O3,H10=int(sys.argv[3]),int(sys.argv[4]),int(sys.argv[5]),int(sys.argv[6])
wd.mkdir(parents=True,exist_ok=True)
DHYD=[1.8,1.6,1.45,1.3,1.15]     # forming hydride C2-H11
DPRO=[1.6,1.4,1.25,1.1,1.0]      # forming proton  O3-H10
def spe(o):
    v=[float(m.group(1)) for m in re.finditer(r'FINAL SINGLE POINT ENERGY\s+([-\d.]+)',open(o).read())]
    return v[-1] if v else None
grid={}; prev=start
for i,dh in enumerate(DHYD):
    for j,dp in enumerate(DPRO):
        d=wd/f"g_{i}_{j}"; d.mkdir(exist_ok=True)
        s,c=read_xyz(prev); write_xyz(d/"s.xyz",s,c,f"{dh},{dp}")
        (d/"c.inp").write_text("! r2SCAN-3c CPCM(water) Opt NoPop DEFGRID3\n"
            "%geom Constraints\n"
            f"  {{ B {C2} {H11} {dh} C }}\n"
            f"  {{ B {O3} {H10} {dp} C }}\n"
            "end end\n%maxcore 4000\n%pal nprocs 8 end\n* xyzfile 0 1 s.xyz *\n")
        with open(d/"c.out","w") as f:
            subprocess.run([ORCA,"c.inp"],cwd=str(d),stdout=f,stderr=subprocess.STDOUT)
        e=spe(d/"c.out"); grid[(i,j)]=e
        if (d/"c.xyz").exists(): prev=d/"c.xyz"
        print(f"g_{i}_{j} hyd={dh} pro={dp} E={e}",flush=True)
E=np.full((len(DHYD),len(DPRO)),np.nan)
for (i,j),e in grid.items():
    if e is not None: E[i,j]=e
Emin=np.nanmin(E); rel=(E-Emin)*627.5
print("=== 2D grid (kcal rel) rows=hydride C2-H11, cols=proton O3-H10 ===")
print("      "+" ".join(f"{d:5.2f}" for d in DPRO))
for i,dh in enumerate(DHYD):
    print(f"{dh:5.2f} "+" ".join(f"{rel[i,j]:5.1f}" if not np.isnan(rel[i,j]) else "  .  " for j in range(len(DPRO))))
valley=[]
for i in range(len(DHYD)):
    row=rel[i,:]
    if np.all(np.isnan(row)): continue
    j=int(np.nanargmin(row)); valley.append((i,j,row[j]))
if valley:
    si,sj,sv=max(valley,key=lambda t:t[2])
    print(f"SADDLE guess g_{si}_{sj} hyd={DHYD[si]} pro={DPRO[sj]} rel={sv:.1f} kcal")
    json.dump({"saddle":[si,sj]},open(wd/"saddle.json","w"))
