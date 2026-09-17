#!/usr/bin/env python3
"""Read Graph Memory: summary, stats, one edge, frontier, or accepted projection.

  graph_query.py --mode summary
  graph_query.py --mode stats --view working
  graph_query.py --mode edge --reactant '...' --product '...'
  graph_query.py --mode frontier --limit 20 --view accepted
  graph_query.py --mode export-accepted --out graph/accepted_network.json
"""
import argparse
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_d = HERE
while _d != '/' and not os.path.isfile(os.path.join(_d, 'tools', 'chem_paths.py')):
    _d = os.path.dirname(_d)
sys.path.insert(0, os.path.join(_d, 'tools'))
sys.path.insert(0, HERE)
import chem_paths as CP  # noqa: E402
import graph_views as GV  # noqa: E402

from rdkit import Chem, RDLogger  # noqa: E402
RDLogger.DisableLog('rdApp.*')


def canon(s):
    if not s:
        return None
    m = Chem.MolFromSmiles(s)
    return Chem.MolToSmiles(m) if m else s


def load():
    p = os.path.join(CP.GRAPH, 'reaction_network.json')
    if not os.path.isfile(p):
        sys.exit('反应网络不存在：%s（先跑 build_reaction_network.py）' % p)
    net = json.load(open(p))
    # genesis stores edges/nodes as dicts; normalize to lists for shared views
    if isinstance(net.get('edges'), dict):
        net['edges'] = list(net['edges'].values())
    if isinstance(net.get('nodes'), dict):
        # keep dict for node_map helpers that expect mapping; also expose list
        net['nodes_list'] = list(net['nodes'].values())
    return net


def dominant_failures(limit=5):
    """Top failure modes from failure_digest (best-effort; empty if digest fails)."""
    try:
        import subprocess
        r = subprocess.run(
            [sys.executable, os.path.join(HERE, 'failure_digest.py'), '--examples', '0'],
            capture_output=True, text=True, timeout=600, cwd=_d)
        d = json.loads(r.stdout)
    except Exception:
        return []
    modes = collections.Counter()
    for g in (d.get('by_kind') or {}).values():
        for m, n in (g.get('failure_modes') or {}).items():
            if m == 'ok':
                continue
            modes[m] += n
    return [{'mode': m, 'count': n} for m, n in modes.most_common(limit)]


def mode_summary(net):
    edges = net.get('edges', [])
    bc = GV.bucket_counts(edges)
    by_kind = collections.Counter(e.get('reaction_kind') or 'unattributed' for e in edges)
    strict_kinds = collections.Counter(
        e.get('reaction_kind') or 'unattributed'
        for e in edges if GV.bucket(e.get('status')) == 'accepted')
    verdicts = os.path.join(CP.GRAPH, 'verdicts.jsonl')
    return {
        'view': 'summary',
        'n_nodes': len(GV.node_map(net)),
        'n_edges': len(edges),
        'buckets': bc,
        'bucket_notes': {
            'unresolved': ('includes provisional QM statuses validated/qm_real; '
                           'see buckets.provisional_qm'),
        },
        'recent_accepted': GV.recent_accepted(net, verdicts, days=14),
        'targets_reachable_strict': net.get('target_reachable_strict_from_glucose'),
        'strict_by_kind': dict(strict_kinds.most_common(12)),
        'kinds_attempted': dict(by_kind.most_common(12)),
        'dominant_failure_signatures': dominant_failures(5),
        'kinds_with_no_strict': sorted(
            k for k, n in by_kind.items()
            if n >= 5 and strict_kinds.get(k, 0) == 0),
    }


def mode_stats(net, view):
    edges = GV.filter_edges(net.get('edges', []), view)
    by_status = collections.Counter(e.get('status') for e in edges)
    by_kind = collections.Counter(e.get('reaction_kind') or 'unattributed' for e in edges)
    strict_kinds = collections.Counter(
        e.get('reaction_kind') or 'unattributed'
        for e in edges if GV.bucket(e.get('status')) == 'accepted')
    return {
        'view': view,
        'n_nodes': len(GV.node_map(net)),
        'n_edges': len(edges),
        'buckets': GV.bucket_counts(net.get('edges', [])),
        'edges_by_status': dict(by_status.most_common()),
        'edges_by_kind': dict(by_kind.most_common()),
        'strict_by_kind': dict(strict_kinds.most_common()),
        'targets_reachable_strict': net.get('target_reachable_strict_from_glucose'),
        'kinds_with_no_strict': sorted(
            k for k, n in by_kind.items()
            if n >= 5 and strict_kinds.get(k, 0) == 0),
    }


def mode_edge(net, reactant, product, view):
    if not reactant:
        sys.exit('--mode edge 需要 --reactant')
    rc, pc = canon(reactant), canon(product)
    edges = GV.filter_edges(net.get('edges', []), view)
    hits = []
    for e in edges:
        if canon(e.get('reactant')) != rc:
            continue
        if pc and canon(e.get('product')) != pc:
            continue
        hits.append({k: e.get(k) for k in
                     ('reactant', 'product', 'coproduct', 'reaction_kind', 'status',
                      'ts_imag', 'n_imag', 'barrier_kcal', 'dE_kcal', 'in_chain',
                      'source')})
        hits[-1]['bucket'] = GV.bucket(e.get('status'))
    return {
        'view': view,
        'query': {'reactant': reactant, 'product': product},
        'n_hits': len(hits),
        'edges': hits,
        'verdict': ('未见记录，可以花 QM' if not hits else
                    'STRICT 已确认' if any(h.get('bucket') == 'accepted' for h in hits) else
                    '已尝试过且未通过，重算前先改方法'),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', default='stats',
                    choices=['summary', 'stats', 'edge', 'frontier', 'export-accepted'])
    ap.add_argument('--view', default='working',
                    choices=['accepted', 'working', 'failures'],
                    help=('投影视图；CLI/运营默认 working（兼容 chem_graph_query）；'
                          '对外讨论请显式传 --view accepted。summary 忽略此参数'))
    ap.add_argument('--reactant', default=None)
    ap.add_argument('--product', default=None)
    ap.add_argument('--limit', type=int, default=20)
    ap.add_argument('--out', default=None,
                    help='export-accepted 时写入的路径（默认 stdout JSON）')
    a = ap.parse_args()
    net = load()

    if a.mode == 'summary':
        out = mode_summary(net)
    elif a.mode == 'stats':
        out = mode_stats(net, a.view)
    elif a.mode == 'edge':
        out = mode_edge(net, a.reactant, a.product, a.view)
    elif a.mode == 'frontier':
        out = GV.frontier(net, a.limit, a.view)
        out['view'] = a.view
    else:
        sub = GV.accepted_subgraph(net)
        if a.out:
            path = a.out if os.path.isabs(a.out) else os.path.join(_d, a.out)
            os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
            with open(path, 'w') as f:
                json.dump(sub, f, ensure_ascii=False, indent=1)
            out = {'written': path, 'stats': sub['stats'],
                   'purity_ok': all(GV.bucket(e.get('status')) == 'accepted'
                                    for e in sub['edges'])}
        else:
            out = sub

    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
