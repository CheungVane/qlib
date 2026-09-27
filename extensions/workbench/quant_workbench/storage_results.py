"""Immutable run/revision publication and reads."""

from __future__ import annotations

from .storage_base import *  # noqa: F401,F403 - moved code keeps its original scope


class ResultsMixin:
    """Immutable run/revision publication and reads."""

    def publish(self, source_instance_id: str, external_id: str, adapter_version: str,
                package: dict[str, Any]) -> dict[str, Any]:
        if not all(isinstance(x, str) and x.strip() for x in (source_instance_id, external_id, adapter_version)):
            raise ValueError("source_instance_id, external_id and adapter_version are required")
        canonical = validate_package(package)
        data = json.dumps(canonical, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        content_hash = hashlib.sha256(data).hexdigest()
        key = self._write_object(content_hash, data)
        identity = json.dumps([source_instance_id, external_id], ensure_ascii=False, separators=(",", ":"))
        run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"quant-workbench:{identity}"))
        if self.before_commit:
            self.before_commit()
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            previous = conn.execute(
                "SELECT run_id FROM runs WHERE source_instance_id=? AND external_id=?",
                (source_instance_id, external_id),
            ).fetchone()
            if previous:
                run_id = previous["run_id"]
            else:
                conn.execute("INSERT INTO runs(run_id,source_instance_id,external_id,created_at) VALUES(?,?,?,?)",
                             (run_id, source_instance_id, external_id, canonical["run"]["created_at"]))
            revision_id = hashlib.sha256(f"{run_id}:{content_hash}:{adapter_version}".encode()).hexdigest()[:32]
            existing = conn.execute("SELECT 1 FROM revisions WHERE revision_id=?", (revision_id,)).fetchone()
            if not existing:
                conn.execute("INSERT INTO revisions(revision_id,run_id,content_hash,adapter_version,object_key) VALUES(?,?,?,?,?)",
                             (revision_id, run_id, content_hash, adapter_version, key))
                conn.execute("UPDATE runs SET latest_revision_id=? WHERE run_id=?", (revision_id, run_id))
        return {"run_id": run_id, "revision_id": revision_id, "created": not bool(existing)}

    def _summary(self, row: sqlite3.Row) -> dict[str, Any]:
        obj = self._read_object(row["object_key"])
        return {
            "run_id": row["run_id"], "source_instance_id": row["source_instance_id"],
            "external_id": row["external_id"], "revision_id": row["revision_id"],
            "published_at": row["published_at"], "run": obj["run"],
        }

    def list_runs(self, limit: int = 20, cursor: str | None = None) -> dict[str, Any]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if cursor is not None and (not isinstance(cursor, str) or len(cursor) != 36):
            raise ValueError("invalid cursor")
        query = """SELECT r.*,v.revision_id,v.object_key,v.published_at FROM runs r
                   JOIN revisions v ON v.revision_id=r.latest_revision_id"""
        params: list[Any] = []
        if cursor:
            with self._connection() as conn:
                anchor = conn.execute("SELECT created_at,run_id FROM runs WHERE run_id=?", (cursor,)).fetchone()
            if anchor is None:
                raise ValueError("unknown cursor")
            query += " WHERE (instant_order(r.created_at) < instant_order(?) OR (instant_order(r.created_at) = instant_order(?) AND r.run_id < ?))"
            params.extend((anchor["created_at"], anchor["created_at"], anchor["run_id"]))
        query += " ORDER BY instant_order(r.created_at) DESC,r.run_id DESC LIMIT ?"
        params.append(limit + 1)
        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
        more = len(rows) > limit
        items = [self._summary(row) for row in rows[:limit]]
        return {"items": items, "next_cursor": items[-1]["run_id"] if more else None}

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute("""SELECT r.*,v.revision_id,v.object_key,v.published_at FROM runs r
                                  JOIN revisions v ON v.revision_id=r.latest_revision_id WHERE r.run_id=?""",
                               (run_id,)).fetchone()
        return self._summary(row) if row else None

    def list_revisions(self, run_id: str) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute("SELECT revision_id,content_hash,adapter_version,published_at FROM revisions WHERE run_id=? ORDER BY published_at,revision_id",
                                (run_id,)).fetchall()
        return [dict(row) for row in rows]

    def list_revisions_page(self, run_id: str, limit: int = 20, cursor: str | None = None) -> dict[str, Any]:
        """Bounded revision list (ARC07); newest first with a stable cursor."""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if cursor is not None and (not isinstance(cursor, str) or not cursor):
            raise ValueError("invalid cursor")
        query = ("SELECT revision_id,content_hash,adapter_version,published_at FROM revisions WHERE run_id=?")
        params: list[Any] = [run_id]
        if cursor:
            with self._connection() as conn:
                anchor = conn.execute(
                    "SELECT published_at FROM revisions WHERE run_id=? AND revision_id=?",
                    (run_id, cursor)).fetchone()
            if anchor is None:
                raise ValueError("unknown cursor")
            query += (" AND (instant_order(published_at) < instant_order(?) OR "
                      "(instant_order(published_at) = instant_order(?) AND revision_id < ?))")
            params.extend((anchor["published_at"], anchor["published_at"], cursor))
        query += " ORDER BY instant_order(published_at) DESC, revision_id DESC LIMIT ?"
        params.append(limit + 1)
        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
        more = len(rows) > limit
        items = [dict(row) for row in rows[:limit]]
        return {"items": items, "next_cursor": items[-1]["revision_id"] if more else None}

    def get_revision(self, run_id: str, revision_id: str | None = None) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute("""SELECT v.* FROM revisions v JOIN runs r ON r.run_id=v.run_id
                                  WHERE v.run_id=? AND v.revision_id=COALESCE(?,r.latest_revision_id)""",
                               (run_id, revision_id)).fetchone()
        if not row:
            return None
        return {"run_id": run_id, "revision_id": row["revision_id"], "published_at": row["published_at"],
                "adapter_version": row["adapter_version"], "content_hash": row["content_hash"],
                "result": self._read_object(row["object_key"])}
