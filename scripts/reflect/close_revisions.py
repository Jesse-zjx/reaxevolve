#!/usr/bin/env python3
"""Close revision records: fill first_downstream_use and expectation_met from the evidence.

A revision record opened at Reflect time states what it *intended*. Closing it states what
happened, and the two close-time fields are what make the capability claim checkable rather
than narrated:

  first_downstream_use  the first attempt that ran under the revised asset version. Without
                        it, "revise, then reuse" is an assertion; with it, it is a lookup.
  expectation_met       whether the failure mode the revision targeted actually became less
                        frequent afterwards. Allowed to be false, and a ledger in which it is
                        never false is not evidence of anything.

Both are derived, never asserted: `first_downstream_use` comes from the `asset_versions`
vector every attempt records, and `expectation_met` from the rate of the targeted failure
mode before and after that point. Revisions with outcome `rolled_back` are skipped — nothing
ran under them.

  python scripts/reflect/close_revisions.py            # report what would change
  python scripts/reflect/close_revisions.py --apply    # rewrite the ledger in place
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import Counter

PKG = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PKG, "scripts", "lib"))
sys.path.insert(0, os.path.join(PKG, "scripts", "reflect"))
import chem_paths as CP  # noqa: E402

LOG = os.path.join(PKG, "evolution", "EVOLUTION_LOG.jsonl")

# The attempt stream the revisions in EVOLUTION_LOG were measured on: one line per attempt,
# each carrying the asset-version vector in force when it ran. It lives beside the ledger
# rather than under graph/ because it is evolution evidence, not Graph Memory — merging it
# into the network would mix two campaigns' reaction data. See evolution/README.md.
ATTEMPT_VECTORS = os.path.join(PKG, "evolution", "attempt_vectors.jsonl")

# An improvement below this is not distinguishable from noise at these sample sizes; the
# field records `inconclusive` rather than a flattering true.
MIN_AFTER_ATTEMPTS = 5


def load_ledger() -> list[dict]:
    if not os.path.isfile(LOG):
        return []
    return [json.loads(l) for l in open(LOG) if l.strip()]


def attempt_records() -> list[dict]:
    """Attempts carrying an asset-version vector, oldest first.

    Two sources, in this order:
      1. evolution/attempt_vectors.jsonl — the stream the ledger's revisions were measured on
      2. live strict_cache.json files — attempts from runs in this checkout

    Only records with a vector are usable: without one there is no way to say which asset
    version an attempt ran under, which is the whole question. Records from an earlier campaign
    that predates the vector are therefore invisible here, and that is the honest outcome
    rather than a guess.
    """
    out: list[dict] = []
    if os.path.isfile(ATTEMPT_VECTORS):
        for line in open(ATTEMPT_VECTORS):
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            r["_edge"] = r.get("edge") or f"{r.get('reactant')}>>{r.get('product')}"
            r["_cache"] = "evolution/attempt_vectors.jsonl"
            out.append(r)

    patterns = [
        os.path.join(CP.RUNS, "**", "strict_cache.json"),
        os.path.join(CP.GRAPH_ROOT, "caches", "**", "strict_cache.json"),
    ]
    for pat in patterns:
        for path in sorted(glob.glob(pat, recursive=True)):
            try:
                data = json.load(open(path))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            for key, rec in data.items():
                if isinstance(rec, dict):
                    r = dict(rec)
                    r["_edge"] = key
                    r["_cache"] = os.path.relpath(path, PKG)
                    out.append(r)
    return out


def asset_version_of(rec: dict, asset_id: str):
    """Version of one asset as recorded on an attempt, or None if not recorded."""
    vec = rec.get("asset_versions") or {}
    rel = asset_id.strip("./")
    for section in ("skills", "tools"):
        table = vec.get(section)
        if not isinstance(table, dict):
            continue
        for k, v in table.items():
            if rel.endswith(k) or rel.split("/")[-1] == k.split("/")[-1]:
                return str(v)
    flat = vec.get(rel) or vec.get(asset_id)
    return str(flat) if flat is not None else None


def parse_v(v) -> int | None:
    if v is None:
        return None
    s = str(v).strip().lstrip("vV")
    return int(s) if s.isdigit() else None


def failure_mode_of(rec: dict) -> str:
    import failure_digest as FD  # noqa: WPS433

    return FD.classify(rec)


def chemistry_modes() -> set[str]:
    """Modes the attempt classifier can actually emit, from the taxonomy."""
    path = os.path.join(PKG, "policy", "failure_modes.json")
    with open(path) as fh:
        tax = json.load(fh)
    return set((tax.get("chemistry") or {}).get("modes") or {})


def version_coverage(attempts: list[dict], asset: str) -> tuple[int | None, int | None]:
    """Lowest and highest version of `asset` that any attempt in the stream records."""
    seen = [parse_v(asset_version_of(r, asset)) for r in attempts]
    seen = [v for v in seen if v is not None]
    return (min(seen), max(seen)) if seen else (None, None)


def close(rows: list[dict], attempts: list[dict]) -> tuple[list[dict], list[dict]]:
    changes = []
    for row in rows:
        if row.get("outcome") == "rolled_back":
            continue
        if row.get("closed_status"):
            continue
        asset = row.get("asset_id") or ""
        after = row.get("asset_version_after")
        if after is None:
            continue

        lo, hi = version_coverage(attempts, asset)
        if hi is None:
            # No attempt in the stream records this asset, so nothing can be said about
            # downstream use — as distinct from saying nothing reused it.
            row["first_downstream_use"] = None
            row["expectation_met"] = None
            row["closed_status"] = "not_closable"
            row["closed_reason"] = (
                "no attempt in evolution/attempt_vectors.jsonl records this asset"
            )
            changes.append({"seq": row.get("seq"), "asset_id": asset,
                            "first_downstream_use": False, "expectation_met": "not_closable"})
            continue
        if int(after) > hi:
            # The ledger's version numbering for this asset was renumbered when two id forms
            # were merged into one lineage, so it is not comparable with the versions recorded
            # on attempts. Saying "no downstream use" here would be a measurement claim that
            # the data does not support.
            row["first_downstream_use"] = None
            row["expectation_met"] = None
            row["closed_status"] = "not_closable"
            row["closed_reason"] = (
                f"ledger version v{after} exceeds the highest version recorded on any attempt "
                f"(v{hi}); this asset's numbering was renumbered when two id lineages were "
                f"merged, so the two are not comparable"
            )
            changes.append({"seq": row.get("seq"), "asset_id": asset,
                            "first_downstream_use": False, "expectation_met": "not_closable"})
            continue

        # first_downstream_use: earliest attempt recorded at or above the revised version.
        first = None
        after_recs, before_recs = [], []
        for rec in attempts:
            v = parse_v(asset_version_of(rec, asset))
            if v is None:
                continue
            if v >= int(after):
                after_recs.append(rec)
                if first is None:
                    first = rec
            else:
                before_recs.append(rec)

        targeted = [m for m in (row.get("failure_mode") or []) if m]
        # Process modes describe the machinery, not a chemical outcome, so the attempt
        # classifier never emits them. Scoring one against attempt failure rates would compare
        # a category to a category it cannot contain, and always report "not met".
        measurable = [m for m in targeted if m in chemistry_modes()]
        met = None
        rate_before = rate_after = None
        if targeted and not measurable:
            met = "not_applicable"
        elif measurable and after_recs:
            targeted = measurable
            def rate(recs):
                if not recs:
                    return None
                c = Counter(failure_mode_of(r) for r in recs)
                return sum(c[m] for m in targeted) / len(recs)

            rate_before, rate_after = rate(before_recs), rate(after_recs)
            if len(after_recs) < MIN_AFTER_ATTEMPTS or rate_before is None:
                met = "inconclusive"
            else:
                met = bool(rate_after < rate_before)

        new = dict(row)
        new["first_downstream_use"] = (
            {
                "edge": first.get("_edge"),
                "guess": first.get("name"),
                "status": first.get("status"),
                "cache": first.get("_cache"),
            }
            if first
            else None
        )
        new["expectation_met"] = met
        new["closed_status"] = "closed" if first else "not_closable"
        if not first:
            new["closed_reason"] = "no attempt recorded at or above the revised version"
        if targeted:
            new["expectation_evidence"] = {
                "targeted_failure_modes": targeted,
                "attempts_before": len(before_recs),
                "attempts_after": len(after_recs),
                "rate_before": round(rate_before, 3) if rate_before is not None else None,
                "rate_after": round(rate_after, 3) if rate_after is not None else None,
                "min_after_attempts": MIN_AFTER_ATTEMPTS,
            }
        if new != row:
            changes.append({"seq": row.get("seq"), "asset_id": asset,
                            "first_downstream_use": bool(first), "expectation_met": met})
        row.clear()
        row.update(new)
    return rows, changes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="rewrite the ledger in place")
    a = ap.parse_args()

    rows = load_ledger()
    attempts = attempt_records()
    rows, changes = close(rows, attempts)

    print(f"ledger rows: {len(rows)} | attempts with an asset vector: "
          f"{sum(1 for r in attempts if r.get('asset_versions'))}/{len(attempts)}")
    if not changes:
        print("nothing to close")
        return 0
    print(f"\n{len(changes)} record(s) would close:")
    for c in changes[:40]:
        print(f"  seq {c['seq']:>3}  {c['asset_id']:<44} "
              f"downstream_use={'yes' if c['first_downstream_use'] else 'no':<3} "
              f"expectation_met={c['expectation_met']}")
    if not a.apply:
        print("\n(report only; pass --apply to write)")
        return 0
    with open(LOG, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nwrote {os.path.relpath(LOG, PKG)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
