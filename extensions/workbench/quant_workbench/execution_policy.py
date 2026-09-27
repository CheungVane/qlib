"""Execution policy and resource-limit capability (EXEC13 / T04 / A41).

Fail-closed rules:

* the policy is loaded from an explicit config file; missing/invalid values raise;
* the policy revision is a hash of the frozen values and is persisted with the attempt;
* a limit listed in `enforce` must be verifiable in this environment — otherwise admission
  is refused with the exact unsupported limit named.

CPU hard limits are enforced with RLIMIT_CPU in the child process. macOS refuses finite
RLIMIT_AS/RLIMIT_DATA in this environment, so memory enforcement is declared as a visible
limitation rather than silently assumed; A41 stays incomplete there by contract.
"""

from __future__ import annotations

import hashlib
import json
import resource
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


def probe_enforcement() -> dict:
    """Actually try the limits in throwaway children; never assume support."""
    cpu_supported = False
    probe = ("import resource;resource.setrlimit(resource.RLIMIT_CPU,(1,1));\n"
             "while True: pass")
    try:
        finished = subprocess.run([sys.executable, "-c", probe], capture_output=True, timeout=20)
        cpu_supported = finished.returncode in (-24, -9)  # SIGXCPU / SIGKILL
    except subprocess.TimeoutExpired:
        cpu_supported = False
    memory_supported = False
    probe_mem = ("import resource;resource.setrlimit(resource.RLIMIT_AS,(134217728,134217728));"
                 "print('ok')")
    try:
        finished = subprocess.run([sys.executable, "-c", probe_mem], capture_output=True, timeout=20)
        memory_supported = finished.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        memory_supported = False
    return {"cpu": cpu_supported, "memory": memory_supported,
            "probe": {"cpu_seconds": 1, "memory_bytes": 134217728}}


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
