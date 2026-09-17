#!/usr/bin/env python3
"""Freeze every QM verdict this package can still reach into one committed file.

The judgements were written per run, into strict_cache.json files that live inside the ORCA
scratch directory of the run that produced them. Those directories are gitignored — one auto_loop
round leaves ~180 MB — and graph/strict_caches/ is a farm of symlinks pointing into them, so a
clone of this package reaches none of the records: failure_digest.py counted 96 attempts where the
campaign recorded ~170, and the remainder existed only in a sibling harness tree. The records
themselves are a few hundred bytes each and are the evidence behind every attempt-axis number in
the paper, so they belong in the package as data rather than as pointers into scratch.

Reads every reachable tree, deduplicates, and writes graph/verdicts.jsonl. Re-running is safe: the
output is sorted and the dedup key is content-derived, so an unchanged campaign gives a byte
identical file. Records already in the frozen file are kept even if their source tree has since
been deleted, which is the point — this is an append-only archive of judgements, not a mirror.

  consolidate_verdicts.py            # refresh from all reachable trees
  consolidate_verdicts.py --dry-run  # report what would change
"""
import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_d = HERE
while _d != '/' and not os.path.isfile(os.path.join(_d, 'tools', 'chem_paths.py')):
    _d = os.path.dirname(_d)
sys.path.insert(0, os.path.join(_d, 'tools'))
import chem_paths as CP  # noqa: E402

OUT = os.path.join(CP.GRAPH, 'verdicts.jsonl')

# Field order in the output, so a re-run diffs cleanly. Anything else a record carries is appended
# after these, sorted; the writers have added fields over the campaign and none may be dropped.
LEAD = ('edge', 'name', 'reactant', 'product', 'coproduct', 'charge', 'status',
        'ts_imag_cm-1', 'ts_imag_all', 'endpoint_match', 'time')


def _extra_roots():
    """Extra read-only trees holding records. Empty by default.

    The upstream campaign shipped defaults under /root/OpenAgentHarness, which agent.md
    lists as a forbidden path here: this repository must never absorb another run's judgements.
    Only an explicit CHEM_EXTRA_STRICT_CACHES (colon-separated) can add roots, and each
    one has to sit inside this package.
    """
    raw = os.environ.get('CHEM_EXTRA_STRICT_CACHES', '').strip()
    if not raw:
        return []
    pkg = os.path.realpath(CP.PACKAGE)
    roots = []
    for p in raw.split(':'):
        if not p or not os.path.isdir(p):
            continue
        if not os.path.realpath(p).startswith(pkg + os.sep):
            print(f'refusing out-of-workspace cache root: {p}', file=sys.stderr)
            continue
        roots.append(p)
    return roots


def source_roots():
    graph_root = getattr(CP, 'GRAPH_ROOT', os.path.dirname(CP.GRAPH.rstrip('/')))
    caches = os.path.join(graph_root, 'caches', 'strict_caches')
    if not os.path.isdir(caches):
        caches = os.path.join(graph_root, 'strict_caches')
    roots = [('graph', caches),
             ('validation', CP.VALIDATION),
             ('runs', getattr(CP, 'RUNS', os.path.join(CP.PACKAGE, 'runs'))),
             ('reaction_network', CP.RN)]
    roots += [('recovered:' + os.path.basename(p.rstrip('/')), p) for p in _extra_roots()]
    return [(label, root) for label, root in roots if os.path.isdir(root)]


def rel(path):
    """Provenance as a package-relative path where possible, absolute for outside trees."""
    real = os.path.realpath(path)
    pkg = os.path.realpath(CP.PACKAGE)
    return os.path.relpath(real, pkg) if real.startswith(pkg + os.sep) else real


def dedup_key(entry, edge):
    """Same judgement seen through two copies of one cache file.

    Keyed on what the run recorded rather than on the whole record: the two trees hold copies
    written by different generations of the validator, and the later one carries extra fields
    (ts_imag_all, note) that the earlier copy of the same judgement lacks. `time` is machine
    written at the moment of the verdict and is present on every record, so a genuine re-run of
    the same guess keeps its own row.
    """
    return (edge, entry.get('name'), entry.get('reactant'), entry.get('product'),
            entry.get('coproduct'), entry.get('time'), str(entry.get('status'))[:60])


def order(rec):
    lead = [(k, rec[k]) for k in LEAD if k in rec]
    rest = [(k, rec[k]) for k in sorted(rec) if k not in LEAD and k != 'source']
    return dict(lead + rest + [('source', rec['source'])])


def collect():
    """key -> record, keeping the richest copy and listing every tree it was found in."""
    found = {}
    per_root = []
    for label, root in source_roots():
        files = sorted(glob.glob(os.path.join(root, '**', 'strict_cache.json'), recursive=True))
        seen_real = set()
        entries = new = 0
        for path in files:
            real = os.path.realpath(path)
            if real in seen_real:          # the symlink farm reaches some files twice
                continue
            seen_real.add(real)
            try:
                blob = json.load(open(path))
            except Exception:
                continue
            if not isinstance(blob, dict):
                continue
            for edge, entry in blob.items():
                if not isinstance(entry, dict):
                    continue
                entries += 1
                key = dedup_key(entry, edge)
                rec = dict(entry)
                rec['edge'] = edge
                prev = found.get(key)
                if prev is None:
                    # Roots are ordered package-first, so the recorded path is the in-package copy
                    # whenever one exists. Listing every tree a record was found in would make the
                    # output depend on which optional trees the machine can reach.
                    where = rel(path)
                    rec['source'] = {'cache': where}
                    if os.path.isabs(where):
                        rec['source']['recovered'] = True
                    found[key] = rec
                    new += 1
                else:
                    # Keep the copy that recorded more: a later validator generation added
                    # ts_imag_all and endpoint_match to records the first one left null.
                    for k, v in entry.items():
                        if v is not None and prev.get(k) is None:
                            prev[k] = v
        per_root.append({'tree': label, 'root': rel(root), 'cache_files': len(seen_real),
                         'entries': entries, 'new_records': new})
    return found, per_root


def load_frozen():
    if not os.path.isfile(OUT):
        return {}
    out = {}
    for line in open(OUT):
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        out[dedup_key(rec, rec.get('edge'))] = rec
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    found, per_root = collect()
    frozen = load_frozen()

    # Records whose source tree is gone stay in the archive; that is what freezing means.
    merged = dict(frozen)
    added = 0
    for key, rec in found.items():
        if key not in merged:
            added += 1
            merged[key] = rec
        else:
            old = merged[key]
            for k, v in rec.items():
                if k == 'source':
                    continue
                if v is not None and old.get(k) is None:
                    old[k] = v
            old['source'] = rec['source']
    orphaned = [k for k in frozen if k not in found]

    rows = [order(r) for _, r in sorted(merged.items(),
                                        key=lambda kv: (str(kv[1].get('time') or ''),
                                                        str(kv[1].get('edge') or ''),
                                                        str(kv[1].get('name') or '')))]
    strict = sum(1 for r in rows if str(r.get('status') or '').startswith('STRICT'))
    undated = sum(1 for r in rows if not r.get('time'))

    for r in per_root:
        print(f"  {r['tree']:28s} files={r['cache_files']:3d} entries={r['entries']:4d} "
              f"new={r['new_records']:4d}")
    print(f"\nrecords: {len(rows)}  (frozen {len(frozen)} + new {added}); STRICT {strict}; "
          f"undated {undated}")
    if orphaned:
        print(f"kept {len(orphaned)} record(s) whose source tree is no longer reachable")

    if a.dry_run:
        print('\n--dry-run: not writing', rel(OUT))
        return
    tmp = OUT + '.tmp'
    with open(tmp, 'w') as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=False) + '\n')
    os.replace(tmp, OUT)
    print('wrote', rel(OUT))


if __name__ == '__main__':
    main()
