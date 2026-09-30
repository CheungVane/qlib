"""Source IO is isolated from normalization, reconciliation and publication.

All refs resolve against the published artifact registry. These are worker
capabilities, not promises of implemented providers or readiness.
"""
from typing import Protocol
from ..domain.artifacts import ArtifactRef
from ..domain.data_pipeline import SourceFetchPlan
from ..domain.worker import ExecutionContext, ProducedArtifact


class SourceAdapter(Protocol):
    def capabilities(self) -> ArtifactRef: ...
    def plan(self, data_plan_ref: ArtifactRef) -> SourceFetchPlan:
        """Select only this source's declared chunks; never resolve latest again."""
        ...
    def fetch(self, plan: SourceFetchPlan, checkpoint_ref: ArtifactRef | None,
              context: ExecutionContext) -> ProducedArtifact: ...


class Normalizer(Protocol):
    def normalize(self, raw_ref: ArtifactRef, mapping_ref: ArtifactRef,
                  context: ExecutionContext) -> ProducedArtifact: ...


class Reconciler(Protocol):
    def merge(self, batch_refs: tuple[ArtifactRef, ...], policy_ref: ArtifactRef,
              context: ExecutionContext) -> ProducedArtifact: ...


class QualityEvaluator(Protocol):
    def evaluate(self, candidate_ref: ArtifactRef, policy_ref: ArtifactRef,
                 context: ExecutionContext) -> ProducedArtifact: ...


class SnapshotPublisher(Protocol):
    def publish(self, candidate_ref: ArtifactRef, report_ref: ArtifactRef,
                context: ExecutionContext) -> ArtifactRef:
        """Recheck quality and dependencies; atomic publication returns snapshot ref.

        Receipt persistence/replay is mandatory even though consumers get only
        the immutable snapshot. Failed quality never returns a snapshot.
        """
        ...
