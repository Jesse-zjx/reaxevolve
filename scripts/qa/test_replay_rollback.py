#!/usr/bin/env python3
"""The replay's `before` arm must roll an asset back, and say exactly how far.

Two ways this goes wrong quietly. It can fail to change anything — then both arms run identical
assets and any difference reported between them is noise. Or it can appear to restore an asset
whole when the snapshot holds only part of it, which would make the `before` arm a claim about "the
system as it was" that the record cannot support: 55 of 59 snapshots contain only SKILL.md.

So the invariants are that the rollback takes effect, that files outside the snapshot are left
alone, and that the runner reports which is which rather than leaving a reader to assume.

The comparison stays valid under the partial restore for a reason that is itself checked here: no
revision in the ledger touched a companion file, so holding companion files fixed leaves the arms
differing only in the text each revision actually changed.
"""
from __future__ import annotations

import filecmp
import json
import os
import shutil
import sys

PKG = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PKG, "scripts", "eval"))

FAILS: list[str] = []


def ok(m):
    print(f"  OK  {m}")


def fail(m):
    print(f" FAIL {m}")
    FAILS.append(m)


def main() -> int:
    import arm_runner as AR

    sel_path = os.path.join(PKG, "preregistration", "c1_selection.json")
    if not os.path.isfile(sel_path):
        fail("no preregistration/c1_selection.json: run scripts/qa/resolve_c1_selection.py --write")
        return 1
    sel = json.load(open(sel_path))

    print("== 1. no revision in the ledger touched a companion file ==")
    # The partial restore is only acceptable while this holds. If a future revision changes a
    # companion file, the snapshot mechanism must be extended before that revision is replayed.
    revs = [json.loads(l) for l in open(os.path.join(PKG, "evolution", "EVOLUTION_LOG.jsonl")) if l.strip()]
    touching = [
        r["seq"] for r in revs
        if any(
            "references/" in str(r.get(k) or "")
            for k in ("diff", "activation_point", "asset_id")
        )
    ]
    if touching:
        fail(f"revision(s) {touching} touch a companion file: the partial restore is no longer safe")
    else:
        ok(f"{len(revs)} revisions, none touching a companion file")

    print("\n== 2. each selected revision rolls back, and reports how far ==")
    for mode, blob in sel["selection"].items():
        rev = blob["revision"]
        asset_id, snap = rev["asset_id"], rev["snapshot"]
        dest = os.path.join(PKG, "runs", "arms", f"_test_{mode}")
        shutil.rmtree(dest, ignore_errors=True)
        try:
            # The selected revisions are on initial-lineage skills, so the arm is the initial set.
            AR.materialise("initial", dest)
            live_copy = os.path.join(dest, asset_id)
            if not os.path.exists(live_copy):
                fail(f"{mode}: {asset_id} absent from the arm")
                continue
            pre = os.path.join(dest, "_pre_rollback")
            shutil.copytree(live_copy, pre)

            report = AR.overlay_snapshot(dest, asset_id, snap)

            # (a) it took effect
            snap_file = os.path.join(PKG, snap, "SKILL.md")
            arm_file = os.path.join(live_copy, "SKILL.md")
            if not os.path.isfile(snap_file):
                fail(f"{mode}: snapshot has no SKILL.md")
            elif filecmp.cmp(arm_file, os.path.join(pre, "SKILL.md"), shallow=False):
                fail(f"{mode}: SKILL.md unchanged after rollback — both arms would be identical")
            elif not filecmp.cmp(arm_file, snap_file, shallow=False):
                fail(f"{mode}: SKILL.md does not match the snapshot after rollback")
            else:
                ok(f"{mode}: SKILL.md restored to {os.path.basename(snap)}")

            # (b) files outside the snapshot were left alone
            drifted = []
            for r, _, fs in os.walk(pre):
                for f in fs:
                    rel = os.path.relpath(os.path.join(r, f), pre)
                    if rel == "SKILL.md":
                        continue
                    a, b = os.path.join(live_copy, rel), os.path.join(pre, rel)
                    if not os.path.isfile(a) or not filecmp.cmp(a, b, shallow=False):
                        drifted.append(rel)
            if drifted:
                fail(f"{mode}: files outside the snapshot changed: {drifted}")
            else:
                ok(f"{mode}: files outside the snapshot untouched")

            # (c) the report does not overstate what happened
            companions = [
                os.path.relpath(os.path.join(r, f), pre)
                for r, _, fs in os.walk(pre) for f in fs
                if os.path.relpath(os.path.join(r, f), pre) != "SKILL.md"
            ]
            if companions and report["whole_asset_restored"]:
                fail(f"{mode}: reported a whole-asset restore while {len(companions)} companion "
                     "file(s) were left at arm content")
            elif companions:
                ok(f"{mode}: reports a partial restore, {len(report['left_at_arm_content'])} "
                   "file(s) named as left as-is")
            else:
                ok(f"{mode}: asset is a single file, restored whole")
        finally:
            shutil.rmtree(dest, ignore_errors=True)

    print("\n== 3. the replay's verdict archive is not merged into the network ==")
    # Archiving these under graph/caches/ took the accepted-edge count from 30 to 44, admitting 14
    # edges that never went through the audit which demoted 8 — and it would have merged an isolated
    # campaign's results into the delivered network. The rebuild globs graph/caches/**, so the only
    # thing keeping them apart is where they live.
    sys.path.insert(0, os.path.join(PKG, "scripts", "graph"))
    import build_reaction_network as BRN  # noqa: E402

    archive = os.path.join(PKG, "evolution", "attempt_verdicts")
    if not os.path.isdir(archive):
        fail("evolution/attempt_verdicts/ is missing: the attempt stream's verdicts are unarchived")
    else:
        n = len([d for d in os.listdir(archive)])
        scanned = {os.path.abspath(p) for p in BRN.collect_caches()} if hasattr(
            BRN, "collect_caches"
        ) else set()
        # collect_caches returns records, not paths, on some versions; fall back to the patterns.
        import glob as _g

        swept = set()
        for pat in (
            os.path.join(PKG, "runs", "**", "strict_cache.json"),
            os.path.join(PKG, "graph", "caches", "**", "strict_cache.json"),
        ):
            swept |= {os.path.abspath(p) for p in _g.glob(pat, recursive=True)}
        mine = {
            os.path.abspath(os.path.join(r, f))
            for r, _, fs in os.walk(archive) for f in fs if f == "strict_cache.json"
        }
        leaked = mine & (swept | scanned)
        if leaked:
            fail(f"{len(leaked)} replay verdict(s) sit inside the rebuild's scan path and would be "
                 "merged into the canonical network")
        else:
            ok(f"{n} archived edge(s), none inside the rebuild's scan path")

    print("\n== 4. the two arms differ only in the asset the revision changed ==")
    # `--set initial` alone is version 0 of every skill. The after arm has to be asset_version_after,
    # and every other asset the revision's vector names has to be that version in both arms.
    # Leaving the after arm at the initial set would compare v0 with v0.
    for mode, blob in sel["selection"].items():
        seq = blob["revision"]["seq"]
        under = blob["revision"]["asset_id"]
        trees, pins = {}, {}
        try:
            for arm_name in ("before", "after"):
                dest = os.path.join(PKG, "runs", "arms", f"_pin_{mode}_{arm_name}")
                shutil.rmtree(dest, ignore_errors=True)
                AR.materialise("initial", dest)
                pins[arm_name] = AR.pin_replay(dest, seq, arm_name)
                trees[arm_name] = dest
            same = True
            for arm_name in ("before", "after"):
                item = next(x for x in pins[arm_name]["applied"] if x["asset_id"] == under)
                arm_md = os.path.join(trees[arm_name], under, "SKILL.md")
                snap_md = os.path.join(PKG, item["snapshot"], "SKILL.md")
                if not filecmp.cmp(arm_md, snap_md, shallow=False):
                    fail(f"{mode} {arm_name}: {under} is not {item['snapshot']}")
                    same = False
                else:
                    ok(f"{mode} {arm_name}: {under} at version {item['version']}")
            before_md = os.path.join(trees["before"], under, "SKILL.md")
            after_md = os.path.join(trees["after"], under, "SKILL.md")
            before_snap = os.path.join(
                PKG, next(x for x in pins["before"]["applied"] if x["asset_id"] == under)["snapshot"],
                "SKILL.md")
            after_snap = os.path.join(
                PKG, next(x for x in pins["after"]["applied"] if x["asset_id"] == under)["snapshot"],
                "SKILL.md")
            if same and filecmp.cmp(before_snap, after_snap, shallow=False):
                # The pin did what the ledger says. The ledger's two images are one file, so the
                # arms cannot differ in this text; that is a property of the record, checked here
                # so a run does not discover it after the compute.
                ok(f"{mode}: the ledger stores the same SKILL.md at both versions")
            elif same and filecmp.cmp(before_md, after_md, shallow=False):
                fail(f"{mode}: before and after carry the same {under}")
            elif same:
                ok(f"{mode}: before and after differ")
            for asset_id in (x["asset_id"] for x in pins["before"]["applied"] if x["asset_id"] != under):
                a = os.path.join(trees["before"], asset_id, "SKILL.md")
                b = os.path.join(trees["after"], asset_id, "SKILL.md")
                initial = os.path.join(PKG, "assets", "initial", asset_id, "SKILL.md")
                if not filecmp.cmp(a, b, shallow=False):
                    fail(f"{mode}: {asset_id} differs between arms")
                elif filecmp.cmp(a, initial, shallow=False):
                    fail(f"{mode}: {asset_id} was left at the initial set, not the pinned version")
                else:
                    ok(f"{mode}: {asset_id} pinned, and identical across arms")
        finally:
            for dest in trees.values():
                shutil.rmtree(dest, ignore_errors=True)

    print("\n==== SUMMARY ====")
    if FAILS:
        print(f"{len(FAILS)} failure(s):")
        for f in FAILS:
            print(" -", f)
        return 1
    print("REPLAY ROLLBACK BEHAVES AS DOCUMENTED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
