#!/usr/bin/env python3
"""Refresh audited STRICT pin + network state after graph growth.

  repin_state.py              # build + consolidate + timeline + pin + NETWORK_STATE
  repin_state.py --skip-build # reuse current reaction_network.json
  repin_state.py --dry-run    # report delta; write nothing

After auto_loop (or any merge of new STRICT caches), run this so
graph/audited_strict_edges.json, evidence/NETWORK_STATE.*, and the timeline
stay aligned with the live graph. smoke_test then checks pin ≡ graph STRICT
rather than a hard-coded count.
"""
import argparse
import collections
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

PIN = os.path.join(CP.GRAPH, 'audited_strict_edges.json')
NET = os.path.join(CP.GRAPH, 'reaction_network.json')
ACCEPTED = os.path.join(CP.GRAPH, 'accepted_network.json')
STATE_DIR = os.path.join(PKG, 'evidence', 'state')
STATE_JSON = os.path.join(STATE_DIR, 'NETWORK_STATE.json')
STATE_MD = os.path.join(STATE_DIR, 'NETWORK_STATE.md')
TIMELINE = os.path.join(STATE_DIR, 'timeline.jsonl')
BUILD_NETWORK = os.path.join(PKG, 'scripts', 'graph', 'build_reaction_network.py')


def run(cmd, timeout=900):
    r = subprocess.run(cmd, cwd=PKG, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        sys.stderr.write(r.stderr[-800:] or r.stdout[-800:])
        sys.exit('%s failed rc=%d' % (' '.join(cmd), r.returncode))
    return r.stdout


def load_json(path, default=None):
    if not os.path.isfile(path):
        return default
    with open(path) as f:
        return json.load(f)


def edge_records(net):
    """Edges as a list, whichever container the graph file uses.

    Graph Memory keys edges by id; iterating the dict directly would yield its keys.
    """
    e = net.get('edges')
    if isinstance(e, dict):
        return [v for v in e.values() if isinstance(v, dict)]
    return [v for v in (e or []) if isinstance(v, dict)]


def strict_pairs(net):
    out = []
    for e in edge_records(net):
        if e.get('status') == 'STRICT' or str(e.get('status', '')).startswith('STRICT'):
            out.append({
                'reactant': e['reactant'],
                'product': e['product'],
                'reaction_kind': e.get('kind') or e.get('reaction_kind'),
                'source': e.get('source'),
            })
    out.sort(key=lambda x: (x['reactant'], x['product']))
    return out


def pin_pair_set(pin):
    if not pin:
        return set()
    return {(e['reactant'], e['product']) for e in pin.get('edges', [])}


def dated_strict_from_timeline():
    """(reactant, product) -> verdict_date from timeline.jsonl strict_edge rows."""
    out = {}
    if not os.path.isfile(TIMELINE):
        return out
    for line in open(TIMELINE):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get('record') != 'strict_edge':
            continue
        key = (r.get('reactant'), r.get('product'))
        day = r.get('verdict_date') or str(r.get('verdict_time') or '')[:10]
        if key[0] and key[1] and day:
            out[key] = day
    return out


def write_network_state(net, pairs, dated, prev_pairs):
    # Counted from the edge records, never read from a stored summary. A cached
    # `stats.edges_by_status` block once survived a re-adjudication unchanged and reported
    # eight more STRICT edges than the audit had left in place.
    meta = net.get('meta') or {}
    records = edge_records(net)
    by = dict(collections.Counter(e.get('status') or 'unknown' for e in records))
    # The documented four-value vocabulary. Raw statuses are kept beside it because the
    # distinction between, say, `failed` and `NOT_CLEAN_TS` is what Reflect diagnoses on.
    sys.path.insert(0, HERE)
    import graph_views as _GV  # noqa: WPS433
    by_bucket = dict(collections.Counter(_GV.bucket(e.get('status')) for e in records))
    reach = meta.get('targets_reachable_strict') or net.get(
        'target_reachable_strict_from_glucose') or {}
    dist = meta.get('strict_distance_to_targets') or {}
    added = sorted(set((p['reactant'], p['product']) for p in pairs) - prev_pairs)
    removed = sorted(prev_pairs - set((p['reactant'], p['product']) for p in pairs))
    undated = [p for p in pairs if (p['reactant'], p['product']) not in dated]
    state = {
        'generated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'n_nodes': len(net.get('nodes') or {}),
        'n_edges': len(net.get('edges') or []),
        'n_strict': len(pairs),
        'edges_by_status': by,
        'edges_by_bucket': by_bucket,
        'targets_reachable_strict': reach,
        'strict_distance_to_targets': dist,
        'readjudication_applied': meta.get('readjudication_applied') or {},
        'n_strict_dated': len(pairs) - len(undated),
        'n_strict_undated': len(undated),
        'delta_vs_previous_pin': {
            'added': [{'reactant': a, 'product': b} for a, b in added],
            'removed': [{'reactant': a, 'product': b} for a, b in removed],
            'd_strict': len(pairs) - len(prev_pairs),
        },
        'pin_path': 'graph/canonical/audited_strict_edges.json',
        'note': (
            'Single source for prose counts. Prefer this file over HANDOVER/README '
            'literals. Refresh via scripts/reflect/repin_state.py.'
        ),
    }
    os.makedirs(os.path.dirname(STATE_JSON), exist_ok=True)
    with open(STATE_JSON, 'w') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write('\n')

    lines = [
        '# Network state',
        '',
        '> Auto-generated by `scripts/reflect/repin_state.py`. Do not hand-edit.',
        '> Prose docs should cite this file instead of hard-coding counts.',
        '',
        '- Generated: `%s`' % state['generated_at'],
        '- Nodes / edges / STRICT: **%d / %d / %d**' % (
            state['n_nodes'], state['n_edges'], state['n_strict']),
        '- STRICT dated (timeline): **%d / %d**' % (
            state['n_strict_dated'], state['n_strict']),
        '- Pin: `graph/canonical/audited_strict_edges.json`',
        '',
        '## Targets reachable (STRICT from glucose)',
        '',
        '| Target | Reachable | Shortest STRICT chain |',
        '|---|---|---|',
    ]
    for name, ok in sorted(reach.items()):
        d = dist.get(name)
        lines.append('| %s | %s | %s |' % (
            name, 'yes' if ok else 'no', '%d steps' % d if d is not None else '—'))
    lines += [
        '',
        '## Edges by bucket',
        '',
        'The documented vocabulary (`CONTEXT.md`): accepted = STRICT, evidence_ok = QM-backed',
        'but not delivery grade, rejected = scientific negative, unresolved = incomplete.',
        '',
        '| Bucket | Edges |',
        '|---|---|',
    ] + [
        '| %s | %d |' % (k, v) for k, v in sorted(by_bucket.items(), key=lambda kv: -kv[1])
    ] + [
        '',
        '## Edges by raw status',
        '',
        'Driver-level statuses, kept for diagnosis. These are not acceptance categories.',
        '',
        '```json',
        json.dumps(dict(sorted(by.items(), key=lambda kv: -kv[1])), ensure_ascii=False, indent=2),
        '```',
        '',
        '## Delta vs previous pin',
        '',
        '- d_strict: **%+d**' % state['delta_vs_previous_pin']['d_strict'],
        '- added: %d' % len(added),
        '- removed: %d' % len(removed),
        '',
    ]
    if added:
        lines.append('Added pairs:')
        for a, b in added:
            lines.append('- `%s` >> `%s`' % (a, b))
        lines.append('')
    if removed:
        lines.append('Removed pairs:')
        for a, b in removed:
            lines.append('- `%s` >> `%s`' % (a, b))
        lines.append('')
    if undated:
        lines.append('## Undated STRICT (must be zero before smoke)')
        lines.append('')
        for p in undated:
            lines.append('- `%s` >> `%s`' % (p['reactant'], p['product']))
        lines.append('')
    with open(STATE_MD, 'w') as f:
        f.write('\n'.join(lines))
    return state


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--skip-build', action='store_true',
                    help='do not run build_reaction_network.py')
    ap.add_argument('--skip-consolidate', action='store_true')
    ap.add_argument('--skip-timeline', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    prev_pin = load_json(PIN, {})
    prev_pairs = pin_pair_set(prev_pin)

    if not a.skip_build:
        print('== build_reaction_network ==')
        out = run([sys.executable,
                   BUILD_NETWORK])
        for ln in out.splitlines():
            if ln.startswith('nodes ') or ln.startswith('by status') or ln.startswith('targets'):
                print(ln)

    if not a.skip_consolidate:
        print('== consolidate_verdicts ==')
        out = run([sys.executable,
                   os.path.join(HERE, 'consolidate_verdicts.py')])
        for ln in out.splitlines()[-8:]:
            print(ln)

    if not a.skip_timeline:
        print('== build_timeline ==')
        out = run([sys.executable, os.path.join(HERE, 'build_timeline.py')])
        for ln in out.splitlines():
            if '验收边定日期' in ln or '写出' in ln:
                print(ln)

    net = load_json(NET)
    if not net:
        sys.exit('missing %s' % NET)
    pairs = strict_pairs(net)
    cur_pairs = {(p['reactant'], p['product']) for p in pairs}
    dated = dated_strict_from_timeline()
    # after timeline rebuild, re-read
    if not a.skip_timeline and not a.dry_run:
        dated = dated_strict_from_timeline()
    elif a.skip_timeline:
        dated = dated_strict_from_timeline()

    undated = [p for p in pairs if (p['reactant'], p['product']) not in dated]
    added = sorted(cur_pairs - prev_pairs)
    removed = sorted(prev_pairs - cur_pairs)

    report = {
        'n_strict': len(pairs),
        'n_strict_previous_pin': len(prev_pairs),
        'd_strict': len(pairs) - len(prev_pairs),
        'added': [{'reactant': a, 'product': b} for a, b in added],
        'removed': [{'reactant': a, 'product': b} for a, b in removed],
        'n_dated': len(pairs) - len(undated),
        'n_undated': len(undated),
        'undated': undated,
    }
    print('== delta ==')
    print(json.dumps({k: report[k] for k in
                      ('n_strict', 'n_strict_previous_pin', 'd_strict',
                       'n_dated', 'n_undated')},
                     ensure_ascii=False, indent=1))
    if added:
        print('added:', len(added))
        for ra, rb in added[:10]:
            print('  +', ra, '>>', rb)
    if removed:
        print('removed:', len(removed))
    if undated:
        print('WARNING undated STRICT:', len(undated))

    if a.dry_run:
        print('--dry-run: not writing pin / NETWORK_STATE')
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return

    pin = {
        'schema': 'audited_strict_edges/v1',
        'description': (
            'Audited STRICT edge set mirrored from graph/reaction_network.json. '
            'Refresh with scripts/reflect/repin_state.py after expansion.'
        ),
        'n_strict': len(pairs),
        'pinned_at': time.strftime('%Y-%m-%d'),
        'edges': pairs,
    }
    with open(PIN, 'w') as f:
        json.dump(pin, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print('wrote', os.path.relpath(PIN, PKG))

    sys.path.insert(0, HERE)
    import graph_views as GV  # noqa: WPS433
    accepted = GV.accepted_subgraph(net)
    with open(ACCEPTED, 'w') as f:
        json.dump(accepted, f, ensure_ascii=False, indent=1)
        f.write('\n')
    print('wrote', os.path.relpath(ACCEPTED, PKG))

    dated = dated_strict_from_timeline()
    state = write_network_state(net, pairs, dated, prev_pairs)
    print('wrote', os.path.relpath(STATE_JSON, PKG))
    print('wrote', os.path.relpath(STATE_MD, PKG))
    print(json.dumps({
        'n_strict': state['n_strict'],
        'n_nodes': state['n_nodes'],
        'n_edges': state['n_edges'],
        'n_strict_dated': state['n_strict_dated'],
        'd_strict': state['delta_vs_previous_pin']['d_strict'],
    }, ensure_ascii=False, indent=1))
    if state['n_strict_undated']:
        sys.exit('repin incomplete: %d STRICT edges lack timeline dates'
                 % state['n_strict_undated'])


if __name__ == '__main__':
    main()
