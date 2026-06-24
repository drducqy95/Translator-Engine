#!/usr/bin/env bash
# hymt_keepalive.sh
# Keeps the Hy-MT server alive and logs restarts

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

LOGDIR="$REPO_ROOT/logs"
LOGFILE="$LOGDIR/hymt_server.log"
mkdir -p "$LOGDIR"

echo "Starting Keepalive loop for hymt_server.sh. Logging to $LOGFILE"

while true; do
    echo "[$(date)] Starting hymt_server.sh..." | tee -a "$LOGFILE"
    bash "$REPO_ROOT/bin/hymt_server.sh" >> "$LOGFILE" 2>&1
    EXIT_CODE=$?
    echo "[$(date)] Server crashed with exit code $EXIT_CODE. Restarting in 5s..." | tee -a "$LOGFILE"
    sleep 5
done
