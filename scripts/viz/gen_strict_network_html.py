#!/usr/bin/env python3
"""Interactive STRICT reaction-network view: all r2SCAN-3c/CPCM(water) STRICT edges,
with the glucose->HMF and glucose->HAA routes highlighted. Node images are RDKit
2D depictions embedded as data URIs (self-contained); vis-network from CDN."""
import json, base64, collections
from rdkit import Chem
from rdkit.Chem import AllChem
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

NAMES = {
    'O=CC(O)C(O)C(O)C(O)CO': 'open D-glucose',
    'O=C(CO)C(O)C(O)C(O)CO': 'open D-fructose',
    'O=CC(O)CO': 'glyceraldehyde',
    'OC=CO': 'glycolaldehyde enol',
    'O=CCO': 'HAA (glycolaldehyde)',
    'O=Cc1ccc(CO)o1': 'HMF',
    'O=CC(O)=CC(O)C(O)CO': '3-deoxyglucosone enol',
    'O=CC(=O)CC(O)C(O)CO': '3-deoxyglucosone (3-DG)',
    'O=CC(=O)C=CC(O)CO': '3,4-DGE',
    'O=CC1(O)C=CC(CO)O1': 'furanic hemiketal',
    'OC=C(O)CO': 'DHA enol',
    'C=O': 'formaldehyde',
    'OC1CO1': '2-hydroxyoxirane',
}
TARGETS = {'O=Cc1ccc(CO)o1': 'HMF', 'O=CCO': 'HAA'}
START = 'O=CC(O)C(O)C(O)C(O)CO'

def svg_uri(smi, w=150, h=120):
    m = Chem.MolFromSmiles(smi)
    if m is None:
        return None
    AllChem.Compute2DCoords(m)
    d = rdMolDraw2D.MolDraw2DSVG(w, h)
    d.drawOptions().bondLineWidth = 2
    d.drawOptions().padding = 0.08
    rdMolDraw2D.PrepareAndDrawMolecule(d, m)
    d.FinishDrawing()
    svg = d.GetDrawingText()
    return 'data:image/svg+xml;base64,' + base64.b64encode(svg.encode()).decode()

def C(s):
    try: return Chem.CanonSmiles(s)
    except Exception: return s

# directed adjacency for path finding (reactant -> product, forward)
fwd = collections.defaultdict(list)
edge_key = {}
for e in STRICT:
    r, p = C(e['reactant']), C(e['product'])
    fwd[r].append(p)
    edge_key[(r, p)] = e

def bfs_path(start, target):
    start, target = C(start), C(target)
    prev = {start: None}
    q = collections.deque([start])
    while q:
        x = q.popleft()
        if x == target:
            break
        for y in fwd.get(x, []):
            if y not in prev:
                prev[y] = x; q.append(y)
    if target not in prev:
        return []
    path = []; cur = target
    while prev[cur] is not None:
        path.append((prev[cur], cur)); cur = prev[cur]
    return list(reversed(path))

hmf_path = bfs_path(START, 'O=Cc1ccc(CO)o1')
haa_path = bfs_path(START, 'O=CCO')
hmf_edges = set(hmf_path)
haa_edges = set(haa_path)

# collect nodes
nodes = set()
for e in STRICT:
    nodes.add(C(e['reactant'])); nodes.add(C(e['product']))

# vis nodes
vis_nodes = []
for smi in sorted(nodes):
    label = NAMES.get(smi, smi if len(smi) < 22 else smi[:20] + '…')
    on_hmf = any(smi in (a, b) for a, b in hmf_path)
    on_haa = any(smi in (a, b) for a, b in haa_path)
    if smi == START:
        color = '#8250df'; border = '#5a1e9e'
    elif smi in TARGETS:
        color = ('#ddf4ff' if TARGETS[smi] == 'HMF' else '#dafbe1'); border = ('#0969da' if TARGETS[smi] == 'HMF' else '#1a7f37')
    elif on_hmf and on_haa:
        color = '#fff1e5'; border = '#9a6700'
    elif on_hmf:
        color = '#ddf4ff'; border = '#0969da'
    elif on_haa:
        color = '#dafbe1'; border = '#1a7f37'
    else:
        color = '#f6f8fa'; border = '#afb8c1'
    node = dict(id=smi, label=label, shape='image', image=svg_uri(smi) or '',
                title=f"{NAMES.get(smi, '')}<br>{smi}", size=34,
                color={'background': color, 'border': border},
                borderWidth=(4 if (smi == START or smi in TARGETS) else 2),
                font={'size': 15, 'face': 'monospace', 'multi': 'html'})
    vis_nodes.append(node)

# vis edges
vis_edges = []
for e in STRICT:
    r, p = C(e['reactant']), C(e['product'])
    on_hmf = (r, p) in hmf_edges
    on_haa = (r, p) in haa_edges
    if on_hmf and on_haa:
        col = '#9a6700'; wid = 5
    elif on_hmf:
        col = '#0969da'; wid = 5
    elif on_haa:
        col = '#1a7f37'; wid = 5
    else:
        col = '#c8d1da'; wid = 1.5
    co = e.get('coproduct')
    lbl = f"{e.get('ts_imag'):.0f}" if e.get('ts_imag') else ''
    vis_edges.append(dict(**{'from': r}, to=p, arrows='to', width=wid,
                          color={'color': col, 'highlight': col},
                          label=lbl, font={'size': 11, 'color': col, 'strokeWidth': 3, 'strokeColor': '#fff'},
                          smooth={'type': 'dynamic'},
                          title=(f"{e['reactant']} → {e['product']}" + (f" + {co}" if co and co not in (None, '', 'O') else (' + H₂O' if co == 'O' else '')) + f"<br>imag {e.get('ts_imag')} cm⁻¹")))

def path_str(path):
    if not path: return '(none)'
    out = [NAMES.get(path[0][0], path[0][0])]
    for a, b in path:
        e = edge_key[(a, b)]; co = e.get('coproduct')
        cot = (f" +{NAMES.get(C(co), co)}" if co and co not in (None, '', 'O') else (' +H₂O' if co == 'O' else ''))
        out.append(f" —({e.get('ts_imag'):.0f})→ {NAMES.get(b, b)}{cot}")
    return ''.join(out)

HTML = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Strict QM Reaction Network — glucose → HMF & HAA</title>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
 body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;margin:0;background:#fff;color:#24292f;}}
 header{{padding:1rem 1.5rem;border-bottom:1px solid #d0d7de;}}
 h1{{font-size:1.4rem;margin:0 0 .3rem;}}
 .sub{{color:#57606a;font-size:.9rem;}}
 .legend{{display:flex;gap:1.2rem;flex-wrap:wrap;margin:.7rem 0 .2rem;font-size:.82rem;align-items:center;}}
 .chip{{display:inline-flex;align-items:center;gap:.35rem;}}
 .sw{{width:26px;height:5px;border-radius:3px;display:inline-block;}}
 .dot{{width:14px;height:14px;border-radius:50%;display:inline-block;border:2px solid;}}
 #net{{width:100%;height:72vh;border-bottom:1px solid #d0d7de;}}
 .paths{{padding:.8rem 1.5rem;font-size:.85rem;}}
 .paths code{{font-family:monospace;color:#1f2328;background:#f6f8fa;padding:2px 5px;border-radius:4px;}}
 .pill{{font-weight:700;padding:1px 8px;border-radius:10px;font-size:.78rem;}}
</style></head><body>
<header>
 <h1>Agent-discovered strict QM reaction network — aqueous valorization of glucose</h1>
 <div class="sub">All {len(STRICT)} edges are QM-validated at <b>r²SCAN-3c / CPCM(water)</b> with a single-imaginary-mode TS and
 exact neutral-SMILES double-ended IRC matching. Node pictures are RDKit depictions. Two target routes are highlighted.</div>
 <div class="legend">
  <span class="chip"><span class="dot" style="background:#efe3ff;border-color:#5a1e9e;"></span>glucose (start)</span>
  <span class="chip"><span class="sw" style="background:#0969da;"></span><span class="dot" style="background:#ddf4ff;border-color:#0969da;"></span>→ HMF route</span>
  <span class="chip"><span class="sw" style="background:#1a7f37;"></span><span class="dot" style="background:#dafbe1;border-color:#1a7f37;"></span>→ HAA route</span>
  <span class="chip"><span class="sw" style="background:#9a6700;"></span>shared by both</span>
  <span class="chip"><span class="sw" style="background:#c8d1da;"></span>other strict edges</span>
  <span class="sub">edge labels = TS imaginary freq (cm⁻¹)</span>
 </div>
</header>
<div id="net"></div>
<div class="paths">
 <p><span class="pill" style="background:#ddf4ff;color:#0969da;">HMF route (5 steps)</span> &nbsp;<code>{path_str(hmf_path)}</code></p>
 <p style="margin-top:.5rem;"><span class="pill" style="background:#dafbe1;color:#1a7f37;">HAA route (4 steps)</span> &nbsp;<code>{path_str(haa_path)}</code></p>
</div>
<script>
 const nodes = new vis.DataSet({json.dumps(vis_nodes)});
 const edges = new vis.DataSet({json.dumps(vis_edges)});
 const container = document.getElementById('net');
 const data = {{nodes:nodes, edges:edges}};
 const options = {{
   layout:{{improvedLayout:true}},
   physics:{{barnesHut:{{gravitationalConstant:-9000,springLength:180,springConstant:0.03,avoidOverlap:0.6}},stabilization:{{iterations:400}}}},
   nodes:{{shapeProperties:{{useImageSize:false}},borderWidthSelected:5}},
   edges:{{selectionWidth:2}},
   interaction:{{hover:true,tooltipDelay:120,navigationButtons:true,keyboard:true}}
 }};
 new vis.Network(container, data, options);
</script>
</body></html>"""

open(_os.path.join(_CP.GRAPH, 'strict_network_highlighted.html'), 'w').write(HTML)
print("HMF path:", path_str(hmf_path))
print("HAA path:", path_str(haa_path))
print("nodes:", len(vis_nodes), "edges:", len(vis_edges))
print("wrote strict_network_highlighted.html")
