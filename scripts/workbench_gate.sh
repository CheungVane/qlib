#!/usr/bin/env bash
# API03 delivery gate: one command for the workbench Python and JavaScript suites.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKBENCH="$REPO_ROOT/extensions/workbench"

echo "[gate] python suite (includes the API03 contract checks)"
(cd "$WORKBENCH" && .venv/bin/python -m unittest discover -s tests)

echo "[gate] javascript suite"
(cd "$WORKBENCH" && node --test tests/test_ui.cjs)

echo "[gate] ok"
