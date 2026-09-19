# Isolation audit

- time: 2026-09-19T17:23:28Z
- workspace: `/root/inno-agent/workspaces/reaxevolve`
- files_scanned: 2
- files_skipped_too_large: 0
- suffixes: .inp .json .jsonl .log .md .out .sh .txt .xyz
- violations: 0

## Result: CLEAN

No out-of-whitelist absolute paths found in scanned artifacts.

Scope note: this detects *references* to forbidden paths recorded in session logs,
loop state, and ORCA scratch. There is no kernel-level sandbox, so an access that
left no textual trace would not appear here.
