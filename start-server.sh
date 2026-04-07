#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv-server"

if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment at $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

echo "Installing/updating dependencies..."
pip install -q -r "$SCRIPT_DIR/requirements-server.txt"

echo "Starting server..."
exec python "$SCRIPT_DIR/server.py" "$@"
