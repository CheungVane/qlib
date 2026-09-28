"""Data catalog browsing; distinct from verified analysis resolution."""
from __future__ import annotations
from typing import Any

from ..ports import DataDirectoryPort

class CatalogService:
    def __init__(self, directory: DataDirectoryPort | None):
        self.data_directory = directory

    def data_snapshots(self) -> dict[str, Any]:
        """Registered snapshots with their summaries (T05/A40); read-only."""
        if self.data_directory is None or not self.data_directory.available():
            return {"available": False, "items": [],
                    "reason": "data_directory_not_configured"}
        items = []
        for snapshot_id in self.data_directory.list_snapshots():
            try:
                items.append(self.data_directory.summary(snapshot_id))
            except Exception as error:
                items.append({"snapshot_id": snapshot_id, "unreadable_reason":
                              f"{type(error).__name__}: {error}"})
        return {"available": True, "items": items}

    def data_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        """Unknown or unreadable snapshots are 'not available' (404), not a malformed request."""
        if self.data_directory is None or not self.data_directory.available():
            return None
        try:
            return self.data_directory.summary(snapshot_id)
        except Exception:
            return None
