"""Data use-case entry. Acquiring/cleaning bytes belongs to worker adapters."""
from ..domain.admission import AdmissionCommand, AdmissionReceipt, EntryPoint
from ..domain.artifacts import ArtifactRef
from .research_runs import ResearchRunService


class DataPipelineService:
    def __init__(self, runs: ResearchRunService):
        self.runs = runs

    def start(self, plan_ref: ArtifactRef, execution_policy_ref: ArtifactRef,
              idempotency_key: str) -> AdmissionReceipt:
        return self.runs.start(AdmissionCommand(EntryPoint.DATA, plan_ref,
                                                execution_policy_ref, idempotency_key))
