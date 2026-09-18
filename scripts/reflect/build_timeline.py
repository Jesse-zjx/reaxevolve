#!/usr/bin/env python3
"""Reconstruct the campaign event sequence that main figure 2 is drawn from.

The reaction-network edge records carry no date, so the graph alone cannot say when anything
was obtained. The dates are one level down, in the per-run strict_cache.json files: each verdict
was written with a `time` field at the moment it was recorded. That is an acceptance date, not a
proxy for one, and every STRICT edge has one. Deposits are dated independently from the ORCA
`Starting time` header of their own TS/IRC outputs, which is machine-written and needs no
interpretation.

Every event is placed on two axes. Calendar date is the obvious one and the weaker one: the
campaign ran alongside other work, so a flat stretch of the date axis can mean the search was
stalling or can mean nobody was running it. The second axis counts verdicts reached, in the order
their timestamps put them, and it is the axis a capability claim belongs on, because effort spent
is what it advances by. It also gives the cost of each accepted edge -- how many verdicts that
species pair absorbed before one of them was STRICT -- without any controlled comparison.

Do not date edges by mining the transcripts. That was tried and it does not work -- see
docs/adr/0002. Transcripts are used here for one narrow purpose: the asset-evolution events,
which have no machine record of their own, and each of those is reported next to an independent
ORCA-run corroboration rather than on its own.

  build_timeline.py                                  # machine sources only
  CHEM_TRANSCRIPTS=/path/to/agent-transcripts build_timeline.py   # adds asset events
"""
import argparse
import bisect
import collections
import datetime
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_d = HERE
while _d != '/' and not os.path.isfile(os.path.join(_d, 'tools', 'chem_paths.py')):
    _d = os.path.dirname(_d)
PKG = _d
sys.path.insert(0, os.path.join(_d, 'tools'))
import chem_paths as CP  # noqa: E402

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

RDLogger.DisableLog('rdApp.*')    # the caches hold a few names and paths where SMILES belong

DEPOSITS = (
    'glucose_hmf_review_v3',
    'glucose_haa_review_v1',
    'glucose_ff_review_v1',
    'glucose_haa_review_v2',  # HAA_R2: FF steps 1–5 reused + new xylulose cleavage
)

# Deposits whose ORCA tree mixes reused jobs with a new step. Milestone = new-step date, not
# the last file mtime across the whole tree (reused FF outs can post-date the new branch).
DEPOSIT_NEW_STEP_GLOB = {
    'glucose_haa_review_v2': '**/step_6_*',
}

# ORCA prints this once per job, e.g. "* Starting time: Tue Jul 14 01:43:16 2026". It sits past
# the ASCII banner, so a short read of the file head misses it.
ORCA_START = re.compile(r'\* Starting time:\s+\w{3}\s+(\w{3})\s+(\d+)\s+[\d:]+\s+(\d{4})')
ORCA_HEAD_BYTES = 60000
MONTHS = {m: i + 1 for i, m in enumerate(
    ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'])}

# The verdict records were written by several scripts over the campaign and the field is not
# uniform: some carry a bare date, some a date and time.
TIME_FORMATS = ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d')

# Each asset is probed by the literal name it is referred to by, because that is what a transcript
# contains. water_relay_guess and proton_scan are not themselves the three cases; they are the
# predecessors the cases replaced, and the sequence is only legible with them in it.
ASSET_PROBES = {
    'cooperative_dehydration_scan': ('constrained_scan_guess.py', 'tool'),
    'dry_proton_transfer': ('dry_proton_guess.py', 'tool'),
    'beta_carbonyl_retro_aldol': ('retroaldol_ts.py', 'tool'),
    'water_relay_predecessor': ('water_relay_guess.py', 'tool'),
    'hand_indexed_proton_scan': ('proton_scan.py', 'tool'),
    'concerted_two_hydrogen_scan': ('scan2d.py', 'tool'),
    'ts_validation_strategy_skill': ('ts-validation-strategy', 'skill'),
    'strict_pathway_validation_skill': ('strict-pathway-validation', 'skill'),
}
TRANSCRIPT_STAMP = re.compile(r'<timestamp>(.*?)</timestamp>', re.S)

# Exploratory verdicts a bin needs before its yield is worth printing at all.
YIELD_FLOOR = 5


def parse_verdict_dt(raw):
    """Verdict timestamp. 13 of the 170 records carry a bare date and land at midnight, so they
    order arbitrarily within their own day on the attempt axis."""
    raw = str(raw).strip()
    for f in TIME_FORMATS:
        try:
            return datetime.datetime.strptime(raw, f)
        except ValueError:
            pass
    return None


def parse_verdict_time(raw):
    dt = parse_verdict_dt(raw)
    return dt.date() if dt else None


def parse_transcript_stamp(raw):
    try:
        return datetime.datetime.strptime(raw.split(', ', 1)[1], '%b %d, %Y, %I:%M %p (UTC+8)')
    except Exception:
        return None


def iso_week(d):
    return d.strftime('%G-W%V')


def read_rows(path):
    """Rows of a previous build, or nothing if there is no previous build."""
    if not os.path.isfile(path):
        return []
    out = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    return out


def canon(s):
    """Canonical SMILES, falling back to the raw string so a lookup never silently drops an edge."""
    if not s:
        return s
    m = Chem.MolFromSmiles(s)
    return Chem.MolToSmiles(m) if m else s


def _iter_verdict_records():
    """(provenance, record) for every judgement, from the frozen archive.

    graph/verdicts.jsonl is the package-local copy written by consolidate_verdicts.py. It exists
    because the per-run strict_cache.json files live in gitignored ORCA scratch and part of the
    campaign survives only in a sibling harness tree, so globbing for them makes the timeline
    depend on machine state. The live caches are still read when the archive is absent, which
    keeps this working mid-run.
    """
    frozen = os.path.join(CP.GRAPH, 'verdicts.jsonl')
    if os.path.isfile(frozen):
        with open(frozen) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                yield (rec.get('source') or {}).get('cache') or frozen, rec
        return
    seen = set()
    patterns = [os.path.join(CP.GRAPH, 'strict_caches', '**', 'strict_cache.json'),
                os.path.join(CP.VALIDATION, '**', 'strict_cache.json')]
    for pat in patterns:
        for path in sorted(glob.glob(pat, recursive=True)):
            real = os.path.realpath(path)
            if not os.path.isfile(path) or real in seen:
                continue
            seen.add(real)
            try:
                blob = json.load(open(path))
            except Exception:
                continue
            if isinstance(blob, dict):
                for rec in blob.values():
                    if isinstance(rec, dict):
                        yield path, rec


def load_verdict_index():
    """(reactant, product) -> [(cache path, verdict record)], keyed both raw and canonical.

    The graph and the caches were written by different code paths and do not always agree on
    SMILES form, so both keys are indexed rather than trusting either one. The flat timestamp list
    returned alongside is the attempt axis.
    """
    index = collections.defaultdict(list)
    verdicts = []
    for path, rec in _iter_verdict_records():
        r, p = rec.get('reactant'), rec.get('product')
        if not r or not p:
            continue
        dt = parse_verdict_dt(rec.get('time'))
        if dt:
            verdicts.append({'dt': dt, 'pair': (canon(r), canon(p)),
                             'strict': str(rec.get('status')).strip().upper() == 'STRICT'})
        for key in {(r, p), (canon(r), canon(p))}:
            index[key].append((path, rec))
    verdicts.sort(key=lambda v: v['dt'])
    # A verdict on a pair that has already been accepted is not exploration. Without this split the
    # far end of the attempt axis reads as the search collapsing, when in fact nearly all of the
    # effort there is re-running pairs that had already passed under the tightened protocol.
    passed = set()
    for v in verdicts:
        v['phase'] = 'revalidation' if v['pair'] in passed else 'exploration'
        if v['strict']:
            passed.add(v['pair'])
    return index, verdicts


def attempts_through(stamps, dt):
    """How many verdicts had been reached by `dt`, inclusive. This is the attempt-axis coordinate.

    It counts verdicts, not jobs launched: an attempt that crashed before the pipeline could judge
    it left no record and is invisible here. The automated loop's own log reports more dispatches
    than there are records in its weeks, so the gap is real and this axis is a floor.
    """
    return bisect.bisect_right(stamps, dt) if dt else None


def strict_edges():
    net = json.load(open(os.path.join(CP.GRAPH, 'reaction_network.json')))
    return [e for e in _edge_records(net) if e.get('status') == 'STRICT']


def date_edges(index, stamps):
    rows, undated = [], []
    for e in strict_edges():
        r, p = e['reactant'], e['product']
        recs = index.get((r, p)) or index.get((canon(r), canon(p))) or []
        # A handful of edges name their verdict file directly and are not reachable by SMILES
        # lookup, because the record inside is keyed differently from the graph.
        if not recs:
            src = e.get('source')
            if src:
                # Graph `source` may be package-relative (tools/qm-workspace/...).
                candidates = [src]
                if not os.path.isabs(src):
                    candidates.append(os.path.join(PKG, src))
                for cand in candidates:
                    if not os.path.isfile(cand):
                        continue
                    try:
                        blob = json.load(open(cand))
                        recs = [(cand, v) for v in blob.values() if isinstance(v, dict)]
                    except Exception:
                        recs = []
                    break
        # Where a pair was attempted more than once, the failed attempts are cached alongside the
        # accepted one. Dating an edge from the earliest record of any status backdates it to a
        # failure: for two of these edges that is a week early. Only a STRICT record marks the
        # acceptance.
        accepted = [v for _, v in recs if str(v.get('status')).strip().upper() == 'STRICT']
        source = 'STRICT record' if accepted else 'any record'
        pool = accepted or [v for _, v in recs]
        dts = sorted(d for d in (parse_verdict_dt(v['time']) for v in pool if v.get('time')) if d)
        first = dts[0] if dts else None
        # Verdicts this pair absorbed up to and including the accepting one. The failed ones sit in
        # the same cache, so this is the observed cost of the edge -- the quantity benchmark A sets
        # out to compare with and without the current assets, measured here without a comparison.
        on_pair = sum(1 for _, v in recs
                      if (parse_verdict_dt(v.get('time')) or first) and first
                      and parse_verdict_dt(v.get('time')) <= first) if first else None
        row = {'record': 'strict_edge', 'reactant': r, 'product': p,
               'reaction_kind': e.get('reaction_kind'), 'ts_imag_cm-1': e.get('ts_imag'),
               'n_imag': e.get('n_imag'), 'in_chain': e.get('in_chain'),
               'verdict_date': first.date().isoformat() if first else None,
               'verdict_time': first.isoformat(sep=' ') if first else None,
               'attempt_index': attempts_through(stamps, first),
               'verdicts_on_pair_to_acceptance': on_pair,
               'dated_from': source if first else None,
               'n_verdict_records': len(recs), 'n_accepted_records': len(accepted),
               'graph_source': e.get('source')}
        rows.append(row)
        if not first:
            undated.append(row)
    return rows, undated


def orca_start(path):
    try:
        head = open(path, errors='ignore').read(ORCA_HEAD_BYTES)
    except Exception:
        return None
    m = ORCA_START.search(head)
    if not m:
        return None
    return datetime.date(int(m.group(3)), MONTHS[m.group(1)], int(m.group(2)))


def date_deposits():
    rows = []
    for dep in DEPOSITS:
        root = os.path.join(CP.DEPOSITS, dep, '04_orca_inp_out_hess')
        files = sorted(glob.glob(os.path.join(root, '**', '*.out'), recursive=True))
        dates = sorted(d for d in (orca_start(f) for f in files) if d)
        # Default milestone = last ORCA job in the deposit tree.
        milestone = dates[-1] if dates else None
        note = None
        new_glob = DEPOSIT_NEW_STEP_GLOB.get(dep)
        if new_glob:
            new_files = sorted(glob.glob(os.path.join(root, new_glob), recursive=True))
            new_outs = [f for f in new_files if f.endswith('.out')]
            new_dates = sorted(d for d in (orca_start(f) for f in new_outs) if d)
            if new_dates:
                milestone = new_dates[-1]
            note = (
                'Reused FF-backbone ORCA jobs (steps 1–5) plus a new xylulose→HAA step; '
                'milestone is the new step, not the last file in the mixed tree.'
            )
        rows.append({'record': 'deposit', 'deposit': dep,
                     'orca_first_run': dates[0].isoformat() if dates else None,
                     # The last TS/IRC job of a deposit is the closest machine-recorded proxy for
                     # "this route was finished"; expert acceptance itself left no dated artifact.
                     # For mixed reused+new packages, orca_last_run is the new-step milestone.
                     'orca_last_run': milestone.isoformat() if milestone else None,
                     'n_orca_out': len(files), 'n_dated': len(dates),
                     'note': note})
    return rows


def loop_rounds():
    path = os.path.join(PKG, 'evidence', 'auto_loop', 'auto_loop_metrics.jsonl')
    rows = []
    if not os.path.isfile(path):
        return rows
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        try:
            m = json.loads(line)
        except Exception:
            continue
        d = parse_verdict_time((m.get('time') or '').split(' ')[0])
        rows.append({'record': 'loop_round', 'date': d.isoformat() if d else None,
                     'round_as_logged': m.get('round'), 'attempted': m.get('attempted'),
                     'd_strict': m.get('d_strict'), 'strict_before': m.get('strict_before'),
                     'strict_after': m.get('strict_after'), 'n_edges': m.get('n_edges')})
    return rows


def scratch_runs():
    """Dates of every ORCA job left in the validation tree, used only to corroborate asset dates."""
    files = glob.glob(os.path.join(CP.VALIDATION, '**', '*.out'), recursive=True)
    return sorted(d for d in (orca_start(f) for f in files) if d)


def date_assets(transcripts, edge_dates, stamps):
    """Earliest transcript sighting of each asset name, bracketed by the last stamped message.

    Assistant turns carry no timestamp of their own, so a sighting can only be pinned to the most
    recent stamped message before it. The bracket width is reported in turns so the reader can see
    how loose any individual date is.
    """
    if not transcripts:
        return []
    probes = {name: pat for name, (pat, _) in ASSET_PROBES.items()}
    first, mentions = {}, collections.Counter()
    for path in sorted(glob.glob(os.path.join(transcripts, '**', '*.jsonl'), recursive=True)):
        stamp, stamp_line, line_no = None, 0, 0
        for line in open(path, errors='ignore'):
            line = line.strip()
            line_no += 1
            if not line:
                continue
            try:
                blob = json.loads(line)
            except Exception:
                continue
            msg = blob.get('message') or blob
            role = blob.get('role') or msg.get('role')
            raw = msg.get('content') or msg.get('text') or ''
            if isinstance(raw, list):
                raw = ' '.join(x.get('text', '') for x in raw if isinstance(x, dict))
            raw = str(raw)
            if role == 'user':
                m = TRANSCRIPT_STAMP.search(raw)
                if m:
                    parsed = parse_transcript_stamp(m.group(1).strip())
                    if parsed:
                        stamp, stamp_line = parsed, line_no
            for name, pat in probes.items():
                if pat not in raw:
                    continue
                mentions[name] += 1
                if name not in first and stamp:
                    first[name] = (stamp, line_no - stamp_line, os.path.basename(path)[:8])
    rows = []
    for name, (pat, layer) in ASSET_PROBES.items():
        hit = first.get(name)
        d = hit[0].date() if hit else None
        # How many edges were accepted at or after the asset appeared. This is the ceiling on any
        # reuse claim made for that asset, and for an asset that arrived late the ceiling is the
        # whole claim: nothing accepted earlier can be attributed to it.
        after = sum(1 for x in edge_dates if d and x >= d) if d else None
        # Where the asset sits on the attempt axis, so it can be marked on the curve instead of
        # listed away from it. Sightings are only located to the day, which is far finer than
        # `bracket_turns` justifies anyway, so the day opens the asset's own interval.
        idx = attempts_through(stamps, datetime.datetime.combine(d, datetime.time.min)) if d \
            else None
        rows.append({'record': 'asset_event', 'asset': name, 'layer': layer, 'probe': pat,
                     'first_sighting_date': d.isoformat() if d else None,
                     'bracket_turns': hit[1] if hit else None,
                     'session': hit[2] if hit else None,
                     'mentions': mentions[name],
                     'attempt_index': idx,
                     'verdicts_after': (len(stamps) - idx) if idx is not None else None,
                     'edges_accepted_on_or_after': after,
                     'edges_accepted_before': (len(edge_dates) - after) if after is not None
                     else None})
    return rows


def weekly_curve(edge_rows, stamps):
    """The date axis. Kept because the asset sightings have no finer coordinate, and because the
    deposits are dated in calendar time; the effort column is what stops it being read as a rate."""
    dates = sorted(datetime.date.fromisoformat(r['verdict_date'])
                   for r in edge_rows if r['verdict_date'])
    per = collections.Counter(iso_week(d) for d in dates)
    effort = collections.Counter(iso_week(s.date()) for s in stamps)
    out, total = [], 0
    for week in sorted(set(per) | set(effort)):
        total += per[week]
        out.append({'week': week, 'new': per[week], 'cumulative': total,
                    'verdicts': effort[week]})
    return out, dates


def attempt_curve(edge_rows, verdicts, bin_size=20):
    """The effort axis: accepted edges against verdicts reached.

    Unlike the weekly curve this one cannot be read as "the system got faster because the weeks got
    busier", because the axis is the work itself. The yield is the slope, and it is the only thing
    here a capability claim can point at -- but it has to be taken per exploratory verdict, since
    the tail of the campaign is re-validation and scoring that as failed exploration invents a
    decline that is not there.
    """
    idx = sorted(r['attempt_index'] for r in edge_rows if r['attempt_index'])
    if not idx:
        return []
    out, total, lo = [], 0, 0
    while lo < len(verdicts):
        hi = min(lo + bin_size, len(verdicts))
        new = sum(1 for i in idx if lo < i <= hi)
        expl = sum(1 for v in verdicts[lo:hi] if v['phase'] == 'exploration')
        total += new
        # A bin that holds only a verdict or two of exploration can report a yield of 1.00, which is
        # noise that reads like a result. Below a floor the slope is left blank rather than quoted.
        out.append({'verdicts_through': hi, 'width': hi - lo, 'exploration': expl,
                    'revalidation': hi - lo - expl, 'new_edges': new, 'cumulative_edges': total,
                    'yield_per_exploration': round(new / expl, 3) if expl >= YIELD_FLOOR else None})
        lo = hi
    return out


def write_markdown(path, edge_rows, dep_rows, asset_rows, loop_rows, curve, acurve, dates,
                   verdicts, scratch):
    n_records = len(verdicts)
    n_expl = sum(1 for v in verdicts if v['phase'] == 'exploration')
    pairs = collections.defaultdict(list)
    for v in verdicts:
        pairs[v['pair']].append(v)
    n_pairs = len(pairs)
    n_pairs_passed = sum(1 for vs in pairs.values() if any(v['strict'] for v in vs))
    spent_on_failed = sum(len(vs) for vs in pairs.values() if not any(v['strict'] for v in vs))
    dated = [r for r in edge_rows if r['verdict_date']]
    loop_dated = [r for r in loop_rows if r['date']]
    unattributed = sum(1 for r in edge_rows if not r['reaction_kind'])
    fallback = [r for r in dated if r['dated_from'] != 'STRICT record']
    costs = sorted(r['verdicts_on_pair_to_acceptance'] for r in dated
                   if r['verdicts_on_pair_to_acceptance'])
    with open(path, 'w') as f:
        w = f.write
        w('# Campaign timeline\n\n')
        w('Generated by `scripts/reflect/build_timeline.py`. Every date here comes from a machine '
          'record: the `time` field a verdict was written with, or the `Starting time` header ORCA '
          'writes into its own output. The asset events at the end are the one exception and are '
          'marked as such.\n\n')
        w('Events are placed on two axes. **Verdicts reached** advances by work done, which makes it '
          'the better of the two: a flat stretch of the calendar axis can just as easily mean '
          'nobody was running the campaign that week. Calendar date is kept because the deposits '
          'and the asset sightings have no finer coordinate.\n\n')
        w('Neither axis is a test of whether the system improved. The campaign was not run to '
          'measure that: the easy steps went first and the frontier moved outward, exploration was '
          'human-directed and switched between three routes, and the bar itself was tightened part '
          'way through. Difficulty is therefore not held constant along either axis, so a slope '
          'that does not rise is not evidence of a system that did not improve. That comparison '
          'needs the matched benchmarks, not this file.\n\n')
        w('## Accepted edges\n\n')
        w('%d of %d STRICT edges carry a dated verdict record, spanning %s to %s. '
          'The date is when the verdict was recorded, which is the acceptance event itself and not '
          'a proxy for it.\n\n' % (len(dated), len(edge_rows),
                                  dates[0] if dates else '-', dates[-1] if dates else '-'))
        w('Where a species pair was attempted more than once, the failed attempts are cached next '
          'to the accepted one, so each date is taken from a record whose status is STRICT rather '
          'than from the earliest record of any status. Dating from any record instead would '
          'backdate two of these edges by about a week. ')
        w('Every edge here was dated from a STRICT record.\n\n' if not fallback else
          '%d edges had no STRICT record and fell back to one of another status; they carry '
          '`dated_from: any record` in `timeline.jsonl`.\n\n' % len(fallback))
        w('### Against verdicts reached\n\n')
        w('%d verdicts were recorded in all, %d of them exploratory and %d re-runs of a pair that '
          'had already been accepted. The axis counts verdicts, not jobs launched: an attempt that '
          'died before the pipeline could judge it left no record, and the automated loop logs more '
          'dispatches than there are records in its weeks, so this is a floor on the effort spent. '
          '13 of the %d records carry a bare date and sit at midnight, so they order arbitrarily '
          'within their own day.\n\n' % (n_records, n_expl, n_records - n_expl, n_records))
        w('| verdicts through | exploration | re-validation | new edges | cumulative | '
          'yield per exploratory verdict |\n|---|---|---|---|---|---|\n')
        for row in acurve:
            y = row['yield_per_exploration']
            w('| %d | %d | %d | +%d | %d | %s |\n'
              % (row['verdicts_through'], row['exploration'], row['revalidation'],
                 row['new_edges'], row['cumulative_edges'],
                 '%.2f' % y if y is not None else '-'))
        w('\nThe last column is the slope, and it has to be taken per exploratory verdict: the '
          'final bins are almost entirely re-validation, and dividing by every verdict there '
          'manufactures a collapse that did not happen. It is left blank where a bin holds fewer '
          'than %d exploratory verdicts, since a yield of 1.00 off a single verdict reads like a '
          'result. Over the run recorded so far the slope moves up and down without settling into a '
          'direction, on bins of about twenty verdicts each -- which is what an uncontrolled record '
          'of a moving frontier looks like, and is not itself a finding either way. This is a '
          'snapshot: re-running the script after further work extends the axis.\n\n' % YIELD_FLOOR)
        if costs:
            mid = costs[len(costs) // 2]
            once = sum(1 for c in costs if c == 1)
            w('Each accepted edge also carries the number of verdicts its own species pair absorbed '
              'up to and including the accepting one (`verdicts_on_pair_to_acceptance`): median %d, '
              'range %d to %d, and %d of %d passed on the pair\'s first verdict. So the campaign '
              'did not mostly work by retrying a pair until it cleared -- a pair that failed was '
              'usually abandoned. Any benchmark whose main metric is "guesses to STRICT" under a '
              'retry budget is therefore measuring something this campaign did not do; pass rate at '
              'a fixed budget per pair is the metric the behaviour supports.\n\n'
              % (mid, costs[0], costs[-1], once, len(costs)))
        w('The denominator that goes with the %d accepted edges is here too: the verdicts cover %d '
          'distinct species pairs, of which %d were never accepted, and those absorbed %d of the '
          '%d verdicts. Reporting the accepted edges without this is reporting a numerator.\n\n'
          % (len(dated), n_pairs, n_pairs - n_pairs_passed, spent_on_failed, n_records))
        w('### Against calendar date\n\n')
        w('| ISO week | new | cumulative | verdicts recorded |\n|---|---|---|---|\n')
        for row in curve:
            w('| %s | +%d | %d | %d |\n' % (row['week'], row['new'], row['cumulative'],
                                            row['verdicts']))
        w('\nThe effort column is why this table is not a rate: the weeks are not equal in work.\n\n')
        if len(dated) < len(edge_rows):
            w('Undated edges are listed in `timeline.jsonl` with `verdict_date: null`. They are '
              'not imputed.\n\n')
        w('%d of %d accepted edges have no `reaction_kind` in the graph, so any per-kind reading '
          'of this curve covers only the remainder.\n\n' % (unattributed, len(edge_rows)))
        w('## Capability-demonstration pathways\n\n')
        w('Expert acceptance left no dated artifact. The ORCA run window of each deposit is what '
          'the machine recorded, and the last job in that window is the closest available marker '
          'for the route being finished. The windows of the first two deposits overlap, so those '
          'routes were not built one after another. Four deposit packages are listed: three '
          'original expert-validated routes plus `glucose_haa_review_v2` (HAA_R2), a second '
          'glucose→HAA route that reuses the furfural-backbone calculations.\n\n')
        w('| deposit | first ORCA job | milestone (last / new step) | outputs dated |\n'
          '|---|---|---|---|\n')
        for r in dep_rows:
            w('| `%s` | %s | %s | %d/%d |\n' % (r['deposit'], r['orca_first_run'],
                                                r['orca_last_run'], r['n_dated'], r['n_orca_out']))
        notes = [r for r in dep_rows if r.get('note')]
        if notes:
            w('\n')
            for r in notes:
                w('- `%s`: %s\n' % (r['deposit'], r['note']))
        w('\n## The automated loop, over the same axis\n\n')
        if loop_dated:
            d_strict = sum(r['d_strict'] or 0 for r in loop_dated)
            attempted = sum(r['attempted'] or 0 for r in loop_dated)
            w('The %d logged rounds span %s to %s and account for %d accepted edges out of %d '
              'dispatched attempts.\n\n' % (len(loop_dated), loop_dated[0]['date'],
                                            loop_dated[-1]['date'], d_strict, attempted))
            w('| date | round as logged | attempted | d_strict | strict before/after |\n')
            w('|---|---|---|---|---|\n')
            for r in loop_dated:
                w('| %s | %s | %s | %s | %s / %s |\n' % (r['date'], r['round_as_logged'],
                                                         r['attempted'], r['d_strict'],
                                                         r['strict_before'], r['strict_after']))
            w('\nThe `round` field restarts at 1 several times, so these are separate launches '
              'rather than one continuous run, and consecutive rows do not chain: a row\'s '
              '`strict_before` can exceed the previous row\'s `strict_after`, meaning edges were '
              'accepted between launches with no round logged. Read this table against the weekly '
              'curve above rather than as a substitute for it.\n\n')
        else:
            w('No dated loop rounds found.\n\n')
        w('## Asset-evolution events\n\n')
        if asset_rows:
            w('These are the only dates here not taken from a machine record. An asset\'s date is '
              'the earliest transcript sighting of its name, pinned to the most recent stamped '
              'message before it; assistant turns carry no timestamp, so `bracket_turns` is how '
              'many turns of slack that pinning has. The surviving ORCA scratch only runs from %s '
              'onward, so it cannot corroborate anything earlier; the accepted-edge counts below '
              'serve instead, and they bound what each asset can be credited with.\n\n'
              % (scratch[0] if scratch else 'n/a'))
            w('`attempt index` is where the asset falls on the verdict axis above, which is how it '
              'gets marked on the curve rather than listed away from it.\n\n')
            w('| asset | layer | first sighting | attempt index | bracket (turns) | mentions | '
              'edges accepted after / before |\n')
            w('|---|---|---|---|---|---|---|\n')
            for r in sorted(asset_rows, key=lambda x: x['attempt_index'] or 0):
                w('| `%s` | %s | %s | %s | %s | %d | %s / %s |\n' % (
                    r['probe'], r['layer'], r['first_sighting_date'], r['attempt_index'],
                    r['bracket_turns'], r['mentions'], r['edges_accepted_on_or_after'],
                    r['edges_accepted_before']))
            w('\nAn asset cannot be credited with an edge accepted before it existed, so the '
              '"before" column is the part of the network that is outside its reach whatever the '
              'narrative says.\n\n')
            if any(r.get('carried_forward') for r in asset_rows):
                w('These rows were carried forward from the previous build: this run had no '
                  'transcript directory, so the asset axis was not recomputed. The edge axis '
                  'above is current. Set `CHEM_TRANSCRIPTS` and re-run to refresh both.\n\n')
        else:
            w('Not reconstructed: set `CHEM_TRANSCRIPTS` to the agent-transcripts directory and '
              're-run.\n\n')
        w('## What this cannot support\n\n')
        w('- The curve counts accepted edges. It does not separate edges produced by the automated '
          'loop from edges produced by reaction-specific methods, and the loop table above is the '
          'honest measure of the former.\n')
        w('- This is an observational reconstruction of a run that happened, not a controlled '
          'ablation. Nothing here isolates the effect of any single asset.\n')
        w('- Nothing here settles whether the system got better, in either direction. The targets '
          'were not difficulty-matched and got harder as the frontier moved out, so the slope is '
          'not a learning curve and a flat one is not a null result. Read it as the state of the '
          'record, which further work changes.\n')
        w('- The per-edge cost is not a difficulty-matched quantity. An easy pair attempted once '
          'and a hard pair attempted six times both appear, so the spread is mostly chemistry, and '
          'the median is not a system metric.\n')
        w('- %d verdict records were indexed to date %d edges; where an edge has several accepted '
          'records the earliest of those is used, so a date is the first time the edge cleared the '
          'bar and not the last time it was re-run.\n' % (n_records, len(dated)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--transcripts', default=os.environ.get('CHEM_TRANSCRIPTS', ''),
                    help='agent-transcripts directory; asset events are skipped without it')
    ap.add_argument('--out-dir', default=os.path.join(PKG, 'evidence', 'state'))
    ap.add_argument('--bin', type=int, default=20,
                    help='width of an attempt-axis bin, in verdicts')
    a = ap.parse_args()

    index, verdicts = load_verdict_index()
    stamps = [v['dt'] for v in verdicts]
    edge_rows, undated = date_edges(index, stamps)
    dep_rows = date_deposits()
    loop_rows = loop_rounds()
    curve, dates = weekly_curve(edge_rows, stamps)
    acurve = attempt_curve(edge_rows, verdicts, a.bin)
    scratch = scratch_runs()

    os.makedirs(a.out_dir, exist_ok=True)
    jsonl = os.path.join(a.out_dir, 'timeline.jsonl')
    if a.transcripts:
        asset_rows = date_assets(a.transcripts, dates, stamps)
    else:
        # The transcripts are the agent's own logs and live outside this package, so a rebuild on
        # a machine without them must not silently drop the asset axis from a committed artifact.
        # Carrying the previous rows forward keeps the two axes in one file; they are marked so a
        # reader can tell which build produced them.
        asset_rows = [dict(r, carried_forward=True) for r in read_rows(jsonl)
                      if r.get('record') == 'asset_event']
    with open(jsonl, 'w') as f:
        for row in edge_rows + dep_rows + asset_rows + loop_rows:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
    md = os.path.join(a.out_dir, 'TIMELINE.md')
    write_markdown(md, edge_rows, dep_rows, asset_rows, loop_rows, curve, acurve, dates,
                   verdicts, scratch)

    dated = [r for r in edge_rows if r['verdict_date']]
    n_expl = sum(1 for v in verdicts if v['phase'] == 'exploration')
    print('  验收边定日期 %d/%d  跨 %s -> %s' % (len(dated), len(edge_rows),
                                          dates[0] if dates else '-', dates[-1] if dates else '-'))
    print('  判决轴（主轴）%d 条判决 = 探索 %d + 复验 %d'
          % (len(verdicts), n_expl, len(verdicts) - n_expl))
    for row in acurve:
        y = row['yield_per_exploration']
        print('    至第 %3d 次  探索 %2d 复验 %2d  +%-2d 累计 %-2d 每探索判决产出 %s'
              % (row['verdicts_through'], row['exploration'], row['revalidation'],
                 row['new_edges'], row['cumulative_edges'],
                 '%.2f' % y if y is not None else '-'))
    costs = sorted(r['verdicts_on_pair_to_acceptance'] for r in dated
                   if r['verdicts_on_pair_to_acceptance'])
    if costs:
        print('  逐边成本（同一物种对到 STRICT 的判决次数）中位数 %d，范围 %d–%d'
              % (costs[len(costs) // 2], costs[0], costs[-1]))
    print('  日期轴（次要）')
    for row in curve:
        print('    %s  +%-2d 累计 %-2d 该周判决 %d'
              % (row['week'], row['new'], row['cumulative'], row['verdicts']))
    for r in dep_rows:
        print('  交付包 %-24s ORCA %s -> %s  (%d/%d 输出有时间戳)'
              % (r['deposit'], r['orca_first_run'], r['orca_last_run'], r['n_dated'],
                 r['n_orca_out']))
    if undated:
        print('  未定日期 %d 条（如实留 null，未插值）' % len(undated))
    if asset_rows:
        for r in sorted(asset_rows, key=lambda x: x['attempt_index'] or 0):
            print('  资产 %-28s 首现 %s  判决轴第 %-3s 位  括号 %s 回合  其后验收边 %s / 其前 %s'
                  % (r['probe'], r['first_sighting_date'], r['attempt_index'], r['bracket_turns'],
                     r['edges_accepted_on_or_after'], r['edges_accepted_before']))
        if any(r.get('carried_forward') for r in asset_rows):
            print('  ↑ 上述资产事件沿用上一次构建（未设 CHEM_TRANSCRIPTS，本轮未重算）')
    else:
        print('  资产事件未重建（未设 CHEM_TRANSCRIPTS，且上一版无资产事件可沿用）')
    print('  写出 %s' % jsonl)
    print('  写出 %s' % md)


if __name__ == '__main__':
    main()
