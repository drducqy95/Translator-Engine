#!/usr/bin/env bash
# hymt_keepalive.sh
# Keeps the Hy-MT server alive and logs restarts

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

LOGDIR="$REPO_ROOT/logs"
LOGFILE="$LOGDIR/hymt_server.log"
mkdir -p "$LOGDIR"

if [[ -f "$REPO_ROOT/Temp/MAINTENANCE.lock" ]]; then
    echo "Maintenance lock present; hymt keepalive disabled"
    exit 0
fi

echo "Starting Keepalive loop for hymt_server.sh. Logging to $LOGFILE"

while true; do
    if [[ -f "$REPO_ROOT/Temp/MAINTENANCE.lock" ]]; then
        echo "[$(date)] Maintenance lock present; stopping keepalive" | tee -a "$LOGFILE"
        exit 0
    fi
    echo "[$(date)] Starting hymt_server.sh..." | tee -a "$LOGFILE"
    bash "$REPO_ROOT/bin/hymt_server.sh" >> "$LOGFILE" 2>&1
    EXIT_CODE=$?
    echo "[$(date)] Server crashed with exit code $EXIT_CODE. Restarting in 5s..." | tee -a "$LOGFILE"
    sleep 5
done
