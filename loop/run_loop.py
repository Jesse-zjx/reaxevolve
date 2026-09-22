#!/usr/bin/env python3
"""Main loop: Explore → Validate → Remember → Reflect.

One agentic loop. Network growth is a by-product of looking for deliverable routes;
there is no second driver and no batch expansion mode.

Stop when any of:
  1) every human-set target has a STRICT route from a glucose seed
     (`--stop-on-targets any` to stop at the first one)
  2) cumulative core-hours >= budget
  3) the preregistered saturation rule fires (`loop/saturation.py`, K and eps from
     `preregistration/panel.json`), which is the rule the method commits to
  4) `--idle-stop` consecutive rounds with neither a new STRICT edge nor an asset revision —
     an operational brake, not the preregistered criterion; it is reported separately so the
     two are never conflated

Acceptance is `policy/acceptance/STRICT.md` (v5) only, written solely by
`scripts/validate/verdict_writer.py`. Everything in this file is scheduling.

Usage:
  python loop/run_loop.py --rounds 24 --budget-hours 10000 --top 8 --cap 4
  python loop/run_loop.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG / "scripts" / "lib"))
sys.path.insert(0, str(PKG / "loop"))
import chem_paths as CP  # noqa: E402

CP.bootstrap()

HIST = PKG / "evidence" / "state" / "loop"
HIST.mkdir(parents=True, exist_ok=True)
METRICS = HIST / "loop_metrics.jsonl"
LOG = HIST / "loop.log"
BUNDLE = HIST / "reflect_bundle.json"
CORE_HOURS = HIST / "core_hours.json"


def log(*a):
    m = time.strftime("[%Y-%m-%d %H:%M:%S] ") + " ".join(str(x) for x in a)
    print(m, flush=True)
    open(LOG, "a").write(m + "\n")


def append_jsonl(path, rec):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def load_core_hours() -> float:
    if CORE_HOURS.is_file():
        try:
            return float(json.load(open(CORE_HOURS)).get("core_hours") or 0.0)
        except Exception:
            return 0.0
    return 0.0


def add_core_hours(delta: float):
    cur = load_core_hours() + float(delta)
    json.dump(
        {"core_hours": cur, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
        open(CORE_HOURS, "w"),
        indent=2,
    )
    return cur


def network_meta() -> dict:
    path = PKG / "graph" / "canonical" / "reaction_network.json"
    if not path.is_file():
        return {}
    try:
        return json.load(open(path)).get("meta") or {}
    except Exception:
        return {}


def count_strict() -> int:
    return int(network_meta().get("n_strict") or 0)


def targets_reached(mode: str = "all") -> bool:
    reach = network_meta().get("targets_reachable_strict") or {}
    if not reach:
        return False
    return any(reach.values()) if mode == "any" else all(reach.values())


def saturation_state() -> dict:
    """Preregistered stopping rule, evaluated against the recorded metrics."""
    try:
        import saturation as SAT  # noqa: WPS433

        return SAT.evaluate()
    except Exception as exc:  # a broken rule must not silently become "never stop"
        log("saturation check failed:", str(exc)[:200])
        return {"saturated": False, "which_fired": None, "error": str(exc)[:200]}


def evo_log_len() -> int:
    p = PKG / "evolution" / "EVOLUTION_LOG.jsonl"
    if not p.is_file():
        return 0
    return sum(1 for line in open(p) if line.strip())


def explore(template_top: int, llm_top: int, dry: bool = False, use_llm: bool = True) -> dict:
    import explore as EX  # noqa: WPS433

    try:
        return EX.run(
            template_top=template_top, llm_top=llm_top, dry_run=dry, use_llm=use_llm
        )
    except Exception as exc:
        return {"status": "error", "stage": "explore", "n_proposed": 0, "error": str(exc)[:1000]}


def attempt_wall_seconds(res: dict) -> float:
    """Wall seconds actually spent on QM for one candidate, counting each guess once.

    `best` is a reference to one of the history results, so adding it separately would
    inflate the core-hour meter and trip the budget stop early.
    """
    wall = 0.0
    counted: set[str] = set()
    for h in res.get("history") or []:
        for i, rr in enumerate(h.get("results") or []):
            key = rr.get("guess_path") or f"{h.get('round')}:{i}"
            if key in counted:
                continue
            counted.add(key)
            wall += float(rr.get("wall_s") or 0)
    if not counted:
        # generator produced nothing per-guess — fall back to the single best record
        wall = float((res.get("best") or {}).get("wall_s") or 0)
    return wall


def validate(
    top: int,
    cap: int,
    max_rounds: int,
    nprocs: int,
    wall_s: int,
    budget_hours: float | None = None,
    max_attempts: int = 3,
) -> dict:
    import select_candidates as SEL  # noqa: WPS433

    info = SEL.analyze(max_attempts=max_attempts)
    picked = SEL.select(top=top, info=info)
    log(
        "select",
        f"queue={info.get('n_queue')}",
        f"eligible={info.get('n_eligible')}",
        f"dropped_unbalanced={info.get('n_dropped_unbalanced')}",
        f"dropped_exhausted={info.get('n_dropped_exhausted')}",
    )

    results = []
    n_done = 0
    budget_stop = False
    for c in picked:
        if n_done >= cap:
            break

        # Hard budget bound. Checking only between rounds let a single round overshoot by
        # however long its guesses happened to run, so the remaining allowance is
        # recomputed here and handed down to cap each guess.
        remaining_core_h = None
        if budget_hours is not None:
            remaining_core_h = budget_hours - load_core_hours()
            if remaining_core_h <= 0:
                log(f"budget exhausted mid-round ({load_core_hours():.2f}/{budget_hours} core-h)")
                budget_stop = True
                break

        rid = c.get("edge_id") or f"step_{n_done}"
        wd = PKG / "runs" / "validation" / rid
        cmd = [
            CP.PYBIN,
            str(PKG / "loop" / "skill_runner.py"),
            "--reactant-smiles",
            c["reactant"],
            "--product-smiles",
            c["product"],
            "--workdir",
            str(wd),
            "--max-rounds",
            str(max_rounds),
            "--nprocs",
            str(nprocs),
            "--wall-s",
            str(wall_s),
        ]
        if remaining_core_h is not None:
            cmd += ["--budget-core-h", f"{remaining_core_h:.4f}"]
        if c.get("coproduct"):
            cmd += ["--coproduct", c["coproduct"]]
        log(
            "validate",
            rid,
            c.get("kind"),
            f"score={c.get('_score'):+.2f}" if c.get("_score") is not None else "",
            f"att={c.get('attempts') or 0}",
            c["reactant"][:40],
            "->",
            c["product"][:40],
            f"(budget left {remaining_core_h:.2f} core-h)" if remaining_core_h is not None else "",
        )
        r = subprocess.run(cmd, cwd=str(PKG), text=True, capture_output=True)
        try:
            res = json.loads(r.stdout)
        except json.JSONDecodeError:
            res = {"status": "unresolved", "stdout": r.stdout[-2000:], "stderr": r.stderr[-2000:]}
        add_core_hours(nprocs * attempt_wall_seconds(res) / 3600.0)
        c["status"] = res.get("status") or "unresolved"
        results.append({"candidate": c, "result": res})
        n_done += 1

    n_written = SEL.writeback(results)
    return {
        "n_validated": n_done,
        "results": results,
        "queue_updated": n_written,
        "budget_stop": budget_stop,
        "select_info": {k: v for k, v in info.items() if k not in ("candidates", "dropped")},
    }


def remember() -> dict:
    # Freeze per-run judgements into verdicts.jsonl before rebuilding, so the committed
    # evidence stream does not depend on gitignored runs/ scratch.
    subprocess.run(
        [CP.PYBIN, str(PKG / "scripts" / "reflect" / "consolidate_verdicts.py")],
        cwd=str(PKG),
        text=True,
        capture_output=True,
        check=False,
    )
    r = subprocess.run(
        [CP.PYBIN, str(PKG / "scripts" / "graph" / "build_reaction_network.py")],
        cwd=str(PKG),
        text=True,
        capture_output=True,
    )
    try:
        summary = json.loads(r.stdout)
    except json.JSONDecodeError:
        summary = {"raw": r.stdout, "rc": r.returncode}
    exp_dir = PKG / "evidence" / "memory" / "experience"
    exp_dir.mkdir(parents=True, exist_ok=True)
    append_jsonl(
        exp_dir / "experience.jsonl",
        {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "kind": "remember",
            "summary": summary,
        },
    )
    return summary


def reflect(enable_fully_auto: bool) -> dict:
    from reflect import run as make_reflect_bundle  # noqa: WPS433

    bundle = make_reflect_bundle(bundle_path=str(BUNDLE))
    out = {
        "bundle": str(BUNDLE),
        "fully_auto": None,
        "must_revise": (bundle.get("reflect_pressure") or {}).get("must_revise"),
    }
    if enable_fully_auto:
        fa = PKG / "loop" / "fully_auto" / "run_fully_auto_reflect.py"
        if fa.is_file():
            # --apply is what makes Reflect actually evolve assets; apply_revision
            # enforces the whitelist and rolls back on syntax/smoke failure.
            r = subprocess.run(
                [CP.PYBIN, str(fa), "--apply", "--smoke"],
                cwd=str(PKG),
                text=True,
                capture_output=True,
            )
            out["fully_auto"] = {"rc": r.returncode, "stdout": (r.stdout or "")[-2000:]}
    audit = PKG / "scripts" / "qa" / "isolation_audit.py"
    if audit.is_file():
        # Capture: an uncaptured child writes onto this process's stdout, and a caller
        # parsing our JSON then sees two concatenated documents and reports a failure.
        r = subprocess.run(
            [CP.PYBIN, str(audit)], cwd=str(PKG), text=True, capture_output=True, check=False
        )
        out["isolation_audit"] = {
            "rc": r.returncode,
            "clean": r.returncode == 0,
            "report": "evidence/audit/ISOLATION_AUDIT.md",
        }
        if r.returncode not in (0, 1):
            log("isolation audit error:", (r.stderr or "")[-300:])
        elif r.returncode == 1:
            log("isolation audit: VIOLATIONS — see evidence/audit/ISOLATION_AUDIT.md")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rounds", type=int, default=6)
    ap.add_argument("--budget-hours", type=float, default=10000.0)
    ap.add_argument("--top", type=int, default=8, help="candidates considered per round")
    ap.add_argument("--cap", type=int, default=4, help="candidates actually validated per round")
    ap.add_argument("--max-rounds-per-step", type=int, default=2)
    ap.add_argument("--nprocs", type=int, default=16)
    ap.add_argument("--wall-s", type=int, default=5400)
    ap.add_argument(
        "--idle-stop",
        type=int,
        default=3,
        help="operational brake: stop after this many rounds with neither a new STRICT edge nor "
        "an asset revision. Not the preregistered criterion; reported as a separate reason.",
    )
    ap.add_argument(
        "--no-saturation-stop",
        action="store_true",
        help="keep running past the preregistered saturation point (diagnostics only; the "
        "protocol licenses freezing the assets once it fires)",
    )
    ap.add_argument("--template-top", type=int, default=24, help="template candidates landed / round")
    ap.add_argument("--llm-top", type=int, default=4, help="LLM hypotheses requested / round")
    ap.add_argument("--no-llm", action="store_true", help="template Explore only (no API spend)")
    ap.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="retries allowed per candidate edge before it is retired; >1 is what makes "
        "'the same edge passed after the asset changed' observable",
    )
    ap.add_argument(
        "--stop-on-targets",
        choices=("all", "any", "never"),
        default="all",
        help="success stop: every target has a STRICT route, the first one does, or never",
    )
    ap.add_argument("--fully-auto", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-validate", action="store_true")
    a = ap.parse_args()

    man = PKG / "scripts" / "qa" / "run_manifest.py"

    def manifest(event: str):
        # Captured for the same reason as the isolation audit: an uncaptured child writes
        # onto this process's stdout and corrupts anything parsing our output.
        if man.is_file():
            subprocess.run(
                [CP.PYBIN, str(man), "--event", event],
                cwd=str(PKG), text=True, capture_output=True, check=False,
            )

    manifest("loop_start")

    log(
        f"run_loop start rounds={a.rounds} budget_h={a.budget_hours} top={a.top} "
        f"cap={a.cap} idle_stop={a.idle_stop} stop_on_targets={a.stop_on_targets}"
    )

    if a.dry_run:
        ex = explore(a.template_top, a.llm_top, dry=True, use_llm=not a.no_llm)
        ref = reflect(False)
        tpl = ex.get("template") or {}
        log(
            "dry-run explore:",
            ex.get("status"),
            f"frontier={tpl.get('n_frontier')}",
            f"enumerated={tpl.get('n_enumerated')}",
            f"kinds={tpl.get('by_kind')}",
            f"llm={(ex.get('llm') or {}).get('status')}",
        )
        log("dry-run reflect bundle:", ref.get("bundle"))
        log("no hypotheses written, no QM launched")
        return 0

    idle = 0
    for i in range(a.rounds):
        strict_before = count_strict()
        evo_before = evo_log_len()
        log(f"=== round {i+1}/{a.rounds} strict={strict_before} core_h={load_core_hours():.2f} ===")

        ex = explore(a.template_top, a.llm_top, use_llm=not a.no_llm)
        log(
            "explore",
            ex.get("status"),
            f"n={ex.get('n_proposed')}",
            f"(template={ex.get('n_from_template')} llm={ex.get('n_from_llm')})",
        )

        if a.skip_validate:
            val = {"n_validated": 0, "results": [], "skipped": True}
        else:
            val = validate(
                a.top,
                a.cap,
                a.max_rounds_per_step,
                a.nprocs,
                a.wall_s,
                budget_hours=a.budget_hours,
                max_attempts=a.max_attempts,
            )
            log("validate", "n=", val.get("n_validated"), "queue_updated=", val.get("queue_updated"))

        rem = remember()
        log("remember", json.dumps(rem, ensure_ascii=False)[:400])

        ref = reflect(a.fully_auto)
        log("reflect", "bundle", ref.get("bundle"))

        meta = network_meta()
        strict_after = count_strict()
        evo_after = evo_log_len()
        d_strict = strict_after - strict_before
        d_evo = evo_after - evo_before
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "round": i + 1,
            "d_strict": d_strict,
            "d_evo": d_evo,
            "strict": strict_after,
            "core_hours": load_core_hours(),
            "targets_reachable_strict": meta.get("targets_reachable_strict"),
            "strict_distance_to_targets": meta.get("strict_distance_to_targets"),
            "explore_n": ex.get("n_proposed"),
            "explore_template_n": ex.get("n_from_template"),
            "explore_llm_n": ex.get("n_from_llm"),
            "validated_n": val.get("n_validated"),
        }
        append_jsonl(METRICS, rec)

        if a.stop_on_targets != "never" and targets_reached(a.stop_on_targets):
            log(f"STOP: targets reached ({a.stop_on_targets}) — {meta.get('targets_reachable_strict')}")
            break
        if load_core_hours() >= a.budget_hours:
            log("STOP: core-hour budget exhausted")
            break

        # The preregistered criterion. Evaluated after the metrics row is written, so it reads
        # this round too. `which_fired` is logged because stopping on zero growth is a weaker
        # statement than stopping because growth became small.
        sat = saturation_state()
        rec["saturation"] = {k: sat.get(k) for k in ("saturated", "which_fired", "rounds_available")}
        if sat.get("saturated") and not a.no_saturation_stop:
            log(f"STOP: preregistered saturation rule fired ({sat.get('which_fired')}) — "
                f"K={sat.get('K')} eps={sat.get('epsilon')}")
            log("      freezing the asset set is now licensed; see preregistration/")
            break

        if d_strict == 0 and d_evo == 0:
            idle += 1
        else:
            idle = 0
        if idle >= a.idle_stop:
            log(f"STOP: operational brake — {idle} idle rounds (no STRICT, no asset revision). "
                f"This is not the preregistered saturation criterion.")
            break

    manifest("loop_end")

    meta = network_meta()
    final = {
        "strict": count_strict(),
        "core_hours": load_core_hours(),
        "targets_reachable_strict": meta.get("targets_reachable_strict"),
        "strict_distance_to_targets": meta.get("strict_distance_to_targets"),
        "metrics": str(METRICS),
    }
    print(json.dumps(final, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
