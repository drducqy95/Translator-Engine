#!/usr/bin/env bash
set -uo pipefail

ENGINE_DIR="${ENGINE_DIR:-/sdcard/My Agent/Translator Engine}"
BOT_SCRIPT="${BOT_SCRIPT:-$ENGINE_DIR/telegram_bot_v2.py}"
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"
LOG_DIR="$ENGINE_DIR/logs"
RUN_DIR="$ENGINE_DIR/Temp/run"
LOG_FILE="$LOG_DIR/telegram_bot_keepalive.log"
BOT_LOG="$LOG_DIR/telegram_bot_v2.log"
LOCK_DIR="$RUN_DIR/telegram_bot_keepalive.lock"
SUP_PID_FILE="$RUN_DIR/telegram_bot_keepalive.pid"
BOT_PID_FILE="$RUN_DIR/telegram_bot_v2.pid"
RESTART_DELAY="${RESTART_DELAY:-10}"

mkdir -p "$LOG_DIR" "$RUN_DIR"

ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { printf '[%s] %s\n' "$(ts)" "$*" | tee -a "$LOG_FILE"; }

is_pid_alive() {
  local pid="${1:-}"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

existing_bot_pid() {
  pgrep -f "python3 .*${BOT_SCRIPT}" | head -n 1 || true
}

cleanup() {
  log "supervisor stopping"
  if [[ -f "$BOT_PID_FILE" ]]; then
    local pid
    pid="$(cat "$BOT_PID_FILE" 2>/dev/null || true)"
    if is_pid_alive "$pid"; then
      log "stopping bot pid=$pid"
      kill "$pid" 2>/dev/null || true
      sleep 2
      is_pid_alive "$pid" && kill -TERM "$pid" 2>/dev/null || true
    fi
  fi
  rm -f "$SUP_PID_FILE" "$BOT_PID_FILE"
  rmdir "$LOCK_DIR" 2>/dev/null || true
}
trap cleanup EXIT
trap 'cleanup; exit 0' INT TERM

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  old_pid="$(cat "$SUP_PID_FILE" 2>/dev/null || true)"
  if is_pid_alive "$old_pid"; then
    echo "telegram bot keepalive already running: pid=$old_pid"
    exit 0
  fi
  rm -rf "$LOCK_DIR"
  mkdir "$LOCK_DIR" || exit 1
fi

echo $$ > "$SUP_PID_FILE"
cd "$ENGINE_DIR" || exit 1

if [[ ! -f "$BOT_SCRIPT" ]]; then
  log "missing bot script: $BOT_SCRIPT"
  exit 1
fi

log "supervisor started engine=$ENGINE_DIR bot=$BOT_SCRIPT"

while true; do
  pid="$(existing_bot_pid)"
  if is_pid_alive "$pid"; then
    echo "$pid" > "$BOT_PID_FILE"
    log "bot already running pid=$pid; watching"
    while is_pid_alive "$pid"; do
      sleep 15
    done
    log "watched bot exited pid=$pid"
  else
    log "starting bot"
    "$PYTHON_BIN" "$BOT_SCRIPT" >> "$BOT_LOG" 2>&1 &
    pid=$!
    echo "$pid" > "$BOT_PID_FILE"
    log "bot started pid=$pid"
    wait "$pid"
    rc=$?
    log "bot exited pid=$pid rc=$rc"
  fi
  sleep "$RESTART_DELAY"
done
