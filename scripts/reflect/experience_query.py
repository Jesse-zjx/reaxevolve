#!/usr/bin/env python3
"""Retrieve Experience Memory: lessons + updates (+ legacy asset_evolution).

  experience_query.py
  experience_query.py --signature multiple_imaginary --kind dehydration --limit 8
  experience_query.py --since 2026-07-01
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
_d = HERE
while _d != '/' and not os.path.isfile(os.path.join(_d, 'tools', 'chem_paths.py')):
    _d = os.path.dirname(_d)
PKG = _d

EXP_DIR = os.path.join(PKG, 'evidence', 'experience')
LESSONS = os.path.join(EXP_DIR, 'lessons.jsonl')
UPDATES = os.path.join(EXP_DIR, 'updates.jsonl')
LEGACY = os.path.join(PKG, 'evidence', 'asset_evolution.jsonl')


def read_jsonl(path):
    if not os.path.isfile(path):
        return []
    out = []
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def parse_day(s):
    if not s:
        return None
    return str(s)[:10]


def recency_boost(ts, now_day):
    """0..1 boost for more recent timestamps (YYYY-MM-DD...)."""
    d = parse_day(ts)
    if not d or not now_day:
        return 0.0
    try:
        # crude day difference
        t0 = time.mktime(time.strptime(d, '%Y-%m-%d'))
        t1 = time.mktime(time.strptime(now_day, '%Y-%m-%d'))
        days = max(0.0, (t1 - t0) / 86400.0)
        return max(0.0, 1.0 - days / 90.0)
    except Exception:
        return 0.0


def match_score(rec, signature, kind):
    score = 0.0
    sig = rec.get('signature') or (rec.get('observed') or {}).get('failure_mode')
    k = rec.get('kind') or (rec.get('observed') or {}).get('kind')
    if signature and sig:
        if sig == signature:
            score += 2.0
        elif signature in str(sig) or str(sig) in signature:
            score += 1.0
    if kind and k:
        if k == kind:
            score += 1.5
        elif kind in str(k):
            score += 0.5
    if not signature and not kind:
        score += 0.5
    return score


def score_item(rec, signature, kind, now_day, source):
    base = match_score(rec, signature, kind)
    util = rec.get('utility')
    if util is None and isinstance(rec.get('measured'), dict):
        em = rec['measured'].get('expectation_met')
        util = 0.5 if em is True else (-0.5 if em is False else 0.0)
    if util is None:
        util = 0.0
    ts = rec.get('updated_at') or rec.get('closed_at') or rec.get('opened_at') or rec.get(
        'created_at')
    recency = recency_boost(ts, now_day)
    total = base + 0.8 * float(util) + 0.4 * recency
    return {
        'source': source,
        'score': round(total, 4),
        'match': round(base, 4),
        'utility': util,
        'recency': round(recency, 4),
        'record': rec,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--signature', default=None)
    ap.add_argument('--kind', default=None)
    ap.add_argument('--since', default=None, help='YYYY-MM-DD')
    ap.add_argument('--limit', type=int, default=8)
    ap.add_argument('--type', choices=['lesson', 'update', 'all'], default='all')
    a = ap.parse_args()
    now_day = time.strftime('%Y-%m-%d')
    since = a.since

    items = []
    if a.type in ('lesson', 'all'):
        for r in read_jsonl(LESSONS):
            if since and parse_day(r.get('created_at')) and parse_day(r.get('created_at')) < since:
                continue
            if a.signature or a.kind:
                if match_score(r, a.signature, a.kind) <= 0:
                    continue
            items.append(score_item(r, a.signature, a.kind, now_day, 'lesson'))

    if a.type in ('update', 'all'):
        for r in read_jsonl(UPDATES):
            ts = r.get('closed_at') or r.get('opened_at')
            if since and parse_day(ts) and parse_day(ts) < since:
                continue
            if a.signature or a.kind:
                if match_score(r, a.signature, a.kind) <= 0:
                    continue
            items.append(score_item(r, a.signature, a.kind, now_day, 'update'))
        for r in read_jsonl(LEGACY):
            ts = r.get('closed_at') or r.get('opened_at')
            if since and parse_day(ts) and parse_day(ts) < since:
                continue
            if a.signature or a.kind:
                if match_score(r, a.signature, a.kind) <= 0:
                    continue
            items.append(score_item(r, a.signature, a.kind, now_day, 'legacy_asset_evolution'))

    items.sort(key=lambda x: -x['score'])
    out = {
        'query': {'signature': a.signature, 'kind': a.kind, 'since': since},
        'n': min(len(items), a.limit),
        'n_total_matched': len(items),
        'items': items[:a.limit],
        'stores': {
            'lessons': LESSONS if os.path.isfile(LESSONS) else None,
            'updates': UPDATES if os.path.isfile(UPDATES) else None,
            'legacy': LEGACY if os.path.isfile(LEGACY) else None,
        },
    }
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
