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
import math
import shutil
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from . import free_sources
from .free_sources import FreeSourceError

SCHEMA_VERSION = 1
COMPONENT_KINDS = ("bar", "calendar", "universe", "status", "financial", "code_map")
MATERIALIZER_VERSION = "1"
LEGACY_SOURCE_CLASS = "legacy_unknown"


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
    if (registry / f"{record['snapshot_id']}.legacy.json").exists():
        raise DataDirectoryError(
            f"{record['snapshot_id']} is registered as a legacy path; "
            "register a new snapshot id instead of promoting it silently")
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
    """Snapshot ids only: `*.legacy.json` registrations are reported by `list_legacy`."""
    return sorted(path.name[:-len(".json")] for path in Path(registry).glob("*.json")
                  if not path.name.endswith(".legacy.json"))


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


# -- A17 materialization -----------------------------------------------------
def materialize_panel(reader: "FreeSnapshotReader", *, output: str | Path, universe: str,
                      fields: Sequence[str], start: date, end: date,
                      seed: int | None = None, limit: int | None = None) -> dict:
    """Write a deterministic long-format panel and return its materialization record.

    Same snapshot + universe + fields + window + seed produces byte-identical output,
    so the output digest is a reproducible identity (A17).
    """
    if not fields:
        raise DataDirectoryError("at least one field is required")
    unknown = [field for field in fields if field not in free_sources.ARCHIVE_FIELDS]
    if unknown:
        raise DataDirectoryError(f"unknown feature fields: {unknown}")
    calendar = [day for day in reader.calendar() if start <= day <= end]
    if not calendar:
        raise DataDirectoryError("window does not intersect the snapshot calendar")
    symbols = [item["symbol"] for item in reader.instruments(universe)]
    if limit:
        symbols = symbols[:limit]
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    full_calendar = reader.calendar()
    rows = 0
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("date,symbol," + ",".join(fields) + "\n")
        for symbol in sorted(symbols):
            series = {}
            for field in fields:
                try:
                    values = free_sources.read_bin_values(
                        reader.path("bar") / symbol.lower() / f"{field}.day.bin")
                except (FreeSourceError, OSError):
                    continue
                series[field] = values
            if not series:
                continue
            length = min(len(values) for values in series.values())
            start_index = free_sources.read_bin_head_tail(
                reader.path("bar") / symbol.lower() / f"{fields[0]}.day.bin")["start_index"]
            for offset in range(length):
                position = start_index + offset
                if position >= len(full_calendar):
                    break
                day = full_calendar[position]
                if not (start <= day <= end):
                    continue
                handle.write(",".join([day.isoformat(), symbol]
                                      + [f"{series[field][offset]:.6f}" for field in fields]) + "\n")
                rows += 1
    digest = "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest()
    return {
        "materializer": {"name": "materialize_panel", "version": MATERIALIZER_VERSION},
        "seed": seed,
        "input_snapshot_id": reader.record["snapshot_id"],
        "input_content_digest": reader.record["content_digest"],
        "universe": universe,
        "fields": list(fields),
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "rows": rows,
        "output_digest": digest,
        "output_name": target.name,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def verify_materialization(record: dict, output: str | Path) -> dict:
    """A17 replay check: recomputed digest must equal the recorded one."""
    actual = "sha256:" + hashlib.sha256(Path(output).read_bytes()).hexdigest()
    return {"ok": actual == record.get("output_digest"), "actual": actual,
            "expected": record.get("output_digest")}


# -- legacy paths and registry migration -------------------------------------
def register_legacy(registry: str | Path, *, legacy_id: str, path_label: str, reason: str) -> Path:
    """Explicitly register a legacy data path so it is never mistaken for a snapshot."""
    registry = Path(registry)
    registry.mkdir(parents=True, exist_ok=True)
    if (registry / f"{legacy_id}.json").exists():
        raise DataDirectoryError(f"{legacy_id} is already registered as a snapshot")
    target = registry / f"{legacy_id}.legacy.json"
    target.write_text(json.dumps({
        "kind": "legacy_path",
        "legacy_id": legacy_id,
        "path_label": path_label,
        "reason": reason,
        "source_class": LEGACY_SOURCE_CLASS,
        "digest": None,
        "status": "legacy",
        "reproducibility": {"state": "limited", "reason": "legacy path has no recorded digest"},
        "registered_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return target


def list_legacy(registry: str | Path) -> list[dict]:
    return [json.loads(path.read_text()) for path in sorted(Path(registry).glob("*.legacy.json"))]


def migrate_registry(registry: str | Path, *, target_version: int = SCHEMA_VERSION,
                     backup_root: str | Path | None = None) -> dict:
    """Upgrade snapshot records; refuse newer schemas; back up before any write."""
    registry = Path(registry)
    records = sorted(path for path in registry.glob("*.json") if not path.name.endswith(".legacy.json"))
    plan = []
    for path in records:
        record = json.loads(path.read_text())
        version = record.get("schema_version", 0)
        if version > target_version:
            raise DataDirectoryError(
                f"refusing to downgrade {path.name}: schema_version={version} > {target_version}")
        plan.append((path, record, version))
    changed = [item for item in plan if item[2] < target_version]
    if not changed:
        return {"registry": str(registry), "migrated": 0, "skipped": len(plan), "backup": None}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = Path(backup_root or registry.parent / "registry-backup") / stamp
    backup.mkdir(parents=True, exist_ok=True)
    for path in records:
        shutil.copy2(path, backup / path.name)
    for path, record, version in changed:
        upgraded = _upgrade_record(record, version, target_version)
        path.write_text(json.dumps(upgraded, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return {"registry": str(registry), "migrated": len(changed), "skipped": len(plan) - len(changed),
            "backup": backup.name}


def _upgrade_record(record: dict, version: int, target: int) -> dict:
    upgraded = dict(record)
    if version < 1 <= target:
        components = upgraded.get("components") or []
        if not components:
            raise DataDirectoryError(
                f"cannot upgrade {upgraded.get('snapshot_id')}: no component manifest")
        upgraded["schema_version"] = 1
        upgraded.setdefault("content_digest", component_digest(components))
        upgraded.setdefault("status", "published")
    return upgraded


def restore_registry(backup_dir: str | Path, registry: str | Path) -> dict:
    """Restore registry files from a migration backup; refuse an empty source."""
    backup, registry = Path(backup_dir), Path(registry)
    files = sorted(list(backup.glob("*.json")))
    if not files:
        raise DataDirectoryError(f"no registry files in backup: {backup}")
    registry.mkdir(parents=True, exist_ok=True)
    restored = []
    for path in files:
        shutil.copy2(path, registry / path.name)
        restored.append(path.name)
    return {"restored": len(restored), "files": restored}


# -- DATA05 bar quality gate -------------------------------------------------
def validate_bars(reader: "FreeSnapshotReader", symbols: Sequence[str],
                  fields: Sequence[str] = ("open", "high", "low", "close", "volume"),
                  tolerance: float = 1e-4) -> dict:
    """Fail-closed bar checks: alignment, positivity, infinities, OHLC ordering.

    NaN is treated as a missing observation (the qlib bin format pads suspended or
    unknown days with NaN) and counted separately; it is not a corruption issue.
    """
    issues: list[dict] = []
    checked = 0
    missing_points = 0
    for symbol in symbols:
        try:
            series = {field: free_sources.read_bin_values(
                reader.path("bar") / symbol.lower() / f"{field}.day.bin") for field in fields}
        except (FreeSourceError, OSError) as error:
            issues.append({"symbol": symbol, "type": "unreadable", "detail": str(error)})
            continue
        lengths = {field: len(values) for field, values in series.items()}
        if len(set(lengths.values())) != 1:
            issues.append({"symbol": symbol, "type": "length_mismatch", "detail": lengths})
            continue
        checked += 1
        seen: set[tuple[str, str]] = set()
        for field, values in series.items():
            for value in values:
                if math.isnan(value):
                    missing_points += 1
                    continue
                if math.isinf(value):
                    problem = "non_finite"
                elif field != "volume" and value <= 0:
                    problem = "non_positive_price"
                elif field == "volume" and value < 0:
                    problem = "negative_volume"
                else:
                    continue
                if (problem, field) not in seen:
                    issues.append({"symbol": symbol, "type": problem, "field": field})
                    seen.add((problem, field))
        if {"open", "high", "low", "close"} <= set(fields):
            seen_ohlc: set[str] = set()
            for index in range(lengths[fields[0]]):
                row = [series[field][index] for field in ("open", "high", "low", "close")]
                if any(math.isnan(value) for value in row):
                    continue
                low, high = series["low"][index], series["high"][index]
                body_low = min(series["open"][index], series["close"][index])
                body_high = max(series["open"][index], series["close"][index])
                if low - body_low > tolerance and "low_above_body" not in seen_ohlc:
                    issues.append({"symbol": symbol, "type": "low_above_body", "index": index})
                    seen_ohlc.add("low_above_body")
                if body_high - high > tolerance and "body_above_high" not in seen_ohlc:
                    issues.append({"symbol": symbol, "type": "body_above_high", "index": index})
                    seen_ohlc.add("body_above_high")
                if len(seen_ohlc) == 2:
                    break
    return {"ok": not issues, "checked_symbols": checked, "issue_count": len(issues),
            "missing_points": missing_points, "issues": issues[:50]}


def coverage_report(reader: "FreeSnapshotReader", instruments: Sequence[dict],
                    as_of: date | None = None) -> dict:
    """DATA05 coverage gate: does each instrument's data actually reach its declared end?

    This is the automated version of the manual check that found the Beijing truncation:
    an instrument whose `instruments` interval claims a later end than its feature series
    is reported as truncated instead of being silently treated as tradable.
    """
    calendar = reader.calendar()
    truncated, ok, missing, stale = [], 0, [], []
    for row in instruments:
        symbol, declared_end = row["symbol"], row["end"]
        try:
            head = free_sources.read_bin_head_tail(
                reader.path("bar") / symbol.lower() / "close.day.bin")
        except (free_sources.FreeSourceError, OSError):
            missing.append({"symbol": symbol, "declared_end": declared_end.isoformat()})
            continue
        last_index = head["start_index"] + head["points"] - 1
        if last_index < 0 or last_index >= len(calendar):
            truncated.append({"symbol": symbol, "declared_end": declared_end.isoformat(),
                              "actual_end": None})
            continue
        actual_end = calendar[last_index]
        if actual_end < declared_end:
            truncated.append({"symbol": symbol, "declared_end": declared_end.isoformat(),
                              "actual_end": actual_end.isoformat(),
                              "gap_days": (declared_end - actual_end).days})
        else:
            ok += 1
            if as_of and declared_end < as_of:
                stale.append(symbol)
    return {"ok": not truncated and not missing, "checked": len(instruments),
            "instruments_ok": ok, "truncated": len(truncated), "missing_series": len(missing),
            "truncated_sample": truncated[:20], "missing_sample": missing[:20],
            "stale_intervals": len(stale),
            "note": "truncated means the instruments interval claims data the feature series "
                    "does not contain. It is a flag, not a verdict: a delisting or merger can "
                    "legitimately end trading before the index removes the name, while a still-"
                    "listed symbol ending early is a real gap (compare with delist dates). "
                    "This does not replace the stale-vs-delisted check."}


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
        self._calendar: list[date] | None = None

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
        if self._calendar is None:
            text = self.path("calendar").read_text().split()
            self._calendar = [date.fromisoformat(item) for item in text]
        return self._calendar

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
