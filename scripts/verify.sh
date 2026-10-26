#!/usr/bin/env bash
# Run all checks. Use this before each commit and in any CI.
set -euo pipefail
cd "$(dirname "$0")/.."
uv run --group dev ruff check .
uv run --group dev ruff format --check .
uv run --group dev pytest "$@"
