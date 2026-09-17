#!/usr/bin/env python3
"""Static self-contained PNG of the STRICT reaction network with glucose->HMF and
glucose->HAA routes highlighted."""
import json, collections
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import networkx as nx
from rdkit import Chem

import sys as _sys, os as _os
_d = _os.path.dirname(_os.path.abspath(__file__))
_pkg = _d
while _pkg != '/' and not _os.path.isdir(_os.path.join(_pkg, 'tools')):
    _pkg = _os.path.dirname(_pkg)
_sys.path.insert(0, _os.path.join(_pkg, 'tools'))
_sys.path.insert(0, _os.path.join(_pkg, 'scripts', 'lib'))
import chem_paths as _CP
_CP.bootstrap()

NET = json.load(open(_os.path.join(_CP.GRAPH, 'reaction_network.json')))
STRICT = [e for e in NET['edges'] if e['status'] == 'STRICT']
def C(s):
    try: return Chem.CanonSmiles(s)
    except Exception: return s

NAMES = {
 'O=CC(O)C(O)C(O)C(O)CO':'glucose','O=C(CO)C(O)C(O)C(O)CO':'fructose','O=CC(O)CO':'glyceraldehyde',
 'OC=CO':'GA-enol','O=CCO':'HAA','O=Cc1ccc(CO)o1':'HMF','O=CC(O)=CC(O)C(O)CO':'3-DG-enol',
 'O=CC(=O)CC(O)C(O)CO':'3-DG','O=CC(=O)C=CC(O)CO':'3,4-DGE','O=CC1(O)C=CC(CO)O1':'furanic\nhemiketal',
 'OC=C(O)CO':'DHA-enol','C=O':'HCHO','OC1CO1':'oxiranol',
 'O=CC(O)C(O)C(O)CO':'xylose','O=CC(O)=CC(O)CO':'xylo-enol','O=CC(=O)CC(O)CO':'3-DXO',
 'O=CC(=O)C=CCO':'xylo-diketone','O=CC1(O)C=CCO1':'FF-hemiketal','O=Cc1ccco1':'furfural','OCC(O)=C(O)C(O)C(O)CO':'fru-2,3-enediol','O=C(C(O)CO)C(O)C(O)CO':'3-ketohexose','OC=C(O)C(O)C(O)CO':'C5-enediol'}
START=C('O=CC(O)C(O)C(O)C(O)CO'); HMF=C('O=Cc1ccc(CO)o1'); HAA=C('O=CCO')
XYL=C('O=CC(O)C(O)C(O)CO'); FF=C('O=Cc1ccco1')

G=nx.DiGraph()
for e in STRICT:
    G.add_edge(C(e['reactant']),C(e['product']),imag=e.get('ts_imag'))

def bfs(start,target):
    prev={start:None};q=collections.deque([start])
    while q:
        x=q.popleft()
        if x==target:break
        for y in G.successors(x):
            if y not in prev:prev[y]=x;q.append(y)
    if target not in prev:return []
    p=[];cur=target
    while prev[cur] is not None:p.append((prev[cur],cur));cur=prev[cur]
    return list(reversed(p))
hmf_e=set(bfs(START,HMF)); haa_e=set(bfs(START,HAA)); ff_e=set(bfs(START,FF))
hmf_n={n for e in hmf_e for n in e}; haa_n={n for e in haa_e for n in e}; ff_n={n for e in ff_e for n in e}

pos=nx.spring_layout(G,k=1.9,iterations=600,seed=7)
fig,ax=plt.subplots(figsize=(17,11))

def ncolor(n):
    if n==START:return '#8250df'
    if n==HMF:return '#0969da'
    if n==HAA:return '#1a7f37'
    if n==FF:return '#e11d48'
    if n in hmf_n and n in haa_n:return '#e8a317'
    if n in hmf_n:return '#79c0ff'
    if n in haa_n:return '#7ee2a8'
    if n in ff_n:return '#fb7185'
    return '#d0d7de'
nodecols=[ncolor(n) for n in G.nodes()]
sizes=[1700 if (n in (START,HMF,HAA,FF)) else 1000 for n in G.nodes()]

# edges by class
def eclass(u,v):
    if (u,v) in hmf_e and (u,v) in haa_e:return '#e8a317',3.2
    if (u,v) in hmf_e:return '#0969da',3.2
    if (u,v) in haa_e:return '#1a7f37',3.2
    if (u,v) in ff_e:return '#e11d48',3.2
    return '#c8d1da',1.0
for u,v in G.edges():
    c,w=eclass(u,v)
    nx.draw_networkx_edges(G,pos,edgelist=[(u,v)],edge_color=c,width=w,ax=ax,
        arrows=True,arrowsize=16,arrowstyle='-|>',connectionstyle='arc3,rad=0.06',
        node_size=1400,alpha=0.9)
nx.draw_networkx_nodes(G,pos,node_color=nodecols,node_size=sizes,edgecolors='#57606a',linewidths=1.2,ax=ax)
labels={n:NAMES.get(n,(n[:12]+'…') if len(n)>13 else n) for n in G.nodes()}
nx.draw_networkx_labels(G,pos,labels,font_size=8.5,font_weight='bold',ax=ax)
# edge imag labels for highlighted edges
elabels={(u,v):(f"{d['imag']:.0f}" if d.get('imag') else '') for u,v,d in G.edges(data=True) if (u,v) in hmf_e or (u,v) in haa_e or (u,v) in ff_e}
nx.draw_networkx_edge_labels(G,pos,edge_labels=elabels,font_size=7,ax=ax,
    bbox=dict(boxstyle='round,pad=0.15',fc='white',ec='none',alpha=0.8))

from matplotlib.lines import Line2D
leg=[Line2D([0],[0],color='#8250df',marker='o',ls='',ms=13,label='glucose (C6 start)'),
     Line2D([0],[0],color='#0969da',lw=3,label='→ HMF route (5 steps)'),
     Line2D([0],[0],color='#1a7f37',lw=3,label='→ HAA route (4 steps)'),
     Line2D([0],[0],color='#e11d48',lw=3,label='→ furfural route (11 steps, via C6→C5 bridge)'),
     Line2D([0],[0],color='#e8a317',lw=3,label='shared (HMF+HAA)'),
     Line2D([0],[0],color='#c8d1da',lw=2,label='other STRICT edges')]
ax.legend(handles=leg,loc='upper left',fontsize=10,framealpha=0.95)
ax.set_title('Agent-discovered STRICT QM reaction network (r²SCAN-3c/CPCM water)\n'
             f'{len(STRICT)} single-imaginary-TS + exact-IRC edges · 3 routes from glucose: →HMF, →HAA, →furfural (via C6→C5 retro-aldol bridge) · edge labels = TS imag (cm⁻¹)',
             fontsize=12)
ax.axis('off')
plt.tight_layout()
plt.savefig(_os.path.join(_CP.GRAPH, 'strict_network_highlighted.png'),dpi=130,bbox_inches='tight')
print('wrote strict_network_highlighted.png')
