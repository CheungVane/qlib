"""Ports used by the application service; no infrastructure imports here."""

from __future__ import annotations

from typing import Any, Protocol


class ResultRepository(Protocol):
    def publish(self, source_instance_id: str, external_id: str, adapter_version: str,
                package: dict[str, Any]) -> dict[str, Any]: ...

    def list_runs(self, limit: int = 20, cursor: str | None = None) -> dict[str, Any]: ...

    def get_run(self, run_id: str) -> dict[str, Any] | None: ...

    def get_revision(self, run_id: str, revision_id: str | None = None) -> dict[str, Any] | None: ...

    def list_revisions(self, run_id: str) -> list[dict[str, Any]]: ...

    def health(self) -> dict[str, Any]: ...


class ResultImporter(Protocol):
    adapter_version: str

    def load(self, **kwargs: Any) -> dict[str, Any]: ...


class AgentObservationPort(Protocol):
    def status(self) -> dict[str, Any]: ...
