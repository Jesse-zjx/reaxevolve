#!/usr/bin/env python3
"""Record / update the genesis run manifest (model, pi, bar, asset versions, core-h)."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

PKG = Path(__file__).resolve().parents[2]
MANIFEST = PKG / "evidence" / "state" / "RUN_MANIFEST.json"


def pi_version() -> str:
    pi = PKG / "node_modules" / ".bin" / "pi"
    if not pi.exists():
        return "missing"
    try:
        return subprocess.check_output([str(pi), "--version"], text=True).strip()
    except Exception as e:
        return f"error:{e}"


def load_env_model() -> dict:
    env_path = PKG / ".env"
    out = {"MODEL_NAME": None, "BASE_URL_host": None, "has_api_key": False}
    if not env_path.is_file():
        return out
    for line in env_path.read_text().splitlines():
        if "=" not in line or line.strip().startswith("#"):
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if k == "MODEL_NAME":
            out["MODEL_NAME"] = v
        elif k == "BASE_URL":
            host = v.split("//")[-1].split("/")[0]
            out["BASE_URL_host"] = host
        elif k == "API_KEY" and v:
            out["has_api_key"] = True
    return out


def asset_versions() -> dict:
    p = PKG / "tools" / "VERSIONS.json"
    if p.is_file():
        return json.load(open(p))
    return {}


def bar_version() -> str:
    p = PKG / "policy" / "acceptance" / "VERSION"
    return p.read_text().strip() if p.is_file() else "unknown"


def _git_head() -> str | None:
    if not (PKG / ".git").exists():
        return None
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(PKG),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError:
        return None  # empty repo, no commits yet


def core_hours() -> float:
    p = PKG / "evidence" / "state" / "loop" / "core_hours.json"
    if p.is_file():
        try:
            return float(json.load(open(p)).get("core_hours") or 0)
        except Exception:
            return 0.0
    return 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--event", default="update", help="loop_start|loop_end|update")
    a = ap.parse_args()

    prev = {}
    if MANIFEST.is_file():
        try:
            prev = json.load(open(MANIFEST))
        except json.JSONDecodeError:
            prev = {}

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    env = load_env_model()
    man = {
        "workspace": str(PKG),
        "event": a.event,
        "updated_at": now,
        "started_at": prev.get("started_at") if a.event != "loop_start" else now,
        "ended_at": now if a.event == "loop_end" else prev.get("ended_at"),
        "pi_version": pi_version(),
        "strict_bar_version": bar_version(),
        "model": env,
        "asset_versions": asset_versions(),
        "core_hours": core_hours(),
        "git_head": _git_head(),
    }
    if a.event == "loop_start" or not prev.get("started_at"):
        man["started_at"] = now
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    json.dump(man, open(MANIFEST, "w"), indent=2)
    open(MANIFEST, "a").write("\n")
    print(json.dumps(man, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
