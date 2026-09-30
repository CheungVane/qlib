"""Shared immutable references. Payload validation remains type-specific.

A valid Ref is an identity, not proof that its bytes exist or are verified.
Resolvers must verify all four fields before exposing any published artifact.
"""
from dataclasses import dataclass
import re


def require_id(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value):
        raise ValueError("expected an opaque identifier, not a path")


@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: str
    artifact_type: str
    schema_version: int
    content_digest: str

    def __post_init__(self):
        require_id(self.artifact_id)
        require_id(self.artifact_type)
        if type(self.schema_version) is not int or self.schema_version < 1:
            raise ValueError("schema_version must be a positive integer")
        if not isinstance(self.content_digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", self.content_digest):
            raise ValueError("expected a sha256 content digest")

    def require_type(self, *allowed: str) -> None:
        if self.artifact_type not in allowed:
            raise ValueError(f"expected artifact type in {allowed}")

    def as_dict(self) -> dict:
        return {"artifact_id": self.artifact_id, "artifact_type": self.artifact_type,
                "schema_version": self.schema_version, "content_digest": self.content_digest}
