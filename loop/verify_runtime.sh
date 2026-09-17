#!/usr/bin/env bash
# Three end-to-end runtime checks for reaxevolve (requires .env).
# 1) provider emits a token
# 2) only whitelisted skills are visible
# 3) bash/write tools work in -p mode
set -euo pipefail

PKG="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${PKG}/evidence/audit/VERIFY_RUNTIME.md"
mkdir -p "$(dirname "$OUT")"

{
  echo "# Runtime verification"
  echo
  echo "- time: $(date -Is)"
  echo "- pi: $("$PKG/node_modules/.bin/pi" --version 2>/dev/null || echo missing)"
  echo
} >"$OUT"

if [[ ! -f "$PKG/.env" ]]; then
  {
    echo "## Status: SKIPPED"
    echo
    echo "Missing \`$PKG/.env\`. Copy \`.env.example\` and fill BASE_URL / API_KEY / MODEL_NAME, then re-run:"
    echo
    echo '```bash'
    echo "./loop/verify_runtime.sh"
    echo '```'
  } >>"$OUT"
  echo "SKIPPED: no .env (see $OUT)"
  exit 0
fi

set -a; . "$PKG/.env"; set +a
export PI_CODING_AGENT_DIR="$PKG/.agentcfg"

PI="$PKG/node_modules/.bin/pi"
EXT="$PKG/.agentcfg/extensions/provider.js"
BASE_ARGS=(-p --mode json --provider "${PI_PROVIDER:-reaxevolve}" --model "$MODEL_NAME" -e "$EXT" -ne --no-skills -nc --approve --session-dir "$PKG/.agentcfg/sessions")

pass=0
fail=0

run_check() {
  local name="$1"; shift
  echo "## $name" >>"$OUT"
  echo '```' >>"$OUT"
  set +e
  out=$("$@" 2>&1)
  rc=$?
  set -e
  echo "$out" | head -c 4000 >>"$OUT"
  echo >>"$OUT"
  echo '```' >>"$OUT"
  if [[ $rc -eq 0 ]] && ! echo "$out" | grep -q '"stopReason":"error"'; then
    echo "OK: $name" | tee -a "$OUT"
    pass=$((pass+1))
  else
    echo "FAIL: $name (rc=$rc or model error)" | tee -a "$OUT"
    fail=$((fail+1))
  fi
  echo >>"$OUT"
}

# 1) provider token
run_check "1_provider_token" \
  "$PI" "${BASE_ARGS[@]}" --no-tools \
  "Reply with exactly the single word: pong"

# 2) skill whitelist — load only generate-ts-guesses if present
SKILL_A="$PKG/.skills/generate-ts-guesses"
if [[ -d "$SKILL_A" ]]; then
  run_check "2_skill_whitelist" \
    "$PI" "${BASE_ARGS[@]}" --skill "$SKILL_A" --no-tools \
    "List the skill names you can see. Reply JSON: {\"skills\":[...]} Only names, no body."
else
  echo "## 2_skill_whitelist" >>"$OUT"
  echo "SKIPPED: skill dir missing ($SKILL_A)" >>"$OUT"
fi

# 3) bash/write without interactive approve
TMPDIR_CHK="$PKG/runs/_verify_runtime"
mkdir -p "$TMPDIR_CHK"
MARKER="$TMPDIR_CHK/hello_from_pi.txt"
rm -f "$MARKER"
run_check "3_bash_write_tools" \
  "$PI" "${BASE_ARGS[@]}" --tools read,bash,write \
  "Create file $MARKER containing exactly: runtime-ok. Then finish."

if [[ -f "$MARKER" ]]; then
  echo "OK: marker file written" | tee -a "$OUT"
  pass=$((pass+1))
else
  echo "FAIL: marker file not written (may need --approve)" | tee -a "$OUT"
  fail=$((fail+1))
fi

{
  echo "## Summary"
  echo "- pass: $pass"
  echo "- fail: $fail"
} >>"$OUT"

echo "Wrote $OUT (pass=$pass fail=$fail)"
exit "$fail"
