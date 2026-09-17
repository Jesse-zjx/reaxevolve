#!/usr/bin/env python3
"""Explore stage — two paths, one queue.

Path A (`explore_templates.py`) enumerates the confirmed frontier with reaction
templates: cheap, deterministic, atom-conserving by construction, and broad. It runs
first so the queue is filled before any model tokens are spent.

Path B (`explore_llm.py`) is then handed path A's coverage report and asked for the
complement — steps the template SMARTS cannot express (concerted aromatization, hydride
shifts, skeletal rearrangements), preferentially from species where path A has already
run out of options.

Both paths write through `scripts/graph/add_hypothesis.py`, so both pass the same
atom-conservation gate and land in the same `candidate_queue.json` with the same schema.
Selection afterwards does not care which path produced a candidate — only what it scored
(`loop/select_candidates.py`).

Usage:
  python loop/explore.py [--template-top 24] [--llm-top 4] [--dry-run] [--no-llm]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PKG, "scripts", "lib"))
sys.path.insert(0, os.path.join(PKG, "loop"))
import chem_paths as CP  # noqa: E402

CP.bootstrap()

STATE = os.path.join(PKG, "evidence", "state", "loop")
LAST = os.path.join(STATE, "explore_last.json")


def run(
    template_top: int = 24,
    llm_top: int = 4,
    dry_run: bool = False,
    use_llm: bool = True,
) -> dict:
    import explore_templates as ET  # noqa: WPS433

    tpl = ET.run(top=template_top, dry_run=dry_run)

    llm = {"path": "llm", "status": "skipped", "n_proposed": 0}
    if use_llm:
        import explore_llm as EL  # noqa: WPS433

        try:
            llm = EL.run(top=llm_top, dry_run=dry_run, template_report=tpl)
        except Exception as exc:  # a model/endpoint failure must not kill the round
            llm = {"path": "llm", "status": "error", "n_proposed": 0, "error": str(exc)[:500]}

    n_tpl = int(tpl.get("n_landed") or 0)
    n_llm = int(llm.get("n_proposed") or 0)
    out = {
        "status": "ok" if tpl.get("status") == "ok" else "error",
        "stage": "explore",
        "n_proposed": n_tpl + n_llm,
        "n_from_template": n_tpl,
        "n_from_llm": n_llm,
        "template": {k: v for k, v in tpl.items() if k != "results"},
        "llm": {k: v for k, v in llm.items() if k not in ("results", "summary_before")},
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if not dry_run:
        os.makedirs(STATE, exist_ok=True)
        # Machine contract for run_loop: prefer this file over stdout parsing, because
        # child tools have leaked JSON onto stdout and made a good stage look failed.
        with open(LAST, "w") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
            f.write("\n")
        with open(os.path.join(STATE, "explore.jsonl"), "a") as f:
            f.write(json.dumps(out, ensure_ascii=False) + "\n")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--template-top", type=int, default=24)
    ap.add_argument("--llm-top", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-llm", action="store_true", help="template path only (no API spend)")
    a = ap.parse_args()
    out = run(
        template_top=a.template_top,
        llm_top=a.llm_top,
        dry_run=a.dry_run,
        use_llm=not a.no_llm,
    )
    print(json.dumps(out, indent=2, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
