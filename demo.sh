#!/usr/bin/env bash
# One-command local demo: boots the offline multi-agent API (mock LLM, no keys needed).
# Usage: ./demo.sh [PORT]   (default 8000)
set -euo pipefail
PORT="${1:-8000}"
cd "$(dirname "$0")"
echo "Booting Support Agent Tools on :$PORT ..."
.venv/bin/python -m uvicorn src.api:app --port "$PORT" &
SRV=$!
trap 'kill $SRV 2>/dev/null' EXIT
for i in $(seq 1 25); do
  curl -s -m 2 "http://127.0.0.1:$PORT/health" | grep -q '"status":"ok"' && break || sleep 1
done
echo "Health:"; curl -s "http://127.0.0.1:$PORT/health"; echo
echo "Try:"
echo "  curl -s -X POST http://127.0.0.1:$PORT/chat -H 'Content-Type: application/json' -d '{\"message\":\"I forgot my password, how do I reset it?\"}'"
echo "Press Ctrl-C to stop."
wait $SRV
