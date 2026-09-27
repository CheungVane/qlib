"""Execution-time agent call ledger and the litellm interception point.

This module is injected into the RD-Agent child process through PYTHONPATH (see
sitecustomize.py). It deliberately uses only the standard library: it must import inside
RD-Agent's own virtualenv, and it must not import the workbench package or touch the
platform database — the child only ever writes the file ledger handed to it by the executor.

Units: one wrapped `litellm.completion` call reserves one unit. Client-level retries inside
that call are not counted separately, which is the documented unit in EXEC13.
"""
from __future__ import annotations

import fcntl
import json
import os
import time
from pathlib import Path


class AgentCallBudgetExhausted(RuntimeError):
    """Raised instead of issuing a call once the shared budget is spent."""

    code = "qwb_agent_call_budget_exhausted"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


def ledger_path() -> Path:
    return Path(os.environ["QWB_AGENT_BUDGET_FILE"])


def read_state(path: str | Path | None = None) -> dict:
    target = Path(path) if path else ledger_path()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"limit": None, "used": 0, "events": [], "blocked_at": None}
    if not isinstance(payload, dict):
        return {"limit": None, "used": 0, "events": [], "blocked_at": None}
    payload.setdefault("events", [])
    payload.setdefault("used", 0)
    payload.setdefault("blocked_at", None)
    return payload


def _write_state(path: Path, state: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def seed(*, path: str | Path | None = None, limit: int, used: int = 0,
         scope: str | None = None, attempt_id: str | None = None) -> dict:
    """Create or top up the ledger for one policy scope (never lowers `used`)."""
    target = Path(path) if path else ledger_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    lock = target.with_suffix(target.suffix + ".lock")
    with lock.open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        state = read_state(target)
        state["limit"] = int(limit)
        state["used"] = max(int(state.get("used") or 0), int(used))
        if scope:
            state["scope"] = scope
        if attempt_id:
            state.setdefault("seeded_for", []).append(attempt_id)
        _write_state(target, state)
        return state


def reserve(units: int = 1, *, path: str | Path | None = None, attempt_id: str | None = None,
            limit: int | None = None, kind: str = "completion") -> tuple[bool, int, int]:
    """Atomically reserve `units`; returns (allowed, used, limit).

    The lock is a separate `.lock` file so the state file itself is only ever replaced
    atomically. `used` never decreases, so cancellation or a platform restart cannot hand
    budget back.
    """
    target = Path(path) if path else ledger_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    lock = target.with_suffix(target.suffix + ".lock")
    env_limit = os.environ.get("QWB_AGENT_BUDGET_LIMIT")
    with lock.open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        state = read_state(target)
        resolved = int(limit or state.get("limit") or (env_limit or 0))
        used = int(state.get("used") or 0)
        if resolved > 0 and used + units > resolved:
            state["blocked_at"] = _now()
            state["blocked_kind"] = kind
            state["blocked_attempt"] = attempt_id
            _write_state(target, state)
            return False, used, resolved
        state["used"] = used + units
        state["limit"] = resolved or state.get("limit")
        state.setdefault("events", []).append(
            {"at": _now(), "kind": kind, "units": units, "attempt_id": attempt_id})
        _write_state(target, state)
        return True, used + units, resolved


def _wrap(function, *, path: str | Path | None = None):  # pragma: no cover - exercised in tests
    def guarded(*args, **kwargs):
        attempt_id = os.environ.get("QWB_ATTEMPT_ID")
        allowed, used, limit = reserve(path=path, attempt_id=attempt_id)
        if not allowed:
            raise AgentCallBudgetExhausted(
                f"{AgentCallBudgetExhausted.code}: agent call budget exhausted ({used}/{limit})")
        return function(*args, **kwargs)

    guarded.__qwb_budget_wrapped__ = True  # type: ignore[attr-defined]
    guarded.__wrapped__ = function  # type: ignore[attr-defined]
    return guarded


def patch_module(module, *, path: str | Path | None = None) -> list[str]:
    """Wrap the call entry points on an imported `litellm` module."""
    patched: list[str] = []
    for name in ("completion",):
        original = getattr(module, name, None)
        if not callable(original) or getattr(original, "__qwb_budget_wrapped__", False):
            continue
        setattr(module, name, _wrap(original, path=path))
        patched.append(name)
    return patched


def install_litellm_hook(*, path: str | Path | None = None) -> None:
    """Patch `litellm` as soon as it is imported, without importing it eagerly."""
    import importlib.util
    import sys

    if any(getattr(finder, "_qwb_budget_finder", False) for finder in sys.meta_path):
        return

    class _Loader:
        def __init__(self, loader):
            self._loader = loader

        def create_module(self, spec):
            return self._loader.create_module(spec)

        def exec_module(self, module):
            self._loader.exec_module(module)
            patch_module(module, path=path)

        def __getattr__(self, name):
            return getattr(self._loader, name)

    class _Finder:
        _qwb_budget_finder = True

        def find_spec(self, fullname, path=None, target=None):
            if fullname != "litellm":
                return None
            sys.meta_path.remove(self)
            try:
                spec = importlib.util.find_spec(fullname)
            finally:
                sys.meta_path.insert(0, self)
            if spec is None or spec.loader is None:
                return None
            spec.loader = _Loader(spec.loader)
            return spec

    sys.meta_path.insert(0, _Finder())
