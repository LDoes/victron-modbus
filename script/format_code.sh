#!/usr/bin/env bash
# Auto-format the codebase with Ruff.
set -euo pipefail
cd "$(dirname "$0")/.."

python -m ruff format .
python -m ruff check --fix .
