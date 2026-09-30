"""Shared verified data preparation for factors, training and backtests.

Returned manifests bind axes, units, masks and availability, per ARTIFACT_CONTRACT.
No implicit label-as-feature or adapter-local redefinition of membership/labels.
"""
from typing import Protocol
from ..domain.artifacts import ArtifactRef
from ..domain.worker import ExecutionContext, ProducedArtifact


class DataInputsPort(Protocol):
    def prepare(self, request_ref: ArtifactRef, context: ExecutionContext) -> ProducedArtifact:
        """preparation_request -> verified prepared_input, chunked outside HTTP."""
        ...

    def materialize(self, prepared_ref: ArtifactRef, engine_binding_ref: ArtifactRef,
                    context: ExecutionContext) -> ProducedArtifact:
        """Return materialization with parent identity and equivalence evidence."""
        ...
