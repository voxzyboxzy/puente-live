#!/usr/bin/env bash
# One command for the API and the console.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -q -r backend/requirements.txt

if [[ ! -d frontend/node_modules ]]; then
  npm ci --prefix frontend
fi

mkdir -p backend/data
export PUENTE_LLM="${PUENTE_LLM:-deterministic}"
export PUENTE_STREAM_MS="${PUENTE_STREAM_MS:-18}"
export PUENTE_DB="${PUENTE_DB:-$ROOT/backend/data/puente.db}"

python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 &
BACK_PID=$!
npm run dev --prefix frontend -- --host 127.0.0.1 --port 5173 &
FRONT_PID=$!

cleanup() {
  kill "$BACK_PID" "$FRONT_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Puente Live API  http://127.0.0.1:8000"
echo "Puente Live UI   http://127.0.0.1:5173"
wait
