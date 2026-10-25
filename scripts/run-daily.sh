#!/bin/bash
# Daily memory reconcile, driven by Claude Haiku through the Claude Code CLI.
# launchd (com.blitzzz.memory-daily) runs it at 07:00 local, and at wake if the Mac slept.
# For each finished local day that still holds pending turns, oldest first, it starts
# fresh `claude -p` sessions that follow task.md for that day, until the day is empty
# or a session makes no progress. Today's turns wait for tomorrow's run.
# Usage: run-daily.sh [--through YYYY-MM-DD] [--max-days N] [--only YYYY-MM-DD]
# --only runs one day (today included) under its own lock, so a backlog can drain in parallel.
set -u
ENGINE=/Users/__blitzzz/Documents/GitHub/agy-memory-engine
CLAUDE_BIN=${CLAUDE_BIN:-/Users/__blitzzz/.local/bin/claude}
MODEL=${AGY_DAILY_MODEL:-claude-haiku-5-5}
MAX_SESSIONS_PER_DAY=${AGY_DAILY_MAX_SESSIONS:-12}
THROUGH=$(date -v-1d +%F)
MAX_DAYS=99
ONLY=""
ARGS=("$@")   # kept for the re-run under the lock; the loop below shifts them away
while [ $# -gt 0 ]; do
  case "$1" in
    --through) THROUGH=$2; shift 2 ;;
    --max-days) MAX_DAYS=$2; shift 2 ;;
    --only) ONLY=$2; THROUGH=$2; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

cd "$ENGINE" || exit 1
export HOME="${HOME:-/Users/__blitzzz}"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
export AGY_INTERNAL_INVOCATION=1   # memory-enqueue hook: do not queue the reconcile's own turns
export BLITZZZ_MODE=0              # blitzzz hooks off in the headless session
LOG_DIR="$ENGINE/tmp/daily"
mkdir -p "$LOG_DIR"
# Kernel lock: lockf holds it while the child runs, and the OS frees it if either dies.
if [ -z "${AGY_DAILY_LOCKED:-}" ]; then
  AGY_DAILY_LOCKED=1 /usr/bin/lockf -t 0 "$LOG_DIR/.lockfile${ONLY:+-$ONLY}" /bin/bash "$0" ${ARGS[@]+"${ARGS[@]}"}
  rc=$?
  if [ "$rc" -eq 75 ]; then
    echo "$(date '+%F %T') another run holds the lock; exiting" >> "$LOG_DIR/runner.log"
    exit 0
  fi
  exit "$rc"
fi
log() { echo "$(date '+%F %T') $*" | tee -a "$LOG_DIR/runner.log"; }

pending_for() {
  .venv/bin/python scripts/queue_cli.py days | .venv/bin/python -c \
    'import json,sys; d=sys.argv[1]; print(next((x["pending"] for x in json.load(sys.stdin) if x["day"]==d), 0))' "$1"
}

days=$(.venv/bin/python scripts/queue_cli.py days | .venv/bin/python -c \
  'import json,sys; [print(x["day"]) for x in json.load(sys.stdin)]')
log "start model=$MODEL through=$THROUGH days=[$(echo $days)]"
done_days=0
status=0
for day in $days; do
  [[ "$day" > "$THROUGH" ]] && continue
  [ -n "$ONLY" ] && [ "$day" != "$ONLY" ] && continue
  [ "$done_days" -ge "$MAX_DAYS" ] && break
  done_days=$((done_days + 1))
  for i in $(seq 1 "$MAX_SESSIONS_PER_DAY"); do
    before=$(pending_for "$day")
    [ "$before" -eq 0 ] && break
    run=$(date +%Y-%m-%d_%H%M%S)
    log "day=$day session=$i pending=$before run=$run"
    # Turn text is untrusted, so the session gets an allow-list instead of every tool.
    # --setting-sources project drops the user settings, whose allow rule admits every
    # Bash command (and their hooks); the memory MCP server comes from daily-mcp.json.
    # The prompt goes first: --allowedTools takes a list and would swallow a trailing prompt.
    "$CLAUDE_BIN" -p "Run one pass of the daily memory reconcile for DAY=$day with RUN=${day}__${run}. Read $ENGINE/task.md first and follow it exactly." \
      --model "$MODEL" --permission-mode dontAsk \
      --setting-sources project --strict-mcp-config --mcp-config "$ENGINE/scripts/daily-mcp.json" \
      --allowedTools "Bash(.venv/bin/python scripts/queue_cli.py:*)" \
        "Bash(.venv/bin/python agy_memory.py consolidate:*)" "Bash(sqlite3:*)" "Bash(date:*)" \
        "Bash(mkdir:*)" "Bash(grep:*)" "Bash(ls:*)" "Bash(wc:*)" "Bash(head:*)" "Bash(tail:*)" \
        "Read" "Write" "Edit" "Glob" "Grep" "ToolSearch" "mcp__memory__search_memory" \
      > "$LOG_DIR/${day}__${run}.log" 2>&1
    rc=$?
    after=$(pending_for "$day")
    log "day=$day session=$i exit=$rc pending_after=$after"
    if [ "$rc" -ne 0 ]; then
      log "day=$day session failed (exit=$rc); stopping the whole run; see $LOG_DIR/${day}__${run}.log"
      status=1
      break 2
    fi
    if [ "$after" -ge "$before" ]; then
      log "day=$day stopped: no progress; see $LOG_DIR/${day}__${run}.log"
      status=1
      break
    fi
  done
  # Queue commits do not embed new rows; drain the vector index jobs so search sees this day.
  vec=$(.venv/bin/python scripts/vector_index_cli.py run --batch-size 100 --max-batches 50 2>&1 | tr -d '\n ')
  log "day=$day vector_index $vec"
done
log "end status=$status"
exit $status
