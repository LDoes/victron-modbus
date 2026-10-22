#!/usr/bin/env bash
# Run the same checks CI runs: formatting, linting, typing, compiling, tests,
# and coverage.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> ruff format --check"
python -m ruff format --check .

echo "==> ruff check"
python -m ruff check .

echo "==> mypy"
python -m mypy

echo "==> compileall"
python -m compileall -q src tests

echo "==> pytest with coverage"
python -m pytest --cov=victron_modbus --cov-report=term-missing --cov-report=xml
