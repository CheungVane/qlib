"""Attempt lifecycle, import receipts and attempt statistics."""

from __future__ import annotations

from ...model import _instant  # star-import skips private names
from .storage_base import *  # noqa: F401,F403 - moved code keeps its original scope


from ...domain.errors import StorageCapacityExceeded


class AttemptsMixin:
    """Attempt lifecycle, import receipts and attempt statistics."""

    def create_attempt(self, record: dict[str, Any], *,
                       max_concurrent: int | None = None) -> tuple[dict[str, Any], bool]:
        """Insert one attempt; a duplicate idempotency key returns the existing row."""
        required = ("attempt_id", "kind", "executor_id", "label", "params", "created_at")
        if not all(record.get(key) not in (None, "") for key in required):
            raise ValueError("attempt_id, kind, executor_id, label, params and created_at are required")
        if record.get("status") not in ATTEMPT_OPEN_STATUSES:
            raise ValueError("new attempts must start queued or running")
        key = record.get("idempotency_key")
        if key is not None and (not isinstance(key, str) or not key.strip() or len(key) > 128):
            raise ValueError("idempotency_key must be a non-empty string of at most 128 characters")
        payload = (
            record["attempt_id"], record["kind"], record["executor_id"], record["label"],
            1 if record.get("probe") else 0, record["status"],
            json.dumps(record["params"], ensure_ascii=False, allow_nan=False, sort_keys=True),
            key, record.get("request_id"), record.get("config_fingerprint"), record.get("workspace"),
            record.get("log_path"), record.get("pid"), record.get("exit_code"), record.get("error_code"),
            record.get("error_message"),
            json.dumps(record["outcome"], ensure_ascii=False, allow_nan=False) if record.get("outcome") else None,
            record["created_at"], record.get("queued_at") or record["created_at"], record.get("started_at"),
            record.get("ended_at"), record.get("heartbeat_at"), record.get("cancel_requested_at"),
            record["created_at"], record.get("deadline_at"), record.get("policy_revision"),
        )
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            # EXEC13: the slot check runs inside the same write transaction as the insert, so two
            # concurrent submissions cannot both take the last slot.
            if max_concurrent is not None:
                placeholders = ",".join("?" for _ in ATTEMPT_OPEN_STATUSES)
                active = conn.execute(
                    f"SELECT COUNT(*) AS n FROM attempts WHERE status IN ({placeholders})",
                    ATTEMPT_OPEN_STATUSES).fetchone()["n"]
                if active >= max_concurrent:
                    raise StorageCapacityExceeded(
                        f"execution capacity is full ({max_concurrent} concurrent attempts)")
            try:
                conn.execute(
                    """INSERT INTO attempts(attempt_id,kind,executor_id,label,probe,status,params_json,
                       idempotency_key,request_id,config_fingerprint,workspace,log_path,pid,exit_code,error_code,
                       error_message,outcome_json,created_at,queued_at,started_at,ended_at,heartbeat_at,
                       cancel_requested_at,updated_at,deadline_at,policy_revision)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    payload)
            except sqlite3.IntegrityError:
                if key is None:
                    raise
                row = conn.execute("SELECT * FROM attempts WHERE idempotency_key=?", (key,)).fetchone()
                if row is None:
                    raise
                return self._attempt_row(row), False
            row = conn.execute("SELECT * FROM attempts WHERE attempt_id=?", (record["attempt_id"],)).fetchone()
        return self._attempt_row(row), True

    def get_attempt(self, attempt_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
        return self._attempt_row(row) if row else None

    def find_attempt_by_key(self, idempotency_key: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM attempts WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        return self._attempt_row(row) if row else None

    def update_attempt(self, attempt_id: str, **fields: Any) -> dict[str, Any] | None:
        unknown = set(fields) - set(ATTEMPT_MUTABLE_FIELDS)
        if unknown:
            raise ValueError(f"attempt fields are not updatable: {sorted(unknown)}")
        if not fields:
            return self.get_attempt(attempt_id)
        columns, values = [], []
        for key, value in fields.items():
            if key == "outcome":
                key, value = "outcome_json", (
                    json.dumps(value, ensure_ascii=False, allow_nan=False) if value is not None else None)
            columns.append(f"{key}=?")
            values.append(value)
        columns.append("updated_at=?")
        values.extend((datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"), attempt_id))
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(f"UPDATE attempts SET {','.join(columns)} WHERE attempt_id=?", values)
            if cursor.rowcount == 0:
                return None
            row = conn.execute("SELECT * FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
        return self._attempt_row(row)

    def list_attempts(self, limit: int = 20, cursor: str | None = None) -> dict[str, Any]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if cursor is not None and (not isinstance(cursor, str) or len(cursor) != 36):
            raise ValueError("invalid cursor")
        query = "SELECT * FROM attempts"
        params: list[Any] = []
        if cursor:
            with self._connection() as conn:
                anchor = conn.execute("SELECT created_at,attempt_id FROM attempts WHERE attempt_id=?", (cursor,)).fetchone()
            if anchor is None:
                raise ValueError("unknown cursor")
            query += (" WHERE (instant_order(created_at) < instant_order(?) OR "
                      "(instant_order(created_at) = instant_order(?) AND attempt_id < ?))")
            params.extend((anchor["created_at"], anchor["created_at"], anchor["attempt_id"]))
        query += " ORDER BY instant_order(created_at) DESC, attempt_id DESC LIMIT ?"
        params.append(limit + 1)
        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
        more = len(rows) > limit
        items = [self._attempt_row(row) for row in rows[:limit]]
        return {"items": items, "next_cursor": items[-1]["attempt_id"] if more else None}

    def list_open_attempts(self, limit: int = 100) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        placeholders = ",".join("?" for _ in ATTEMPT_OPEN_STATUSES)
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM attempts WHERE status IN ({placeholders}) "
                "ORDER BY instant_order(created_at) ASC LIMIT ?", (*ATTEMPT_OPEN_STATUSES, limit)).fetchall()
        return [self._attempt_row(row) for row in rows]

    def reserve_agent_budget(self, *, policy_revision: str, scope: str, kind: str,
                             limit: int, amount: int = 1) -> dict[str, Any]:
        """EXEC13: atomic reservation. Refuses (without writing) when the limit would be exceeded.

        The ledger is keyed by (policy_revision, scope, kind) and is never decremented by
        cancellation or restart — a retry reserves again, which is the intended behaviour.
        """
        if amount < 1:
            raise ValueError("amount must be >= 1")
        now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        with self._connection() as conn:
            row = conn.execute(
                "SELECT used FROM agent_budget WHERE policy_revision=? AND scope=? AND kind=?",
                (policy_revision, scope, kind)).fetchone()
            used = int(row["used"]) if row else 0
            if used + amount > limit:
                return {"allowed": False, "used": used, "limit": limit}
            conn.execute(
                "INSERT INTO agent_budget(policy_revision,scope,kind,used,updated_at) "
                "VALUES(?,?,?,?,?) ON CONFLICT(policy_revision,scope,kind) "
                "DO UPDATE SET used=excluded.used, updated_at=excluded.updated_at",
                (policy_revision, scope, kind, used + amount, now))
            return {"allowed": True, "used": used + amount, "limit": limit}

    def agent_budget_rows(self, policy_revision: str) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT scope, kind, used, updated_at FROM agent_budget "
                "WHERE policy_revision=? ORDER BY scope, kind", (policy_revision,)).fetchall()
        return [dict(row) for row in rows]

    def record_agent_budget(self, *, policy_revision: str, scope: str, kind: str, limit: int,
                            used: int) -> dict[str, Any]:
        """Reconcile an execution-time count into the durable ledger.

        Used for counts produced outside the platform process (the container/hook ledger).
        Monotonic per (revision, scope, kind): the stored value never decreases, so a lost or
        reset runtime counter cannot hand budget back.
        """
        now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        with self._connection() as conn:
            row = conn.execute(
                "SELECT used FROM agent_budget WHERE policy_revision=? AND scope=? AND kind=?",
                (policy_revision, scope, kind)).fetchone()
            current = int(row["used"]) if row else 0
            resolved = max(current, int(used))
            conn.execute(
                "INSERT INTO agent_budget(policy_revision,scope,kind,used,updated_at) "
                "VALUES(?,?,?,?,?) ON CONFLICT(policy_revision,scope,kind) "
                "DO UPDATE SET used=excluded.used, updated_at=excluded.updated_at",
                (policy_revision, scope, kind, resolved, now))
        return {"used": resolved, "limit": limit, "previous": current}

    @staticmethod
    def _attempt_row(row: sqlite3.Row) -> dict[str, Any]:
        record = dict(row)
        record["probe"] = bool(record.get("probe"))
        record["params"] = json.loads(record.pop("params_json") or "{}")
        outcome = record.pop("outcome_json", None)
        record["outcome"] = json.loads(outcome) if outcome else None
        return record

    def record_import(self, record: dict[str, Any]) -> dict[str, Any]:
        """Upsert one import receipt; the receipt is the platform fact for EXEC12."""
        required = ("receipt_id", "source_instance_id", "external_id", "adapter_version", "status", "imported_at")
        if not all(isinstance(record.get(key), str) and record[key].strip() for key in required):
            raise ValueError(
                "receipt_id, source_instance_id, external_id, adapter_version, status and imported_at are required")
        if record["status"] not in IMPORT_STATUSES:
            raise ValueError(f"unknown import status: {record['status']}")
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """INSERT INTO imports(receipt_id,attempt_id,run_id,revision_id,source_instance_id,external_id,
                   adapter_version,status,reason,imported_at) VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(receipt_id) DO UPDATE SET run_id=excluded.run_id,revision_id=excluded.revision_id,
                   status=excluded.status,reason=excluded.reason,imported_at=excluded.imported_at""",
                (record["receipt_id"], record.get("attempt_id"), record.get("run_id"), record.get("revision_id"),
                 record["source_instance_id"], record["external_id"], record["adapter_version"],
                 record["status"], record.get("reason"), record["imported_at"]))
            row = conn.execute("SELECT * FROM imports WHERE receipt_id=?", (record["receipt_id"],)).fetchone()
        return dict(row)

    def latest_import(self, attempt_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM imports WHERE attempt_id=? ORDER BY instant_order(imported_at) DESC LIMIT 1",
                (attempt_id,)).fetchone()
        return dict(row) if row else None

    def list_imports(self, attempt_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        query, params = "SELECT * FROM imports", []
        if attempt_id:
            query += " WHERE attempt_id=?"
            params.append(attempt_id)
        query += " ORDER BY instant_order(imported_at) DESC LIMIT ?"
        params.append(limit)
        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def attempt_stats(self, window_seconds: int = 86400) -> dict[str, Any]:
        """Attempt-level rates; cancelled and interrupted are counted apart from failures."""
        if isinstance(window_seconds, bool) or not isinstance(window_seconds, int) or not 60 <= window_seconds <= 2592000:
            raise ValueError("window_seconds must be between 60 and 2592000")
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(seconds=window_seconds)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        with self._connection() as conn:
            rows = conn.execute(
                """SELECT kind, status, started_at, ended_at FROM attempts
                   WHERE instant_order(created_at) >= instant_order(?)""", (cutoff,)).fetchall()
            first = conn.execute(
                "SELECT created_at FROM attempts ORDER BY instant_order(created_at) ASC LIMIT 1").fetchone()
        statuses = {"queued": 0, "running": 0, "succeeded": 0, "failed": 0, "cancelled": 0, "interrupted": 0}
        durations: list[float] = []
        by_kind: dict[str, dict[str, Any]] = {}
        for row in rows:
            status = row["status"] if row["status"] in statuses else "interrupted"
            statuses[status] += 1
            entry = by_kind.setdefault(row["kind"], {"kind": row["kind"], "total": 0, **{k: 0 for k in statuses}})
            entry["total"] += 1
            entry[status] += 1
            if row["started_at"] and row["ended_at"]:
                seconds = (_instant(row["ended_at"], "ended_at") - _instant(row["started_at"], "started_at")).total_seconds()
                if seconds >= 0:
                    durations.append(seconds)
        durations.sort()
        denominator = statuses["succeeded"] + statuses["failed"]
        p95 = durations[min(len(durations) - 1, max(0, math.ceil(0.95 * len(durations)) - 1))] if durations else None
        coverage = 0.0
        if first and first["created_at"]:
            coverage = max(0.0, (now - _instant(first["created_at"], "created_at")).total_seconds())
        total = len(rows)
        return {
            "availability": "available" if total else "empty",
            "window_seconds": window_seconds,
            "total": total,
            "statuses": statuses,
            "failure_rate": (statuses["failed"] / denominator) if denominator else None,
            "failure_denominator": denominator,
            "cancelled": statuses["cancelled"],
            "interrupted": statuses["interrupted"],
            "terminal_p95_seconds": p95,
            "by_kind": sorted(by_kind.values(), key=lambda item: (-item["total"], item["kind"])),
            "collection_started_at": first["created_at"] if first else None,
            "coverage_seconds": min(float(window_seconds), coverage),
            "observed_at": now.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "scope": ("平台Attempt（本机工作台库）；窗口按Attempt创建时间；failure_rate=failed/(succeeded+failed)，"
                      "cancelled与interrupted单列；不从日志推断额外语义。"),
        }
