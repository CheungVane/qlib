"""Infrastructure-neutral interfaces; DTO semantics are defined in docs/spec."""
from __future__ import annotations
from typing import Any, Protocol

class AgentObservationPort(Protocol):
    def status(self) -> dict[str, Any]: ...

class ResearchObservationPort(Protocol):
    def listing(self, limit=20, offset=0, query='') -> dict: ...
    def detail(self, identity: str) -> dict | None: ...

class ResultImporter(Protocol):
    adapter_version: str
    def load(self, **kwargs: Any) -> dict[str, Any]: ...
