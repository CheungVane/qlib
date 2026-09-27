"""Execution policy and resource-limit capability (EXEC13 / T04 / A41).

Fail-closed rules:

* the policy is loaded from an explicit config file; missing/invalid values raise;
* the policy revision is a hash of the frozen values and is persisted with the attempt;
* a limit listed in `enforce` must be verifiable in this environment — otherwise admission
  is refused with the exact unsupported limit named.

CPU hard limits are enforced with RLIMIT_CPU (`ulimit -t` on the host path, `--ulimit cpu=`
inside a container). macOS refuses finite RLIMIT_AS/RLIMIT_DATA, so a memory hard limit can
only be enforced through container cgroups (`--memory`/`--memory-swap`); an executor that
cannot apply them must refuse admission instead of running uncapped.
"""

from __future__ import annotations

import hashlib
import json
import resource
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[3] / "configs/workbench/execution_policy.json"


class PolicyError(ValueError):
    """Missing, invalid or unenforceable execution policy."""


@dataclass(frozen=True)
class ExecutionPolicy:
    max_concurrent: int
    timeout_seconds: int
    terminate_grace_seconds: int
    cpu_seconds: int
    memory_bytes: int
    enforce: tuple[str, ...]
    agent_max_trials: int
    agent_max_calls: int
    agent_scope: str
    source: str = "config"

    def revision(self) -> str:
        payload = json.dumps({
            "max_concurrent": self.max_concurrent, "timeout_seconds": self.timeout_seconds,
            "terminate_grace_seconds": self.terminate_grace_seconds,
            "cpu_seconds": self.cpu_seconds, "memory_bytes": self.memory_bytes,
            "enforce": list(self.enforce), "agent_max_trials": self.agent_max_trials,
            "agent_max_calls": self.agent_max_calls, "agent_scope": self.agent_scope,
        }, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()[:32]

    def limit_profile(self) -> dict:
        profile = {"cpu_seconds": self.cpu_seconds, "memory_bytes": self.memory_bytes,
                   "enforced": list(self.enforce)}
        profile["unenforced"] = [name for name in ("cpu", "memory") if name not in self.enforce]
        return profile


def _positive(payload: dict, key: str, *, allow_zero: bool = False) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or (value < 0 if allow_zero else value <= 0):
        raise PolicyError(f"execution policy field {key!r} must be an explicit "
                          f"{'non-negative' if allow_zero else 'positive'} integer")
    return value


def load_policy(path: str | Path | None = None) -> ExecutionPolicy:
    target = Path(path) if path else DEFAULT_POLICY_PATH
    if not target.exists():
        raise PolicyError(f"execution policy config is missing: {target}")
    try:
        payload = json.loads(target.read_text())
    except json.JSONDecodeError as error:
        raise PolicyError(f"execution policy is not valid JSON: {error}") from error
    enforce = payload.get("enforce")
    if not isinstance(enforce, list) or not enforce or any(
            item not in ("cpu", "memory") for item in enforce):
        raise PolicyError("execution policy field 'enforce' must list 'cpu' and/or 'memory'")
    budget = payload.get("agent_budget") or {}
    return ExecutionPolicy(
        max_concurrent=_positive(payload, "max_concurrent"),
        timeout_seconds=_positive(payload, "timeout_seconds"),
        terminate_grace_seconds=_positive(payload, "terminate_grace_seconds"),
        cpu_seconds=_positive(payload, "cpu_seconds"),
        memory_bytes=_positive(payload, "memory_bytes"),
        enforce=tuple(enforce),
        agent_max_trials=_positive(budget, "max_trials"),
        agent_max_calls=_positive(budget, "max_calls"),
        agent_scope=str(budget.get("scope") or "policy_revision"),
        source=str(target.name),
    )


PROBE_IMAGE = "python:3.12-alpine"
PROBE_MEMORY_BYTES = 134217728


def _probe_cpu_rlimit() -> bool:
    """macOS/Linux support RLIMIT_CPU; verified by actually killing a child."""
    cpu_supported = False
    probe = ("import resource;resource.setrlimit(resource.RLIMIT_CPU,(1,1));\n"
             "while True: pass")
    try:
        finished = subprocess.run([sys.executable, "-c", probe], capture_output=True, timeout=20)
        cpu_supported = finished.returncode in (-24, -9)  # SIGXCPU / SIGKILL
    except subprocess.TimeoutExpired:
        cpu_supported = False
    return cpu_supported


def _probe_memory_container() -> bool:
    """Memory hard limits are enforceable through cgroups, not macOS rlimits.

    Verified by running a container that tries to exceed its cap: an OOM kill (137)
    proves the limit is real; anything else means we must not claim support.
    """
    if shutil.which("docker") is None:
        return False
    try:
        finished = subprocess.run(
            ["docker", "run", "--rm", f"--memory={PROBE_MEMORY_BYTES}b",
             f"--memory-swap={PROBE_MEMORY_BYTES}b", PROBE_IMAGE, "python", "-c",
             f"bytearray({PROBE_MEMORY_BYTES * 3})"],
            capture_output=True, timeout=300)
    except (subprocess.TimeoutExpired, OSError):
        return False
    return finished.returncode == 137


def probe_enforcement() -> dict:
    """Actually probe each mechanism in throwaway processes; never assume support."""
    cpu_rlimit = _probe_cpu_rlimit()
    memory_container = _probe_memory_container()
    return {
        "cpu": cpu_rlimit,
        "memory": memory_container,
        "mechanisms": {"cpu": "rlimit_cpu", "memory": "container_cgroup"},
        "probe": {"cpu_seconds": 1, "memory_bytes": PROBE_MEMORY_BYTES, "image": PROBE_IMAGE},
        "notes": {"memory": "macOS rlimit cannot cap memory; the container path is verified "
                            "by an OOM probe, but an executor only benefits once it runs in "
                            "that container"},
    }


def unsupported_limits(policy: ExecutionPolicy, capabilities: dict) -> list[str]:
    """Required limits that this environment cannot enforce (admission must be refused)."""
    return [name for name in policy.enforce if not capabilities.get(name)]


def child_limits(policy: ExecutionPolicy) -> dict:
    """Limits handed to the executor for the child process, with a hard cap for the soft one."""
    limits = {}
    if "cpu" in policy.enforce:
        limits["cpu_seconds"] = (policy.cpu_seconds, policy.cpu_seconds)
    if "memory" in policy.enforce:
        limits["memory_bytes"] = (policy.memory_bytes, policy.memory_bytes)
    return limits


def container_flags(limits: dict) -> list[str]:
    """Docker flags expressing the policy for a container-routed attempt.

    Memory is the cgroup limit (`--memory`/`--memory-swap`, swap disabled so the cap is real);
    CPU stays RLIMIT_CPU, applied inside the container through `--ulimit cpu=`. Only limits the
    policy actually hands to the executor (`child_limits`) become flags.
    """
    flags: list[str] = []
    memory = (limits.get("memory_bytes") or (None,))[0]
    if memory:
        flags.append(f"--memory={int(memory)}b")
        flags.append(f"--memory-swap={int(memory)}b")
    cpu = (limits.get("cpu_seconds") or (None,))[0]
    if cpu:
        flags.append(f"--ulimit=cpu={int(cpu)}:{int(cpu)}")
    return flags


def container_limits(policy: ExecutionPolicy) -> list[str]:
    """Docker flags for the container path, derived from the executor's own limit dict."""
    return container_flags(child_limits(policy))
