#!/usr/bin/env bash
# Unified project-local pi launcher for reaxevolve.
#
# Usage:
#   SKILL_FLAGS="--skill $PKG/.skills/generate-ts-guesses" \
#   TOOL_FLAGS="--tools read,bash,write" \
#   ./loop/pi_call.sh "your prompt"
#
# Env from .env: BASE_URL, API_KEY, MODEL_NAME
# Extra optional env:
#   SKILL_FLAGS   e.g. --skill /abs/path/a --skill /abs/path/b
#   TOOL_FLAGS    e.g. --no-tools  or  --tools read,bash,write,edit
#   EXTRA_FLAGS   any additional pi CLI flags
#   PI_MODE       json (default) | text | rpc

set -euo pipefail

PKG="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${PKG}/.env"
PI_BIN="${PKG}/node_modules/.bin/pi"

if [[ ! -x "$PI_BIN" ]]; then
  echo "error: project-local pi not found at $PI_BIN" >&2
  echo "run: (cd $PKG && npm install)" >&2
  exit 2
fi

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
else
  echo "error: missing $ENV_FILE — copy .env.example and fill BASE_URL/API_KEY/MODEL_NAME" >&2
  exit 2
fi

: "${BASE_URL:?BASE_URL required in .env}"
: "${API_KEY:?API_KEY required in .env}"
: "${MODEL_NAME:?MODEL_NAME required in .env}"

export PI_CODING_AGENT_DIR="${PKG}/.agentcfg"
export BASE_URL API_KEY MODEL_NAME

PI_MODE="${PI_MODE:-json}"
SKILL_FLAGS="${SKILL_FLAGS:-}"
TOOL_FLAGS="${TOOL_FLAGS:---no-tools}"
EXTRA_FLAGS="${EXTRA_FLAGS:---approve}"
# deepseek-v4-pro reasons until the output cap is hit and then returns nothing, so
# structured-output callers (Explore, Reflect) must turn thinking off. Override with
# THINKING=high for a call that genuinely needs deliberation.
THINKING="${THINKING:-off}"
PROMPT="${*:-}"

if [[ -z "$PROMPT" ]]; then
  echo "usage: $0 <prompt...>" >&2
  exit 2
fi

# shellcheck disable=SC2086
exec "$PI_BIN" -p --mode "$PI_MODE" \
  --provider "${PI_PROVIDER:-reaxevolve}" --model "$MODEL_NAME" \
  --thinking "$THINKING" \
  -e "${PKG}/.agentcfg/extensions/provider.js" -ne \
  --no-skills $SKILL_FLAGS \
  -nc \
  --session-dir "${PKG}/.agentcfg/sessions" \
  $TOOL_FLAGS \
  $EXTRA_FLAGS \
  "$PROMPT"
