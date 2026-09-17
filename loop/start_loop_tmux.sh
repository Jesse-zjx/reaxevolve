#!/usr/bin/env bash
# Launch run_loop.py in a detached tmux session so it survives the calling shell.
#
#   ./loop/start_loop_tmux.sh [extra run_loop args...]
#
# Defaults track policy/targets_and_budget.md (operational knobs, not STRICT).
# Intra-round budget is enforced via --budget-core-h inside skill_runner.
set -euo pipefail

PKG="$(cd "$(dirname "$0")/.." && pwd)"
SESSION="${REAXEVOLVE_TMUX_SESSION:-reaxevolve}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOGDIR="$PKG/evidence/state/loop"
LOG="$LOGDIR/run_${STAMP}.log"
mkdir -p "$LOGDIR"

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "error: tmux session '$SESSION' already exists — attach with: tmux attach -t $SESSION" >&2
  exit 2
fi

PY="${CHEM_PYTHON:-/root/miniforge3/envs/harness/bin/python3}"
ARGS=(
  --rounds 24
  --top 8
  --cap 4
  --max-rounds-per-step 2
  --max-attempts 3
  --template-top 24
  --llm-top 4
  --nprocs 16
  --wall-s 5400
  --budget-hours 10000
  --stop-on-targets all
  --fully-auto
)
if [[ $# -gt 0 ]]; then
  ARGS=("$@")
fi

printf 'launching: %s loop/run_loop.py %s\n' "$PY" "${ARGS[*]}"
printf 'log: %s\n' "$LOG"

tmux new-session -d -s "$SESSION" -c "$PKG" \
  "exec $PY -u loop/run_loop.py ${ARGS[*]} 2>&1 | tee '$LOG'"

# Keep the pane alive after the command exits so the tail is readable.
tmux set-option -t "$SESSION" remain-on-exit on >/dev/null 2>&1 || true

sleep 2
echo
echo "session '$SESSION' started:"
tmux list-sessions | sed 's/^/  /'
echo
echo "  attach : tmux attach -t $SESSION   (detach with Ctrl-b d)"
echo "  tail   : tail -f $LOG"
echo "  stop   : tmux kill-session -t $SESSION   # then check for stray orca: pgrep -af orca"
echo "$LOG" > "$LOGDIR/.current_run_log"
