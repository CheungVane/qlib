#!/usr/bin/env bash
set -euo pipefail

# Local Apple Silicon research runtime. Keep the Linux VM separate from Qlib and
# RD-Agent checkouts so both forks can continue tracking their upstreams.
command -v colima >/dev/null || { echo "colima is missing" >&2; exit 1; }
command -v docker >/dev/null || { echo "docker CLI is missing" >&2; exit 1; }
command -v ollama >/dev/null || { echo "ollama is missing" >&2; exit 1; }

colima start rdagent --cpus 4 --memory 6 --disk 40 --vm-type vz --runtime docker
docker context use colima-rdagent >/dev/null
brew services start ollama >/dev/null

docker info --format '{{.OSType}}/{{.Architecture}}'
ollama show bge-m3 >/dev/null
echo "Linux Docker runtime and local bge-m3 are ready"
