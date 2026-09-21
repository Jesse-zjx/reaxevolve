#!/usr/bin/env python3
"""Single source for Graph Memory status buckets and frontier computation.

Vocabulary (post-refactor):
  STRICT       — delivery-grade; only via policy/acceptance STRICT(v5)
  evidence_ok  — QM-backed positive signal, not delivery-grade
  rejected     — scientific negative evidence
  unresolved   — incomplete / throttled / not yet adjudicated

  accepted projection (deposits / publication) = STRICT only
  expansion frontier = STRICT ∪ evidence_ok

Legacy aliases (validated, qm_real, MISMATCH, PARTIAL_MATCH, NOT_CLEAN_TS…) are
mapped in bucket() / is_confirmed_edge() for old graph files.
"""
import collections
import json
import os
import time

# Expansion frontier (Explore working view).
CONFIRMED = frozenset({'STRICT', 'evidence_ok'})

ACCEPTED = frozenset({'STRICT'})

REJECTED = frozenset({
    'rejected', 'MISMATCH', 'PARTIAL_MATCH',
})

# Legacy statuses treated as evidence_ok for frontier seeding.
_EVIDENCE_OK_ALIASES = frozenset({'evidence_ok', 'validated', 'qm_real'})


def bucket(status):
    """Map a raw edge status string to accepted | evidence_ok | rejected | unresolved."""
    s = status or ''
    if s in ACCEPTED or str(s).startswith('STRICT'):
        return 'accepted'
    if s in _EVIDENCE_OK_ALIASES:
        return 'evidence_ok'
    if s in REJECTED or str(s).startswith('rejected'):
        return 'rejected'
    return 'unresolved'


def edges_list(net):
    """Edge records as a list, whichever container the graph file uses.

    Graph Memory stores edges as a dict keyed by edge id; older exports and the
    accepted-subgraph projection use a list. Iterating a dict yields its keys, so
    every consumer must come through here or it silently sees strings.
    """
    e = net.get('edges')
    if isinstance(e, dict):
        return [v for v in e.values() if isinstance(v, dict)]
    if isinstance(e, list):
        return [v for v in e if isinstance(v, dict)]
    return []


def node_map(net):
    n = net.get('nodes') or {}
    if isinstance(n, dict):
        # Graph Memory keys nodes by id; views index by SMILES.
        out = {}
        for k, v in n.items():
            if not isinstance(v, dict):
                continue
            out[v.get('smiles') or k] = v
        return out
    return {r['smiles']: r for r in n if isinstance(r, dict) and r.get('smiles')}


def as_node(s, nodes):
    """Largest fragment when product is stored as 'main.coproduct'."""
    if not s or s in nodes:
        return s
    frags = [f for f in s.split('.') if f]
    return max(frags, key=len) if frags else s


def is_confirmed_edge(edge, confirmed=CONFIRMED):
    """True if the edge seeds the expansion frontier.

    Verdict only. `in_chain` — membership of a delivered route — used to short-circuit this,
    but it is a packaging fact rather than a judgement, so it let an edge seed the frontier
    without a verdict admitting it. The formal definition is
    F = seeds ∪ {v | ∃e ∋ v, verdict(e) ∈ {STRICT, evidence_ok}}, and nothing else.
    """
    st = edge.get('status') or ''
    if st in confirmed:
        return True
    if 'STRICT' in confirmed and str(st).startswith('STRICT'):
        return True
    if 'evidence_ok' in confirmed and st in _EVIDENCE_OK_ALIASES:
        return True
    return False


def filter_edges(edges, view='working'):
    """view: accepted | working | failures."""
    if view == 'accepted':
        return [e for e in edges if bucket(e.get('status')) == 'accepted']
    if view == 'failures':
        return [e for e in edges if bucket(e.get('status')) in ('rejected', 'unresolved')
                and e.get('status') not in ('validated', 'qm_real')]
    return list(edges)


def bucket_counts(edges):
    c = collections.Counter(bucket(e.get('status')) for e in edges)
    provisional = sum(1 for e in edges if e.get('status') in ('validated', 'qm_real'))
    return {
        'accepted': c.get('accepted', 0),
        'rejected': c.get('rejected', 0),
        'unresolved': c.get('unresolved', 0),
        # Subcount inside unresolved: QM-seen but not STRICT (easy to misread).
        'provisional_qm': provisional,
    }


def confirmed_nodes(net, view='working', seeds=None):
    """Species reachable via confirmed edges (+ optional seeds)."""
    edges = edges_list(net)
    nodes = node_map(net)
    confirmed = ACCEPTED if view == 'accepted' else CONFIRMED
    reached = set()
    for s in seeds or []:
        if s:
            reached.add(s)
    for e in edges:
        if not is_confirmed_edge(e, confirmed):
            continue
        reached.add(as_node(e.get('reactant'), nodes))
        reached.add(as_node(e.get('product'), nodes))
    reached.discard(None)
    return reached, confirmed


def frontier(net, limit=20, view='working', seeds=None):
    """Nodes reachable via confirmed edges, ranked least-explored first.

    view=accepted restricts the confirmed set to STRICT only.
    view=working|failures use CONFIRMED = {STRICT, validated, qm_real} (+ in_chain).
    """
    edges = edges_list(net)
    nodes = node_map(net)
    reached, confirmed = confirmed_nodes(net, view=view, seeds=seeds)

    out_deg, confirmed_out = collections.Counter(), collections.Counter()
    for e in edges:
        r = as_node(e.get('reactant'), nodes)
        out_deg[r] += 1
        if is_confirmed_edge(e, confirmed):
            confirmed_out[r] += 1

    rows = []
    for s in reached:
        if not s:
            continue
        n = nodes.get(s) or {}
        rows.append({
            'smiles': s,
            'formula': n.get('formula'),
            'is_target': n.get('is_target'),
            'target_name': n.get('target_name'),
            'edges_tried': out_deg.get(s, 0),
            'edges_confirmed': confirmed_out.get(s, 0),
        })
    rows.sort(key=lambda r: (r['edges_tried'], -(r['edges_confirmed'])))
    return {'n_confirmed_nodes': len(reached), 'frontier': rows[:limit],
            'confirmed_statuses': sorted(confirmed)}


def accepted_subgraph(net):
    """STRICT-only projection for export / paper network views."""
    nodes = node_map(net)
    edges = [e for e in edges_list(net) if bucket(e.get('status')) == 'accepted']
    used = set()
    for e in edges:
        used.add(as_node(e.get('reactant'), nodes))
        used.add(as_node(e.get('product'), nodes))
    used.discard(None)
    out_nodes = {s: nodes[s] for s in used if s in nodes}
    return {
        'nodes': out_nodes,
        'edges': edges,
        'targets': net.get('targets') or (net.get('meta') or {}).get('target_smiles'),
        'targets_reachable_strict': targets_reachable(net),
        'stats': {
            'n_nodes': len(out_nodes),
            'n_edges': len(edges),
            'edges_by_status': {'STRICT': len(edges)},
            'projection': 'accepted',
        },
    }


def graph_snapshot_buckets(net):
    """Compact snapshot used by experience_record close."""
    edges = edges_list(net)
    bc = bucket_counts(edges)
    return {
        'n_nodes': len(node_map(net)),
        'n_edges': len(edges),
        'n_strict': bc['accepted'],
        'n_rejected': bc['rejected'],
        'n_unresolved': bc['unresolved'],
        'n_provisional_qm': bc['provisional_qm'],
        'targets_reachable': targets_reachable(net),
    }


def targets_reachable(net):
    """Per-target STRICT reachability as recorded by the last graph rebuild."""
    meta = net.get('meta') or {}
    out = meta.get('targets_reachable_strict')
    if isinstance(out, dict):
        return out
    legacy = net.get('target_reachable_strict_from_glucose')
    if legacy is None:
        legacy = meta.get('target_reachable_strict_from_glucose')
    return {'any': bool(legacy)} if legacy is not None else {}


def recent_accepted(net, verdicts_path, days=14):
    """Count accepted edges whose earliest STRICT verdict falls in the window.

    Returns {days, count, as_of}. Missing verdicts → count 0 with note.
    """
    as_of = time.strftime('%Y-%m-%d')
    out = {'days': days, 'count': 0, 'as_of': as_of, 'note': None}
    if not verdicts_path or not os.path.isfile(verdicts_path):
        out['note'] = 'verdicts.jsonl missing'
        return out

    earliest = {}
    for line in open(verdicts_path):
        line = line.strip()
        if not line:
            continue
        try:
            v = json.loads(line)
        except Exception:
            continue
        st = str(v.get('status') or '')
        if not (st == 'STRICT' or st.startswith('STRICT')):
            continue
        key = (v.get('reactant'), v.get('product'))
        day = str(v.get('time') or '')[:10]
        if len(day) < 10:
            continue
        prev = earliest.get(key)
        if prev is None or day < prev:
            earliest[key] = day

    # Restrict to edges currently accepted in the graph (projection-consistent).
    accepted_pairs = set()
    nodes = node_map(net)
    for e in edges_list(net):
        if bucket(e.get('status')) != 'accepted':
            continue
        accepted_pairs.add((e.get('reactant'), e.get('product')))

    try:
        t1 = time.mktime(time.strptime(as_of, '%Y-%m-%d'))
    except Exception:
        out['note'] = 'bad as_of'
        return out

    n = 0
    for key, day in earliest.items():
        if key not in accepted_pairs:
            continue
        try:
            t0 = time.mktime(time.strptime(day, '%Y-%m-%d'))
        except Exception:
            continue
        if (t1 - t0) / 86400.0 <= days:
            n += 1
    out['count'] = n
    return out


if __name__ == '__main__':
    # Library module; --help keeps smoke_test subprocess checks quiet.
    import argparse
    ap = argparse.ArgumentParser(
        description='Graph Memory view helpers (import from graph_query / experience_record).')
    ap.parse_args()
    print('graph_views: importable library '
          '(bucket/frontier/accepted_subgraph); use graph_query.py for CLI.')
