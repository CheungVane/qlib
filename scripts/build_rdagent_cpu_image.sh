#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
context=.data/rdagent-cpu-build
mkdir -p "$context"
rsync -a --delete --exclude='__pycache__/' --exclude='*.pyc' qlib "$context/"
mkdir -p "$context/workbench"
rsync -a --delete --exclude='__pycache__/' --exclude='*.pyc' extensions/workbench/quant_workbench "$context/workbench/"
cp pyproject.toml setup.py README.md MANIFEST.in "$context/"
cp extensions/workbench/docker/rdagent-qlib-cpu/Dockerfile "$context/"

version="$(.venv/bin/python -c 'import qlib; print(qlib.__version__)')"
docker build --platform linux/arm64 --build-arg "QLIB_VERSION=$version" \
    -t qwb-qlib-cpu:local "$context"
