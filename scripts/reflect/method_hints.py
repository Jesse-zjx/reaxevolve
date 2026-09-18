#!/usr/bin/env python3
"""EMG-lite: aggregate (reaction_kind, guess method name) success vs failure from verdicts.

  method_hints.py
  method_hints.py --kind dehydration --top 8
  method_hints.py --emit-lessons   # print lesson-shaped records (does not write)
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

def _edge_records(net):
    """Edges as a list, whichever container the graph file uses.

    Graph Memory keys edges by id; iterating the dict directly yields its keys, which
    silently produces an empty result rather than an error.
    """
    e = net.get("edges")
    if isinstance(e, dict):
        return [v for v in e.values() if isinstance(v, dict)]
    return [v for v in (e or []) if isinstance(v, dict)]

RDLogger.DisableLog('rdApp.*')


def canon(s):
    if not s:
        return None
    m = Chem.MolFromSmiles(s)
    return Chem.MolToSmiles(m) if m else s


def load_kind_index():
    idx = {}
    p = os.path.join(CP.GRAPH, 'reaction_network.json')
    if not os.path.isfile(p):
        return idx
    try:
        net = json.load(open(p))
    except Exception:
        return idx
    for e in _edge_records(net):
        k = e.get('reaction_kind')
        if not k:
            continue
        key = (canon(e.get('reactant')), canon(e.get('product')))
        idx[key] = k
    return idx


def load_verdicts():
    p = os.path.join(CP.GRAPH, 'verdicts.jsonl')
    if not os.path.isfile(p):
        sys.exit('缺少 %s' % p)
    out = []
    for line in open(p):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def aggregate(verdicts, kind_idx, kind_filter=None):
    """(kind, method) -> {accepted, failed, examples_ok, examples_fail}"""
    stats = {}

    def slot(kind, name):
        key = (kind or 'unattributed', name or 'unknown')
        if key not in stats:
            stats[key] = {'accepted': 0, 'failed': 0,
                          'examples_ok': [], 'examples_fail': []}
        return stats[key]

    for v in verdicts:
        r, p = canon(v.get('reactant')), canon(v.get('product'))
        kind = kind_idx.get((r, p)) or 'unattributed'
        if kind_filter and kind != kind_filter:
            continue
        name = v.get('name') or 'unknown'
        st = v.get('status') or ''
        b = GV.bucket(st)
        edge = v.get('edge') or ('%s>>%s' % (r or '', p or ''))
        s = slot(kind, name)
        if b == 'accepted':
            s['accepted'] += 1
            if len(s['examples_ok']) < 3:
                s['examples_ok'].append(edge)
        else:
            s['failed'] += 1
            if len(s['examples_fail']) < 3:
                s['examples_fail'].append(edge)
    return stats


def hints_for_kind(stats, kind, top=8):
    rows = []
    for (k, name), s in stats.items():
        if k != kind:
            continue
        total = s['accepted'] + s['failed']
        if total == 0:
            continue
        rows.append({
            'kind': k,
            'method': name,
            'accepted': s['accepted'],
            'failed': s['failed'],
            'accept_rate': s['accepted'] / total,
            'examples_ok': s['examples_ok'],
            'examples_fail': s['examples_fail'],
            'hint': ('reuse' if s['accepted'] > 0 and s['accepted'] >= s['failed']
                     else 'avoid_or_cleanup' if s['failed'] >= 2 and s['accepted'] == 0
                     else 'mixed'),
        })
    rows.sort(key=lambda r: (-r['accepted'], -r['failed']))
    return rows[:top]


def emit_lessons(stats):
    """Lesson-shaped dicts derived from strong avoid/reuse signals."""
    lessons = []
    by_kind = collections.defaultdict(list)
    for (k, name), s in stats.items():
        if not name or name in ('unknown', 'None'):
            continue
        if not k or k in ('unattributed', '?'):
            continue
        by_kind[k].append((name, s))
    for kind, items in by_kind.items():
        best = sorted(items, key=lambda x: -x[1]['accepted'])
        worst = sorted(items, key=lambda x: -x[1]['failed'])
        if best and best[0][1]['accepted'] > 0:
            name, s = best[0]
            lessons.append({
                'signature': 'method_reuse',
                'kind': kind,
                'hypothesis': '方法 %s 在 %s 上产出过 STRICT' % (name, kind),
                'suggested_action': 'prefer_method:%s' % name,
                'evidence_edges': list(s['examples_ok']),
                'provenance': 'machine_derived_seed',
                'author': 'method_hints_seed',
                'note': ('Derived by method_hints --emit-lessons; not a '
                         'reflection-authored lesson.'),
            })
        if worst and worst[0][1]['failed'] >= 2 and worst[0][1]['accepted'] == 0:
            name, s = worst[0]
            lessons.append({
                'signature': 'method_avoid',
                'kind': kind,
                'hypothesis': '方法 %s 在 %s 上反复失败且无 STRICT' % (name, kind),
                'suggested_action': 'avoid_or_cleanup:%s' % name,
                'evidence_edges': list(s['examples_fail']),
                'provenance': 'machine_derived_seed',
                'author': 'method_hints_seed',
                'note': ('Derived by method_hints --emit-lessons; not a '
                         'reflection-authored lesson.'),
            })
    return lessons


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--kind', default=None)
    ap.add_argument('--top', type=int, default=8)
    ap.add_argument('--emit-lessons', action='store_true')
    a = ap.parse_args()

    kind_idx = load_kind_index()
    verdicts = load_verdicts()
    stats = aggregate(verdicts, kind_idx, a.kind)

    if a.emit_lessons:
        print(json.dumps(emit_lessons(stats), ensure_ascii=False, indent=1))
        return

    if a.kind:
        out = {'kind': a.kind, 'methods': hints_for_kind(stats, a.kind, a.top)}
    else:
        kinds = sorted({k for k, _ in stats})
        out = {'by_kind': {k: hints_for_kind(stats, k, a.top) for k in kinds}}
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
