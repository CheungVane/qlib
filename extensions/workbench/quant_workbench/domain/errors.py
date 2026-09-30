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

    def __init__(self, message: str = "concurrency slots are full", *, scope_id: str | None = None,
                 dimension: str = "concurrency", limit: int | None = None,
                 used: int | None = None, requested: int | None = None):
        self._details = ({} if limit is None else
                         {"scope_id": scope_id, "dimension": dimension, "limit": limit,
                          "used": used, "requested": requested})
        super().__init__(message)

    def as_details(self) -> dict[str, Any]:
        return dict(self._details)


class BudgetExhausted(ExecutionError):
    """EXEC13: the Agent trial/call budget is used up; the next call must be blocked."""

    code = "budget_exhausted"
    status_code = 409

    def __init__(self, message: str = "budget exhausted", *, scope_id: str | None = None,
                 dimension: str | None = None, limit: int | None = None,
                 used: int | None = None, requested: int | None = None):
        self._details = ({} if limit is None else
                         {"scope_id": scope_id, "dimension": dimension, "limit": limit,
                          "used": used, "requested": requested})
        super().__init__(message)

    def as_details(self) -> dict[str, Any]:
        return dict(self._details)


class IdempotencyConflict(ExecutionError):
    """COMMAND §4: one key was reused with a different normalized payload."""

    code = "idempotency_conflict"
    status_code = 409

    def __init__(self, idempotency_key: str, original_operation: str):
        self.idempotency_key = idempotency_key
        self.original_operation = original_operation
        super().__init__(f"idempotency key {idempotency_key!r} was used by another payload")

    def as_details(self) -> dict[str, Any]:
        return {"idempotency_key": self.idempotency_key,
                "original_operation": self.original_operation}


class PlanExpired(ExecutionError):
    """COMMAND §4 / PHYSICAL §3: a frozen plan may be replayed but not newly admitted."""

    code = "plan_expired"
    status_code = 409

    def __init__(self, plan_ref: dict[str, Any], expired_at: str):
        self.plan_ref = plan_ref
        self.expired_at = expired_at
        super().__init__("the data preparation plan has expired")

    def as_details(self) -> dict[str, Any]:
        return {"plan_ref": self.plan_ref, "expired_at": self.expired_at}


class ReferenceMismatch(ExecutionError):
    """One of the four Ref fields did not match the published artifact."""

    code = "reference_mismatch"
    status_code = 409

    def __init__(self, artifact_id: str, expected_digest: str | None = None,
                 provided_digest: str | None = None):
        self.artifact_id = artifact_id
        self.expected_digest = expected_digest
        self.provided_digest = provided_digest
        super().__init__(f"reference {artifact_id!r} does not match the published artifact")

    def as_details(self) -> dict[str, Any]:
        return {"artifact_id": self.artifact_id, "expected_digest": self.expected_digest,
                "provided_digest": self.provided_digest}


class RetryNotAllowed(ExecutionError):
    """COMMAND §4: retry requires a settled previous Attempt on the same Run."""

    code = "retry_not_allowed"
    status_code = 409

    def __init__(self, run_id: str | None = None, workflow_id: str | None = None,
                 reason_code: str = "previous_attempt_not_settled"):
        self.run_id = run_id
        self.workflow_id = workflow_id
        self.reason_code = reason_code
        super().__init__("retry is not allowed for this Run")

    def as_details(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "workflow_id": self.workflow_id,
                "reason_code": self.reason_code}


class LedgerScopeMissing(ExecutionError):
    """PHYSICAL §3: reserve_usage never invents a limit; the scope must be registered."""

    code = "precondition_failed"
    status_code = 409

    def __init__(self, scope_id: str, dimension: str):
        self.scope_id = scope_id
        self.dimension = dimension
        super().__init__(f"budget scope {scope_id!r}/{dimension!r} is not registered")

    def as_details(self) -> dict[str, Any]:
        return {"checks": [{"code": "budget_scope_missing", "status": "fail",
                            "message": f"{self.scope_id}/{self.dimension}",
                            "field_path": None, "blocking": True}]}


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
