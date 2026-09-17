#!/usr/bin/env python3
"""Stage-2 entry: bundle → LLM propose → apply (whitelist) → optional short loop."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, PKG)
sys.path.insert(0, HERE)

from client import propose  # noqa: E402
from loop.reflect import run as make_bundle  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="apply proposal if revise")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--rerun-loop-dry", action="store_true")
    a = ap.parse_args()

    out_dir = os.path.join(PKG, "evidence", "state", "loop", "fully_auto_runs")
    os.makedirs(out_dir, exist_ok=True)
    tag = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    bundle = make_bundle(
        bundle_path=os.path.join(out_dir, f"{tag}_bundle.json")
    )
    prop = propose(bundle)
    prop_path = os.path.join(out_dir, f"{tag}_proposal.json")
    json.dump(prop, open(prop_path, "w"), indent=2)
    result = {"bundle": bundle, "proposal": prop, "applied": False}
    if a.apply and prop.get("action") == "revise":
        cmd = [
            sys.executable,
            os.path.join(HERE, "apply_revision.py"),
            "--proposal",
            prop_path,
        ]
        if a.smoke:
            cmd.append("--smoke")
        r = subprocess.run(cmd, cwd=PKG, capture_output=True, text=True)
        result["apply_stdout"] = r.stdout
        result["apply_rc"] = r.returncode
        result["applied"] = r.returncode == 0
    if a.rerun_loop_dry:
        r = subprocess.run(
            [sys.executable, os.path.join(PKG, "loop", "run_loop.py"), "--dry-run"],
            cwd=PKG,
            capture_output=True,
            text=True,
        )
        result["loop_dry_rc"] = r.returncode
        result["loop_dry_tail"] = (r.stdout or "")[-1000:]
    out = os.path.join(out_dir, f"{tag}_result.json")
    json.dump(result, open(out, "w"), indent=2, default=str)
    print(json.dumps({"result": out, "action": prop.get("action")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
