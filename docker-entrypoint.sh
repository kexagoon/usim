#!/bin/sh
set -e
PORT="${PORT:-8765}"
HOST="${HOST:-0.0.0.0}"
exec python -m uvicorn app.main:app --host "$HOST" --port "$PORT"
