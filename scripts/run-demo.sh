#!/bin/sh
# Start the simulated dashboard. Refuses to start if the port is already taken.
# Does not stop, kill, or signal any existing process.
set -eu
cd "$(dirname "$0")/.."
PORT="${1:-8000}"
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port $PORT is already in use. This script will not stop that process."
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN
  exit 1
fi
if [ ! -x .venv/bin/python ]; then
  echo "No .venv in $(pwd)."
  echo "Create it with:"
  echo "  python3.11 -m venv .venv"
  echo "  . .venv/bin/activate"
  echo "  python -m pip install -r requirements.txt"
  exit 1
fi
exec .venv/bin/python -m fusion.server --demo --host 127.0.0.1 --listen "$PORT"
