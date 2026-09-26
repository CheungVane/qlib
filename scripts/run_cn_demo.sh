#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v uv >/dev/null 2>&1; then
    echo "Please install uv first: https://docs.astral.sh/uv/getting-started/installation/" >&2
    exit 1
fi

if [[ "$(uname -s)" == "Darwin" ]]; then
    if ! command -v brew >/dev/null 2>&1; then
        echo "Homebrew is required to install LightGBM's libomp on macOS." >&2
        exit 1
    fi
    if ! brew list --versions libomp >/dev/null 2>&1 || [[ -z "$(brew list --versions libomp)" ]]; then
        HOMEBREW_NO_AUTO_UPDATE=1 brew install libomp
    fi
    xcode_sdk="/Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk"
    if [[ -f "$xcode_sdk/usr/include/stdlib.h" ]]; then
        export SDKROOT="$xcode_sdk"
    fi
fi

if [[ ! -x .venv/bin/python ]]; then
    uv venv --python 3.11 .venv
fi
uv pip install --quiet --python .venv/bin/python -e .
uv pip check --python .venv/bin/python
.venv/bin/python scripts/make_cn_current_data.py
workflow_path="$(.venv/bin/python scripts/prepare_cn_scenario.py --target qlib)"
MLFLOW_DISABLE_AGENT_HINT=1 .venv/bin/qrun "$workflow_path"
