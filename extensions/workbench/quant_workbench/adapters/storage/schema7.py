"""Schema7 managed-run storage adapter (PHYSICAL_CONTRACT §2—§4).

This is the G1-2 storage slice: immutable artifact registration, idempotent
managed admission (Run/Attempt/Stages/lease/event/receipt in ONE transaction)
and atomic multi-dimension usage reservation. It is deliberately not wired
into the production composition root (G1-5) and starts no supervisor (G1-3):
the running service still supports schema6 only.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from ...domain.admission import AdmissionCommand, AdmissionReceipt, AdmissionRequest, EntryPoint
from ...domain.artifacts import ArtifactRef
from ...domain.contracts import parse_envelope
from ...domain.errors import (BudgetExhausted, CapacityExceeded, IdempotencyConflict,
                              LedgerScopeMissing, PlanExpired, PreconditionFailed,
                              ReferenceMismatch, RetryNotAllowed)
from .migrations import database_path
from .storage_base import LocalObjectStore

SCHEMA_VERSION = 7
CONCURRENCY_SCOPE = "concurrency:global"
SETTLED_ATTEMPT_STATUSES = ("succeeded", "failed", "cancelled")


class Schema7VersionError(RuntimeError):
    """The adapter refuses anything but the frozen schema7 target."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False)


def artifact_content_digest(artifact_type: str, schema_version: int, parent_refs: list[dict],
                            payload: Any, provenance: dict) -> str:
    """ARTIFACT_CONTRACT §1 digest input; IDs/created_at/producer are excluded."""
    ordered = sorted(parent_refs, key=lambda item: (item["role"], item["ordinal"]))
    body = {"artifact_type": artifact_type, "schema_version": schema_version,
            "parent_refs": ordered, "payload": payload, "provenance": provenance}
    return "sha256:" + hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


class Schema7Store:
    """Explicit schema7 fixture/production-candidate adapter; never auto-migrates."""

    def __init__(self, root: str | Path, *, before_commit: Callable[[], None] | None = None):
        self.root = Path(root).expanduser().resolve()
        self.db = database_path(self.root)
        self.object_store = LocalObjectStore(self.root / "objects")
        self.before_commit = before_commit
        self._require_version()

    # -- connection and version ------------------------------------------
    def _require_version(self) -> None:
        if not self.db.is_file():
            raise Schema7VersionError(f"schema7 database does not exist: {self.db}; run storage migrate")
        conn = sqlite3.connect(f"file:{self.db}?mode=ro", uri=True)
        try:
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        finally:
            conn.close()
        if version != SCHEMA_VERSION:
            raise Schema7VersionError(f"database schema {version}; this adapter requires {SCHEMA_VERSION}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    @contextmanager
    def _transaction(self, *, immediate: bool = True):
        conn = self._connect()
        begun = False
        try:
            conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            begun = True
            yield conn
            if self.before_commit is not None:
                self.before_commit()
            conn.execute("COMMIT")
        except BaseException:
            if begun:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
            raise
        finally:
            conn.close()

    # -- artifact registration (immutable part of save_revision) ----------
    def save_experiment(self, display_name: str, description: str = "") -> str:
        """Create the minimal Experiment entity a managed research Run needs."""
        if not isinstance(display_name, str) or not 1 <= len(display_name) <= 200:
            raise ValueError("display_name must be 1-200 characters")
        if not isinstance(description, str) or len(description) > 32768:
            raise ValueError("description is too long")
        entity_id = uuid.uuid4().hex
        now = utc_now()
        with self._transaction() as conn:
            conn.execute(
                "INSERT INTO entities(entity_id,entity_kind,experiment_id,display_name,description,"
                "head_artifact_id,row_version,created_at,updated_at) "
                "VALUES(?,'experiment',NULL,?,?,NULL,0,?,?)",
                (entity_id, display_name, description, now, now))
        return entity_id

    def save_artifact(self, envelope: Mapping[str, Any]) -> ArtifactRef:
        """Validate, content-address and register one immutable artifact."""
        parsed = parse_envelope(dict(envelope))
        computed = artifact_content_digest(parsed["artifact_type"], parsed["schema_version"],
                                           parsed["parent_refs"], parsed["payload"],
                                           parsed["provenance"])
        if parsed["content_digest"] != computed:
            raise ReferenceMismatch(parsed["artifact_id"], computed, parsed["content_digest"])
        blob = canonical_json(parsed).encode("utf-8")
        object_digest = "sha256:" + hashlib.sha256(blob).hexdigest()
        object_key = self.object_store.write(object_digest.removeprefix("sha256:"), blob)
        entity_id = parsed["entity_id"]
        with self._transaction() as conn:
            existing = conn.execute(
                "SELECT artifact_id,artifact_type,schema_version,content_digest FROM artifacts "
                "WHERE artifact_type=? AND schema_version=? AND content_digest=? "
                "AND ((entity_id IS NULL AND ? IS NULL) OR entity_id=?)",
                (parsed["artifact_type"], parsed["schema_version"], computed,
                 entity_id, entity_id)).fetchone()
            if existing is not None:
                return ArtifactRef(existing["artifact_id"], existing["artifact_type"],
                                   existing["schema_version"], existing["content_digest"])
            conn.execute(
                "INSERT INTO artifacts(artifact_id,artifact_type,schema_version,content_digest,"
                "entity_id,object_key,producer_run_id,producer_attempt_id,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (parsed["artifact_id"], parsed["artifact_type"], parsed["schema_version"], computed,
                 parsed["entity_id"], object_key, parsed["producer"]["run_id"],
                 parsed["producer"]["attempt_id"], parsed["created_at"]))
            for parent in sorted(parsed["parent_refs"], key=lambda item: (item["role"], item["ordinal"])):
                conn.execute(
                    "INSERT INTO artifact_parents(child_id,role,ordinal,parent_id) VALUES(?,?,?,?)",
                    (parsed["artifact_id"], parent["role"], parent["ordinal"],
                     parent["ref"]["artifact_id"]))
        return ArtifactRef(parsed["artifact_id"], parsed["artifact_type"], parsed["schema_version"],
                           computed)

    # -- reference resolution --------------------------------------------
    def resolve_ref(self, ref: ArtifactRef, conn: sqlite3.Connection | None = None) -> sqlite3.Row:
        close = conn is None
        conn = conn or self._connect()
        try:
            row = conn.execute(
                "SELECT artifact_id,artifact_type,schema_version,content_digest,object_key,entity_id "
                "FROM artifacts WHERE artifact_id=?", (ref.artifact_id,)).fetchone()
        finally:
            if close:
                conn.close()
        if row is None:
            raise ReferenceMismatch(ref.artifact_id, ref.content_digest, None)
        if (row["artifact_type"] != ref.artifact_type or row["schema_version"] != ref.schema_version
                or row["content_digest"] != ref.content_digest):
            expected = f"{row['artifact_type']}@{row['schema_version']}:{row['content_digest']}"
            provided = f"{ref.artifact_type}@{ref.schema_version}:{ref.content_digest}"
            raise ReferenceMismatch(ref.artifact_id, expected, provided)
        return row

    def read_payload(self, ref: ArtifactRef) -> dict[str, Any]:
        row = self.resolve_ref(ref)
        envelope = json.loads(self.object_store.read(row["object_key"]))
        if (envelope.get("artifact_id") != ref.artifact_id
                or envelope.get("content_digest") != ref.content_digest):
            raise ReferenceMismatch(ref.artifact_id, ref.content_digest, envelope.get("content_digest"))
        return envelope["payload"]

    # -- ManagedAdmissionPort --------------------------------------------
    def replay(self, command: AdmissionCommand) -> AdmissionReceipt | None:
        conn = self._connect()
        try:
            return self._replay(conn, command)
        finally:
            conn.close()

    def _replay(self, conn: sqlite3.Connection, command: AdmissionCommand) -> AdmissionReceipt | None:
        row = conn.execute("SELECT operation,payload_digest,response_json FROM commands "
                           "WHERE idempotency_key=?", (command.idempotency_key,)).fetchone()
        if row is None:
            return None
        if row["operation"] != command.operation or row["payload_digest"] != command.payload_digest():
            raise IdempotencyConflict(command.idempotency_key, row["operation"])
        return self._receipt_from_json(row["response_json"], created=False)

    def _receipt_from_json(self, text: str, *, created: bool) -> AdmissionReceipt:
        data = json.loads(text)
        plan = data.get("plan_ref")
        return AdmissionReceipt(data["run_id"], data["attempt_id"], data["attempt_no"],
                                ArtifactRef(**data["definition_ref"]),
                                ArtifactRef(**plan) if plan else None,
                                ArtifactRef(**data["execution_policy_ref"]), created)

    def admit_run(self, request: AdmissionRequest) -> AdmissionReceipt:
        command = request.command
        with self._transaction() as conn:
            previous = self._replay(conn, command)
            if previous is not None:
                return previous
            definition_ref = request.prepared.definition_ref
            plan_ref = request.prepared.plan_ref
            workflow_ref = request.prepared.workflow_ref
            if command.entry == EntryPoint.DATA and plan_ref != command.reference:
                raise ReferenceMismatch(command.reference.artifact_id)
            if command.entry in (EntryPoint.RESEARCH, EntryPoint.RETRY) and definition_ref != command.reference:
                raise ReferenceMismatch(command.reference.artifact_id)
            if command.entry == EntryPoint.WORKFLOW and workflow_ref != command.reference:
                raise ReferenceMismatch(command.reference.artifact_id)
            self.resolve_ref(definition_ref, conn)
            if plan_ref is not None:
                self.resolve_ref(plan_ref, conn)
            if workflow_ref is not None:
                self.resolve_ref(workflow_ref, conn)
            policy = self.read_payload(command.execution_policy_ref)
            now = utc_now()
            if plan_ref is not None:
                payload = self.read_payload(plan_ref)
                if payload["definition_ref"] != definition_ref.as_dict():
                    raise ReferenceMismatch(plan_ref.artifact_id)
                if payload["expires_at"] <= now:
                    raise PlanExpired(plan_ref.as_dict(), payload["expires_at"])
            self._check_workflow(conn, command, workflow_ref)
            if request.prepared.experiment_id is not None:
                self._check_experiment(conn, request.prepared.experiment_id)
            if command.entry == EntryPoint.RETRY:
                run_id, attempt_no, experiment_id, plan_id = self._retry_target(conn, request)
            else:
                run_id = uuid.uuid4().hex
                attempt_no = 1
                experiment_id = request.prepared.experiment_id
                plan_id = plan_ref.artifact_id if plan_ref is not None else None
                self._insert_run(conn, run_id, request, experiment_id, plan_id, now)
            self._check_concurrency(conn, policy)
            attempt_id = uuid.uuid4().hex
            launch_token = uuid.uuid4().hex
            self._insert_attempt(conn, attempt_id, run_id, attempt_no, request, now, launch_token)
            self._insert_stages(conn, attempt_id, request)
            self._acquire_lease(conn, attempt_id, now)
            self._insert_event(conn, attempt_id, launch_token, command.payload_digest(), now)
            receipt = AdmissionReceipt(run_id, attempt_id, attempt_no, definition_ref, plan_ref,
                                       command.execution_policy_ref, True)
            self._insert_command(conn, command, receipt, now)
            return receipt

    def _check_workflow(self, conn: sqlite3.Connection, command: AdmissionCommand,
                        workflow_ref: ArtifactRef | None) -> None:
        if workflow_ref is None:
            return
        row = conn.execute("SELECT workflow_revision_id,enabled FROM workflow_instances "
                           "WHERE workflow_id=?", (command.workflow_id,)).fetchone()
        if row is None or row["enabled"] != 1 or row["workflow_revision_id"] != workflow_ref.artifact_id:
            raise PreconditionFailed(
                [{"code": "workflow_not_enabled", "status": "fail", "message": str(command.workflow_id),
                  "field_path": None, "blocking": True}],
                ["workflow is disabled, missing or bound to another revision"])

    def _check_experiment(self, conn: sqlite3.Connection, experiment_id: str) -> None:
        row = conn.execute("SELECT entity_kind FROM entities WHERE entity_id=?",
                           (experiment_id,)).fetchone()
        if row is None or row["entity_kind"] != "experiment":
            raise PreconditionFailed(
                [{"code": "experiment_missing", "status": "fail", "message": experiment_id,
                  "field_path": None, "blocking": True}],
                ["the Run must belong to an existing Experiment entity"])

    def _check_concurrency(self, conn: sqlite3.Connection, policy: dict[str, Any]) -> None:
        limit = policy["max_concurrent"]
        used = int(conn.execute("SELECT count(*) FROM resource_leases "
                                "WHERE resource_scope=? AND released_at IS NULL",
                                (CONCURRENCY_SCOPE,)).fetchone()[0])
        if used >= limit:
            raise CapacityExceeded("concurrency slots are full", scope_id="global",
                                   dimension="concurrency", limit=limit, used=used, requested=1)

    def _retry_target(self, conn: sqlite3.Connection, request: AdmissionRequest
                      ) -> tuple[str, int, str | None, str | None]:
        run_id = request.command.run_id
        row = conn.execute("SELECT origin,workflow_kind,experiment_id,definition_id,plan_id "
                           "FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None or row["origin"] != "managed":
            raise RetryNotAllowed(run_id, reason_code="run_not_managed")
        if row["definition_id"] != request.prepared.definition_ref.artifact_id:
            raise ReferenceMismatch(request.prepared.definition_ref.artifact_id)
        open_previous = int(conn.execute(
            "SELECT count(*) FROM attempts WHERE run_id=? AND end_confirmed_at IS NULL",
            (run_id,)).fetchone()[0])
        if open_previous:
            raise RetryNotAllowed(run_id, reason_code="previous_attempt_not_settled")
        attempt_no = int(conn.execute("SELECT coalesce(max(attempt_no),0) FROM attempts "
                                      "WHERE run_id=?", (run_id,)).fetchone()[0]) + 1
        return run_id, attempt_no, row["experiment_id"], row["plan_id"]

    # -- write steps (separate methods so each write point can be fault-injected)
    def _insert_run(self, conn: sqlite3.Connection, run_id: str, request: AdmissionRequest,
                    experiment_id: str | None, plan_id: str | None, now: str) -> None:
        definition_id = request.prepared.definition_ref.artifact_id
        conn.execute(
            "INSERT INTO runs(run_id,origin,workflow_kind,experiment_id,definition_id,plan_id,"
            "created_at,latest_revision_id) VALUES(?,?,?,?,?,?,?,NULL)",
            (run_id, "managed", request.prepared.kind.value, experiment_id, definition_id, plan_id, now))

    def _insert_attempt(self, conn: sqlite3.Connection, attempt_id: str, run_id: str,
                        attempt_no: int, request: AdmissionRequest, now: str,
                        launch_token: str) -> None:
        command = request.command
        conn.execute(
            "INSERT INTO attempts(attempt_id,kind,executor_id,label,probe,status,params_json,"
            "idempotency_key,request_id,config_fingerprint,workspace,log_path,pid,exit_code,error_code,"
            "error_message,outcome_json,created_at,queued_at,started_at,ended_at,heartbeat_at,"
            "cancel_requested_at,updated_at,deadline_at,policy_revision,run_id,attempt_no,definition_id,"
            "admission_digest,process_identity_json,end_confirmed_at,launch_token) "
            "VALUES(?,?,?,?,0,'queued','{}',?,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,?,?,NULL,"
            "NULL,NULL,NULL,?,NULL,?,?,?,?,?,NULL,NULL,?)",
            (attempt_id, request.prepared.kind.value, "managed", request.prepared.kind.value,
             command.idempotency_key, now, now, now, command.execution_policy_ref.artifact_id,
             run_id, attempt_no, request.prepared.definition_ref.artifact_id,
             command.payload_digest(), launch_token))

    def _insert_stages(self, conn: sqlite3.Connection, attempt_id: str,
                       request: AdmissionRequest) -> None:
        for ordinal, step in enumerate(request.plan.steps):
            inputs = {"step": step.key, "owner": step.owner, "depends_on": list(step.depends_on)}
            conn.execute(
                "INSERT INTO stages(attempt_id,stage_id,ordinal,state,inputs_json,outputs_json,"
                "reason_code,started_at,ended_at) VALUES(?,?,?,'pending',?,'[]',NULL,NULL,NULL)",
                (attempt_id, step.key, ordinal, canonical_json(inputs)))

    def _acquire_lease(self, conn: sqlite3.Connection, attempt_id: str, now: str) -> None:
        conn.execute("INSERT INTO resource_leases(attempt_id,resource_scope,reserved_at,released_at) "
                     "VALUES(?,?,?,NULL)", (attempt_id, CONCURRENCY_SCOPE, now))

    def _insert_event(self, conn: sqlite3.Connection, attempt_id: str, launch_token: str,
                      admission_digest: str, now: str) -> None:
        evidence = {"admission_digest": admission_digest, "launch_token": launch_token}
        conn.execute("INSERT INTO attempt_events(attempt_id,seq,event_type,evidence_json,occurred_at) "
                     "VALUES(?,1,'admitted',?,?)", (attempt_id, canonical_json(evidence), now))

    def _insert_command(self, conn: sqlite3.Connection, command: AdmissionCommand,
                        receipt: AdmissionReceipt, now: str) -> None:
        response = {"run_id": receipt.run_id, "attempt_id": receipt.attempt_id,
                    "attempt_no": receipt.attempt_no, "definition_ref": receipt.definition_ref.as_dict(),
                    "plan_ref": receipt.plan_ref.as_dict() if receipt.plan_ref else None,
                    "execution_policy_ref": receipt.execution_policy_ref.as_dict(), "created": True}
        conn.execute("INSERT INTO commands(idempotency_key,operation,payload_digest,response_json,"
                     "committed_at) VALUES(?,?,?,?,?)",
                     (command.idempotency_key, command.operation, command.payload_digest(),
                      canonical_json(response), now))

    # -- UsageBudgetPort --------------------------------------------------
    def set_budget_scope(self, scope_id: str, dimension: str, policy_ref: ArtifactRef,
                         limit: int) -> None:
        """Register one frozen limit; never a runtime 'increase to fit' path."""
        if type(limit) is not int or limit < 0:
            raise ValueError("limit must be a non-negative integer")
        with self._transaction() as conn:
            row = conn.execute("SELECT policy_id,limit_value FROM budget_scopes "
                               "WHERE scope_id=? AND dimension=?", (scope_id, dimension)).fetchone()
            if row is None:
                conn.execute("INSERT INTO budget_scopes(scope_id,dimension,policy_id,limit_value,"
                             "used_value) VALUES(?,?,?,?,0)",
                             (scope_id, dimension, policy_ref.artifact_id, limit))
            elif row["limit_value"] != limit or row["policy_id"] != policy_ref.artifact_id:
                raise ValueError("budget scope is already frozen with another limit/policy")

    def reserve_usage(self, event_key: str, attempt_id: str | None,
                      items: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
        """Atomically check and consume one or more scope/dimension increments."""
        requested: dict[tuple[str, str], int] = {}
        for item in items:
            scope_id, dimension, amount = item["scope_id"], item["dimension"], item["amount"]
            if type(amount) is not int or amount < 0:
                raise ValueError("amount must be a non-negative integer")
            if (scope_id, dimension) in requested:
                raise ValueError("duplicate scope/dimension in one reservation")
            requested[(scope_id, dimension)] = amount
        if not requested:
            raise ValueError("a reservation requires at least one scope/dimension")
        with self._transaction() as conn:
            existing = conn.execute("SELECT scope_id,dimension,amount FROM budget_entries "
                                    "WHERE event_key=?", (event_key,)).fetchall()
            if existing:
                recorded = {(row["scope_id"], row["dimension"]): row["amount"] for row in existing}
                if recorded != requested:
                    raise IdempotencyConflict(event_key, "reserve_usage")
                return self._usage_view(conn, event_key, requested)
            checked: dict[tuple[str, str], sqlite3.Row] = {}
            for (scope_id, dimension), amount in requested.items():
                row = conn.execute("SELECT policy_id,limit_value,used_value FROM budget_scopes "
                                   "WHERE scope_id=? AND dimension=?",
                                   (scope_id, dimension)).fetchone()
                if row is None:
                    raise LedgerScopeMissing(scope_id, dimension)
                if row["used_value"] + amount > row["limit_value"]:
                    raise BudgetExhausted("budget exhausted", scope_id=scope_id, dimension=dimension,
                                          limit=row["limit_value"], used=row["used_value"],
                                          requested=amount)
                checked[(scope_id, dimension)] = row
            now = utc_now()
            for (scope_id, dimension), amount in requested.items():
                conn.execute("INSERT INTO budget_entries(entry_id,scope_id,dimension,event_key,"
                             "attempt_id,amount,kind,created_at) VALUES(?,?,?,?,?,?,'reserve',?)",
                             (uuid.uuid4().hex, scope_id, dimension, event_key, attempt_id, amount, now))
                conn.execute("UPDATE budget_scopes SET used_value=used_value+? "
                             "WHERE scope_id=? AND dimension=?", (amount, scope_id, dimension))
            return self._usage_view(conn, event_key, requested)

    def _usage_view(self, conn: sqlite3.Connection, event_key: str,
                    requested: Mapping[tuple[str, str], int]) -> dict[str, Any]:
        rows = []
        for (scope_id, dimension), amount in sorted(requested.items()):
            row = conn.execute("SELECT limit_value,used_value,policy_id FROM budget_scopes "
                               "WHERE scope_id=? AND dimension=?", (scope_id, dimension)).fetchone()
            rows.append({"scope_id": scope_id, "dimension": dimension,
                         "policy_id": row["policy_id"], "amount": amount, "limit": row["limit_value"],
                         "used": row["used_value"],
                         "remaining": max(0, row["limit_value"] - row["used_value"])})
        return {"event_key": event_key, "items": rows}

    def release_lease(self, attempt_id: str, scope: str = CONCURRENCY_SCOPE) -> int:
        """Release once after confirmed end; called by record_transition (G1-3)."""
        with self._transaction() as conn:
            cursor = conn.execute("UPDATE resource_leases SET released_at=? "
                                  "WHERE attempt_id=? AND resource_scope=? AND released_at IS NULL",
                                  (utc_now(), attempt_id, scope))
            return cursor.rowcount

    # -- read helpers (tests / future projections) ------------------------
    def attempt_row(self, attempt_id: str) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            return dict(row) if row is not None else None
        finally:
            conn.close()

    def open_lease_count(self, scope: str = CONCURRENCY_SCOPE) -> int:
        conn = self._connect()
        try:
            return int(conn.execute("SELECT count(*) FROM resource_leases "
                                    "WHERE resource_scope=? AND released_at IS NULL",
                                    (scope,)).fetchone()[0])
        finally:
            conn.close()

    def command_row(self, idempotency_key: str) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM commands WHERE idempotency_key=?",
                               (idempotency_key,)).fetchone()
            return dict(row) if row is not None else None
        finally:
            conn.close()
