#!/bin/sh
# Run the simulated test suite. Does not start a server and does not open a serial port.
set -eu
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then
  echo "No .venv in $(pwd)."
  echo "Create it with:"
  echo "  python3.11 -m venv .venv"
  echo "  . .venv/bin/activate"
  echo "  python -m pip install -r requirements.txt"
  exit 1
fi
exec .venv/bin/python -m unittest discover -s tests
