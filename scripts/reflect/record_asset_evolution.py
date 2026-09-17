#!/usr/bin/env python3
"""Asset-evolution ledger: open after a change, close later against the graph.

  record_asset_evolution.py open --kind dehydration --failure no_match \\
      --asset .skills/ts-validation-strategy/SKILL.md \\
      --change "脱水扫描改为 C-O + beta-H 双坐标" \\
      --expect "dehydration 的 no_match 占比下降"
  record_asset_evolution.py close --id ae_20260803_1
  record_asset_evolution.py list
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
_d = HERE
while _d != '/' and not os.path.isfile(os.path.join(_d, 'tools', 'chem_paths.py')):
    _d = os.path.dirname(_d)
PKG = _d
sys.path.insert(0, os.path.join(_d, 'tools'))
import chem_paths as CP  # noqa: E402

LEDGER = os.path.join(PKG, 'evidence', 'asset_evolution.jsonl')


def sha256(path):
    try:
        return hashlib.sha256(open(path, 'rb').read()).hexdigest()[:16]
    except Exception:
        return None


def graph_snapshot():
    p = os.path.join(CP.GRAPH, 'reaction_network.json')
    if not os.path.isfile(p):
        return None
    try:
        net = json.load(open(p))
    except Exception:
        return None
    by = (net.get('stats') or {}).get('edges_by_status') or {}
    return {'n_nodes': (net.get('stats') or {}).get('n_nodes'),
            'n_edges': (net.get('stats') or {}).get('n_edges'),
            'n_strict': by.get('STRICT', 0),
            'targets_reachable': net.get('target_reachable_strict_from_glucose')}


def failure_share(kind, failure):
    try:
        r = subprocess.run([sys.executable, os.path.join(HERE, 'failure_digest.py'),
                            '--kind', kind, '--examples', '0'],
                           capture_output=True, text=True, timeout=600)
        d = json.loads(r.stdout)
    except Exception:
        return None
    g = (d.get('by_kind') or {}).get(kind)
    if not g:
        return None
    modes = g.get('failure_modes') or {}
    total = sum(modes.values())
    return {'attempts': g.get('attempts'), 'passed': g.get('passed'),
            'failures': total, 'mode_count': modes.get(failure, 0),
            'mode_share': (modes.get(failure, 0) / total) if total else None}


def read_all():
    if not os.path.isfile(LEDGER):
        return []
    out = []
    for line in open(LEDGER):
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def write_all(rows):
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER, 'w') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)

    o = sub.add_parser('open')
    o.add_argument('--kind', required=True)
    o.add_argument('--failure', required=True)
    o.add_argument('--asset', required=True)
    o.add_argument('--change', required=True)
    o.add_argument('--expect', required=True)
    o.add_argument('--author', default='reflection')

    c = sub.add_parser('close')
    c.add_argument('--id', required=True)
    c.add_argument('--note', default='')

    sub.add_parser('list')
    a = ap.parse_args()
    rows = read_all()

    if a.cmd == 'list':
        for r in rows:
            print(json.dumps(r, ensure_ascii=False))
        return

    if a.cmd == 'open':
        abs_asset = os.path.join(PKG, a.asset)
        if not os.path.isfile(abs_asset):
            sys.exit('资产不存在：%s' % a.asset)
        eid = 'ae_%s_%d' % (time.strftime('%Y%m%d'), len(rows) + 1)
        rec = {'id': eid, 'status': 'open', 'opened_at': time.strftime('%Y-%m-%d %H:%M:%S'),
               'author': a.author,
               'observed': {'kind': a.kind, 'failure_mode': a.failure,
                            'at_open': failure_share(a.kind, a.failure)},
               'asset': {'path': a.asset, 'change': a.change, 'sha256': sha256(abs_asset)},
               'expectation': a.expect, 'graph_at_open': graph_snapshot()}
        rows.append(rec)
        write_all(rows)
        print(json.dumps(rec, ensure_ascii=False, indent=1))
        return

    for r in rows:
        if r.get('id') != a.id:
            continue
        if r.get('status') == 'closed':
            sys.exit('已关闭：%s' % a.id)
        kind, mode = r['observed']['kind'], r['observed']['failure_mode']
        before, after = r['observed'].get('at_open') or {}, failure_share(kind, mode)
        d_share = None
        if before.get('mode_share') is not None and (after or {}).get('mode_share') is not None:
            d_share = after['mode_share'] - before['mode_share']
        g0, g1 = r.get('graph_at_open') or {}, graph_snapshot() or {}
        r['status'] = 'closed'
        r['closed_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
        r['note'] = a.note
        r['measured'] = {
            'at_close': after, 'd_mode_share': d_share,
            'd_strict': (g1.get('n_strict') or 0) - (g0.get('n_strict') or 0),
            'd_edges': (g1.get('n_edges') or 0) - (g0.get('n_edges') or 0),
            'asset_sha256_at_close': sha256(os.path.join(PKG, r['asset']['path'])),
            'expectation_met': (None if d_share is None else bool(d_share < 0))}
        write_all(rows)
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return
    sys.exit('找不到条目：%s' % a.id)


if __name__ == '__main__':
    main()
