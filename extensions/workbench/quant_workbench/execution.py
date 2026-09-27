"""Execution domain: Attempt lifecycle, executor port and the shared execution service.

No engine SDK, database SDK or UI imports belong here; executors are injected ports.
"""

from __future__ import annotations

import json
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from .source_safety import Sanitizer
from .storage_attempts import StorageCapacityExceeded

TERMINAL_STATUSES = ("succeeded", "failed", "cancelled", "interrupted")
OPEN_STATUSES = ("queued", "running")
MAX_PARAMS_BYTES = 8192
MAX_ERROR_MESSAGE = 500


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


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


def attempt_dto(row: dict[str, Any]) -> dict[str, Any]:
    """Browser/CLI projection: no server paths, no credentials, unknown stays null."""
    sanitizer = Sanitizer()
    workspace = row.get("workspace") or ""
    cancel_requested_at = row.get("cancel_requested_at")
    return {
        "attempt_id": row["attempt_id"],
        "kind": row["kind"],
        "executor_id": row["executor_id"],
        "label": row["label"],
        "probe": bool(row.get("probe")),
        "status": row["status"],
        "cancel_pending": bool(cancel_requested_at and row["status"] in OPEN_STATUSES),
        "cancel_requested_at": cancel_requested_at,
        "created_at": row["created_at"],
        "queued_at": row.get("queued_at"),
        "started_at": row.get("started_at"),
        "ended_at": row.get("ended_at"),
        "heartbeat_at": row.get("heartbeat_at"),
        "exit_code": row.get("exit_code"),
        "error_code": row.get("error_code"),
        "error_message": sanitizer.text(row.get("error_message"), MAX_ERROR_MESSAGE) if row.get("error_message") else None,
        "config_fingerprint": row.get("config_fingerprint"),
        "workspace_label": Path(workspace).name if workspace else None,
        "has_log": bool(row.get("log_path")),
        "idempotency_key_present": bool(row.get("idempotency_key")),
        "request_id": row.get("request_id"),
        "params": sanitizer.scrub(row.get("params") or {}),
        "outcome": sanitizer.scrub(row.get("outcome")),
    }


class ExecutionService:
    """Submit, inspect, reconcile and cancel attempts through injected executors."""

    def __init__(self, repository, executors: list[ExecutorPort] | None = None, importer=None,
                 stats_window_seconds: int = 86400, policy=None):
        self.repository = repository
        self.executors = list(executors or [])
        self.policy = policy
        self.policy_error: str | None = None
        if self.policy is None:
            try:
                from .execution_policy import load_policy
                self.policy = load_policy()
            except Exception as exc:  # missing/invalid policy must refuse admission, not crash reads
                self.policy_error = f"{type(exc).__name__}: {exc}"
        # EXEC12: the importer is an injected port; the core never imports an engine SDK.
        self.importer = importer
        self.stats_window_seconds = stats_window_seconds
        self._by_kind: dict[str, ExecutorPort] = {}
        self._by_id: dict[str, ExecutorPort] = {}
        for executor in self.executors:
            self._by_id[executor.executor_id] = executor
            for kind in executor.kinds:
                self._by_kind[kind] = executor

    # -- catalog ---------------------------------------------------------
    def platform_checks(self) -> list[dict[str, Any]]:
        kinds = sorted(self._by_kind)
        try:
            health = self.repository.health()
            status = "ok" if health.get("status") == "ok" else "missing"
            detail = f"platform attempt store ready (schema {health.get('schema_version')})"
        except Exception as exc:
            status, detail = "missing", f"platform attempt store unavailable: {type(exc).__name__}"
        return [{"id": "platform.attempt_store", "status": status, "detail": detail, "required_for": kinds}]

    def _preflight(self, kind: str, refresh: bool = False) -> tuple[ExecutorPort, list[dict[str, Any]], list[str]]:
        executor = self._by_kind.get(kind)
        if executor is None:
            raise UnknownExecutionKind(f"no executor is configured for kind '{kind}'")
        payload = executor.preflight(refresh=refresh)
        platform = self.platform_checks()
        reasons = [reason for reason in payload.get("reasons", {}).get(kind, [])
                   if reason not in {check["id"] for check in platform}]
        reasons += [check["id"] for check in platform if check["status"] != "ok"]
        return executor, list(payload.get("checks", [])) + platform, reasons

    def catalog(self, refresh: bool = False) -> dict[str, Any]:
        items = []
        platform = self.platform_checks()
        for executor in self.executors:
            preflight = executor.preflight(refresh=refresh)
            for kind in executor.kinds:
                meta = executor.describe(kind)
                reasons = list(preflight.get("reasons", {}).get(kind, []))
                available = bool(preflight.get("available", {}).get(kind)) and all(
                    check["status"] == "ok" for check in platform)
                reasons += [check["id"] for check in platform if check["status"] != "ok"]
                items.append({
                    "kind": kind,
                    "executor_id": executor.executor_id,
                    "label": meta.get("label", kind),
                    "description": meta.get("description"),
                    "probe": bool(meta.get("probe")),
                    "data_nature": meta.get("data_nature"),
                    "result_destination": meta.get("result_destination", "unknown"),
                    "params": meta.get("params", []),
                    "available": available,
                    "checks": list(preflight.get("checks", [])) + platform,
                    "reasons": sorted(set(reasons)),
                    "checked_at": preflight.get("checked_at"),
                })
        return {"items": items, "checked_at": utc_now(), "policy": self.policy_summary()}

    def policy_summary(self) -> dict[str, Any]:
        """EXEC13/T04: the frozen policy and its usage, so limits are visible rather than implied."""
        if not self.policy:
            return {"available": False, "error": self.policy_error or "no_policy"}
        used = {row["kind"]: row["used"]
                for row in self.repository.agent_budget_rows(self.policy.revision())}
        return {
            "available": True, "revision": self.policy.revision(), "source": self.policy.source,
            "max_concurrent": self.policy.max_concurrent,
            "timeout_seconds": self.policy.timeout_seconds,
            "terminate_grace_seconds": self.policy.terminate_grace_seconds,
            "cpu_seconds": self.policy.cpu_seconds, "memory_bytes": self.policy.memory_bytes,
            "enforce": list(self.policy.enforce),
            "unenforced": [name for name in ("cpu", "memory") if name not in self.policy.enforce],
            "agent": {"max_trials": self.policy.agent_max_trials,
                      "max_calls": self.policy.agent_max_calls,
                      "scope": self.policy.agent_scope, "used": used,
                      "calls_enforced": any(self._agent_call_enforcement(executor)
                                            for executor in self.executors)},
            "notes": {"memory": "内存硬上限由容器 cgroup 强制：Qlib 入口在 qwb-qlib-cpu:local，"
                                "RD-Agent 整个 Attempt（驱动+因子代码）在 qwb-rdagent-cpu:local",
                      "calls": "调用次数由执行期文件账本强制（sitecustomize 包装 litellm."
                               "completion），终态核对进本表"},
        }

    @staticmethod
    def _agent_call_enforcement(executor) -> bool:
        probe = getattr(executor, "agent_call_enforcement", None)
        try:
            return bool(probe()) if callable(probe) else False
        except Exception:
            return False

    def capabilities(self) -> dict[str, Any]:
        return {
            "executor": "subprocess_v1" if self.executors else "not_implemented",
            "kinds": sorted(self._by_kind),
            "executors": [executor.executor_id for executor in self.executors],
            "policy": self.policy_summary(),
        }

    # -- lifecycle -------------------------------------------------------
    def submit(self, kind: str, params: dict[str, Any] | None = None,
               idempotency_key: str | None = None, request_id: str | None = None) -> dict[str, Any]:
        if not isinstance(kind, str) or not kind.strip():
            raise InvalidExecutionRequest("kind is required")
        params = {} if params is None else params
        if not isinstance(params, dict):
            raise InvalidExecutionRequest("params must be an object")
        try:
            encoded_params = json.dumps(params, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise InvalidExecutionRequest(f"params must be JSON serialisable: {exc}") from exc
        if len(encoded_params.encode()) > MAX_PARAMS_BYTES:
            raise InvalidExecutionRequest("params are too large")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 128:
            raise InvalidExecutionRequest("a non-empty idempotency_key of at most 128 characters is required")

        previous = self.repository.find_attempt_by_key(idempotency_key)
        if previous is not None:
            return {"attempt": attempt_dto(previous), "created": False}

        # EXEC13: bounded admission. A replay above never consumes a slot; a missing/invalid
        # policy refuses admission instead of pretending to be bounded.
        if self.policy_error:
            raise PreconditionFailed(
                [{"id": "execution_policy", "status": "fail", "detail": self.policy_error,
                  "required_for": []}], ["execution_policy"])
        open_attempts = self.repository.list_open_attempts(limit=max(1, self.policy.max_concurrent))
        if len(open_attempts) >= self.policy.max_concurrent:
            raise CapacityExceeded(
                f"execution capacity is full ({self.policy.max_concurrent} concurrent attempts)")
        # EXEC13: Agent entries reserve a trial before launch; retries count because every
        # submit reserves again, and the ledger is never cleared by cancel/restart.
        if str(kind).startswith("rdagent."):
            reservation = self.repository.reserve_agent_budget(
                policy_revision=self.policy.revision(), scope=self.policy.agent_scope,
                kind="trials", limit=self.policy.agent_max_trials)
            if not reservation["allowed"]:
                raise BudgetExhausted(
                    f"agent trial budget exhausted ({reservation['used']}/{reservation['limit']} "
                    f"for policy {self.policy.revision()}); research completeness is not implied")

        executor, checks, reasons = self._preflight(kind)
        if reasons:
            raise PreconditionFailed(checks, reasons)

        seed = getattr(executor, "seed_call_ledger", None)
        if callable(seed) and self._agent_call_enforcement(executor):
            # EXEC13: the call counter must survive across attempts, so the durable count
            # seeds the execution-time ledger before the child can reserve from it.
            durable = {row["kind"]: row["used"]
                       for row in self.repository.agent_budget_rows(self.policy.revision())}
            seed(attempts_seen=int(durable.get("calls", 0)))

        attempt_id = str(uuid.uuid4())
        prepared = executor.prepare(attempt_id, kind, params)
        meta = executor.describe(kind)
        created_at = utc_now()
        try:
            row, created = self.repository.create_attempt({
                "attempt_id": attempt_id, "kind": kind, "executor_id": executor.executor_id,
                "label": meta.get("label", kind), "probe": bool(meta.get("probe")), "status": "queued",
                "params": prepared.get("params", params), "idempotency_key": idempotency_key,
                "request_id": request_id,
                "config_fingerprint": prepared.get("config_fingerprint"),
                "workspace": prepared.get("workspace"),
                "log_path": prepared.get("log_path"), "created_at": created_at, "queued_at": created_at,
                "policy_revision": self.policy.revision() if self.policy else None,
            }, max_concurrent=self.policy.max_concurrent if self.policy else None)
        except StorageCapacityExceeded as exc:
            raise CapacityExceeded(str(exc)) from exc
        if not created:
            return {"attempt": attempt_dto(row), "created": False}
        try:
            started = executor.start(attempt_id, prepared)
        except Exception as exc:  # start failure is a platform-side failure, not a silent queued attempt
            self.repository.update_attempt(
                row["attempt_id"], status="failed", ended_at=utc_now(), error_code="start_failed",
                error_message=f"{type(exc).__name__}: {exc}")
            raise ExecutionError(f"executor failed to start the attempt: {exc}") from exc
        started_at = utc_now()
        deadline = None
        if self.policy:
            deadline = (datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                        + timedelta(seconds=self.policy.timeout_seconds)
                        ).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        updated = self.repository.update_attempt(
            row["attempt_id"], status="running", started_at=started_at, heartbeat_at=started_at,
            deadline_at=deadline,
            pid=started.get("pid"), workspace=started.get("workspace", prepared.get("workspace")),
            log_path=started.get("log_path", prepared.get("log_path")))
        return {"attempt": attempt_dto(updated or row), "created": True}

    def enforce_timeouts(self, now: str | None = None) -> dict[str, Any]:
        """EXEC13: terminate attempts past the policy deadline.

        There is no scheduler in this version, so supervision runs on the status-check path
        (reconcile/list/get). It only ends over-deadline work; it never starts anything.
        A confirmed end becomes `failed/timeout`; an unconfirmed one keeps `interrupted`
        plus a recorded timeout request instead of pretending the process is gone.
        """
        if not self.policy:
            return {"checked": 0, "timed_out": [], "reason": self.policy_error or "no_policy"}
        moment = datetime.fromisoformat((now or utc_now()).replace("Z", "+00:00"))
        timed_out = []
        for row in self.repository.list_open_attempts(limit=500):
            if row.get("status") != "running" or not row.get("started_at"):
                continue
            # The deadline is persisted at start; fall back to deriving it only for legacy rows.
            if row.get("deadline_at"):
                deadline = datetime.fromisoformat(str(row["deadline_at"]).replace("Z", "+00:00"))
            else:
                started = datetime.fromisoformat(str(row["started_at"]).replace("Z", "+00:00"))
                deadline = started + timedelta(seconds=self.policy.timeout_seconds)
            if moment <= deadline:
                continue
            outcome = self.cancel(row["attempt_id"])
            confirmed = bool(outcome.get("cancel_confirmed"))
            detail = (f"exceeded the {self.policy.timeout_seconds}s deadline "
                      f"(policy {self.policy.revision()})")
            if confirmed:
                self.repository.update_attempt(
                    row["attempt_id"], status="failed", error_code="timeout",
                    error_message=detail, ended_at=utc_now(), cancel_requested_at=utc_now())
                timed_out.append({"attempt_id": row["attempt_id"], "result": "timed_out"})
            else:
                self.repository.update_attempt(
                    row["attempt_id"], error_code="timeout_unconfirmed",
                    error_message=detail + "; termination not confirmed", cancel_requested_at=utc_now())
                timed_out.append({"attempt_id": row["attempt_id"], "result": "timeout_unconfirmed"})
        return {"checked": 1, "timed_out": timed_out}

    def reconcile(self, attempt_ids: list[str] | None = None, limit: int = 100) -> dict[str, Any]:
        self.enforce_timeouts()
        if attempt_ids:
            rows = [self.repository.get_attempt(attempt_id) for attempt_id in attempt_ids]
        else:
            rows = self.repository.list_open_attempts(limit)
        checked, transitioned = 0, 0
        for row in rows:
            if not row or row["status"] not in OPEN_STATUSES:
                continue
            executor = self._by_id.get(row["executor_id"])
            if executor is None:
                self.repository.update_attempt(
                    row["attempt_id"], error_code="executor_not_configured",
                    error_message=f"executor '{row['executor_id']}' is not configured in this process")
                continue
            checked += 1
            result = executor.poll(row)
            state = result.get("state")
            if state == "running":
                self.repository.update_attempt(row["attempt_id"], heartbeat_at=utc_now())
                continue
            if state not in TERMINAL_STATUSES:
                continue
            if state == "cancelled":
                # A cancel signal observed first must not resurrect an open attempt.
                self.repository.update_attempt(
                    row["attempt_id"], status="cancelled", ended_at=result.get("ended_at") or utc_now(),
                    exit_code=result.get("exit_code"), heartbeat_at=utc_now(),
                    error_code=result.get("error_code"), error_message=result.get("error_message"))
                transitioned += 1
                continue
            terminal = {**row, "status": state, "exit_code": result.get("exit_code"),
                        "ended_at": result.get("ended_at") or utc_now()}
            outcome = None
            try:
                outcome = executor.outcome(terminal)
            except Exception as exc:  # outcome collection must never overwrite the execution result
                outcome = {"collection_error": f"{type(exc).__name__}: {exc}"}
            reporter = getattr(executor, "agent_budget_report", None)
            if callable(reporter):
                try:
                    report = reporter(terminal)
                except Exception as exc:
                    report = {"kind": "calls", "status": "report_failed",
                              "error": f"{type(exc).__name__}: {exc}"}
                if report:
                    reconciled = self.repository.record_agent_budget(
                        policy_revision=self.policy.revision(),
                        scope=str(report.get("scope") or self.policy.agent_scope), kind="calls",
                        limit=self.policy.agent_max_calls, used=int(report.get("used") or 0))
                    outcome = {**(outcome or {}), "agent_budget": {
                        "calls": {**report, "durable_used": reconciled["used"]}}}
            if state == "succeeded":
                outcome = self._auto_import(terminal, outcome)
            self.repository.update_attempt(
                row["attempt_id"], status=state, ended_at=terminal["ended_at"],
                exit_code=result.get("exit_code"), heartbeat_at=utc_now(),
                error_code=result.get("error_code"), error_message=result.get("error_message"), outcome=outcome)
            transitioned += 1
        return {"checked": checked, "transitioned": transitioned}

    # -- result import (EXEC12) ------------------------------------------
    def _auto_import(self, attempt: dict[str, Any], outcome: dict[str, Any] | None) -> dict[str, Any]:
        outcome = dict(outcome or {})
        executor = self._by_id.get(attempt.get("executor_id"))
        getter = getattr(executor, "import_candidate", None) if executor else None
        candidate = None
        if getter is not None:
            try:
                candidate = getter({**attempt, "outcome": outcome})
            except Exception as exc:
                candidate = None
                outcome["import_notes"] = [*outcome.get("import_notes", []),
                                           f"import candidate failed: {type(exc).__name__}"]
        if not candidate:
            reason = "no_import_candidate_for_kind"
            if executor is not None:
                describe = getattr(executor, "import_unavailable_reason", None)
                reason = (describe(attempt) if describe else None) or reason
            if getter is None:
                reason = "executor_has_no_importer"
            outcome["result_import"] = {"status": "manual_import_required", "reason": reason, "checked_at": utc_now()}
            return outcome
        if self.importer is None:
            outcome["result_import"] = {"status": "manual_import_required",
                                        "reason": "platform_importer_not_configured", "checked_at": utc_now()}
            return outcome
        source_instance_id = candidate.get("source_instance_id") or "attempt-result"
        external_id = str(candidate.get("external_id") or attempt["attempt_id"])
        adapter_version = candidate.get("adapter_version") or "unknown"
        try:
            receipt = self.importer.import_attempt(attempt, candidate) or {}
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"[:MAX_ERROR_MESSAGE]
            outcome["result_import"] = {"status": "failed", "reason": reason, "checked_at": utc_now()}
            self._record_receipt({
                "receipt_id": hashlib.sha256(f"failed:{attempt['attempt_id']}".encode()).hexdigest()[:32],
                "attempt_id": attempt["attempt_id"], "run_id": None, "revision_id": None,
                "source_instance_id": source_instance_id, "external_id": external_id,
                "adapter_version": adapter_version, "status": "failed", "reason": reason,
                "imported_at": utc_now()})
            return outcome
        record = {
            "receipt_id": receipt.get("receipt_id") or hashlib.sha256(
                f"{attempt['attempt_id']}:{receipt.get('run_id')}:{receipt.get('revision_id')}".encode()).hexdigest()[:32],
            "attempt_id": attempt["attempt_id"],
            "run_id": receipt.get("run_id"), "revision_id": receipt.get("revision_id"),
            "source_instance_id": receipt.get("source_instance_id") or source_instance_id,
            "external_id": str(receipt.get("external_id") or external_id),
            "adapter_version": receipt.get("adapter_version") or adapter_version,
            "status": "reused" if receipt.get("created") is False else "imported",
            "reason": None, "imported_at": utc_now(),
        }
        self._record_receipt(record)
        outcome["result_import"] = {
            "status": record["status"], "run_id": record["run_id"], "revision_id": record["revision_id"],
            "receipt_id": record["receipt_id"], "adapter_version": record["adapter_version"],
            "imported_at": record["imported_at"],
        }
        return outcome

    def _record_receipt(self, record: dict[str, Any]) -> None:
        try:
            self.repository.record_import(record)
        except Exception:  # a receipt failure must not rewrite an execution result
            pass

    def import_result(self, attempt_id: str) -> dict[str, Any]:
        """Explicit retry for an attempt that has no successful import receipt yet."""
        row = self.repository.get_attempt(attempt_id)
        if row is None:
            raise AttemptNotFound(f"attempt '{attempt_id}' was not found")
        if row["status"] != "succeeded":
            raise InvalidExecutionRequest("only succeeded attempts can be imported")
        current = (row.get("outcome") or {}).get("result_import") or {}
        if current.get("status") in ("imported", "reused"):
            return {"attempt": attempt_dto(row), "imported": False, "reason": "already_imported",
                    "receipt": self.repository.latest_import(attempt_id)}
        outcome = self._auto_import({**row, "status": "succeeded"}, row.get("outcome"))
        updated = self.repository.update_attempt(attempt_id, outcome=outcome)
        state = (outcome.get("result_import") or {}).get("status")
        return {"attempt": attempt_dto(updated or row), "imported": state in ("imported", "reused"),
                "reason": None if state in ("imported", "reused") else (outcome.get("result_import") or {}).get("reason"),
                "receipt": self.repository.latest_import(attempt_id)}

    def stats(self, window_seconds: int | None = None) -> dict[str, Any]:
        return self.repository.attempt_stats(window_seconds or self.stats_window_seconds)

    def list(self, limit: int = 20, cursor: str | None = None) -> dict[str, Any]:
        self.reconcile()
        page = self.repository.list_attempts(limit, cursor)
        return {"items": [attempt_dto(row) for row in page["items"]], "next_cursor": page["next_cursor"]}

    def get(self, attempt_id: str) -> dict[str, Any] | None:
        self.reconcile([attempt_id])
        row = self.repository.get_attempt(attempt_id)
        return attempt_dto(row) if row else None

    def cancel(self, attempt_id: str) -> dict[str, Any]:
        attempt = self.repository.get_attempt(attempt_id)
        if attempt is None:
            raise AttemptNotFound(f"attempt '{attempt_id}' was not found")
        if attempt["status"] in TERMINAL_STATUSES:
            return {"attempt": attempt_dto(attempt), "cancel_confirmed": False, "reason": "already_terminal"}
        executor = self._by_id.get(attempt["executor_id"])
        if executor is None:
            raise InvalidExecutionRequest(f"executor '{attempt['executor_id']}' is not configured")
        if not attempt.get("pid"):
            updated = self.repository.update_attempt(
                attempt_id, status="cancelled", ended_at=utc_now(),
                cancel_requested_at=attempt.get("cancel_requested_at") or utc_now(),
                outcome={"cancel": {"reason": "not_started", "confirmed_at": utc_now()}})
            return {"attempt": attempt_dto(updated), "cancel_confirmed": True, "reason": "not_started"}

        requested_at = attempt.get("cancel_requested_at") or utc_now()
        attempt = self.repository.update_attempt(attempt_id, cancel_requested_at=requested_at)
        result = executor.cancel(attempt)
        state = result.get("state")
        if state in TERMINAL_STATUSES and state != "cancelled":
            # Completion evidence wins over a late cancel request (RUN02).
            fresh = self.repository.get_attempt(attempt_id)
            if fresh["status"] not in TERMINAL_STATUSES:
                outcome = None
                try:
                    outcome = executor.outcome({**fresh, "status": state, "exit_code": result.get("exit_code")})
                except Exception:
                    outcome = None
                if state == "succeeded":
                    outcome = self._auto_import({**fresh, "status": state}, outcome)
                self.repository.update_attempt(
                    attempt_id, status=state, ended_at=result.get("ended_at") or utc_now(),
                    exit_code=result.get("exit_code"), outcome=outcome, heartbeat_at=utc_now())
            return {"attempt": attempt_dto(self.repository.get_attempt(attempt_id)),
                    "cancel_confirmed": False, "reason": "terminal_evidence_wins"}
        if not result.get("confirmed"):
            updated = self.repository.update_attempt(
                attempt_id, error_code="cancel_not_confirmed",
                error_message=result.get("reason") or "executor did not confirm the process end")
            return {"attempt": attempt_dto(updated), "cancel_confirmed": False,
                    "reason": result.get("reason") or "cancel_not_confirmed"}
        # A concurrent refresh can observe the killed process before the exit marker exists and
        # label it interrupted; a confirmed cancel must not keep that failure label (RUN02).
        updated = self.repository.update_attempt(
            attempt_id, status="cancelled", ended_at=result.get("ended_at") or utc_now(),
            exit_code=result.get("exit_code"), heartbeat_at=utc_now(),
            error_code=None, error_message=None,
            outcome={"cancel": {"requested_at": requested_at, "confirmed_at": utc_now(),
                                "evidence": result.get("evidence")}})
        return {"attempt": attempt_dto(updated), "cancel_confirmed": True,
                "reason": result.get("reason") or "process_end_confirmed"}

    def log(self, attempt_id: str, lines: int = 200) -> dict[str, Any]:
        if isinstance(lines, bool) or not isinstance(lines, int) or not 1 <= lines <= 1000:
            raise InvalidExecutionRequest("tail must be between 1 and 1000 lines")
        attempt = self.repository.get_attempt(attempt_id)
        if attempt is None:
            raise AttemptNotFound(f"attempt '{attempt_id}' was not found")
        executor = self._by_id.get(attempt["executor_id"])
        if executor is None:
            return {"attempt_id": attempt_id, "available": False, "reason": "executor_not_configured", "lines": []}
        return {"attempt_id": attempt_id, **executor.log_tail(attempt, lines)}
