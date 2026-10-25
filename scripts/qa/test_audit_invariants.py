#!/usr/bin/env python3
"""Invariants from the ec6934e audit: geometry-less STRICT, arm isolation, replay versions."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

PKG = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG / "scripts" / "graph"))
sys.path.insert(0, str(PKG / "scripts" / "eval"))
sys.path.insert(0, str(PKG / "scripts" / "reflect"))
sys.path.insert(0, str(PKG / "loop" / "fully_auto"))
sys.path.insert(0, str(PKG / "tools" / "workflow"))

FAILS: list[str] = []


def check(cond, msg):
    if cond:
        print(f"  OK  {msg}")
    else:
        print(f" FAIL {msg}")
        FAILS.append(msg)


def main() -> int:
    import audit_pinned_edges as AU
    import build_reaction_network as BRN
    import arm_runner as AR
    import apply_revision as REV
    import run_qm_step as QM
    import close_revisions as CR
    import repair_queue as RQ

    print("== provisional record is not STRICT ==")
    st, prov, _ = AU.status_from_record_only(
        {"status": "STRICT", "ts_imag_cm-1": -400.0},
        [-400.0],
    )
    check(st == "unresolved", f"geometry-less record is unresolved (got {st})")
    check(prov is True, "flagged provisional for the repair queue")
    check(st != "STRICT", "must not keep an accepted status")

    print("\n== control-arm caches do not enter the main collector ==")
    arm = PKG / "runs" / "arms" / "_audit_probe"
    arm.mkdir(parents=True, exist_ok=True)
    cache = arm / "strict_cache.json"
    json.dump(
        {"C>>CC": {"status": "STRICT", "reactant": "C", "product": "CC"}},
        open(cache, "w"),
    )
    try:
        check(BRN.is_eval_arm_cache(str(cache)), "runs/arms/ is classified as an eval arm")
        check(
            BRN.is_eval_arm_cache(str(PKG / "runs" / "review_x" / "strict_cache.json")),
            "review worktrees are isolated",
        )
        check(
            not BRN.is_eval_arm_cache(str(PKG / "runs" / "validation" / "e1" / "strict_cache.json")),
            "live validation caches stay visible",
        )
        collected = BRN.collect_caches()
        paths = [str(v.get("_cache_path") or "") for v in collected.values()]
        check(
            not any(BRN.is_eval_arm_cache(p) for p in paths),
            "collector dropped the arm cache",
        )
    finally:
        shutil.rmtree(arm, ignore_errors=True)

    print("\n== nested snapshot restores without doubling the path ==")
    dest = Path(tempfile.mkdtemp(prefix="reaxevolve_snap_"))
    snap = Path(tempfile.mkdtemp(prefix="reaxevolve_snapsrc_"))
    try:
        inner = snap / "demo-skill"
        inner.mkdir()
        (inner / "SKILL.md").write_text("FROM_SNAPSHOT\n")
        skill_dir = dest / ".skills" / "demo-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("ARM_COPY\n")
        (skill_dir / "reference.md").write_text("keep me\n")
        report = AR.overlay_snapshot(str(dest), ".skills/demo-skill", str(snap))
        restored = dest / ".skills" / "demo-skill" / "SKILL.md"
        doubled = dest / ".skills" / "demo-skill" / "demo-skill" / "SKILL.md"
        check(restored.read_text() == "FROM_SNAPSHOT\n", "nested snapshot landed on the asset")
        check(not doubled.is_file(), "path was not joined twice")
        check(
            (dest / ".skills" / "demo-skill" / "reference.md").read_text() == "keep me\n",
            "companion file left at arm content",
        )
        check(".skills/demo-skill/SKILL.md" in report["restored_from_snapshot"]
              or "SKILL.md" in str(report["restored_from_snapshot"]),
              "report names the restored file")
    finally:
        shutil.rmtree(dest, ignore_errors=True)
        shutil.rmtree(snap, ignore_errors=True)

    print("\n== replay VERSIONS follows the overlaid files ==")
    dest = Path(tempfile.mkdtemp(prefix="reaxevolve_ver_"))
    try:
        (dest / "tools").mkdir()
        json.dump(
            {"skills": {"pathway-method": "v0"}, "tools": {"guess/ladder.py": "v0"}},
            open(dest / "tools" / "VERSIONS.json", "w"),
        )
        AR._write_replay_versions(
            str(dest),
            [
                {"asset_id": ".skills/pathway-method", "version": 2},
                {"asset_id": "tools/guess/ladder.py", "version": 3},
            ],
        )
        vers = json.load(open(dest / "tools" / "VERSIONS.json"))
        check(vers["skills"]["pathway-method"] == "v2", "skill version is the overlaid one")
        check(vers["tools"]["guess/ladder.py"] == "v3", "tool version is the overlaid one")
    finally:
        shutil.rmtree(dest, ignore_errors=True)

    print("\n== not_closable is re-opened when evidence arrives ==")
    row = {
        "seq": 99,
        "outcome": "applied",
        "closed_status": "not_closable",
        "origin_asset_id": "tools/guess/ladder.py",
        "origin_version_after": 2,
        "asset_id": "tools/guess/ladder.py",
        "asset_version_after": 2,
        "failure_mode": ["no_endpoint_record"],
    }
    attempts = [
        {
            "asset_versions": {"tools": {"guess/ladder.py": "v1"}},
            "status": "unresolved",
            "detail": "IRC_FAILED",
        },
        {
            "asset_versions": {"tools": {"guess/ladder.py": "v2"}},
            "status": "STRICT",
            "_edge": "C>>CC",
        },
    ] * 6
    rows, _ = CR.close([dict(row)], attempts)
    check(rows[0].get("closed_status") == "closed", "later evidence can close a not_closable row")

    print("\n== Reflect diff cannot name a protected path ==")
    check(
        REV.reject_protected_write(["policy/acceptance/STRICT.md"]) is not None,
        "policy is rejected even if the declared path was a skill",
    )
    check(
        REV.reject_protected_write(["tools/geometry/parse_orca_output.py"]) is not None,
        "evidence parser is rejected",
    )
    check(
        REV.reject_protected_write([".skills/pathway-method/SKILL.md"]) is None,
        "a live skill is writable",
    )
    named = REV.paths_in_unified_diff(
        "--- a/policy/acceptance/STRICT.md\n+++ b/policy/acceptance/STRICT.md\n@@ -1 +1 @@\n-x\n+y\n"
    )
    check(named == ["policy/acceptance/STRICT.md"], "unified diff paths are parsed")

    print("\n== demote walks a dict-shaped network without crashing ==")
    td = Path(tempfile.mkdtemp(prefix="reaxevolve_demote_"))
    try:
        pin = {"edges": [{"edge": "C>>CC", "reactant": "C", "product": "CC"}], "n_strict": 1}
        net = {"edges": {"E_x": {"id": "E_x", "reactant": "C", "product": "CC", "status": "STRICT"}}}
        pin_p = td / "pin.json"
        net_p = td / "net.json"
        json.dump(pin, open(pin_p, "w"))
        json.dump(net, open(net_p, "w"))
        old_pin, old_net, old_log = RQ.PIN, RQ.NET, RQ.DEMOTE_LOG
        RQ.PIN, RQ.NET, RQ.DEMOTE_LOG = str(pin_p), str(net_p), str(td / "DEMOTE_LOG.md")
        try:
            RQ.demote([{"edge": "C>>CC", "action": "demote_rejected"}], dry_run=False)
            pin2 = json.load(open(pin_p))
            net2 = json.load(open(net_p))
            check(pin2["n_strict"] == 0, "pin updated after a successful network write")
            check(net2["edges"]["E_x"]["status"] == "rejected", "dict-shaped network was demoted")
        except Exception as e:
            check(False, f"demote crashed: {e}")
        finally:
            RQ.PIN, RQ.NET, RQ.DEMOTE_LOG = old_pin, old_net, old_log
    finally:
        shutil.rmtree(td, ignore_errors=True)

    print("\n== failed IRC cannot reuse leftover endpoints ==")
    td = Path(tempfile.mkdtemp(prefix="reaxevolve_irc_"))
    try:
        f = td / "F.xyz"
        b = td / "B.xyz"
        f.write_text("1\n\nO 0 0 0\n")
        b.write_text("1\n\nO 0 0 0\n")
        old = os.path.getmtime(f) - 120
        os.utime(f, (old, old))
        os.utime(b, (old, old))
        check(
            QM.stale_irc_endpoints(str(f), str(b), started=old + 60) is True,
            "xyz older than this IRC job is rejected",
        )
        os.utime(f, None)
        os.utime(b, None)
        check(
            QM.stale_irc_endpoints(str(f), str(b), started=os.path.getmtime(f) - 1) is False,
            "fresh xyz from this job is accepted",
        )
    finally:
        shutil.rmtree(td, ignore_errors=True)

    print("\n== archive flatten keeps every attempt ==")
    sys.path.insert(0, str(PKG / "scripts" / "validate"))
    import verdict_writer as VW  # noqa: E402
    import consolidate_verdicts as CV  # noqa: E402

    entry = {
        "status": "STRICT",
        "detail": "last",
        "attempts": [
            {"status": "unresolved", "detail": "IRC_FAILED", "time": "2026-10-01 01:00"},
            {"status": "unresolved", "detail": "WALL_TIME", "time": "2026-10-01 02:00"},
            {"status": "STRICT", "detail": "last", "time": "2026-10-01 03:00"},
        ],
    }
    rows = VW.expand_attempts("C>>CC", entry)
    check(len(rows) == 3, f"three archived attempts stay visible (got {len(rows)})")
    check(rows[0].get("detail") == "IRC_FAILED", "first failure survives flatten")
    check(rows[1].get("detail") == "WALL_TIME", "second failure survives flatten")

    inherited = {
        "reactant": "C",
        "product": "CC",
        "status": "STRICT",
        "ts_imag_cm-1": -400.0,
        "ts_imag_all": [-400.0],
        "endpoint_match": {"F_isReactant": True, "B_isProduct": True},
        "asset_versions": {"tools": {"workflow/run_qm_step.py": "v9"}},
        "attempts": [
            {"name": "g0", "status": "unresolved", "detail": "WALL_TIME", "time": "t0"},
            {"name": "g1", "status": "unresolved", "detail": "IRC_FAILED", "time": "t1"},
            {
                "name": "g2",
                "status": "STRICT",
                "ts_imag_cm-1": -400.0,
                "ts_imag_all": [-400.0],
                "endpoint_match": {"F_isReactant": True, "B_isProduct": True},
                "time": "t2",
            },
        ],
    }
    flat = VW.expand_attempts("C>>CC", inherited)
    check(flat[0].get("ts_imag_cm-1") is None, "g0 does not inherit a later frequency")
    check(flat[0].get("endpoint_match") is None, "g0 does not inherit later endpoints")
    check(flat[0].get("asset_versions") is None, "g0 does not inherit a later version vector")
    import failure_digest as FD  # noqa: E402
    check(FD.classify(flat[0]) != "ok", "an early failure is not classified ok")
    check(FD.classify(flat[2]) == "ok", "the successful attempt stays ok")
    nested = {
        "edge": "C>>CC",
        "reactant": "C",
        "product": "CC",
        "name": "g1",
        "status": "unresolved",
        "time": "t1",
        "attempts": [
            {"name": "g0", "status": "unresolved", "time": "t0"},
            {"name": "g1", "status": "unresolved", "time": "t1"},
        ],
    }
    seen = set()
    names = []
    for rec in (nested, *flat):
        for a in VW.expand_attempts(rec.get("edge") or "C>>CC", rec):
            key = CV.dedup_key(a, a.get("edge"))
            if key in seen:
                continue
            seen.add(key)
            names.append(a.get("name"))
    check(names.count("g0") == 1, f"old nested + flat g0 is counted once (got {names})")
    check(len(names) == 3, f"migration keeps three identities (got {names})")
    same_min = {
        "name": "r0_g0",
        "reactant": "C",
        "product": "CC",
        "time": "2026-10-25 14:00",
        "status": "unresolved",
        "detail": "WALL_TIME",
        "invocation_id": "run-1",
        "input_fingerprint": {"g.xyz": "aaa"},
    }
    retry = dict(same_min, invocation_id="run-2", detail="IRC_FAILED",
                 input_fingerprint={"g.xyz": "bbb"})
    check(
        CV.dedup_key(same_min, "C>>CC") != CV.dedup_key(retry, "C>>CC"),
        "same minute and name but different invocation stay two archive rows",
    )
    check(
        CV.dedup_key(same_min, "C>>CC") == CV.dedup_key(dict(same_min), "C>>CC"),
        "a copied cache of the same invocation still collapses",
    )
    legacy = {"name": "r0_g0", "reactant": "C", "product": "CC",
              "time": "2026-10-25 14:00", "status": "unresolved"}
    check(
        CV.dedup_key(legacy, "C>>CC") == CV.dedup_key(dict(legacy), "C>>CC"),
        "old rows without invocation_id still share one key",
    )

    print("\n== consolidate skips control-arm caches ==")
    arm = PKG / "runs" / "arms" / "_audit_cons"
    arm.mkdir(parents=True, exist_ok=True)
    json.dump(
        {"C>>CC": {"status": "STRICT", "reactant": "C", "product": "CC",
                   "attempts": [{"status": "STRICT", "detail": "arm"}]}},
        open(arm / "strict_cache.json", "w"),
    )
    try:
        found, _ = CV.collect()
        arm_hits = [
            rec for rec in found.values()
            if (rec.get("source") or {}).get("cache", "").replace("\\", "/").find("runs/arms/") >= 0
            or rec.get("detail") == "arm"
        ]
        check(not arm_hits, "consolidate does not import runs/arms/ caches")
    finally:
        shutil.rmtree(arm, ignore_errors=True)

    print("\n== provisional STRICT ledger remaps instead of keeping cache STRICT ==")
    td = Path(tempfile.mkdtemp(prefix="reaxevolve_readj_"))
    try:
        led = td / "readj.jsonl"
        led.write_text(json.dumps({
            "reactant": "C", "product": "CC", "new_status": "STRICT", "provisional": True,
        }) + "\n")
        i = BRN.eid(BRN.canon("C"), BRN.canon("CC"))
        net = {"edges": {
            i: {"id": i, "reactant": "C", "product": "CC", "status": "STRICT"},
        }}
        BRN.apply_readjudication(net, ledgers=[("readjudication", str(led))])
        check(net["edges"][i]["status"] == "unresolved",
              "geometry-less provisional is unresolved after rebuild")
        led2 = td / "readj_bound.jsonl"
        led2.write_text(json.dumps({
            "reactant": "C",
            "product": "CC",
            "new_status": "STRICT",
            "provisional": True,
            "time": "2026-08-01 00:00",
            "input_fingerprint": {"guess.xyz": "old"},
            "cache_path": "/tmp/old/strict_cache.json",
        }) + "\n")
        later = {
            "id": i,
            "reactant": "C",
            "product": "CC",
            "status": "STRICT",
            "input_fingerprint": {"guess.xyz": "new"},
            "attempt_time": "2026-10-25 01:00",
            "cache_path": "/tmp/new/strict_cache.json",
        }
        net2 = {"edges": {i: later}}
        BRN.apply_readjudication(net2, ledgers=[("readjudication", str(led2))])
        check(net2["edges"][i]["status"] == "STRICT",
              "a later independent STRICT is not covered by an old provisional")
        historic = {
            "reactant": "O=C(C(O)CO)C(O)C(O)CO",
            "product": "O=C(C=C(O)CO)C(O)CO",
            "new_status": "STRICT",
            "provisional": True,
            "judgement_source": "record",
            "imag": [-1873.27],
        }
        hi = BRN.eid(BRN.canon(historic["reactant"]), BRN.canon(historic["product"]))
        boundless = td / "historic.jsonl"
        boundless.write_text(json.dumps(historic) + "\n")
        old_rec = {"id": hi, "reactant": historic["reactant"],
                   "product": historic["product"], "status": "STRICT"}
        net3 = {"edges": {hi: old_rec}}
        BRN.apply_readjudication(net3, ledgers=[("readjudication", str(boundless))])
        check(net3["edges"][hi]["status"] == "unresolved",
              "an unbound provisional still demotes a geometry-less record")
        new_rec = {
            "id": hi,
            "reactant": historic["reactant"],
            "product": historic["product"],
            "status": "STRICT",
            "input_fingerprint": {"new_guess.xyz": "6e2bd300353817a4"},
            "attempt_time": "2026-10-25 14:00",
            "cache_path": "/tmp/new/strict_cache.json",
        }
        net4 = {"edges": {hi: new_rec}}
        BRN.apply_readjudication(net4, ledgers=[("readjudication", str(boundless))])
        check(net4["edges"][hi]["status"] == "STRICT",
              "the real historic format does not cover a later fingerprinted STRICT")
        net5 = {"edges": {hi: dict(new_rec)}}
        BRN.apply_readjudication(net5)
        check(net5["edges"][hi]["status"] == "STRICT",
              "the shipped unbound ledger does not cover a later fingerprinted STRICT")
        inv_only = {
            "id": hi,
            "reactant": historic["reactant"],
            "product": historic["product"],
            "status": "STRICT",
            "invocation_id": "s5-new-complete-attempt",
            "input_fingerprint": None,
            "attempt_time": "2026-10-25 14:00",
            "cache_path": "/tmp/new-inv/strict_cache.json",
        }
        net6 = {"edges": {hi: dict(inv_only)}}
        BRN.apply_readjudication(net6, ledgers=[("readjudication", str(boundless))])
        check(net6["edges"][hi]["status"] == "STRICT",
              "invocation-only later STRICT is not covered by an unbound provisional")
        net7 = {"edges": {hi: dict(inv_only)}}
        BRN.apply_readjudication(net7)
        check(net7["edges"][hi]["status"] == "STRICT",
              "the shipped ledger does not cover an invocation-only later STRICT")
        pasted = {
            "id": hi,
            "reactant": historic["reactant"],
            "product": historic["product"],
            "status": "STRICT",
            "ts_imag_cm-1": -1873.27,
            "input_fingerprint": {"pasted.xyz": "deadbeefdeadbeef"},
            "attempt_time": "2026-07-20",
            "cache_path": str(
                PKG / "graph/caches/strict_caches/reaction_network/r2_hmfdehyd/strict_cache.json"
            ),
        }
        net8 = {"edges": {hi: dict(pasted)}}
        BRN.apply_readjudication(net8, ledgers=[("readjudication", str(boundless))])
        check(net8["edges"][hi]["status"] == "unresolved",
              "pasting a fingerprint onto the old imag still remaps")
        net9 = {"edges": {hi: dict(pasted)}}
        BRN.apply_readjudication(net9)
        check(net9["edges"][hi]["status"] == "unresolved",
              "the shipped ledger still remaps the old imag after metadata paste")
        old_path = str(
            PKG / "graph/caches/strict_caches/reaction_network/r2_hmfdehyd/strict_cache.json"
        )
        pasted_inv = {
            "id": hi,
            "reactant": historic["reactant"],
            "product": historic["product"],
            "status": "STRICT",
            "ts_imag_cm-1": -1873.27,
            "name": "r2_hmfdehyd",
            "invocation_id": "pasted-on-old-record",
            "input_fingerprint": None,
            "attempt_time": "2026-07-20",
            "cache_path": old_path,
        }
        net10 = {"edges": {hi: dict(pasted_inv)}}
        BRN.apply_readjudication(net10, ledgers=[("readjudication", str(boundless))])
        check(net10["edges"][hi]["status"] == "unresolved",
              "pasting an invocation_id onto the bound attempt still remaps")
        net11 = {"edges": {hi: dict(pasted_inv)}}
        BRN.apply_readjudication(net11)
        check(net11["edges"][hi]["status"] == "unresolved",
              "the shipped ledger still remaps the bound attempt after an ID paste")
        same_imag_new = {
            "id": hi,
            "reactant": historic["reactant"],
            "product": historic["product"],
            "status": "STRICT",
            "ts_imag_cm-1": -1873.27,
            "name": "s5-new-job",
            "input_fingerprint": {"new_guess.xyz": "6e2bd300353817a4"},
            "attempt_time": "2026-10-25 14:00",
            "cache_path": "/tmp/new-same-imag/strict_cache.json",
        }
        net12 = {"edges": {hi: dict(same_imag_new)}}
        BRN.apply_readjudication(net12, ledgers=[("readjudication", str(boundless))])
        check(net12["edges"][hi]["status"] == "STRICT",
              "a new fingerprinted attempt is kept even if the imag matches")
        net13 = {"edges": {hi: dict(same_imag_new)}}
        BRN.apply_readjudication(net13)
        check(net13["edges"][hi]["status"] == "STRICT",
              "the shipped ledger keeps a new same-imag attempt")
        reused = {
            "id": hi,
            "reactant": historic["reactant"],
            "product": historic["product"],
            "status": "STRICT",
            "ts_imag_cm-1": -1873.27,
            "name": "r2_hmfdehyd",
            "invocation_id": "s5-same-dir-retry",
            "input_fingerprint": {"raw_guess.xyz": "aabbccddeeff0011"},
            "attempt_time": "2026-10-25 14:00",
            "cache_path": old_path,
        }
        net14 = {"edges": {hi: dict(reused)}}
        BRN.apply_readjudication(net14, ledgers=[("readjudication", str(boundless))])
        check(net14["edges"][hi]["status"] == "STRICT",
              "same-dir same-name retry with new time/id/fp is kept")
        net15 = {"edges": {hi: dict(reused)}}
        BRN.apply_readjudication(net15)
        check(net15["edges"][hi]["status"] == "STRICT",
              "the shipped ledger keeps a same-dir same-name retry")
        fields = BRN.cache_identity_fields({
            "input_fingerprint": None,
            "time": "2026-10-25 14:00",
            "invocation_id": "s5-new-complete-attempt",
            "name": "s5-new-job",
        })
        check(fields.get("invocation_id") == "s5-new-complete-attempt",
              "cache→edge keeps invocation_id")
        check("invocation_id" in fields and fields["invocation_id"],
              "edge identity is not fingerprint-only")
        binds = BRN.provisional_binds()
        check(len(binds) == 7, f"seven provisional attempts are bound (got {len(binds)})")
        hk = f"{BRN.canon(historic['reactant'])}>>{BRN.canon(historic['product'])}"
        check(binds.get(hk, {}).get("name") == "r2_hmfdehyd",
              "the historic pair binds to r2_hmfdehyd")
    finally:
        shutil.rmtree(td, ignore_errors=True)

    print("\n== xTB fallback still fingerprints the raw guess ==")
    td = Path(tempfile.mkdtemp(prefix="reaxevolve_guess_"))
    here = os.getcwd()
    try:
        guess = td / "raw_guess.xyz"
        guess.write_text("2\n\nC 0 0 0\nO 1 0 0\n")
        os.chdir(td)
        res = {
            "reactant": "C",
            "product": "CO",
            "invocation_id": "s5-xtb-fallback",
            "status": None,
        }
        QM.attach_guess(res, str(guess))
        check(res.get("guess_path") == str(guess), "raw guess is recorded before xTB")
        QM._save(res, "STRICT", None)
        check(isinstance(res.get("input_fingerprint"), dict) and res["input_fingerprint"],
              "xTB-less save still hashes the raw guess")
        check(res.get("invocation_id") == "s5-xtb-fallback",
              "invocation_id survives the write")
        fields = BRN.cache_identity_fields(res)
        check(fields.get("invocation_id") == "s5-xtb-fallback",
              "edge identity keeps the fallback invocation")
        check(bool(fields.get("input_fingerprint")),
              "edge identity keeps the fallback fingerprint")
    finally:
        os.chdir(here)
        shutil.rmtree(td, ignore_errors=True)

    print("\n== negative readjudication does not cover a later STRICT attempt ==")
    td = Path(tempfile.mkdtemp(prefix="reaxevolve_neg_"))
    try:
        led = td / "readj.jsonl"
        led.write_text(json.dumps({
            "reactant": "C",
            "product": "CC",
            "new_status": "rejected",
            "provisional": False,
            "time": "2026-08-01 00:00",
            "input_fingerprint": {"guess.xyz": "old"},
            "cache_path": "/tmp/old/strict_cache.json",
        }) + "\n")
        i = BRN.eid(BRN.canon("C"), BRN.canon("CC"))
        net = {"edges": {
            i: {
                "id": i,
                "reactant": "C",
                "product": "CC",
                "status": "STRICT",
                "input_fingerprint": {"guess.xyz": "new"},
                "attempt_time": "2026-10-24 12:00",
                "cache_path": "/tmp/new/strict_cache.json",
            },
        }}
        BRN.apply_readjudication(net, ledgers=[("readjudication", str(led))])
        check(net["edges"][i]["status"] == "STRICT",
              "later fingerprint keeps STRICT against an old reject")
    finally:
        shutil.rmtree(td, ignore_errors=True)

    print("\n== delete patch of STRICT.md is refused and restorable ==")
    delete_diff = (
        "--- a/policy/acceptance/STRICT.md\n"
        "+++ /dev/null\n"
        "@@ -1,2 +0,0 @@\n"
        "-# STRICT\n"
        "-bar\n"
    )
    named = REV.paths_in_unified_diff(delete_diff)
    check("policy/acceptance/STRICT.md" in named, "delete hunk names the protected file")
    check(REV.reject_protected_write(named) is not None, "delete of STRICT.md is refused")
    root = Path(tempfile.mkdtemp(prefix="reaxevolve_del_"))
    try:
        target = root / "policy" / "acceptance" / "STRICT.md"
        target.parent.mkdir(parents=True)
        target.write_text("PROTECTED\n")
        backups = REV.backup_files(["policy/acceptance/STRICT.md"], root=str(root))
        target.unlink()
        check(not target.is_file(), "probe deleted the protected file")
        REV.restore_files(backups, root=str(root))
        check(target.is_file() and target.read_text() == "PROTECTED\n",
              "rollback restores the deleted STRICT.md")
        before = REV._guard_hashes()
        bak_dir = tempfile.mkdtemp(prefix="reaxevolve_bakdir_")
        REV.backup_files(["policy/acceptance/STRICT.md"], dest_dir=bak_dir)
        stray = REV._unexpected_writes([], before)
        check(
            not any(p.endswith(".bak_fully_auto") for p in stray),
            "off-tree backups are not unexpected writes",
        )
        shutil.rmtree(bak_dir, ignore_errors=True)
        existed = REV.writable_tree_files(str(root))
        created = root / "tools" / "guess" / "audit_created.py"
        created.parent.mkdir(parents=True)
        created.write_text("x\n")
        REV.remove_created_files(existed, root=str(root))
        check(not created.is_file(), "rollback deletes files this revision created")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\n== endpoint opt requires convergence, not just normal termination ==")
    td = Path(tempfile.mkdtemp(prefix="reaxevolve_opt_"))
    try:
        dead = td / "dead.out"
        dead.write_text("ORCA TERMINATED NORMALLY\n****ORCA TERMINATED NORMALLY****\n")
        check(QM.terminated_ok(str(dead)) is True, "fixture did terminate")
        check(QM.opt_converged(str(dead)) is False, "normal termination is not convergence")
        good = td / "good.out"
        good.write_text(
            "                    ***        HURRAY     ***\n"
            "          *** THE OPTIMIZATION HAS CONVERGED ***\n"
            "ORCA TERMINATED NORMALLY\n"
        )
        check(QM.opt_converged(str(good)) is True, "converged opt is accepted")
    finally:
        shutil.rmtree(td, ignore_errors=True)

    print("\n== newer STRICT attempt is not covered by an old pair demotion ==")
    edge = {
        "status": "STRICT",
        "input_fingerprint": {"guess.xyz": "bbbb"},
        "attempt_time": "2026-10-24 12:00",
        "cache_path": "/tmp/new/strict_cache.json",
    }
    rec = {
        "new_status": "rejected",
        "input_fingerprint": {"guess.xyz": "aaaa"},
        "time": "2026-08-01 00:00",
        "cache_path": "/tmp/old/strict_cache.json",
    }
    check(
        BRN._newer_qualifying_attempt(edge, rec, "") is True,
        "a later fingerprint is not demoted",
    )
    old_edge = dict(edge, input_fingerprint=rec["input_fingerprint"],
                    attempt_time="2026-07-01 00:00", cache_path=rec["cache_path"])
    check(
        BRN._newer_qualifying_attempt(old_edge, rec, "") is False,
        "the audited attempt is still demoted",
    )

    print("\n== accepted projection matches the pin ==")
    acc = json.load(open(PKG / "graph" / "canonical" / "accepted_network.json"))
    pin = json.load(open(PKG / "graph" / "canonical" / "audited_strict_edges.json"))
    acc_edges = acc.get("edges") or []
    if isinstance(acc_edges, dict):
        acc_edges = list(acc_edges.values())
    as_ = {(e["reactant"], e["product"]) for e in acc_edges
           if e.get("status") == "STRICT" or str(e.get("status") or "").startswith("STRICT")}
    ps = {(e["reactant"], e["product"]) for e in pin["edges"]}
    check(as_ == ps, f"accepted projection {len(as_)} equals pin {len(ps)}")

    print("\n==== SUMMARY ====")
    if FAILS:
        print(f"{len(FAILS)} failure(s):")
        for f in FAILS:
            print(" -", f)
        return 1
    print("ALL AUDIT INVARIANT CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
