#!/usr/bin/env bash
# ==============================================================================
# Wrapper Shell untuk Otomasi register-app.py
# ==============================================================================
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$DIR/register-app.py" "$@"
