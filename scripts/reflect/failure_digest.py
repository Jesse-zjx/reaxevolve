#!/usr/bin/env python3
"""Aggregate what went wrong in the campaign, in terms a mechanism decision can act on.

The per-edge verdict in dispatch_cache.json only says "no_strict", which is not enough to change
anything. The actionable detail is one level down, in the per-run verdict records: the IRC
endpoint match as a four-way flag, and the imaginary-mode list (which for older entries is only
present inside the status string). This joins the two and groups the result by reaction kind, so
the reflection step sees "dehydration fails because both IRC ends fall back to the reactant"
rather than "dehydration failed 57 times".

Records come from graph/verdicts.jsonl (see consolidate_verdicts.py), falling back to the live
strict_cache.json files when the archive has not been written yet.

Runs standalone; the harness tool is a thin wrapper around it.

  failure_digest.py --since 2026-08-01 --kind dehydration
"""
import argparse
import collections
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_d = HERE
while _d != '/' and not os.path.isfile(os.path.join(_d, 'tools', 'chem_paths.py')):
    _d = os.path.dirname(_d)
sys.path.insert(0, os.path.join(_d, 'tools'))
import chem_paths as CP  # noqa: E402

from rdkit import Chem, RDLogger  # noqa: E402
RDLogger.DisableLog('rdApp.*')    # the caches hold a few names and paths where SMILES belong

# A mode this soft is a hindered rotor, not a second reaction coordinate; the screening rule in
# skill strict-pathway-validation tolerates it and only counts -200 cm-1 and below as a
# contaminant. It also wants the reaction mode itself below -300. The deposit bar is stricter;
# this digest is for triage.
CONTAMINANT_CM = -200.0
DOMINANT_CM = -300.0

IMAG_IN_STATUS = re.compile(r'imag modes=\[([^\]]*)\]')


def canon(s):
    if not s:
        return None
    m = Chem.MolFromSmiles(s)
    return Chem.MolToSmiles(m) if m else s


def main_fragment(s):
    """Largest organic fragment, matching how the graph keys an edge with a co-product."""
    if not s:
        return None
    frags = [f for f in s.split('.') if f and f not in ('O', '[H]', '[H][H]', '[OH]', '[H+]')]
    return max(frags, key=len) if frags else s


def load_kind_index():
    """(canonical reactant, canonical main product) -> reaction_kind.

    The graph is the better source: build_reaction_network merges kind across every cache it
    ingests, so it covers edges the dispatcher never touched.
    """
    idx = {}
    for path, reader in ((os.path.join(CP.GRAPH, 'dispatch_cache.json'),
                          lambda d: d.values()),
                         (os.path.join(CP.GRAPH, 'reaction_network.json'),
                          lambda d: d.get('edges', []))):
        if not os.path.isfile(path):
            continue
        try:
            data = json.load(open(path))
        except Exception:
            continue
        for v in reader(data):
            if not isinstance(v, dict):
                continue
            # chem-discovery uses reaction_kind; reaxevolve edges use kind.
            rk = v.get('reaction_kind') or v.get('kind')
            if not rk or rk in ('unknown', '?'):
                continue
            key = (canon(v.get('reactant')), canon(main_fragment(v.get('product'))))
            idx.setdefault(key, rk)
    return idx


def formula_counts(smiles):
    """Element counts including implicit hydrogens, or None if unparseable."""
    m = Chem.MolFromSmiles(smiles or '')
    if not m:
        return None
    c = collections.Counter()
    for at in m.GetAtoms():
        c[at.GetSymbol()] += 1
        c['H'] += at.GetTotalNumHs()
    return c


def infer_kind(reactant, product, coproduct):
    """Fall back to the stoichiometry when the graph has no kind for this edge.

    Roughly half the strict_cache entries predate kind bookkeeping, and leaving them in one
    "unattributed" bucket hides exactly the per-kind pattern the reflection step is looking for.
    The mass balance distinguishes the classes that matter here; it cannot tell a tautomerization
    from a skeletal isomerization, so those stay merged under one honest label.
    """
    r = formula_counts(reactant)
    if r is None:
        return None
    p = formula_counts(product)
    if p is None:
        return None
    total = collections.Counter(p)
    if coproduct:
        c = formula_counts(coproduct)
        if c:
            total.update(c)
    lost = {el: r[el] - total.get(el, 0) for el in set(r) | set(total)}
    lost = {k: v for k, v in lost.items() if v}
    if not lost:
        return 'isomerization_or_tautomerization'
    if lost == {'H': 2, 'O': 1}:
        return 'dehydration'
    if lost == {'H': 2}:
        return 'dehydrogenation'
    # Product carries fewer carbons than the reactant and a co-product exists: a C-C scission.
    if not coproduct and p.get('C', 0) < r.get('C', 0):
        return 'fragmentation'
    return None


def imaginary_modes(entry):
    modes = [x for x in (entry.get('ts_imag_all') or []) if isinstance(x, (int, float))]
    if modes:
        return modes
    # Older entries carry the whole list only inside the status string.
    m = IMAG_IN_STATUS.search(str(entry.get('status') or ''))
    if not m:
        one = entry.get('ts_imag_cm-1')
        return [one] if isinstance(one, (int, float)) else []
    out = []
    for tok in m.group(1).split(','):
        tok = tok.strip()
        if tok:
            try:
                out.append(float(tok))
            except ValueError:
                pass
    return out


def classify(entry):
    """Name the failure so a reader knows which knob it implicates."""
    status = str(entry.get('status') or '')
    if status.startswith('STRICT'):
        return 'ok'
    if status.startswith('TS_FAILED'):
        return 'ts_not_converged'          # OptTS never landed on a saddle; guess or scan problem
    modes = imaginary_modes(entry)
    contaminants = [x for x in modes if x <= CONTAMINANT_CM]
    if len(contaminants) > 1:
        # Report the Hessian problem first: a structure with two real imaginary modes is not a
        # transition state, so its endpoint verdict says nothing about the mechanism.
        return 'multiple_imaginary'
    if modes and not any(x <= DOMINANT_CM for x in modes):
        return 'no_dominant_mode'          # only soft modes: a floppy minimum, not a saddle
    em = entry.get('endpoint_match')
    if not em:
        return 'no_endpoint_record'
    f_r, f_p = bool(em.get('F_isReactant')), bool(em.get('F_isProduct'))
    b_r, b_p = bool(em.get('B_isReactant')), bool(em.get('B_isProduct'))
    if (f_r and b_p) or (f_p and b_r):
        return 'ok'
    if f_r and b_r:
        return 'both_ends_reactant'        # the saddle sits on the wrong side of the barrier
    if f_p and b_p:
        return 'both_ends_product'
    if sum([f_r, f_p, b_r, b_p]) == 1:
        return 'one_end_only'              # half the coordinate is right, the other end wanders
    return 'no_match'                      # the saddle connects a pair nobody asked for


# What each failure mode implicates, so the reflection step starts from a hypothesis rather than
# from raw counts. These are descriptions of the mode, not instructions to apply blindly.
IMPLICATION = {
    'ts_not_converged': 'OptTS 未收敛：猜测几何或扫描坐标问题，不是机理问题',
    'multiple_imaginary': '多个实虚模：需要软模清理（沿模位移后 DEFGRID3 + VeryTightOpt 重优化）',
    'no_dominant_mode': '只有软模：落在柔性极小而非鞍点，猜测未跨过反应坐标',
    'both_ends_reactant': 'IRC 两端都回到反应物：鞍点在目标势垒的错误一侧，扫描坐标选错',
    'both_ends_product': 'IRC 两端都落到产物：同上，方向相反',
    'one_end_only': '一端对、一端跑偏：坐标方向大致正确，另一端需要预组织或更强约束',
    'no_match': '两端都不是目标物种：该鞍点连接的是别的物种对，机理假设可能不成立',
    'no_endpoint_record': '没有 IRC 端点记录：计算未走到 IRC 或记录缺失',
}


def iter_records():
    """Every verdict record, from the frozen archive when it exists.

    graph/verdicts.jsonl is written by consolidate_verdicts.py and is the only copy that travels
    with the package: the per-run strict_cache.json files sit in gitignored ORCA scratch, and part
    of the campaign survives only in a sibling harness tree. Falling back to the live caches keeps
    this usable mid-run, before the archive is refreshed.
    """
    frozen = os.path.join(CP.GRAPH, 'verdicts.jsonl')
    if os.path.isfile(frozen):
        with open(frozen) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rec = json.loads(line)
                    yield rec.get('edge'), rec
        return
    for f in glob.glob(os.path.join(CP.GRAPH, 'strict_caches', '**', 'strict_cache.json'),
                       recursive=True):
        try:
            cache = json.load(open(f))
        except Exception:
            continue
        if not isinstance(cache, dict):
            continue
        for name, e in cache.items():
            if isinstance(e, dict):
                yield name, e


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--since', default=None, help='only entries at or after this date, YYYY-MM-DD')
    ap.add_argument('--kind', default=None, help='restrict to one reaction kind')
    ap.add_argument('--examples', type=int, default=2, help='concrete cases per failure mode')
    a = ap.parse_args()

    kinds = load_kind_index()
    by_kind = collections.defaultdict(lambda: {
        'attempts': 0, 'ok': 0, 'modes': collections.Counter(),
        'attributed_by': collections.Counter(),
        'examples': collections.defaultdict(list)})
    undated = 0

    for name, e in iter_records():
        t = e.get('time') or ''
        if a.since:
            if not t:
                undated += 1
                continue
            if t[:10] < a.since:
                continue
        kind = kinds.get((canon(e.get('reactant')), canon(main_fragment(e.get('product')))))
        attributed_by = 'graph'
        if not kind:
            kind = infer_kind(e.get('reactant'), e.get('product'), e.get('coproduct'))
            attributed_by = 'formula'
        if not kind:
            kind, attributed_by = 'unattributed', 'none'
        if a.kind and kind != a.kind:
            continue
        g = by_kind[kind]
        g['attempts'] += 1
        g['attributed_by'][attributed_by] += 1
        mode = classify(e)
        if mode == 'ok':
            g['ok'] += 1
            continue
        g['modes'][mode] += 1
        if len(g['examples'][mode]) < a.examples:
            g['examples'][mode].append({
                'guess': e.get('name') or name, 'reactant': e.get('reactant'),
                'product': e.get('product'),
                'imaginary_modes': imaginary_modes(e) or None,
                'endpoint_match': e.get('endpoint_match'), 'time': t or None})

    frozen = os.path.join(CP.GRAPH, 'verdicts.jsonl')
    out = {'scope': {'since': a.since, 'kind': a.kind,
                     'source': 'graph/verdicts.jsonl' if os.path.isfile(frozen)
                               else 'live strict_cache.json'},
           'thresholds_cm-1': {'contaminant': CONTAMINANT_CM, 'dominant': DOMINANT_CM},
           'undated_entries_skipped': undated, 'by_kind': {}}
    for kind, g in sorted(by_kind.items(), key=lambda kv: -kv[1]['attempts']):
        dominant = g['modes'].most_common(1)[0][0] if g['modes'] else None
        out['by_kind'][kind] = {
            'attempts': g['attempts'], 'passed': g['ok'],
            'kind_attributed_by': dict(g['attributed_by']),
            'failure_modes': dict(g['modes'].most_common()),
            'dominant_failure': dominant,
            'implication': IMPLICATION.get(dominant),
            'examples': dict(g['examples'])}
    out['totals'] = {'attempts': sum(v['attempts'] for v in out['by_kind'].values()),
                     'passed': sum(v['passed'] for v in out['by_kind'].values())}
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
