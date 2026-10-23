#!/usr/bin/env python3
"""Reflect user JSON must keep the bundle whole. No final-string slice, no disk hints."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PKG = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG / "loop" / "fully_auto"))

import client as FA  # noqa: E402

FAILS: list[str] = []


def check(cond, msg):
    if cond:
        print(f"  OK  {msg}")
    else:
        print(f" FAIL {msg}")
        FAILS.append(msg)


def _tiny_tree() -> Path:
    root = Path(tempfile.mkdtemp(prefix="reaxevolve_reflect_"))
    (root / ".skills" / "alpha").mkdir(parents=True)
    (root / ".skills" / "beta").mkdir(parents=True)
    (root / "tools" / "guess").mkdir(parents=True)
    (root / ".skills" / "alpha" / "SKILL.md").write_text("alpha skill\n")
    (root / ".skills" / "beta" / "SKILL.md").write_text("beta skill, a bit longer\n")
    (root / "tools" / "guess" / "tiny.py").write_text("print(1)\n")
    (root / "tools" / "guess" / "huge.py").write_text("X" * 80000 + "\n")
    json.dump(
        {"tools": {"guess/tiny.py": "v1", "guess/huge.py": "v1"}},
        open(root / "tools" / "VERSIONS.json", "w"),
    )
    return root


def main() -> int:
    print("== packer keeps a complete bundle ==")
    bundle = {
        "time": "2026-10-23T00:00:00Z",
        "reflect_pressure": {"must_revise": True, "reason": "no STRICT this window"},
        "failure_digest": {"no_endpoint_record": 3, "stale_path_reference": 1},
    }
    tree = _tiny_tree()
    user = FA._user_message(bundle, pkg=str(tree), budget=20000)
    payload = json.loads(user)
    check(payload["bundle"] == bundle, "bundle survives packing intact")
    check(
        payload["bundle"]["reflect_pressure"]["must_revise"] is True,
        "must_revise is still present",
    )
    check("read the file on disk" not in user, "no disk-read hint")
    check("truncated" not in user.lower(), "no truncated-file marker")
    files = payload["live_assets"]["files"]
    omitted = payload["live_assets"]["omitted_files"]
    check(".skills/alpha/SKILL.md" in files, "small skill fits")
    check("tools/guess/huge.py" not in files, "file that would break the budget is omitted whole")
    check("tools/guess/huge.py" in omitted, "omitted path is listed")
    for rel, text in files.items():
        disk = (tree / rel).read_text()
        check(text == disk, f"{rel} is the complete file, not a slice")

    print("\n== live tree + small bundle stays valid JSON ==")
    live = FA._user_message(bundle)
    live_payload = json.loads(live)
    check(live_payload["bundle"] == bundle, "live inventory does not drop the bundle")
    check("read the file on disk" not in live, "live payload has no disk-read hint")
    check("[:120000]" not in Path(FA.__file__).read_text(), "client no longer slices the final JSON")
    for rel, text in live_payload["live_assets"]["files"].items():
        disk = PKG / rel
        if disk.is_file():
            check(text == disk.read_text(errors="replace"), f"live {rel} is complete")

    print("\n==== SUMMARY ====")
    if FAILS:
        print(f"{len(FAILS)} failure(s):")
        for f in FAILS:
            print(" -", f)
        return 1
    print("ALL REFLECT PAYLOAD CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
