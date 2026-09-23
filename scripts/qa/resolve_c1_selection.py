#!/usr/bin/env python3
"""Resolve the C1 selection rule into a committed file, before any compute.

The rule is in `preregistration/c1_protocol.md`. This applies it mechanically so the mapping from
rule to instances is auditable and cannot drift toward a result: nothing here inspects an outcome in
order to decide what to select. Rerunning it on the same inputs must give the same selection, which
`--check` asserts against the committed file.

Failure modes come from the existing classifier in `scripts/reflect/failure_digest.py`, applied to
the archived verdict records — not from a fresh reading of the `detail` strings. That distinction is
the point: a mode assigned by hand here would be a judgement made with the outcomes visible.

  python scripts/qa/resolve_c1_selection.py            # print what the rule selects
  python scripts/qa/resolve_c1_selection.py --write
  python scripts/qa/resolve_c1_selection.py --check     # committed file still matches the rule
"""
from __future__ import annotations

import argparse
import json
import os
import sys

PKG = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PKG, "scripts", "reflect"))
from failure_digest import classify  # noqa: E402

LEDGER = os.path.join(PKG, "evolution", "EVOLUTION_LOG.jsonl")
ATTEMPTS = os.path.join(PKG, "evolution", "attempt_vectors.jsonl")
# Deliberately not under graph/caches/: the network rebuild globs that tree, so archiving these
# there merged them into the canonical network and took the accepted-edge count from 30 to 44,
# adding 14 edges that never went through the audit which demoted 8. These are per-attempt evidence
# for the evolution ledger, from an isolated campaign — not part of the delivered network — so they
# live beside the attempt stream they explain.
CACHES = os.path.join(PKG, "evolution", "attempt_verdicts")
OUT = os.path.join(PKG, "preregistration", "c1_selection.json")

# Per the protocol: at least this many instances on each side of the activation point, or the mode
# does not qualify and contributes nothing.
PER_SIDE = 2


def jsonl(path):
    return [json.loads(l) for l in open(path) if l.strip()]


def modes_of(rev) -> list[str]:
    v = rev.get("failure_mode") or []
    return v if isinstance(v, list) else [v]


def attempt_verdict(att: dict) -> dict | None:
    """The archived verdict record for an attempt, which carries the classifiable detail.

    The attempt stream records asset versions and ordering but not imaginary modes or endpoint
    flags, so the mode cannot be read off it. The two live in different files because they were
    written by different things.
    """
    src = att.get("source") or {}
    p = src.get("cache") if isinstance(src, dict) else None
    if not p:
        return None
    edge_dir = os.path.basename(os.path.dirname(p))
    cache = os.path.join(CACHES, edge_dir, "strict_cache.json")
    if not os.path.isfile(cache):
        return None
    blob = json.load(open(cache))
    # A cache is keyed by edge; prefer the record whose name matches this attempt.
    for v in blob.values():
        if v.get("name") == att.get("name"):
            return v
    return next(iter(blob.values()), None)


def classified_stream() -> list[dict]:
    """The attempt stream, time-ordered, each attempt carrying its classified failure mode."""
    out = []
    for att in sorted(jsonl(ATTEMPTS), key=lambda r: r.get("time") or ""):
        v = attempt_verdict(att)
        mode = classify(v) if v else None
        detail = (att.get("detail") or "")
        # An attempt the validator crashed on has no outcome: the protocol forbids selecting it as
        # a repair or transfer instance, and it must not count as a failure of any mode.
        void = "DRIVER_NO_VERDICT" in detail
        out.append({
            "name": att.get("name"),
            "edge": att.get("edge"),
            "reactant": att.get("reactant"),
            "product": att.get("product"),
            "coproduct": att.get("coproduct"),
            "time": att.get("time"),
            "status": att.get("status"),
            "mode": None if void else mode,
            "void": void,
            "void_reason": "validator crashed, no verdict" if void else None,
            "has_verdict_record": v is not None,
        })
    return out


def eligible_revisions(revs, stream) -> list[dict]:
    edge_at = {}
    for i, a in enumerate(stream):
        edge_at.setdefault(a["edge"], i)
    out = []
    for r in revs:
        if r.get("class") != "qm_feedback":
            continue
        if not r.get("activation_point") or not r.get("snapshot"):
            continue
        fdu = r.get("first_downstream_use")
        edge = fdu.get("edge") if isinstance(fdu, dict) else None
        if not edge or edge not in edge_at:
            continue
        out.append({**r, "_activation_index": edge_at[edge], "_activation_edge": edge})
    return sorted(out, key=lambda r: r["seq"])


def select() -> dict:
    revs = jsonl(LEDGER)
    stream = classified_stream()
    elig = eligible_revisions(revs, stream)

    # Candidate modes: those any eligible revision targets. Which of them qualify is decided by the
    # instance counts below, not chosen here.
    candidates = sorted({m for r in elig for m in modes_of(r)})

    chosen, rejected = {}, {}
    for mode in candidates:
        revs_for_mode = [r for r in elig if mode in modes_of(r)]
        if not revs_for_mode:
            rejected[mode] = "no eligible revision targets it"
            continue
        rev = revs_for_mode[0]  # lowest seq: the choice cannot follow the result
        idx = rev["_activation_index"]
        before = [a for a in stream[:idx] if a["mode"] == mode and not a["void"]]
        after = [a for a in stream[idx:] if a["mode"] == mode and not a["void"]]
        if len(before) < PER_SIDE or len(after) < PER_SIDE:
            rejected[mode] = (
                f"only {len(before)} instance(s) before and {len(after)} after the activation "
                f"point of seq {rev['seq']}; the rule requires {PER_SIDE} on each side"
            )
            continue
        keep = ("name", "edge", "reactant", "product", "coproduct", "time", "status", "mode")
        chosen[mode] = {
            "revision": {
                "seq": rev["seq"],
                "asset_id": rev["asset_id"],
                "asset_version_before": rev.get("asset_version_before"),
                "asset_version_after": rev.get("asset_version_after"),
                "snapshot": rev.get("snapshot"),
                "activation_point": rev.get("activation_point"),
                "activation_edge": rev["_activation_edge"],
                "activation_index": idx,
                "targets": modes_of(rev),
            },
            # last two before: the instances the digest was summarising
            "repair": [{k: a[k] for k in keep} for a in before[-PER_SIDE:]],
            # first two from activation onward: not yet run when the revision was authored
            "transfer": [{k: a[k] for k in keep} for a in after[:PER_SIDE]],
        }

    return {
        "note": (
            "Resolved from preregistration/c1_protocol.md by scripts/qa/resolve_c1_selection.py. "
            "Do not edit by hand; rerun the resolver. Failure modes come from the classifier in "
            "scripts/reflect/failure_digest.py applied to archived verdict records, not from a "
            "fresh reading of detail strings."
        ),
        "rule": {
            "instances_per_side": PER_SIDE,
            "revision_choice": "lowest seq among eligible, so the choice cannot follow the result",
            "repair": "the last N qualifying attempts before the activation index",
            "transfer": "the first N qualifying attempts from the activation index onward",
            "excluded": "attempts with no verdict (validator crash) are not selectable and do not "
                        "count as failures of any mode",
        },
        "stream": {
            "attempts": len(stream),
            "with_verdict_record": sum(1 for a in stream if a["has_verdict_record"]),
            "void": sum(1 for a in stream if a["void"]),
        },
        "eligible_revisions": len(elig),
        "modes_considered": candidates,
        "modes_selected": sorted(chosen),
        "modes_rejected": rejected,
        "selection": chosen,
        "totals": {
            "instances": sum(len(v["repair"]) + len(v["transfer"]) for v in chosen.values()),
            "runs": 2 * sum(len(v["repair"]) + len(v["transfer"]) for v in chosen.values()),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    sel = select()

    print(f"attempt stream: {sel['stream']['attempts']} attempts, "
          f"{sel['stream']['with_verdict_record']} with a verdict record, "
          f"{sel['stream']['void']} void")
    print(f"eligible revisions: {sel['eligible_revisions']}")
    print(f"modes considered: {', '.join(sel['modes_considered']) or '(none)'}")
    print()
    for mode, blob in sel["selection"].items():
        r = blob["revision"]
        print(f"[{mode}]  revision seq {r['seq']}  {r['asset_id']}  "
              f"{r['asset_version_before']} -> {r['asset_version_after']}")
        print(f"    activation at stream index {r['activation_index']}")
        for kind in ("repair", "transfer"):
            for inst in blob[kind]:
                print(f"    {kind:<9} {str(inst['name'])[:20]:<20} {inst['reactant'][:26]} -> "
                      f"{inst['product'][:26]}")
    if sel["modes_rejected"]:
        print("\nmodes the rule rejected:")
        for mode, why in sel["modes_rejected"].items():
            print(f"  {mode}: {why}")
    print(f"\nselected {sel['totals']['instances']} instance(s) => "
          f"{sel['totals']['runs']} runs across both arms")

    if a.check:
        if not os.path.isfile(OUT):
            print(f"\n{os.path.relpath(OUT, PKG)} does not exist")
            return 1
        committed = json.load(open(OUT))
        if committed.get("selection") != sel["selection"]:
            print("\nCOMMITTED SELECTION DOES NOT MATCH THE RULE")
            return 1
        print("\ncommitted selection matches the rule")
    if a.write:
        json.dump(sel, open(OUT, "w"), indent=2)
        print(f"\n[wrote] {os.path.relpath(OUT, PKG)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
