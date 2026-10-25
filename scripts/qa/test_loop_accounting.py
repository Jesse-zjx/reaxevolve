#!/usr/bin/env python3
"""Loop bookkeeping invariants. Pure functions: no ORCA, no API, safe to run anywhere.

Each check guards a bug that silently corrupted a campaign rather than crashing it:

1. Core-hours double-counted `best`, which aliases a history entry, so the budget stop
   fired early and rounds were lost.
2. The queue writeback keyed off the wrapper dict, so every key was "None>>None" and no
   attempt was ever persisted. The same edge was re-validated every round, which both
   burned compute and made the idle-stop gate meaningless.
3. Explore failing must not abort the round: a model or endpoint error has to come back
   as a recorded zero-proposal round, not an exception.
4. The intra-round budget cap must refuse to launch a guess it cannot finish.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

PKG = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG / "loop"))
sys.path.insert(0, str(PKG / "scripts" / "lib"))

import run_loop as RL  # noqa: E402
import select_candidates as SEL  # noqa: E402

FAILS: list[str] = []


def check(cond, msg):
    if cond:
        print(f"  OK  {msg}")
    else:
        print(f" FAIL {msg}")
        FAILS.append(msg)


def main() -> int:
    print("== core-hour accounting ==")

    g1 = {"guess_path": "/w/g1.xyz", "wall_s": 100.0, "status": "unresolved"}
    g2 = {"guess_path": "/w/g2.xyz", "wall_s": 200.0, "status": "rejected"}
    res = {"best": g2, "history": [{"round": 0, "results": [g1, g2]}]}
    check(
        RL.attempt_wall_seconds(res) == 300.0,
        f"two guesses counted once each = 300s (got {RL.attempt_wall_seconds(res)})",
    )

    multi = {
        "best": g2,
        "history": [
            {"round": 0, "results": [g1, g2]},
            {"round": 1, "results": [{"guess_path": "/w/g3.xyz", "wall_s": 50.0}]},
        ],
    }
    check(RL.attempt_wall_seconds(multi) == 350.0, "multi-round sums across rounds = 350s")

    empty = {"best": {"wall_s": 42.0}, "history": [{"round": 0, "results": []}]}
    check(RL.attempt_wall_seconds(empty) == 42.0, "falls back to best when no per-guess record")

    check(RL.attempt_wall_seconds({"best": None, "history": []}) == 0.0, "empty result = 0s")

    print("\n== explore failure containment ==")
    # A model or endpoint failure must be reported as a zero-proposal round, not raised:
    # an exception here would abort the loop and lose the rounds already paid for.
    from unittest import mock

    with mock.patch.dict(sys.modules, {"explore": mock.Mock(run=mock.Mock(side_effect=RuntimeError("endpoint down")))}):
        got = RL.explore(template_top=2, llm_top=1)
    check(got.get("status") == "error", f"explore error is reported, not raised (got {got.get('status')})")
    check(got.get("n_proposed") == 0, "failed explore contributes zero proposals")
    check("endpoint down" in str(got.get("error")), "the underlying error is preserved for the log")

    print("\n== intra-round core-hour budget ==")
    sys.path.insert(0, str(PKG / "loop"))
    from skill_runner import budget_wall_cap  # noqa: E402

    check(budget_wall_cap(1200, 4, None, 0.0) == 1200, "no budget given = full wall clock")
    check(
        budget_wall_cap(1200, 4, 12.0, 0.0) == 1200,
        "plenty of budget left = full wall clock",
    )
    # 1.0 core-h left on 4 procs = 900s of wall clock, less than the 1200s request
    check(
        budget_wall_cap(1200, 4, 12.0, 11.0) == 900,
        f"tight budget shortens the guess to 900s (got {budget_wall_cap(1200, 4, 12.0, 11.0)})",
    )
    check(budget_wall_cap(1200, 4, 12.0, 12.0) is None, "exactly spent = do not launch")
    check(budget_wall_cap(1200, 4, 12.0, 13.0) is None, "overspent = do not launch")
    # 0.2 core-h on 4 procs = 180s, below the useful floor
    check(
        budget_wall_cap(1200, 4, 12.0, 11.8) is None,
        "remainder too small to be useful = do not launch",
    )
    # 0.2 core-h on 1 proc is ~720s; float subtraction makes the exact value 719,
    # so assert the band rather than an exact second.
    one_proc = budget_wall_cap(1200, 1, 12.0, 11.8)
    check(
        one_proc is not None and 700 <= one_proc <= 720,
        f"same remainder on 1 proc buys a usable ~720s run (got {one_proc})",
    )

    print("\n== candidate-queue writeback ==")
    tmp = Path(tempfile.mkdtemp(prefix="reaxevolve_qtest_"))
    q = tmp / "candidate_queue.json"
    json.dump(
        {
            "candidates": [
                {"reactant": "A", "product": "B", "status": "pending", "priority": 0.9},
                {"reactant": "B", "product": "C", "status": "pending", "priority": 0.5},
            ]
        },
        open(q, "w"),
    )
    results = [
        {
            "candidate": {"reactant": "A", "product": "B"},
            "result": {"status": "rejected"},
        }
    ]
    n = SEL.writeback(results, q)
    data = json.load(open(q))
    by = {(c["reactant"], c["product"]): c for c in data["candidates"]}

    check(n == 1, f"one candidate updated (got {n})")
    check(by[("A", "B")]["status"] == "rejected", "attempted candidate now carries its verdict")
    check(by[("A", "B")]["attempts"] == 1, "attempt counter incremented")
    check("last_attempt_at" in by[("A", "B")], "attempt timestamp recorded")
    check(by[("B", "C")]["status"] == "pending", "untouched candidate stays pending")

    # second attempt on the same edge must increment, not reset
    SEL.writeback([{"candidate": {"reactant": "A", "product": "B"}, "result": {"status": "unresolved"}}], q)
    data = json.load(open(q))
    by = {(c["reactant"], c["product"]): c for c in data["candidates"]}
    check(by[("A", "B")]["attempts"] == 2, "repeat attempt increments to 2")

    # a candidate whose driver returned nothing must not silently stay pending
    SEL.writeback([{"candidate": {"reactant": "B", "product": "C"}, "result": {}}], q)
    data = json.load(open(q))
    by = {(c["reactant"], c["product"]): c for c in data["candidates"]}
    check(by[("B", "C")]["status"] == "unresolved", "status-less result recorded as unresolved")

    print("\n== cache cost is what the arm budget reads ==")
    sys.path.insert(0, str(PKG / "loop"))
    sys.path.insert(0, str(PKG / "scripts" / "eval"))
    import skill_runner as SR  # noqa: E402
    import arm_runner as AR  # noqa: E402

    dest = Path(tempfile.mkdtemp(prefix="reaxevolve_cost_"))
    cache = dest / "runs" / "step" / "strict_cache.json"
    cache.parent.mkdir(parents=True)
    json.dump({"C>>CC": {"status": "unresolved", "nprocs": 8}}, open(cache, "w"))
    check(AR.spent_core_h(str(dest)) == 0.0, "cache without wall_s sums to 0")
    SR._stamp_cost(str(cache), "C>>CC", 3600.0, 8)
    got = AR.spent_core_h(str(dest))
    check(got == 8.0, f"1 hour × 8 cores is 8 core-h after stamp (got {got})")

    sys.path.insert(0, str(PKG / "scripts" / "validate"))
    import verdict_writer as VW  # noqa: E402

    dest2 = Path(tempfile.mkdtemp(prefix="reaxevolve_cost2_"))
    cache2 = dest2 / "runs" / "step" / "strict_cache.json"
    cache2.parent.mkdir(parents=True)
    VW.write_strict_cache(str(cache2), "C>>CC", {"name": "g0", "nprocs": 8}, "unresolved")
    SR._stamp_cost(str(cache2), "C>>CC", 3600.0, 8)
    VW.write_strict_cache(str(cache2), "C>>CC", {"name": "g1", "nprocs": 8}, "unresolved")
    SR._stamp_cost(str(cache2), "C>>CC", 3600.0, 8)
    got2 = AR.spent_core_h(str(dest2))
    check(got2 == 16.0, f"two 8 core-h attempts on one key sum to 16 (got {got2})")

    hv = Path(tempfile.mkdtemp(prefix="reaxevolve_hv_")) / "discovered_cache.json"
    SR._harvest_perceived(
        {
            "status": "rejected",
            "reactant": "CCO",
            "product": "C=C",
            "coproduct": "O",
            "irc_fwd": "C=C.O",
            "irc_bwd": "CCO",
            "endpoint_double_ended": True,
        },
        dest=hv,
    )
    check(not hv.is_file() or json.loads(hv.read_text()) == [], "double-ended match with coproduct is not harvested")
    SR._harvest_perceived(
        {
            "status": "rejected",
            "reactant": "CCO",
            "product": "C=C",
            "irc_fwd": "CCC",
            "irc_bwd": "CC",
            "endpoint_double_ended": False,
        },
        dest=hv,
    )
    got_h = json.loads(hv.read_text()) if hv.is_file() else []
    check(len(got_h) == 1, f"true mismatch is harvested (got {len(got_h)})")

    print("\n== attempt archive keeps failure evidence ==")
    dest3 = Path(tempfile.mkdtemp(prefix="reaxevolve_arch_"))
    cache3 = dest3 / "strict_cache.json"
    VW.write_strict_cache(
        str(cache3),
        "C>>CC",
        {
            "reactant": "C",
            "product": "CC",
            "detail": "IRC_FAILED",
            "irc_fwd": None,
            "asset_versions": {"tools": {"workflow/run_qm_step.py": "v0"}},
            "wall_s": 10,
            "nprocs": 8,
        },
        "unresolved",
        "IRC_FAILED",
    )
    VW.write_strict_cache(
        str(cache3),
        "C>>CC",
        {
            "reactant": "C",
            "product": "CC",
            "detail": "WALL_TIME",
            "wall_s": 20,
            "nprocs": 8,
        },
        "unresolved",
        "WALL_TIME",
    )
    VW.write_strict_cache(
        str(cache3),
        "C>>CC",
        {
            "reactant": "C",
            "product": "CC",
            "status": "STRICT",
            "irc_fwd": "CC",
            "irc_bwd": "C",
            "wall_s": 30,
            "nprocs": 8,
        },
        "STRICT",
    )
    blob = json.load(open(cache3))
    atts = blob["C>>CC"]["attempts"]
    check(len(atts) == 3, f"three writes leave three archived attempts (got {len(atts)})")
    check(atts[0].get("detail") == "IRC_FAILED", "first failure reason is kept")
    check(
        isinstance(atts[0].get("asset_versions"), dict)
        and atts[0]["asset_versions"].get("tools"),
        "first attempt version vector is kept",
    )
    check("attempts" not in atts[0], "archived row does not nest attempts")

    print("\n== exception path still counts spent core-h ==")
    sys.path.insert(0, str(PKG / "loop"))
    import run_loop as RL2  # noqa: E402

    dead = {"status": "unresolved", "stdout": "traceback"}
    recovered = RL2._recover_result(
        dead,
        dest3,
    )
    # dest3 has no skill_runner_result; seed one
    json.dump(
        {
            "history": [{"round": 0, "results": [{"guess_path": "g.xyz", "wall_s": 3600}]}],
            "core_hours_spent": 8.0,
            "status": "unresolved",
        },
        open(dest3 / "skill_runner_result.json", "w"),
    )
    recovered = RL2._recover_result(dead, dest3)
    check(
        RL2._result_core_hours(recovered, 8) == 8.0,
        f"spent 8 core-h is recovered after a generator crash "
        f"(got {RL2._result_core_hours(recovered, 8)})",
    )

    print("\n== reused workdir does not double historical core-h or revive STRICT ==")
    reuse = Path(tempfile.mkdtemp(prefix="reaxevolve_reuse_"))
    old_t = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - 86400))
    json.dump(
        {
            "C>>CC": {
                "status": "STRICT",
                "wall_s": 3600,
                "nprocs": 8,
                "time": old_t,
                "attempts": [
                    {"status": "STRICT", "wall_s": 3600, "nprocs": 8, "time": old_t},
                ],
            }
        },
        open(reuse / "strict_cache.json", "w"),
    )
    json.dump(
        {
            "status": "STRICT",
            "core_hours_spent": 8.0,
            "history": [{"round": 0, "results": [{"guess_path": "g.xyz", "wall_s": 3600}]}],
        },
        open(reuse / "skill_runner_result.json", "w"),
    )
    crash = {"status": "unresolved", "stdout": "died"}
    recovered2 = RL2._recover_result(crash, reuse, invocation_id="run-2")
    check(
        RL2._result_core_hours(recovered2, 8) == 0.0,
        f"stale 8 core-h from a previous launch is not added "
        f"(got {RL2._result_core_hours(recovered2, 8)})",
    )
    check(
        recovered2.get("status") != "STRICT" or recovered2 is crash,
        "a leftover STRICT result is not returned for this launch",
    )
    stale = SR.load_result_if_this_run(reuse / "skill_runner_result.json", "run-2")
    check(stale == {}, "skill_runner ignores a previous invocation's STRICT file")

    json.dump(
        {
            "status": "STRICT",
            "invocation_id": "run-1",
            "core_hours_spent": 8.0,
            "history": [{"round": 0, "results": [{"guess_path": "g.xyz", "wall_s": 3600}]}],
        },
        open(reuse / "skill_runner_result.json", "w"),
    )
    os.utime(reuse / "skill_runner_result.json", None)
    quick = RL2._recover_result(
        {"status": "unresolved"}, reuse, invocation_id="run-2"
    )
    check(
        RL2._result_core_hours(quick, 8) == 0.0,
        f"a same-second leftover 8 core-h is not billed again "
        f"(got {RL2._result_core_hours(quick, 8)})",
    )
    json.dump(
        {
            "C>>CC": {
                "status": "unresolved",
                "attempts": [
                    {"wall_s": 3600, "nprocs": 8, "time": "2026-10-25 12:00",
                     "invocation_id": "run-1"},
                    {"wall_s": 3600, "nprocs": 8, "time": "2026-10-25 13:00",
                     "invocation_id": "run-1"},
                ],
            }
        },
        open(reuse / "strict_cache.json", "w"),
    )
    (reuse / "skill_runner_result.json").unlink()
    minute = RL2._recover_result(
        {"status": "unresolved"}, reuse, invocation_id="run-2"
    )
    check(
        RL2._result_core_hours(minute, 8) == 0.0,
        f"minute-resolution history without this id is not recovered "
        f"(got {RL2._result_core_hours(minute, 8)})",
    )
    this = RL2._recover_result(
        {"status": "unresolved"}, reuse, invocation_id="run-1"
    )
    check(
        RL2._result_core_hours(this, 8) == 16.0,
        f"both attempts of this invocation are recovered "
        f"(got {RL2._result_core_hours(this, 8)})",
    )

    print("\n== driver label follows the running tree ==")
    dest_v0 = Path(tempfile.mkdtemp(prefix="reaxevolve_drv0_"))
    (dest_v0 / "tools").mkdir()
    json.dump(
        {"tools": {"workflow/run_qm_step.py": "v0"}},
        open(dest_v0 / "tools" / "VERSIONS.json", "w"),
    )
    check(
        SR._run_qm_step_label(dest_v0) == "run_qm_step.v0",
        "explicit root with VERSIONS v0 is run_qm_step.v0",
    )
    dest_v1 = Path(tempfile.mkdtemp(prefix="reaxevolve_drv1_"))
    (dest_v1 / "tools").mkdir()
    json.dump(
        {"tools": {"workflow/run_qm_step.py": "v1"}},
        open(dest_v1 / "tools" / "VERSIONS.json", "w"),
    )
    check(
        SR._run_qm_step_label(dest_v1) == "run_qm_step.v1",
        "explicit root with VERSIONS v1 is run_qm_step.v1",
    )
    prev = os.getcwd()
    try:
        os.chdir(dest_v0)
        check(
            SR._run_qm_step_label() == "run_qm_step.v0",
            "cwd VERSIONS v0 wins over the live tree",
        )
    finally:
        os.chdir(prev)

    print("\n==== SUMMARY ====")
    if FAILS:
        print(f"{len(FAILS)} failure(s):")
        for f in FAILS:
            print(" -", f)
        return 1
    print("ALL ACCOUNTING CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
