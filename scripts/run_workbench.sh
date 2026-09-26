#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ -z "${QWB_RDAGENT_ROOT:-}" && -d "../RD-Agent/.git" ]]; then
    export QWB_RDAGENT_ROOT="$(cd ../RD-Agent && pwd)"
fi

if ! command -v uv >/dev/null 2>&1; then
    echo "Please install uv first: https://docs.astral.sh/uv/getting-started/installation/" >&2
    exit 1
fi

uv sync --directory extensions/workbench --extra api --extra qlib-import --extra test --frozen
extensions/workbench/.venv/bin/qwb --root .data/workbench import-json \
    extensions/workbench/examples/generic-result.json \
    --source-instance fixture --external-id example-1 >/dev/null
exec extensions/workbench/.venv/bin/qwb --root .data/workbench serve --port "${1:-8765}"
