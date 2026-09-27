#!/usr/bin/env bash
# Build the bounded container that runs one RD-Agent Attempt (driver + factor code).
#
# The RD-Agent checkout is only *mounted* at run time; this image carries its dependencies
# and a copy of the package for version metadata, so upstream code changes never require a
# rebuild. Rebuild when RD-Agent's requirements.txt changes.
set -euo pipefail

cd "$(dirname "$0")/.."
agent_root="${QWB_RDAGENT_ROOT:-$(cd .. && pwd)/RD-Agent}"
if [[ ! -f "$agent_root/requirements.txt" ]]; then
  echo "RD-Agent checkout not found at $agent_root; set QWB_RDAGENT_ROOT" >&2
  exit 2
fi

context=.data/rdagent-runner-build
mkdir -p "$context"
cp "$agent_root/requirements.txt" "$context/"
cp "$agent_root/pyproject.toml" "$agent_root/README.md" "$context/"
rsync -a --delete --exclude='__pycache__/' --exclude='*.pyc' "$agent_root/rdagent/" "$context/rdagent/"
cp extensions/workbench/docker/rdagent-runner/Dockerfile "$context/"

version="$(cd "$agent_root" && git describe --tags --always 2>/dev/null || echo unknown)"
docker build --platform linux/arm64 --build-arg "RDAGENT_VERSION=$version" \
  -t qwb-rdagent-cpu:local "$context"

echo "built qwb-rdagent-cpu:local from $agent_root ($version)"
