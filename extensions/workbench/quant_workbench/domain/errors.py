"""Shared errors; adapters and use cases depend on the same error identities."""
from __future__ import annotations
from typing import Any

class StorageCapacityExceeded(RuntimeError):
    """Repository admission capacity exhausted inside its write transaction."""

class ExecutionError(RuntimeError):
    code = "execution_error"
    status_code = 400

    def as_details(self) -> dict[str, Any]:
        return {}

class InvalidExecutionRequest(ExecutionError):
    code = "invalid_request"
    status_code = 400

class UnknownExecutionKind(ExecutionError):
    code = "unknown_kind"
    status_code = 404

class AttemptNotFound(ExecutionError):
    code = "attempt_not_found"
    status_code = 404

class PreconditionFailed(ExecutionError):
    code = "precondition_failed"
    status_code = 409

    def __init__(self, checks: list[dict[str, Any]], reasons: list[str]):
        self.checks = checks
        self.reasons = reasons
        super().__init__("execution preconditions are not satisfied")

    def as_details(self) -> dict[str, Any]:
        return {"checks": self.checks, "reasons": self.reasons}

class CapacityExceeded(ExecutionError):
    """EXEC13: the concurrency slots are full, so no new attempt may be created."""

    code = "capacity_exceeded"
    status_code = 409

class BudgetExhausted(ExecutionError):
    """EXEC13: the Agent trial/call budget is used up; the next call must be blocked."""

    code = "budget_exhausted"
    status_code = 409


class SnapshotError(ValueError):
    """Public DATA04-A failure; details contain logical identities, never host paths."""
    def __init__(self, code: str, snapshot_id: str, component: str | None = None):
        self.code = code
        self.status_code = 404 if code == 'snapshot_not_found' else 409
        self.details = {'snapshot_id': snapshot_id}
        if component is not None:
            self.details['component'] = component
        super().__init__(code)


class ManagedExecutionUnavailable(ExecutionError):
    """Managed Run adapters/protection are absent; never fall back to legacy submit."""
    code = "capability_unavailable"
    status_code = 409
