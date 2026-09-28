"""Infrastructure-neutral interfaces; DTO semantics are defined in docs/spec."""
from __future__ import annotations
from typing import Any, Protocol

class ExecutorPort(Protocol):
    """Executor boundary.

    ``preflight`` returns ``{"checks": [...], "available": {kind: bool}, "reasons": {kind: [check_id]}}``;
    a check carries ``required_for`` listing the kinds it blocks. ``prepare`` must not start work.
    """

    executor_id: str
    kinds: tuple[str, ...]

    def describe(self, kind: str) -> dict[str, Any]: ...

    def preflight(self, refresh: bool = False) -> dict[str, Any]: ...

    def prepare(self, attempt_id: str, kind: str, params: dict[str, Any]) -> dict[str, Any]: ...

    def start(self, attempt_id: str, prepared: dict[str, Any]) -> dict[str, Any]: ...

    def poll(self, attempt: dict[str, Any]) -> dict[str, Any]: ...

    def cancel(self, attempt: dict[str, Any]) -> dict[str, Any]: ...

    def outcome(self, attempt: dict[str, Any]) -> dict[str, Any]: ...

    def log_tail(self, attempt: dict[str, Any], lines: int) -> dict[str, Any]: ...

class AttemptImporter(Protocol):
    def import_attempt(self, attempt: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]: ...
