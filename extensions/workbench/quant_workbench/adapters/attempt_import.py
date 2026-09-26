"""EXEC12 adapter: publish an attempt-produced engine run through the trusted importer.

The platform core never imports MLflow or an engine SDK; the composition root wires this
adapter into ExecutionService as the `importer` port.
"""

from __future__ import annotations

from typing import Any

from ..source_safety import SourceConflict
from .qlib_mlflow import QlibMlflowImporter


class AttemptResultImporter:
    """Same validation as an explicit `qwb import-qlib`, driven by an attempt candidate."""

    def __init__(self, repository, loaders: dict[str, Any] | None = None):
        self.repository = repository
        self.loaders = {"qlib_mlflow": QlibMlflowImporter(), **(loaders or {})}

    def import_attempt(self, attempt: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
        name = candidate.get("importer")
        loader = self.loaders.get(name)
        if loader is None:
            raise ValueError(f"no importer registered for '{name}'")
        package = loader.load(
            tracking_uri=candidate["tracking_uri"],
            external_id=str(candidate["external_id"]),
            dataset_id=candidate["dataset_id"],
            dataset_version=candidate.get("dataset_version"),
            synthetic=bool(candidate.get("synthetic")),
            trust_local_artifacts=bool(candidate.get("trust_local_artifacts")),
            config_path=candidate.get("config_path"),
        )
        evidence = package.get("evidence") or {}
        if candidate.get("require_cn_scenario_evidence"):
            missing = [key for key in ("cn_scenario", "research_quality") if not evidence.get(key)]
            if missing:
                raise SourceConflict(
                    "attempt result lacks required source evidence: " + ", ".join(missing))
        published = self.repository.publish(
            candidate["source_instance_id"], str(candidate["external_id"]), loader.adapter_version, package)
        return {
            "run_id": published["run_id"], "revision_id": published["revision_id"],
            "created": published["created"], "source_instance_id": candidate["source_instance_id"],
            "external_id": str(candidate["external_id"]), "adapter_version": loader.adapter_version,
        }
