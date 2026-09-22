#!/usr/bin/env bash
# Verify the repository from a fresh clone. One command, nine checks, no DFT and no API.
#
# This exists because local testing cannot see the failure that matters most here: a file
# that is present on disk but not committed. Cloning first is the only way to check what a
# reader actually receives — it is how four dangling references were found after they had
# already passed every local check.
#
#   bash scripts/qa/verify_clone.sh            # clone this repository and verify it
#   bash scripts/qa/verify_clone.sh /path/to   # verify another checkout
#
# Requires git, Python with RDKit and NetworkX. ORCA and xTB are not needed: nothing here
# recomputes chemistry, it only re-derives the reported numbers from the shipped evidence.
set -uo pipefail

SRC="${1:-$(cd "$(dirname "$0")/../.." && pwd)}"
PY="${CHEM_PYTHON:-python3}"
TMP=$(mktemp -d)
C="$TMP/c"
rc=0

git clone -q "$SRC" "$C"

echo "=== 1. deposits verify as built ==="
for d in "$C"/deposits/*/; do
  [ -d "$d" ] || continue
  printf '  %-26s ' "$(basename "$d")"
  ( cd "$C" && $PY policy/acceptance/check_strict_bar.py --deposit "deposits/$(basename "$d")" 2>&1 ) \
    | grep 'clauses 2-4 met' || rc=1
done

echo "=== 2. accepted count re-derives from the shipped evidence ==="
( cd "$C" && $PY scripts/graph/build_reaction_network.py 2>/dev/null ) \
  | grep -E '"n_strict"|n_targets_reachable_strict|status_changes' | sed 's/^/  /' || rc=1

echo "=== 3. network STRICT set equals the audited pin ==="
( cd "$C" && $PY - <<'PY'
import json
net = json.load(open("graph/canonical/reaction_network.json"))
pin = json.load(open("graph/canonical/audited_strict_edges.json"))
ns = {(e["reactant"], e["product"]) for e in net["edges"].values() if e.get("status") == "STRICT"}
ps = {(e["reactant"], e["product"]) for e in pin["edges"]}
print(f"  network {len(ns)} | pin {pin['n_strict']} | identical: {ns == ps}")
raise SystemExit(0 if ns == ps else 1)
PY
) || rc=1

echo "=== 4. every documented path exists in the clone ==="
( cd "$C" && $PY scripts/qa/check_doc_paths.py ) | sed 's/^/  /' || rc=1

echo "=== 5. rediscovery report matches its data ==="
( cd "$C" && $PY experiments/rediscovery/render_report.py --check ) | sed 's/^/  /' || rc=1

echo "=== 5b. preregistration is consistent ==="
( cd "$C" && $PY scripts/qa/test_preregistration.py | tail -2 ) | sed 's/^/  /' || rc=1

echo "=== 5c. guess ladder is reachable and the mapper contract holds ==="
( cd "$C" && $PY scripts/qa/test_guess_ladder.py | tail -2 ) | sed 's/^/  /' || rc=1

echo "=== 5d. an unusable IRC endpoint rejects instead of crashing ==="
( cd "$C" && $PY scripts/qa/test_endpoint_match.py | tail -2 ) | sed 's/^/  /' || rc=1

echo "=== 6a. failure taxonomy and classifier agree ==="
( cd "$C" && $PY scripts/qa/test_failure_taxonomy.py | tail -2 ) | sed 's/^/  /' || rc=1

echo "=== 6b. generated evolution view matches the record ==="
( cd "$C" && $PY scripts/reflect/render_evolution_log.py --check ) | sed 's/^/  /' || rc=1

echo "=== 6. evolution ledger is diffable ==="
( cd "$C" && $PY - <<'PY'
import json, os
rows = [json.loads(l) for l in open("evolution/EVOLUTION_LOG.jsonl") if l.strip()]
want = [r for r in rows if r.get("snapshot")]
have = [r for r in want if os.path.isdir(r["snapshot"])]
print(f"  {len(rows)} revisions | {len(have)}/{len(want)} snapshots resolvable")
raise SystemExit(0 if len(have) == len(want) else 1)
PY
) || rc=1

echo "=== 7. structural + accounting checks ==="
( cd "$C" && $PY scripts/smoke_test.py 2>&1 | tail -2 ) | sed 's/^/  /' || rc=1
( cd "$C" && $PY scripts/qa/test_loop_accounting.py 2>&1 | tail -1 ) | sed 's/^/  /' || rc=1

echo "=== 8. loop wiring (no DFT, no API) ==="
( cd "$C" && $PY loop/run_loop.py --dry-run --no-llm 2>&1 | tail -2 ) | sed 's/^/  /' || rc=1

echo "=== 9. size ==="
printf '  %s working tree, %s tracked files\n' \
  "$(du -sh --exclude=.git "$C" | cut -f1)" "$(git -C "$C" ls-files | wc -l)"

rm -rf "$TMP"
echo
echo "verify_clone: $([ $rc -eq 0 ] && echo PASS || echo FAIL)"
exit $rc
