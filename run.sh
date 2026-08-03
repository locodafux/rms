#!/usr/bin/env bash
# Run DocuTrack Registry (backend + frontend) with one command.
# Usage:  ./run.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

echo "▶ DocuTrack Registry — starting up…"

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

echo ""
echo "  API      → http://localhost:8000/api/docs"
echo "  App      → http://localhost:5173"
echo "  Login    → admin@docutrack.local  /  ChangeMe!123"
echo ""
echo "  (Ctrl-C to stop both)"
wait
