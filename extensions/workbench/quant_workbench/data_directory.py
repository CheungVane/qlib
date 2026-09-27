"""Data directory: immutable snapshot registry, component manifest and access port.

Contract: docs/spec/WORKBENCH_SPEC.md DATA01—DATA06, ARC11; docs/spec/DATA_SOURCES.md.
Design rules enforced here:

* a snapshot has a content digest over its component manifest and is immutable once published;
* components carry a source class, coverage and an `available_at` (or explicit unknown);
* readers resolve components by snapshot id plus a configured data root, so changing the
  current profile or data root cannot silently change a historical snapshot's identity;
* missing fields, duplicates and non-monotonic time axes fail closed with a reason.

No qlib import: the free-source archive is read through `free_sources` primitives.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from . import free_sources
from .free_sources import FreeSourceError

SCHEMA_VERSION = 1
COMPONENT_KINDS = ("bar", "calendar", "universe", "status", "financial", "code_map")


class DataDirectoryError(ValueError):
    """Invalid snapshot, component or query."""


def _canonical(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def component_digest(components: Sequence[dict]) -> str:
    """Digest of the component manifest (identity, not a data walk)."""
    trimmed = [{key: item.get(key) for key in
                ("kind", "uri", "content_digest", "coverage_start", "coverage_end", "source_class")}
               for item in components]
    trimmed.sort(key=lambda item: (item["kind"] or "", item["uri"] or "", item["content_digest"] or ""))
    return "sha256:" + hashlib.sha256(_canonical(trimmed).encode("utf-8")).hexdigest()


def build_snapshot_record(*, snapshot_id: str, source: dict, components: Sequence[dict],
                          created_at: str | None = None, limitations: Sequence[str] = (),
                          provenance: dict | None = None, materializer: dict | None = None,
                          status: str = "published") -> dict:
    """Assemble a snapshot record; raises when required component fields are missing."""
    if not snapshot_id or "/" in snapshot_id:
        raise DataDirectoryError("snapshot_id must be a non-empty path-safe string")
    if status not in ("draft", "published", "rejected"):
        raise DataDirectoryError(f"unknown status: {status}")
    checked = []
    for item in components:
        missing = [key for key in ("kind", "uri", "content_digest", "source_class")
                   if not item.get(key)]
        if missing:
            raise DataDirectoryError(f"component missing fields {missing}: {item.get('uri')}")
        if item["kind"] not in COMPONENT_KINDS:
            raise DataDirectoryError(f"unknown component kind: {item['kind']}")
        checked.append(dict(item))
    if not checked:
        raise DataDirectoryError("a snapshot needs at least one component")
    return {
        "schema_version": SCHEMA_VERSION,
        "snapshot_id": snapshot_id,
        "status": status,
        "created_at": created_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": dict(source),
        "materializer": dict(materializer or {}),
        "provenance": dict(provenance or {}),
        "limitations": list(limitations),
        "components": checked,
        "content_digest": component_digest(checked),
    }


def publish_snapshot(registry: str | Path, record: dict) -> Path:
    """Write a snapshot record; an existing id may only be reused with identical content."""
    registry = Path(registry)
    registry.mkdir(parents=True, exist_ok=True)
    target = registry / f"{record['snapshot_id']}.json"
    if target.exists():
        existing = json.loads(target.read_text())
        if existing.get("content_digest") == record.get("content_digest"):
            return target
        raise DataDirectoryError(
            f"snapshot {record['snapshot_id']} already published with a different digest")
    target.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return target


def list_snapshots(registry: str | Path) -> list[str]:
    return sorted(path.stem for path in Path(registry).glob("*.json"))


def load_snapshot(registry: str | Path, snapshot_id: str) -> dict:
    path = Path(registry) / f"{snapshot_id}.json"
    if not path.exists():
        raise DataDirectoryError(f"unknown snapshot: {snapshot_id}")
    record = json.loads(path.read_text())
    if record.get("schema_version") != SCHEMA_VERSION:
        raise DataDirectoryError(f"unsupported snapshot schema: {record.get('schema_version')}")
    if component_digest(record.get("components", [])) != record.get("content_digest"):
        raise DataDirectoryError(f"snapshot {snapshot_id} digest does not match its manifest")
    return record


def reproducibility(record: dict) -> dict:
    """A17: complete evidence plus a recorded materializer is required for 'reproducible'."""
    completeness = (record.get("provenance") or {}).get("completeness", "unknown")
    materializer = record.get("materializer") or {}
    missing = [key for key in ("name", "version") if not materializer.get(key)]
    if completeness != "complete":
        return {"state": "limited", "reason": f"provenance completeness={completeness}"}
    if missing:
        return {"state": "limited", "reason": f"materializer missing {missing}"}
    return {"state": "reproducible", "reason": None}


# -- A16 semantics -----------------------------------------------------------
def select_as_of(records: Iterable[dict], as_of: str, key: str = "available_at") -> dict | None:
    """Latest revision knowable at `as_of`; later revisions are never returned (A16)."""
    usable = [item for item in records if item.get(key) and item[key] <= as_of]
    if not usable:
        return None
    return max(usable, key=lambda item: (item[key], str(item.get("revision", ""))))


def resolve_symbol(code_map: Iterable[dict], market_code: str, day: str) -> str | None:
    """Resolve a market code to an instrument id using validity intervals (A16)."""
    matches = [item for item in code_map
               if item.get("market_code") == market_code
               and item.get("start", "") <= day <= item.get("end", "9999-12-31")]
    if not matches:
        return None
    if len(matches) > 1:
        raise DataDirectoryError(f"ambiguous code mapping for {market_code} on {day}")
    return matches[0]["instrument_id"]


# -- reader over a free-source snapshot -------------------------------------
class FreeSnapshotReader:
    """Read components of a registered free-source snapshot from a configured data root."""

    def __init__(self, data_root: str | Path, record: dict):
        self.data_root = Path(data_root)
        self.record = record

    def component(self, kind: str) -> dict:
        matches = [item for item in self.record["components"] if item["kind"] == kind]
        if not matches:
            raise DataDirectoryError(f"snapshot {self.record['snapshot_id']} has no {kind} component")
        if len(matches) > 1:
            raise DataDirectoryError(f"snapshot has {len(matches)} {kind} components; pick one explicitly")
        return matches[0]

    def path(self, kind: str) -> Path:
        return self.data_root / self.component(kind)["uri"]

    def calendar(self) -> list[date]:
        text = self.path("calendar").read_text().split()
        return [date.fromisoformat(item) for item in text]

    def instruments(self, name: str = "all") -> list[dict]:
        return free_sources.load_instruments(self.path("universe").read_text()) if name == "all" \
            else free_sources.load_instruments(
                (self.path("universe").parent / f"{name}.txt").read_text())

    def universe_on(self, day: date, name: str = "all") -> list[str]:
        return sorted(free_sources.active_universe(self.instruments(name), day))

    def feature(self, symbol: str, field: str) -> dict:
        if field not in free_sources.ARCHIVE_FIELDS:
            raise DataDirectoryError(f"unknown feature field: {field}")
        return free_sources.read_bin_head_tail(
            self.path("bar") / symbol.lower() / f"{field}.day.bin")

    def validate(self) -> dict:
        """DATA05 checks that can be done from the manifest and small files only."""
        problems = []
        try:
            calendar = self.calendar()
        except (FreeSourceError, OSError) as error:
            return {"ok": False, "problems": [f"calendar unreadable: {error}"]}
        if calendar != sorted(set(calendar)):
            problems.append("calendar is not strictly increasing and unique")
        for item in self.record["components"]:
            if not (self.data_root / item["uri"]).exists():
                problems.append(f"missing component path: {item['uri']}")
            if not item.get("coverage_start") or not item.get("coverage_end"):
                problems.append(f"coverage unknown for {item['kind']}")
        return {"ok": not problems, "problems": problems,
                "calendar": {"first": calendar[0].isoformat(), "last": calendar[-1].isoformat(),
                             "days": len(calendar)}}
