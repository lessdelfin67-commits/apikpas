#!/usr/bin/env bash
set -euo pipefail
exec uvicorn app.main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}"
