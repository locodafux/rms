#!/usr/bin/env bash
# Same as ./run.sh, plus a public ngrok tunnel to the app.
# Only port 5173 is tunneled — Vite proxies /api to the backend server-side.
# Usage:  ./run-ngrok.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

command -v ngrok >/dev/null || { echo "ngrok not found — brew install ngrok"; exit 1; }

"$ROOT/run.sh" &
APP=$!
trap 'kill $APP 2>/dev/null || true' EXIT INT TERM

echo "  · waiting for frontend on :5173"
until curl -sf -o /dev/null http://localhost:5173; do
  kill -0 $APP 2>/dev/null || { echo "run.sh exited"; exit 1; }
  sleep 1
done

exec ngrok http 5173
