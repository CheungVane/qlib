"""Factor entities and immutable factor panels."""

from __future__ import annotations

from .storage_base import *  # noqa: F401,F403 - moved code keeps its original scope


class FactorsMixin:
    """Factor entities and immutable factor panels."""

    def publish_factor(self, identity: dict[str, Any], panel: dict[str, Any]) -> dict[str, Any]:
        """Insert or reuse one factor and one immutable panel (content hashed)."""
        for key in ("source_instance_id", "external_id", "name"):
            if not isinstance(identity.get(key), str) or not identity[key].strip():
                raise ValueError(f"{key} is required")
        data = json.dumps(panel, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        content_hash = hashlib.sha256(data).hexdigest()
        key = self._write_object(content_hash, data)
        dataset_version = (identity.get("dataset") or {}).get("version")
        created_at = identity.get("created_at") or datetime.now(timezone.utc).isoformat(
            timespec="milliseconds").replace("+00:00", "Z")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT factor_id FROM factors WHERE source_instance_id=? AND external_id=?
                   AND dataset_version IS ?""",
                (identity["source_instance_id"], identity["external_id"], dataset_version)).fetchone()
            if row:
                factor_id, created = row["factor_id"], False
            else:
                factor_id, created = str(uuid.uuid4()), True
                conn.execute(
                    """INSERT INTO factors(factor_id,name,source_instance_id,external_id,definition_json,
                       dataset_id,dataset_version,snapshot_label,calendar_id,provenance_json,created_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (factor_id, identity["name"], identity["source_instance_id"], identity["external_id"],
                     json.dumps(identity.get("definition") or {}, ensure_ascii=False, sort_keys=True),
                     (identity.get("dataset") or {}).get("id"), dataset_version,
                     (identity.get("dataset") or {}).get("snapshot_label"),
                     identity.get("calendar_id"),
                     json.dumps(identity.get("provenance") or {}, ensure_ascii=False, sort_keys=True), created_at))
            existing = conn.execute(
                "SELECT panel_id FROM factor_panels WHERE factor_id=? AND content_hash=?",
                (factor_id, content_hash)).fetchone()
            if existing:
                panel_id = existing["panel_id"]
            else:
                panel_id = str(uuid.uuid4())
                conn.execute(
                    """INSERT INTO factor_panels(panel_id,factor_id,content_hash,object_key,date_count,
                       instrument_count,cell_count,valid_count,start_date,end_date,published_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (panel_id, factor_id, content_hash, key, panel["date_count"], panel["instrument_count"],
                     panel["cell_count"], panel["valid_count"], panel["dates"][0] if panel["dates"] else None,
                     panel["dates"][-1] if panel["dates"] else None, created_at))
            row = conn.execute("SELECT * FROM factors WHERE factor_id=?", (factor_id,)).fetchone()
        return {"factor_id": factor_id, "panel_id": panel_id, "content_hash": content_hash,
                "created": created, "panel_created": not bool(existing), "factor": self._factor_row(row)}

    @staticmethod
    def _factor_row(row: sqlite3.Row) -> dict[str, Any]:
        record = dict(row)
        record["definition"] = json.loads(record.pop("definition_json") or "{}")
        record["provenance"] = json.loads(record.pop("provenance_json") or "{}")
        record["dataset"] = {"id": record.pop("dataset_id", None),
                             "version": record.pop("dataset_version", None),
                             "snapshot_label": record.pop("snapshot_label", None)}
        return record

    def list_factors(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT f.*, (SELECT COUNT(*) FROM factor_panels p WHERE p.factor_id=f.factor_id) AS panel_count
                   FROM factors f ORDER BY instant_order(f.created_at) DESC, f.factor_id DESC""").fetchall()
        return [self._factor_row(row) for row in rows]

    def get_factor(self, factor_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM factors WHERE factor_id=?", (factor_id,)).fetchone()
        return self._factor_row(row) if row else None

    def list_factor_panels(self, factor_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT panel_id,factor_id,content_hash,object_key,date_count,instrument_count,cell_count,
                   valid_count,start_date,end_date,published_at FROM factor_panels WHERE factor_id=?
                   ORDER BY instant_order(published_at) DESC, panel_id DESC""", (factor_id,)).fetchall()
        return [dict(row) for row in rows]

    def get_factor_panel(self, factor_id: str, panel_id: str | None = None) -> dict[str, Any] | None:
        panels = self.list_factor_panels(factor_id)
        if not panels:
            return None
        panel = next((row for row in panels if row["panel_id"] == panel_id), panels[0]) if panel_id else panels[0]
        payload = self._read_object(panel["object_key"])
        if hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest() != panel["content_hash"]:
            raise RuntimeError("factor panel digest mismatch")
        return {**panel, "panel": payload}

    # -- import receipts --------------------------------------------------
