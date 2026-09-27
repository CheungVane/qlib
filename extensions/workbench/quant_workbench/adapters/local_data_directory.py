"""Local data-directory adapter (T05 / A40 first step).

Resolves registered snapshots by id against a configured data root, so analysis can ask for
"snapshot X" instead of reading the current CN profile. Wiring this adapter into the
application service, API and CLI is the remaining A40 work; this module only provides the
adapter and its summaries.
"""

from __future__ import annotations

from pathlib import Path

from .. import data_directory as dd


class LocalDataDirectory:
    """Implements the data-directory port over a registry directory plus a data root."""

    def __init__(self, registry_dir: str | Path, data_root: str | Path):
        self.registry_dir = Path(registry_dir).expanduser()
        self.data_root = Path(data_root).expanduser()

    def available(self) -> bool:
        return self.registry_dir.is_dir()

    def list_snapshots(self) -> list[str]:
        return dd.list_snapshots(self.registry_dir) if self.available() else []

    def load(self, snapshot_id: str) -> dict:
        return dd.load_snapshot(self.registry_dir, snapshot_id)

    def summary(self, snapshot_id: str) -> dict:
        """Compact, display-safe summary: identity plus counts, never absolute paths."""
        record = self.load(snapshot_id)
        reader = dd.FreeSnapshotReader(self.data_root, record)
        components = [{"kind": item["kind"], "coverage_start": item.get("coverage_start"),
                       "coverage_end": item.get("coverage_end"),
                       "source_class": item.get("source_class")} for item in record["components"]]
        summary = {
            "snapshot_id": record["snapshot_id"], "content_digest": record["content_digest"],
            "status": record.get("status"), "source": record.get("source"),
            "components": components,
            "reproducibility": dd.reproducibility(record),
            "limitations": record.get("limitations", []),
        }
        try:
            calendar = reader.calendar()
            summary["calendar"] = {"first": calendar[0].isoformat(),
                                   "last": calendar[-1].isoformat(), "days": len(calendar)}
        except Exception as error:  # a summary must not pretend the snapshot is readable
            summary["calendar"] = None
            summary["unreadable_reason"] = f"{type(error).__name__}: {error}"
        return summary

    def validate(self, snapshot_id: str) -> dict:
        record = self.load(snapshot_id)
        return dd.FreeSnapshotReader(self.data_root, record).validate()
