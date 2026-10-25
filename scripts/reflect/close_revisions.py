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
sys.path.insert(0, os.path.join(PKG, "scripts", "validate"))
import chem_paths as CP  # noqa: E402
import verdict_writer as VW  # noqa: E402

LOG = os.path.join(PKG, "evolution", "EVOLUTION_LOG.jsonl")

# The attempt stream the revisions in EVOLUTION_LOG were measured on: one line per attempt,
# each carrying the asset-version vector in force when it ran. It lives beside the ledger
# rather than under graph/ because it is evolution evidence, not Graph Memory — merging it
# into the network would mix two campaigns' reaction data. See evolution/README.md.
ATTEMPT_VECTORS = os.path.join(PKG, "evolution", "attempt_vectors.jsonl")

# Comparison window, in attempts, on each side of the revision.
#
# Bounded and balanced on purpose. Comparing "every attempt before" against "every attempt
# after" looks rigorous and is not: consecutive revisions then share almost their entire
# before-window, so the measurements are not independent, and the after-window collapses
# toward the end of a campaign — the last revision gets judged on two attempts. Run once that
# way, this produced 39 apparent failures whose `rate_after` climbed monotonically as `n` fell,
# which is a description of where each revision sat in the campaign rather than of the revision.
WINDOW = 12
MIN_SIDE = 6  # below this on either side, report inconclusive rather than a direction


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
            if CP.is_eval_arm_cache(path):
                continue
            try:
                data = json.load(open(path))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            for key, rec in data.items():
                if not isinstance(rec, dict):
                    continue
                for r in VW.expand_attempts(key, rec):
                    r["_edge"] = key
                    r["_cache"] = os.path.relpath(path, PKG)
                    out.append(r)
    return out


def asset_version_of(rec: dict, asset_id: str):
    """Version of one asset as recorded on an attempt, or None if not recorded.

    Two lookups, because the early campaign kept two counters for one skill in two places: the
    `skills` section, keyed by bare name, and a flat top-level key spelled with `/SKILL.md`.
    A revision belongs to exactly one of those lineages, so the caller passes the id form the
    revision was written under (`origin_asset_id`) and this resolves it against the matching
    key. Looking only in the sections is what made the SKILL.md-lineage revisions appear to
    have no downstream evidence.
    """
    vec = rec.get("asset_versions") or {}
    rel = (asset_id or "").strip()
    # Exact flat key first: it is unambiguous when present.
    for candidate in (rel, rel.lstrip("./"), f"./{rel}"):
        if candidate in vec and not isinstance(vec[candidate], dict):
            return str(vec[candidate])
    bare = rel.strip("./")
    for section in ("skills", "tools"):
        table = vec.get(section)
        if not isinstance(table, dict):
            continue
        for k, v in table.items():
            if bare.endswith(k) or bare.split("/")[-1] == k.split("/")[-1]:
                return str(v)
    return None


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
        if row.get("closed_status") == "closed":
            continue
        # Compare against the identifier and numbering the attempts actually carry. For
        # revisions from the two-lineage era that is `origin_*`; the merged `asset_id` and
        # `asset_version_*` are the readable lineage and are not comparable with the vectors.
        asset = row.get("origin_asset_id") or row.get("asset_id") or ""
        after = row.get("origin_version_after")
        if after is None:
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
                f"the revised version v{after} of `{asset}` is above the highest version any "
                f"attempt records (v{hi}): the campaign stopped before an attempt ran under it"
            )
            changes.append({"seq": row.get("seq"), "asset_id": asset,
                            "first_downstream_use": False, "expectation_met": "not_closable"})
            continue

        # Attempts that record this asset, in the order they ran, split at the revision.
        indexed = []
        for rec in attempts:
            v = parse_v(asset_version_of(rec, asset))
            if v is not None:
                indexed.append((v, rec))
        before_all = [r for v, r in indexed if v < int(after)]
        after_all = [r for v, r in indexed if v >= int(after)]
        first = after_all[0] if after_all else None
        # Bounded, balanced windows: the last W before and the first W after.
        before_recs = before_all[-WINDOW:]
        after_recs = after_all[:WINDOW]

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
            if (
                len(after_recs) < MIN_SIDE
                or len(before_recs) < MIN_SIDE
                or rate_before is None
                or rate_after is None
            ):
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
                # Observational, not a replay: it compares neighbouring attempts rather than
                # re-running the same instance under both asset versions. The method's causal
                # arm is the repair/transfer replay, which fixes everything except the asset
                # version; this is the weaker signal available from the existing record.
                "measurement": "observational_balanced_window",
                "targeted_failure_modes": targeted,
                "window": WINDOW,
                "min_side": MIN_SIDE,
                "attempts_before": len(before_recs),
                "attempts_after": len(after_recs),
                "attempts_before_total": len(before_all),
                "attempts_after_total": len(after_all),
                "rate_before": round(rate_before, 3) if rate_before is not None else None,
                "rate_after": round(rate_after, 3) if rate_after is not None else None,
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
