#!/usr/bin/env python3
"""Every repo-relative path named in a skill or a document must exist.

A skill is the asset this method is about. A reader who copies a command out of one and
gets file-not-found has found a defect in the centrepiece, not a typo — and it is the
cheapest possible thing to check, so there is no excuse for shipping one.

Scans backtick-quoted tokens that look like repository paths, skips the ones that are
obviously not (URLs, shell variables, glob patterns, paths marked retired, scratch under
runs/ that only exists after a run), and reports the rest that do not resolve.

  python scripts/qa/check_doc_paths.py            # skills + top-level docs
  python scripts/qa/check_doc_paths.py --all      # every tracked .md
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

PKG = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PATH_RE = re.compile(r"`([A-Za-z0-9_][A-Za-z0-9_./@-]*\.(?:py|md|json|jsonl|sh|txt|xyz|out|hess|inp))`")

# Paths that legitimately do not exist in a clean checkout.
SKIP_PREFIX = (
    "runs/",            # QM scratch, created by a run
    "tsbench/",         # supplementary lane, gitignored by design
    "node_modules/",
    ".agentcfg/sessions/",
)
SKIP_CONTAINS = (
    "$",                # shell variable
    "*",                # glob
    "<",                # placeholder
    "…",
    "round_N",          # per-round working directory, created during a run
    "step_n",           # placeholder step index
    "workdir/",
)
# Filenames that are described generically rather than referenced as a location.
SKIP_BASENAME = {
    "SKILL.md", "README.md", "record.json", "reaction_mapping.json",
    "ts_search_result.json", "strict_cache.json", "chain.json", "versions.json",
    "guesses.record_update.json", "yarp_route.json", "path_queue.json",
    "requirements.txt", "settings.json", "config.json", "sandbox.json",
}


def tracked_markdown() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "*.md"], cwd=PKG, text=True, capture_output=True
    ).stdout
    return [l for l in out.splitlines() if l.strip()]


def default_scope() -> list[str]:
    files = []
    for rel in tracked_markdown():
        if rel.startswith((".skills/", "assets/")) or "/" not in rel or rel.startswith("docs/"):
            files.append(rel)
    return files


def interesting(token: str) -> bool:
    if any(c in token for c in SKIP_CONTAINS):
        return False
    if token.startswith(SKIP_PREFIX):
        return False
    if os.path.basename(token) in SKIP_BASENAME:
        return False
    # A bare filename with no directory is a description, not a location.
    return "/" in token


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--all", action="store_true", help="scan every tracked markdown file")
    a = ap.parse_args()

    files = tracked_markdown() if a.all else default_scope()
    missing: list[tuple[str, int, str]] = []
    checked = 0
    for rel in files:
        p = os.path.join(PKG, rel)
        if not os.path.isfile(p):
            continue
        for i, line in enumerate(open(p, errors="ignore"), 1):
            if "retired" in line.lower():
                continue
            for m in PATH_RE.finditer(line):
                tok = m.group(1)
                if not interesting(tok):
                    continue
                checked += 1
                # A skill may reference a file it bundles, relative to its own directory.
                if os.path.exists(os.path.join(PKG, tok)):
                    continue
                if os.path.exists(os.path.join(os.path.dirname(p), tok)):
                    continue
                missing.append((rel, i, tok))

    print(f"scanned {len(files)} documents, {checked} repo-relative path references")
    if missing:
        print(f"\n{len(missing)} reference(s) do not resolve:")
        for rel, i, tok in missing:
            print(f"  {rel}:{i}  {tok}")
        return 1
    print("all resolve")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
