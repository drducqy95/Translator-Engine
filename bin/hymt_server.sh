#!/usr/bin/env bash
# hymt_server.sh
# Starts llama.cpp OpenAI-compatible server for Hy-MT Offline Fallback

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PORT="${HYMT_PORT:-8088}"
HOST="${HYMT_HOST:-127.0.0.1}"
MODEL="${HYMT_MODEL:-$REPO_ROOT/models/hymt/Hy-MT1.5-1.8B-2bit.gguf}"
THREADS="${HYMT_THREADS:-4}"
CTX="${HYMT_CTX:-2048}"
LLAMA_SERVER="${LLAMA_SERVER:-$(command -v llama-server || true)}"
if [ -z "$LLAMA_SERVER" ] && [ -x "/root/llama.cpp/build-nosssl/bin/llama-server" ]; then
    LLAMA_SERVER="/root/llama.cpp/build-nosssl/bin/llama-server"
fi

if [ -z "$LLAMA_SERVER" ]; then
    echo "Error: llama-server not found. Set LLAMA_SERVER or install/build llama.cpp."
    exit 1
fi

if [ ! -f "$MODEL" ]; then
    echo "Error: Model file not found at $MODEL"
    exit 1
fi

echo "Starting Hy-MT Server on $HOST:$PORT using $MODEL..."
exec "$LLAMA_SERVER" -m "$MODEL" --host "$HOST" --port "$PORT" -t "$THREADS" -c "$CTX" --no-ui
