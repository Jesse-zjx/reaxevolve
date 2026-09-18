#!/usr/bin/env python3
"""Interactive STRICT reaction-network explorer.
- draggable physics graph on top; detail panel below (empty until a click)
- nodes are uniform colored dots (no text); hover -> molecule image + SMILES
- click node -> full molecule detail in the panel
- hover edge -> barrier / imaginary freq; click edge -> reaction + agent discovery process
- glucose->HMF and glucose->HAA routes highlighted with an outer bright halo
"""
import json, base64, collections, html
from rdkit import Chem
from rdkit.Chem import AllChem, rdMolDescriptors
from rdkit.Chem.Draw import rdMolDraw2D

import sys as _sys, os as _os
_d = _os.path.dirname(_os.path.abspath(__file__))
_pkg = _d
while _pkg != '/' and not _os.path.isdir(_os.path.join(_pkg, 'tools')):
    _pkg = _os.path.dirname(_pkg)
_sys.path.insert(0, _os.path.join(_pkg, 'tools'))
_sys.path.insert(0, _os.path.join(_pkg, 'scripts', 'lib'))
import chem_paths as _CP

def _edge_records(net):
    """Edges as a list, whichever container the graph file uses.

    Graph Memory keys edges by id; iterating the dict directly yields its keys, which
    silently produces an empty result rather than an error.
    """
    e = net.get("edges")
    if isinstance(e, dict):
        return [v for v in e.values() if isinstance(v, dict)]
    return [v for v in (e or []) if isinstance(v, dict)]

_CP.bootstrap()

NET = json.load(open(_os.path.join(_CP.GRAPH, 'reaction_network.json')))
STRICT = [e for e in _edge_records(NET) if e.get('status') == 'STRICT']
def C(s):
    try: return Chem.CanonSmiles(s)
    except Exception: return s

# ---- names ----
NAMES = {
 'O=CC(O)C(O)C(O)C(O)CO':'open-chain D-glucose','O=C(CO)C(O)C(O)C(O)CO':'open-chain D-fructose',
 'O=CC(O)CO':'D-glyceraldehyde','OC=CO':'glycolaldehyde enol (1,2-ethenediol)','O=CCO':'HAA (glycolaldehyde)',
 'O=Cc1ccc(CO)o1':'HMF (5-hydroxymethylfurfural)','O=CC(O)=CC(O)C(O)CO':'3-deoxyglucosone enol',
 'O=CC(=O)CC(O)C(O)CO':'3-deoxyglucosone (3-DG)','O=CC(=O)C=CC(O)CO':'3,4-dideoxyglucosone-3-ene (3,4-DGE)',
 'O=CC1(O)C=CC(CO)O1':'furanic hemiketal (HMF precursor)','OC=C(O)CO':'dihydroxyacetone enol','C=O':'formaldehyde',
 'OC1CO1':'2-hydroxyoxirane',
 # C5 / furfural route
 'O=CC(O)C(O)C(O)CO':'open-chain D-xylose','O=CC(O)=CC(O)CO':'xylo 3-deoxy-enol',
 'O=CC(=O)CC(O)CO':'3-deoxyxylosone','O=CC(=O)C=CCO':'xylo unsaturated dicarbonyl',
 'O=CC1(O)C=CCO1':'furanic hemiketal (FF precursor)','O=Cc1ccco1':'furfural (FF)',
 'OCC(O)=C(O)C(O)C(O)CO':'D-fructose 2,3-enediol','O=C(C(O)CO)C(O)C(O)CO':'3-ketohexose (C6)','OC=C(O)C(O)C(O)CO':'C5 enediol (xylo)'}
# ---- energies (Eh) from the two finalized manifests ----
ENERGY = {}
for src in [_os.path.join(_CP.DEPOSITS, 'glucose_hmf_review_v3', '06_final_chain', 'MANIFEST.json')]:
    m = json.load(open(src))
    for n in m['nodes']: ENERGY[C(n['expected_smiles'])] = n['E_Eh']
haa = json.load(open(_os.path.join(_CP.DEPOSITS, 'glucose_haa_review_v1', '06_final_chain', 'MANIFEST.json')))
for n in haa['nodes']: ENERGY[C(n['smiles'])] = n['E_Eh']
for cp in haa['coproducts']: ENERGY[C(cp['smiles'])] = cp['E_Eh']

# ---- per-edge extra info: barrier, dE, reaction type, agent process ----
# keyed by canonical "r>>p"
def K(r,p): return C(r)+'>>'+C(p)
EDGE_EXTRA = {
 K('O=CC(O)C(O)C(O)C(O)CO','O=C(CO)C(O)C(O)C(O)CO'):dict(bar=35.9,dE=-3.6,kind='aldose–ketose isomerization',
   proc="Glucose→fructose (Lobry de Bruyn). TS found in the strict GFN2-guided sweep: GFN2 pre-guess → r²SCAN-3c OptTS+NumFreq → IRC. Single imaginary −474 cm⁻¹; raw IRC endpoints are exactly open glucose and open fructose."),
 K('O=C(CO)C(O)C(O)C(O)CO','O=CC(O)CO'):dict(bar=35.1,dE=29.8,kind='C6 retro-aldol (C–C cleavage)',
   proc="Fructose C3–C4 retro-aldol → glyceraldehyde + DHA-enol. Agent path: (1) a plain C–C scan only climbed a wall (no concerted proton transfer); (2) diagnosed the missing β-OH→carbonyl proton relay; (3) xTB pre-organised the 6-membered H-bonded conformer; (4) DFT dual-constrained relaxed scan (open C4–C6 while holding the β-OH proton near the carbonyl O) → peak ≈25 kcal; (5) OptTS with TS_Active_Atoms on the reactive core {C,O,Cα,Cβ,Oβ,Hβ} to stop drift among floppy C6 torsions; (6) DEFGRID3 re-opt removed a −13.5 cm⁻¹ grid-noise soft mode → single imaginary −758 cm⁻¹. IRC: exact fructose ↔ glyceraldehyde + DHA-enol."),
 K('O=CC(O)CO','OC=CO'):dict(bar=31.5,dE=27.5,kind='C3 retro-aldol (C–C cleavage)',
   proc="Glyceraldehyde retro-aldol → glycolaldehyde-enol + formaldehyde. Agent path: DFT relaxed C–C scan traced the concerted MEP (peak at C–C≈2.4 Å, 32.6 kcal) — a single coordinate sufficed here because the β-OH is already close to the carbonyl; OptTS from the scan peak → single imaginary −942 cm⁻¹. IRC: exact glyceraldehyde ↔ glycolaldehyde-ENOL + formaldehyde (retro-aldol delivers the enol tautomer)."),
 K('OC=CO','O=CCO'):dict(bar=30.4,dE=-4.6,kind='water-catalysed enol→keto tautomerization',
   proc="Glycolaldehyde enol → keto (HAA). Agent path: dry 1,3-H shift is >70 kcal and a dry NEB found an epoxide side-reaction instead; switched to an explicit relay water; DFT dual-constrained proton-wire scan (drive water-H → acceptor carbon while holding water-O near the donor O–H) → peak ≈31.6 kcal; OptTS → single imaginary −920 cm⁻¹. IRC: exact enol + H₂O ↔ HAA + H₂O (catalytic water stripped as spectator)."),
 K('O=CC(O)C(O)C(O)C(O)CO','O=CC(O)=CC(O)C(O)CO'):dict(bar=50.2,dE=7.5,kind='dehydration (β-elimination of C3-OH)',
   proc="Glucose 1,2-enolization/dehydration. TS from a constrained C–O relaxed scan (not NEB) → r²SCAN-3c OptTS+NumFreq → IRC. Single imaginary −1410 cm⁻¹; loses one H₂O."),
 K('O=CC(O)=CC(O)C(O)CO','O=CC(=O)CC(O)C(O)CO'):dict(bar=68.2,dE=-5.6,kind='keto–enol tautomerization',
   proc="Enol → 3-deoxyglucosone (3-DG). Single imaginary −1450 cm⁻¹. This is the rate-determining step of the HMF route (ΔE‡≈68 kcal)."),
 K('O=CC(=O)CC(O)C(O)CO','O=CC(=O)C=CC(O)CO'):dict(bar=46.6,dE=11.6,kind='dehydration',
   proc="3-DG → 3,4-DGE (C4-OH β-elimination). Constrained C–O scan guess. Single imaginary −1533 cm⁻¹; loses one H₂O."),
 K('O=CC(=O)C=CC(O)CO','O=CC1(O)C=CC(CO)O1'):dict(bar=32.9,dE=-7.3,kind='ring closure (retro-hemiketal)',
   proc="3,4-DGE → furanic hemiketal. Agent path: the auto-mapper kept scanning the wrong C–O bond; the fix was a TARGETED dual scan of the anomeric C1–O5 stretch + C1-OH proton→O5. A spurious −34.9 cm⁻¹ soft torsion was removed by soft-mode displacement + reopt → single imaginary −1574 cm⁻¹."),
 K('O=CC1(O)C=CC(CO)O1','O=Cc1ccc(CO)o1'):dict(bar=51.1,dE=-10.7,kind='aromatizing dehydration',
   proc="Furanic hemiketal → HMF (aromatization). Constrained C–O scan guess. Single imaginary −830 cm⁻¹; loses the final H₂O, forming the aromatic furan."),
 # ---- C5 furfural route (from xylose) ----
 K('O=CC(O)C(O)C(O)CO','O=CC(O)=CC(O)CO'):dict(kind='dehydration (C3-OH)',
   proc="Xylose enolization/dehydration (C5 analogue of glucose step 1). Targeted DFT dual-constrained scan (break C3–O + transfer β-H to the leaving O). Single imaginary −1458 cm⁻¹; loses one H₂O. First step of the agent-built furfural route."),
 K('O=CC(O)=CC(O)CO','O=CC(=O)CC(O)CO'):dict(kind='keto–enol tautomerization',
   proc="Enol → 3-deoxyxylosone. Dry intramolecular 1,3-H shift. Agent path: single-coordinate C–H proton scan located the transfer point; a well-centred midpoint guess (H midway O↔C) gave a clean strong saddle. Single imaginary −2159 cm⁻¹."),
 K('O=CC(=O)CC(O)CO','O=CC(=O)C=CCO'):dict(kind='dehydration (C4-OH)',
   proc="3-deoxyxylosone → unsaturated dicarbonyl. Targeted DFT dual-constrained C–O + β-H scan. Single imaginary −1582 cm⁻¹; loses one H₂O (C5 analogue of glucose step 3)."),
 K('O=CC(=O)C=CCO','O=CC1(O)C=CCO1'):dict(kind='ring closure (hemiketal)',
   proc="Ring closure to the furanic hemiketal: the terminal CH₂OH oxygen attacks the internal carbonyl carbon (5-membered ring) with proton transfer to the forming hemiketal O. DFT dual scan (form C–O ring bond + proton transfer) → OptTS(active-atoms). Single imaginary −399.9 cm⁻¹ (heavy-atom ring-forming mode)."),
 K('O=CC1(O)C=CCO1','O=Cc1ccco1'):dict(kind='aromatizing dehydration',
   proc="Furanic hemiketal → furfural (aromatization). A plain C–OH scan only gave zwitterion/bicyclic artifacts; the constrained DUAL scan (C–O break + the ring β-H via the auto-identified 1,4 coordinate) produced the concerted neutral TS. Single imaginary −935 cm⁻¹; loses the final H₂O, forming the aromatic furan. Final step of the furfural route."),
}
GENERIC_PROC = ("STRICT-validated elementary step (r²SCAN-3c/CPCM water): single-imaginary OptTS + NumFreq and "
                "raw IRC endpoints matching exact neutral reactant/product SMILES. Part of the broader explored "
                "network; not (yet) on a complete route to a named target product.")

# ---- highlighted paths ----
fwd = collections.defaultdict(list)
for e in STRICT: fwd[C(e['reactant'])].append(C(e['product']))
def bfs(start,target):
    start,target=C(start),C(target);prev={start:None};q=collections.deque([start])
    while q:
        x=q.popleft()
        if x==target:break
        for y in fwd.get(x,[]):
            if y not in prev:prev[y]=x;q.append(y)
    if target not in prev:return []
    p=[];cur=target
    while prev[cur] is not None:p.append((prev[cur],cur));cur=prev[cur]
    return list(reversed(p))
START=C('O=CC(O)C(O)C(O)C(O)CO'); HMF=C('O=Cc1ccc(CO)o1'); HAA=C('O=CCO')
XYL=C('O=CC(O)C(O)C(O)CO'); FF=C('O=Cc1ccco1')
hmf_path=bfs(START,HMF); haa_path=bfs(START,HAA); ff_path=bfs(START,FF)
hmf_e=set(hmf_path); haa_e=set(haa_path); ff_e=set(ff_path)
hmf_n={n for e in hmf_path for n in e}; haa_n={n for e in haa_path for n in e}; ff_n={n for e in ff_path for n in e}

def svg(smi,w=230,h=180):
    m=Chem.MolFromSmiles(smi)
    if m is None:return ''
    AllChem.Compute2DCoords(m)
    d=rdMolDraw2D.MolDraw2DSVG(w,h);d.drawOptions().bondLineWidth=2;d.drawOptions().padding=0.1
    rdMolDraw2D.PrepareAndDrawMolecule(d,m);d.FinishDrawing()
    return d.GetDrawingText().replace("<?xml version='1.0' encoding='iso-8859-1'?>",'')
def formula(smi):
    m=Chem.MolFromSmiles(smi)
    return rdMolDescriptors.CalcMolFormula(m) if m else ''

nodes=sorted({C(e['reactant']) for e in STRICT}|{C(e['product']) for e in STRICT})

# role & color
def role(smi):
    if smi==START:return 'start'
    if smi==HMF:return 'hmf'
    if smi==HAA:return 'haa'
    if smi==FF:return 'ff'
    if smi in hmf_n and smi in haa_n:return 'shared'
    if smi in hmf_n:return 'hmfpath'
    if smi in haa_n:return 'haapath'
    if smi in ff_n:return 'ffpath'
    return 'other'
COL={'start':('#a78bfa','#7c3aed'),'xstart':('#f0abfc','#c026d3'),
     'hmf':('#60a5fa','#2563eb'),'haa':('#4ade80','#16a34a'),'ff':('#fb7185','#e11d48'),
     'hmfpath':('#60a5fa','#2563eb'),'haapath':('#4ade80','#16a34a'),'ffpath':('#fb7185','#e11d48'),
     'shared':('#fbbf24','#d97706'),'other':('#94a3b8','#64748b')}
HALO={'start':'#c4b5fd','xstart':'#f5d0fe','hmf':'#93c5fd','haa':'#86efac','ff':'#fecdd3',
      'hmfpath':'#93c5fd','haapath':'#bbf7d0','ffpath':'#fecdd3','shared':'#fde68a','other':None}

# reactions per node
reacts=collections.defaultdict(list)
for e in STRICT:
    reacts[C(e['reactant'])].append(e); reacts[C(e['product'])].append(e)

NODEINFO={}
vis_nodes=[]
for smi in nodes:
    r=role(smi); fill,border=COL[r]; halo=HALO[r]
    hi = r in ('start','xstart','hmf','haa','ff','hmfpath','haapath','ffpath','shared')
    size = 26 if r in ('start','xstart','hmf','haa','ff') else (18 if hi else 14)
    nd=dict(id=smi,shape='dot',size=size,
            color={'background':fill,'border':border,'highlight':{'background':fill,'border':'#fff'}},
            borderWidth=2)
    if halo:
        nd['shadow']={'enabled':True,'color':halo,'size':26 if r in('start','xstart','hmf','haa','ff') else 18,'x':0,'y':0}
    vis_nodes.append(nd)
    e_eh=ENERGY.get(smi)
    NODEINFO[smi]=dict(name=NAMES.get(smi,'(intermediate)'),smiles=smi,formula=formula(smi),
                       role=r,energy=(f"{e_eh:.5f} Eh" if e_eh is not None else "—"),
                       svg=svg(smi),degree=len(reacts[smi]),
                       reactions=[f"{C(x['reactant'])} → {C(x['product'])}"+(f" + {x['coproduct']}" if x.get('coproduct') and x['coproduct'] not in(None,'') else '') for x in reacts[smi]],
                       on_hmf=(smi in hmf_n),on_haa=(smi in haa_n))

EDGEINFO={}
vis_edges=[]
for i,e in enumerate(STRICT):
    r,p=C(e['reactant']),C(e['product'])
    on_h=(r,p) in hmf_e; on_a=(r,p) in haa_e; on_f=(r,p) in ff_e
    if on_h and on_a: base,halo='#d97706','#fde68a'
    elif on_h: base,halo='#2563eb','#93c5fd'
    elif on_a: base,halo='#16a34a','#86efac'
    elif on_f: base,halo='#e11d48','#fecdd3'
    else: base,halo='#475569',None
    w=4 if (on_h or on_a or on_f) else 1.3
    ed=dict(id=f"e{i}",**{'from':r},to=p,arrows={'to':{'enabled':True,'scaleFactor':0.7}},
            width=w,color={'color':base,'highlight':base,'hover':base},
            smooth={'type':'dynamic'})
    if halo: ed['shadow']={'enabled':True,'color':halo,'size':14,'x':0,'y':0}
    vis_edges.append(ed)
    ex=EDGE_EXTRA.get(K(r,p),{})
    co=e.get('coproduct')
    EDGEINFO[f"e{i}"]=dict(reactant=r,product=p,coproduct=(co if co not in(None,'') else None),
        rname=NAMES.get(r,r),pname=NAMES.get(p,p),coname=(NAMES.get(C(co),co) if co and co not in(None,'','O') else ('water' if co=='O' else None)),
        imag=e.get('ts_imag'),barrier=ex.get('bar'),dE=ex.get('dE'),kind=ex.get('kind','elementary step'),
        process=ex.get('proc',GENERIC_PROC),source=e.get('source',''),
        svg_r=NODEINFO[r]['svg'],svg_p=NODEINFO[p]['svg'],
        svg_co=(svg(C(co)) if co and co not in(None,'') else ''),
        route=('HMF & HAA' if (on_h and on_a) else ('HMF route' if on_h else ('HAA route' if on_a else ('furfural route' if on_f else 'explored network')))))

def pstr(path):
    if not path:return '—'
    s=[NODEINFO[path[0][0]]['name']]
    for a,b in path:
        e=EDGEINFO[next(k for k,v in EDGEINFO.items() if v['reactant']==a and v['product']==b)]
        s.append(f" → {NODEINFO[b]['name']}")
    return ''.join(s)

DATA=dict(nodes=vis_nodes,edges=vis_edges,nodeinfo=NODEINFO,edgeinfo=EDGEINFO,
          hmf_path=pstr(hmf_path),haa_path=pstr(haa_path),ff_path=pstr(ff_path),n_strict=len(STRICT))

HTML=r"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Strict QM Reaction Network Explorer — aqueous glucose valorization</title>
<script>__VISLIB__</script>
<style>
 :root{--bg:#0b1220;--panel:#111a2e;--card:#0f1830;--line:#22304d;--text:#e5edf7;--dim:#93a4bf;--acc:#7dd3fc;}
 *{box-sizing:border-box;}
 body{margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;background:var(--bg);color:var(--text);}
 header{padding:.8rem 1.2rem;border-bottom:1px solid var(--line);}
 h1{margin:0;font-size:1.15rem;font-weight:650;}
 .sub{color:var(--dim);font-size:.82rem;margin-top:.25rem;}
 .legend{display:flex;gap:1rem;flex-wrap:wrap;margin-top:.5rem;font-size:.78rem;align-items:center;}
 .chip{display:inline-flex;align-items:center;gap:.35rem;color:var(--dim);}
 .dot{width:14px;height:14px;border-radius:50%;display:inline-block;}
 .halo{box-shadow:0 0 0 3px rgba(255,255,255,.10);}
 #net{width:100%;height:60vh;background:radial-gradient(circle at 50% 40%,#0e1a34,#0a1120);}
 .panel{border-top:1px solid var(--line);background:var(--panel);min-height:30vh;padding:1rem 1.2rem;}
 .empty{color:var(--dim);font-size:.9rem;display:flex;align-items:center;justify-content:center;height:22vh;text-align:center;}
 .detail{display:flex;gap:1.2rem;flex-wrap:wrap;}
 .molcard{background:#fff;border-radius:10px;padding:.4rem;}
 .molcard svg{display:block;}
 .info{flex:1;min-width:280px;}
 .info h2{margin:.1rem 0 .2rem;font-size:1.15rem;}
 .kv{display:grid;grid-template-columns:130px 1fr;gap:.25rem .8rem;font-size:.85rem;margin-top:.5rem;}
 .kv .k{color:var(--dim);}
 .smiles{font-family:monospace;color:var(--acc);word-break:break-all;}
 .tag{display:inline-block;padding:1px 8px;border-radius:10px;font-size:.72rem;font-weight:600;}
 .proc{margin-top:.7rem;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:.7rem .8rem;font-size:.85rem;line-height:1.55;color:#cdd9ec;}
 .proc b{color:var(--text);}
 .rxnrow{display:flex;align-items:center;gap:.6rem;flex-wrap:wrap;}
 .arr{font-size:1.6rem;color:var(--acc);}
 .plus{font-size:1.3rem;color:var(--dim);}
 .routes{font-size:.8rem;color:var(--dim);margin-top:.4rem;}
 .routes code{color:#cbd5e1;background:var(--card);padding:2px 6px;border-radius:4px;}
 .vis-tooltip{position:absolute;background:#fff!important;border:1px solid #cbd5e1!important;border-radius:10px!important;
   padding:6px!important;box-shadow:0 6px 24px rgba(0,0,0,.35)!important;color:#111!important;font-family:monospace!important;}
</style></head><body>
<header>
 <h1>Agent-discovered strict QM reaction network — aqueous glucose valorization</h1>
 <div class="sub">__N__ elementary edges, each validated at r²SCAN-3c / CPCM(water) with a single-imaginary-mode TS and exact neutral-SMILES double-ended IRC matching · drag nodes · hover for structure · click a node or edge for details below</div>
 <div class="legend">
  <span class="chip"><span class="dot" style="background:#7c3aed;"></span>glucose (C6 start)</span>
  <span class="chip"><span class="dot" style="background:#2563eb;"></span>→ HMF</span>
  <span class="chip"><span class="dot" style="background:#16a34a;"></span>→ HAA</span>
  <span class="chip"><span class="dot" style="background:#e11d48;"></span>→ furfural</span>
  <span class="chip"><span class="dot" style="background:#d97706;"></span>shared</span>
  <span class="chip"><span class="dot" style="background:#64748b;"></span>other strict edge</span>
  <span class="chip">highlighted routes carry a bright outer halo</span>
 </div>
 <div class="routes" style="margin-top:.5rem;">
  <b style="color:#60a5fa;">HMF</b>: <code>__HMFP__</code><br>
  <b style="color:#4ade80;">HAA</b>: <code>__HAAP__</code><br>
  <b style="color:#fb7185;">furfural</b>: <code>__FFP__</code>
 </div>
</header>
<div id="net"></div>
<div class="panel" id="panel"><div class="empty">Click a node (molecule) or an edge (reaction) to see details here.</div></div>
<script>
const D=__DATA__;
const nodes=new vis.DataSet(D.nodes), edges=new vis.DataSet(D.edges);
// hover tooltip = molecule svg + smiles (nodes) / barrier (edges)
D.nodes.forEach(n=>{const i=D.nodeinfo[n.id];
  n.title=htmlEl(`<div style="text-align:center"><div style="background:#fff;border-radius:8px;padding:2px">${i.svg}</div>`
    +`<div style="font-family:monospace;font-size:11px;margin-top:3px;color:#111">${i.name}</div>`
    +`<div style="font-family:monospace;font-size:10px;color:#555">${i.smiles}</div></div>`);});
D.edges.forEach(e=>{const i=D.edgeinfo[e.id];
  const bar=(i.barrier!=null?`ΔE‡ ${i.barrier} kcal/mol · `:'')+`imag ${i.imag} cm⁻¹`;
  e.title=htmlEl(`<div style="font-family:monospace;font-size:11px;color:#111">${i.kind}<br>${bar}</div>`);});
function htmlEl(s){const d=document.createElement('div');d.innerHTML=s;return d;}
const net=new vis.Network(document.getElementById('net'),{nodes,edges},{
  layout:{improvedLayout:true},
  physics:{barnesHut:{gravitationalConstant:-11000,springLength:190,springConstant:0.03,avoidOverlap:0.7},stabilization:{iterations:500}},
  nodes:{shadow:false},
  edges:{selectionWidth:1.5,hoverWidth:1.5},
  interaction:{hover:true,tooltipDelay:90,navigationButtons:true,keyboard:true,multiselect:false}
});
const panel=document.getElementById('panel');
function badge(role){const m={start:['#a78bfa','glucose (start)'],xstart:['#f0abfc','xylose (start)'],
 hmf:['#60a5fa','HMF target'],haa:['#4ade80','HAA target'],ff:['#fb7185','furfural target'],
 hmfpath:['#60a5fa','on HMF route'],haapath:['#4ade80','on HAA route'],ffpath:['#fb7185','on furfural route'],
 shared:['#fbbf24','shared route'],other:['#94a3b8','explored']};
 const [c,t]=m[role]||m.other;return `<span class="tag" style="background:${c}22;color:${c};border:1px solid ${c}55">${t}</span>`;}
function showNode(id){const i=D.nodeinfo[id];
 panel.innerHTML=`<div class="detail"><div class="molcard">${i.svg}</div><div class="info">
  <h2>${i.name} ${badge(i.role)}</h2>
  <div class="kv">
   <div class="k">SMILES</div><div class="smiles">${i.smiles}</div>
   <div class="k">Formula</div><div>${i.formula}</div>
   <div class="k">Electronic energy</div><div>${i.energy} <span style="color:var(--dim)">(r²SCAN-3c/CPCM water)</span></div>
   <div class="k">Reactions here</div><div>${i.degree} strict edge(s)</div>
   <div class="k">On target route</div><div>${i.on_hmf?'HMF ':''}${i.on_haa?'HAA':''}${(!i.on_hmf&&!i.on_haa)?'—':''}</div>
  </div>
  <div class="proc"><b>Participating elementary reactions</b><br>${i.reactions.map(x=>'· '+x).join('<br>')}</div>
 </div></div>`;}
function showEdge(id){const i=D.edgeinfo[id];
 panel.innerHTML=`<div class="info" style="min-width:100%">
  <h2>${i.kind} <span class="tag" style="background:#7dd3fc22;color:#7dd3fc;border:1px solid #7dd3fc55">${i.route}</span></h2>
  <div class="rxnrow" style="margin:.6rem 0">
   <div class="molcard">${i.svg_r}</div><div class="arr">→</div>
   <div class="molcard">${i.svg_p}</div>
   ${i.svg_co?'<div class="plus">+</div><div class="molcard">'+i.svg_co+'</div>':''}
  </div>
  <div class="kv">
   <div class="k">Reactant</div><div class="smiles">${i.reactant} <span style="color:var(--dim)">(${i.rname})</span></div>
   <div class="k">Product</div><div class="smiles">${i.product} <span style="color:var(--dim)">(${i.pname})</span></div>
   ${i.coproduct?`<div class="k">Co-product</div><div class="smiles">${i.coproduct} <span style="color:var(--dim)">(${i.coname})</span></div>`:''}
   <div class="k">TS imaginary</div><div>${i.imag} cm⁻¹ (single dominant mode)</div>
   <div class="k">Barrier ΔE‡</div><div>${i.barrier!=null?i.barrier+' kcal/mol':'—'}</div>
   <div class="k">Reaction ΔE</div><div>${i.dE!=null?(i.dE>0?'+':'')+i.dE+' kcal/mol':'—'}</div>
   <div class="k">Method</div><div>r²SCAN-3c / CPCM(water), ORCA — OptTS + NumFreq + IRC</div>
   <div class="k">Source</div><div style="font-size:.75rem;color:var(--dim)">${i.source}</div>
  </div>
  <div class="proc"><b>How the agent found this transition state</b><br>${i.process}</div>
 </div>`;}
net.on('selectNode',p=>{if(p.nodes.length)showNode(p.nodes[0]);});
net.on('selectEdge',p=>{if(p.edges.length&&!p.nodes.length)showEdge(p.edges[0]);});
net.on('deselectNode',()=>{});
</script></body></html>"""
try:
    VISLIB=open('vis-network.min.js').read()
except Exception:
    VISLIB=''
HTML=(HTML.replace('__VISLIB__',VISLIB)
          .replace('__DATA__',json.dumps(DATA))
          .replace('__N__',str(len(STRICT)))
          .replace('__HMFP__',html.escape(DATA['hmf_path']))
          .replace('__HAAP__',html.escape(DATA['haa_path']))
          .replace('__FFP__',html.escape(DATA['ff_path'])))
open(_os.path.join(_CP.GRAPH, 'network_explorer.html'),'w').write(HTML)
print('nodes',len(vis_nodes),'edges',len(vis_edges))
print('HMF:',DATA['hmf_path'])
print('HAA:',DATA['haa_path'])
print('FF :',DATA['ff_path'])
print('wrote network_explorer.html', len(HTML),'bytes')
