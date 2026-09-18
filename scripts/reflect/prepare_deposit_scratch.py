#!/usr/bin/env python3
"""Stage a new deposit under experiments/ (not deposits/) until check_strict_bar passes.

smoke_test walks every directory under deposits/ and fails on incomplete packs.
Assemble new routes here first:

  prepare_deposit_scratch.py --name glucose_xxx_review_v1 --from-edges edge_list.txt
  # edge_list.txt: one "reactant>>product" per line (STRICT edges only)

Then copy ORCA evidence into the scratch tree, run:

  python3 .skills/strict-pathway-validation/scripts/check_strict_bar.py \\
      --deposit experiments/deposit_scratch/<name>

Only after PASS, move/copy into deposits/<name>.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_d = HERE
while _d != '/' and not os.path.isfile(os.path.join(_d, 'tools', 'chem_paths.py')):
    _d = os.path.dirname(_d)
PKG = _d
sys.path.insert(0, os.path.join(_d, 'tools'))
import chem_paths as CP  # noqa: E402


def _edge_records(net):
    """Edges as a list, whichever container the graph file uses.

    Graph Memory keys edges by id; iterating the dict directly yields its keys, which
    silently produces an empty result rather than an error.
    """
    e = net.get("edges")
    if isinstance(e, dict):
        return [v for v in e.values() if isinstance(v, dict)]
    return [v for v in (e or []) if isinstance(v, dict)]

SCRATCH = os.path.join(PKG, 'experiments', 'deposit_scratch')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--name', required=True, help='deposit directory name')
    ap.add_argument('--from-edges', default=None,
                    help='optional text file of reactant>>product lines')
    ap.add_argument('--note', default='')
    a = ap.parse_args()

    dest = os.path.join(SCRATCH, a.name)
    os.makedirs(os.path.join(dest, '01_chain_nodes_xyz'), exist_ok=True)
    os.makedirs(os.path.join(dest, '02_transition_states_xyz'), exist_ok=True)
    os.makedirs(os.path.join(dest, '03_irc_endpoints_xyz'), exist_ok=True)
    os.makedirs(os.path.join(dest, '04_orca_inp_out_hess'), exist_ok=True)
    os.makedirs(os.path.join(dest, '05_docs'), exist_ok=True)

    edges = []
    if a.from_edges and os.path.isfile(a.from_edges):
        for line in open(a.from_edges):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '>>' not in line:
                sys.exit('bad edge line (want R>>P): %s' % line)
            r, p = line.split('>>', 1)
            edges.append({'reactant': r.strip(), 'product': p.strip()})

    # Cross-check against live STRICT set
    net = json.load(open(os.path.join(CP.GRAPH, 'reaction_network.json')))
    strict = {(e['reactant'], e['product']) for e in _edge_records(net)
              if e.get('status') == 'STRICT'}
    missing = [e for e in edges if (e['reactant'], e['product']) not in strict]
    manifest = {
        'name': a.name,
        'status': 'scratch',
        'note': a.note or (
            'Assemble QM evidence here; run check_strict_bar before moving to deposits/.'
        ),
        'edges': edges,
        'n_edges': len(edges),
        'edges_not_yet_strict': missing,
        'check_cmd': (
            'python3 .skills/strict-pathway-validation/scripts/check_strict_bar.py '
            '--deposit experiments/deposit_scratch/%s' % a.name
        ),
    }
    with open(os.path.join(dest, 'SCRATCH_MANIFEST.json'), 'w') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write('\n')
    readme = os.path.join(dest, 'README.txt')
    with open(readme, 'w') as f:
        f.write('SCRATCH deposit — do NOT treat as expert-ready.\n')
        f.write('1. Fill xyz / ORCA evidence mirroring deposits/glucose_*_review_*.\n')
        f.write('2. %s\n' % manifest['check_cmd'])
        f.write('3. On PASS: mv to deposits/%s (or copy) and refresh expert pack.\n' % a.name)
        if missing:
            f.write('\nWARNING: %d listed edges are not STRICT on the live graph yet.\n'
                    % len(missing))
    print(json.dumps({'scratch': os.path.relpath(dest, PKG),
                      'n_edges': len(edges),
                      'n_not_strict': len(missing)},
                     ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
