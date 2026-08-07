#!/usr/bin/env bash
# Run DocuTrack Registry (backend + frontend + public ngrok tunnel) with one command.
# Only port 5173 is tunneled — Vite proxies /api to the backend server-side.
# Usage:  ./run.sh          (set NGROK=0 to skip the tunnel)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

echo "▶ DocuTrack Registry — starting up…"

for p in 8000 5173; do
  lsof -nP -iTCP:$p -sTCP:LISTEN -t >/dev/null 2>&1 && { echo "✗ port $p already in use"; exit 1; }
done

# --- Backend one-time setup ---
[ -f "$BACKEND/.env" ] || cp "$BACKEND/.env.example" "$BACKEND/.env"
if [ ! -x "$BACKEND/.venv/bin/python" ]; then
  echo "  · creating Python venv"
  python3.12 -m venv "$BACKEND/.venv"
  "$BACKEND/.venv/bin/pip" install -q --upgrade pip
  "$BACKEND/.venv/bin/pip" install -q -r "$BACKEND/requirements.txt"
fi
echo "  · seeding database (idempotent)"
(cd "$BACKEND" && .venv/bin/python -m scripts.seed >/dev/null)

# --- Frontend one-time setup ---
[ -d "$FRONTEND/node_modules" ] || (echo "  · installing npm deps"; cd "$FRONTEND" && npm install --silent)

# --- Launch both; Ctrl-C stops both ---
pids=()
cleanup() { echo; echo "■ stopping…"; kill "${pids[@]}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

(cd "$BACKEND" && exec .venv/bin/uvicorn app.main:app --reload --port 8000) &
pids+=($!)
(cd "$FRONTEND" && exec npm run dev) &
pids+=($!)

# --- Public tunnel (optional; ngrok doesn't need :5173 up yet) ---
public=""
if [ "${NGROK:-1}" = "1" ] && command -v ngrok >/dev/null; then
  ngrok http 5173 --log stdout >/dev/null 2>&1 &
  pids+=($!)
  for _ in $(seq 20); do
    public=$(curl -s http://127.0.0.1:4040/api/tunnels | grep -o 'https://[^"]*ngrok[^"]*' | head -1 || true)
    [ -n "$public" ] && break
    sleep 0.5
  done
  [ -n "$public" ] || public="(ngrok failed — already running elsewhere, or account limit)"
fi

echo ""
echo "  API      → http://localhost:8000/api/docs"
echo "  App      → http://localhost:5173"
[ -n "$public" ] && echo "  Public   → $public"
echo "  Login    → admin@docutrack.local  /  ChangeMe!123"
echo ""
echo "  (Ctrl-C to stop both)"
wait
