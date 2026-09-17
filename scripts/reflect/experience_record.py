#!/usr/bin/env python3
"""Write Experience Memory: lessons and skill/tool updates with utility.

  experience_record.py lesson --signature multiple_imaginary --kind dehydration \\
      --hypothesis '软模污染' --action soft_mode_cleanup --edges 'R>>P,R2>>P2'
  experience_record.py open --kind dehydration --failure no_match \\
      --asset .skills/ts-validation-strategy/SKILL.md \\
      --change '...' --expect '...' [--addresses les_...]
  experience_record.py close --id upd_...
  experience_record.py list [--type lesson|update]
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
sys.path.insert(0, HERE)
import chem_paths as CP  # noqa: E402
import graph_views as GV  # noqa: E402

EXP_DIR = os.path.join(PKG, 'evidence', 'experience')
LESSONS = os.path.join(EXP_DIR, 'lessons.jsonl')
UPDATES = os.path.join(EXP_DIR, 'updates.jsonl')


def sha256(path):
    try:
        return hashlib.sha256(open(path, 'rb').read()).hexdigest()[:16]
    except Exception:
        return None


def read_jsonl(path):
    if not os.path.isfile(path):
        return []
    out = []
    for line in open(path):
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def write_jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')


def append_jsonl(path, rec):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'a') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')


def graph_snap():
    p = os.path.join(CP.GRAPH, 'reaction_network.json')
    if not os.path.isfile(p):
        return None
    try:
        return GV.graph_snapshot_buckets(json.load(open(p)))
    except Exception:
        return None


def failure_share(kind, failure):
    try:
        r = subprocess.run(
            [sys.executable, os.path.join(HERE, 'failure_digest.py'),
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


def compute_utility(measured):
    """Map close measurements to a scalar utility in [-1, 1]."""
    if not measured:
        return 0.0
    score = 0.0
    em = measured.get('expectation_met')
    if em is True:
        score += 0.5
    elif em is False:
        score -= 0.5
    ds = measured.get('d_strict') or 0
    if ds > 0:
        score += min(0.5, 0.1 * ds)
    elif ds < 0:
        score -= 0.2
    dms = measured.get('d_mode_share')
    if dms is not None:
        # negative d_mode_share = failure mode shrank = good
        score += max(-0.3, min(0.3, -dms))
    return max(-1.0, min(1.0, score))


def cmd_lesson(a):
    rows = read_jsonl(LESSONS)
    eid = 'les_%s_%d' % (time.strftime('%Y%m%d'), len(rows) + 1)
    edges = [x.strip() for x in (a.edges or '').split(',') if x.strip()]
    now = time.strftime('%Y-%m-%d %H:%M:%S')
    rec = {
        'id': eid,
        'signature': a.signature,
        'kind': a.kind,
        'evidence_edges': edges,
        'hypothesis': a.hypothesis,
        'suggested_action': a.action,
        'utility': 0.0,
        'count': 0,
        'created_at': now,
        'updated_at': now,
        'author': a.author,
    }
    append_jsonl(LESSONS, rec)
    print(json.dumps(rec, ensure_ascii=False, indent=1))


def cmd_open(a):
    abs_asset = os.path.join(PKG, a.asset)
    if not os.path.isfile(abs_asset):
        sys.exit('资产不存在：%s' % a.asset)
    rows = read_jsonl(UPDATES)
    eid = 'upd_%s_%d' % (time.strftime('%Y%m%d'), len(rows) + 1)
    addresses = [x.strip() for x in (a.addresses or '').split(',') if x.strip()]
    rec = {
        'id': eid, 'status': 'open',
        'opened_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'author': a.author,
        'observed': {'kind': a.kind, 'failure_mode': a.failure,
                     'at_open': failure_share(a.kind, a.failure)},
        'asset': {'path': a.asset, 'change': a.change, 'sha256': sha256(abs_asset)},
        'expectation': a.expect,
        'addresses': addresses,
        'utility': None,
        'count': 0,
        'graph_at_open': graph_snap(),
    }
    append_jsonl(UPDATES, rec)
    print(json.dumps(rec, ensure_ascii=False, indent=1))


def cmd_close(a):
    rows = read_jsonl(UPDATES)
    for r in rows:
        if r.get('id') != a.id:
            continue
        if r.get('status') == 'closed':
            sys.exit('已关闭：%s' % a.id)
        kind = r['observed']['kind']
        mode = r['observed']['failure_mode']
        before = r['observed'].get('at_open') or {}
        after = failure_share(kind, mode)
        d_share = None
        if before.get('mode_share') is not None and (after or {}).get('mode_share') is not None:
            d_share = after['mode_share'] - before['mode_share']
        g0, g1 = r.get('graph_at_open') or {}, graph_snap() or {}
        measured = {
            'at_close': after,
            'd_mode_share': d_share,
            'd_strict': (g1.get('n_strict') or 0) - (g0.get('n_strict') or 0),
            'd_edges': (g1.get('n_edges') or 0) - (g0.get('n_edges') or 0),
            'asset_sha256_at_close': sha256(os.path.join(PKG, r['asset']['path'])),
            'expectation_met': (None if d_share is None else bool(d_share < 0)),
        }
        r['status'] = 'closed'
        r['closed_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
        r['note'] = a.note or ''
        r['measured'] = measured
        r['utility'] = compute_utility(measured)
        r['count'] = (r.get('count') or 0) + 1
        # bump utility on addressed lessons
        if r.get('addresses'):
            lessons = read_jsonl(LESSONS)
            changed = False
            for les in lessons:
                if les.get('id') in r['addresses']:
                    les['utility'] = round(
                        0.7 * (les.get('utility') or 0.0) + 0.3 * r['utility'], 4)
                    les['count'] = (les.get('count') or 0) + 1
                    les['updated_at'] = r['closed_at']
                    changed = True
            if changed:
                write_jsonl(LESSONS, lessons)
        write_jsonl(UPDATES, rows)
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return
    sys.exit('找不到条目：%s' % a.id)


def cmd_list(a):
    if a.type in (None, 'lesson'):
        for r in read_jsonl(LESSONS):
            print(json.dumps(r, ensure_ascii=False))
    if a.type in (None, 'update'):
        for r in read_jsonl(UPDATES):
            print(json.dumps(r, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)

    les = sub.add_parser('lesson')
    les.add_argument('--signature', required=True)
    les.add_argument('--kind', required=True)
    les.add_argument('--hypothesis', required=True)
    les.add_argument('--action', required=True, dest='action')
    les.add_argument('--edges', default='')
    les.add_argument('--author', default='reflection')

    o = sub.add_parser('open')
    o.add_argument('--kind', required=True)
    o.add_argument('--failure', required=True)
    o.add_argument('--asset', required=True)
    o.add_argument('--change', required=True)
    o.add_argument('--expect', required=True)
    o.add_argument('--addresses', default='', help='comma-separated lesson ids')
    o.add_argument('--author', default='reflection')

    c = sub.add_parser('close')
    c.add_argument('--id', required=True)
    c.add_argument('--note', default='')

    li = sub.add_parser('list')
    li.add_argument('--type', choices=['lesson', 'update'], default=None)

    a = ap.parse_args()
    if a.cmd == 'lesson':
        cmd_lesson(a)
    elif a.cmd == 'open':
        cmd_open(a)
    elif a.cmd == 'close':
        cmd_close(a)
    else:
        cmd_list(a)


if __name__ == '__main__':
    main()
