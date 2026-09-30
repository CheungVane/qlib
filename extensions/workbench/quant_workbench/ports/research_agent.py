"""Agents produce versioned review/proposals, not trusted numeric metrics."""
from typing import Protocol
from ..domain.artifacts import ArtifactRef
from ..domain.worker import ExecutionContext, ProducedArtifact


class ResearchAgentPort(Protocol):
    def review(self, input_ref: ArtifactRef, workflow_ref: ArtifactRef,
               context: ExecutionContext) -> tuple[ProducedArtifact, ...]:
        """Adapter resolves HR05 TaskEnvelope; frozen capability/model/prompt only.

        Return staged review/proposals for central validation/publication; no DB writes. Explicitly reject
        unsupported tasks; never switch providers or bypass usage reservation.
        """
        ...
