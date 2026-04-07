#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv-transcription"

if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment at $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

echo "Installing/updating dependencies..."
pip install -q -r "$SCRIPT_DIR/requirements-transcription.txt"

echo "Starting transcription service..."
exec python "$SCRIPT_DIR/transcription_service.py" "$@"
