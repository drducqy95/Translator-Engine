#!/usr/bin/env bash
set -euo pipefail
ROOT="/sdcard/My Agent/Translator Engine"
PORT="${1:-8765}"
cd "$ROOT"
exec python3 -m http.server "$PORT" --bind 0.0.0.0
