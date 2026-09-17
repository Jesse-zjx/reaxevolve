#!/usr/bin/env python3
"""Post-hoc isolation audit: the main loop must stay inside this repository.

Scans agent session logs and loop logs for absolute paths outside the allowed roots.
There is no hard sandbox, so this is the only check; it is run every Reflect round by
`loop/run_loop.py`.

Two things it protects:

1. **Self-containment.** The repository plus the ORCA/xTB toolchain is all the loop may
   read. A result that depended on a path outside it would not be reproducible from a
   clone.
2. **The held-out evaluation set.** `TSBench-main/benchmark` and `TSBench-main/results`
   hold the reaction manifest, reference transition states and published per-model
   scores. The loop must never read them, or the transfer evaluation in `tsbench/` stops
   being held out. Supplementary TSBench runs are driven from `tsbench/` and are not
   part of the main loop.

Allowed roots:
  - this repository
  - ORCA_DIR, the xTB tree, conda/miniforge, ordinary system paths

Forbidden (always red):
  - TSBench-main/{benchmark,results}          — held-out evaluation set
  - other agents' session transcripts
  - any prior campaign workspace or backup tree
"""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

PKG = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG / "scripts" / "lib"))
import chem_paths as CP  # noqa: E402

ABS_PATH_RE = re.compile(r"(/(?:root|home|opt|var|srv|tmp|usr|lib|bin|etc)[^\s\"'`<>]+)")

FORBIDDEN_SUBSTR = [
    # Held-out evaluation set: manifest, reference TS geometries, published scores.
    "/TSBench-main/benchmark",
    "/TSBench-main/results",
    "TSBench/benchmark",
    "TSBench/results",
    # Other agents' transcripts, prior campaign trees, backups.
    "/agent-transcripts",
    "/inno-agent/backups",
    "/workspaces/chem-discovery",
    "/workspaces/chem-genesis",
    "/OpenAgentHarness",
]

ALLOWED_PREFIXES = [
    str(PKG),
    CP.ORCA_DIR,
    os.path.dirname(CP.XTB_BIN),
    "/root/xtb",
    "/root/miniforge3",
    "/root/conda",
    "/usr",
    "/lib",
    "/lib64",
    "/bin",
    "/sbin",
    "/etc",
    "/tmp",
    "/proc",
    "/dev",
    "/var/tmp",
    str(Path.home() / ".cache"),  # pip/rdkit caches sometimes
]


def allowed(path: str) -> bool:
    # normalize
    p = path.rstrip(".,;:)'\"")
    for bad in FORBIDDEN_SUBSTR:
        if bad in p:
            return False
    for pref in ALLOWED_PREFIXES:
        if pref and p.startswith(pref):
            return True
    # node_modules and .agentcfg live under PKG and are already covered by it.
    return False


SCAN_SUFFIXES = {
    ".jsonl",
    ".log",
    ".txt",
    ".json",
    ".md",
    ".out",   # ORCA stdout records every path it touched
    ".inp",
    ".sh",
    ".xyz",
}
MAX_SCAN_BYTES = 200 * 1024 * 1024


def scan_file(path: Path) -> list[dict]:
    """Line-stream the file so large ORCA outputs are covered without loading them."""
    hits = []
    try:
        fh = path.open("r", errors="ignore")
    except OSError:
        return hits
    with fh:
        for i, line in enumerate(fh, 1):
            for m in ABS_PATH_RE.finditer(line):
                p = m.group(1).rstrip(".,;:)'\"")
                if not p.startswith("/") or len(p) < 6:
                    continue
                if not allowed(p):
                    hits.append(
                        {"file": str(path), "line": i, "path": p, "snippet": line[:240].rstrip()}
                    )
    return hits


def _legacy_scan_file(path: Path) -> list[dict]:
    hits = []
    try:
        text = path.read_text(errors="ignore")
    except OSError:
        return hits
    for i, line in enumerate(text.splitlines(), 1):
        for m in ABS_PATH_RE.finditer(line):
            p = m.group(1).rstrip(".,;:)'\"")
            if not p.startswith("/"):
                continue
            # skip ultra-short / noise
            if len(p) < 6:
                continue
            if not allowed(p):
                hits.append({"file": str(path), "line": i, "path": p, "snippet": line[:240]})
    return hits


def main() -> int:
    # Main-loop artifacts only. `tsbench/` is the supplementary evaluation lane and is
    # expected to reference the local TSBench checkout, so auditing it would report the
    # thing it is allowed to do; the point of this audit is that the *loop* never did.
    roots = [
        PKG / ".agentcfg" / "sessions",
        PKG / "evidence" / "state" / "loop",
        PKG / "runs",
    ]
    files: list[Path] = []
    skipped: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            files.append(root)
            continue
        for p in root.rglob("*"):
            if p.is_file() and p.suffix in SCAN_SUFFIXES:
                if p.stat().st_size > MAX_SCAN_BYTES:
                    skipped.append(str(p))
                    continue
                files.append(p)

    all_hits = []
    for f in files:
        all_hits.extend(scan_file(f))

    out = PKG / "evidence" / "audit" / "ISOLATION_AUDIT.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Isolation audit",
        "",
        f"- time: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        f"- workspace: `{PKG}`",
        f"- files_scanned: {len(files)}",
        f"- files_skipped_too_large: {len(skipped)}",
        f"- suffixes: {' '.join(sorted(SCAN_SUFFIXES))}",
        f"- violations: {len(all_hits)}",
        "",
    ]
    if skipped:
        lines += ["### Skipped (over size cap — not audited)", ""]
        lines += [f"- `{s}`" for s in skipped[:20]]
        lines.append("")
    if not all_hits:
        lines += [
            "## Result: CLEAN",
            "",
            "No out-of-whitelist absolute paths found in scanned artifacts.",
            "",
            "Scope note: this detects *references* to forbidden paths recorded in session logs,",
            "loop state, and ORCA scratch. There is no kernel-level sandbox, so an access that",
            "left no textual trace would not appear here.",
            "",
        ]
    else:
        lines += ["## Result: VIOLATIONS", ""]
        for h in all_hits[:200]:
            lines.append(f"- `{h['path']}` @ `{h['file']}:{h['line']}`")
            lines.append(f"  - snippet: `{h['snippet']}`")
        if len(all_hits) > 200:
            lines.append(f"- ... and {len(all_hits) - 200} more")
        lines.append("")

    out.write_text("\n".join(lines))
    print(f"wrote {out} violations={len(all_hits)} scanned={len(files)}")
    return 1 if all_hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
