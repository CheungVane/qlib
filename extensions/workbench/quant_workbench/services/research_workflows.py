"""Human workflow entry; Run and Attempt ownership stays in shared services.

Selection/handoff persistence and automatic supervision are separate future
use cases, not callbacks that launch arbitrary code from a GET request.
"""
from ..domain.admission import AdmissionCommand, AdmissionReceipt, EntryPoint
from ..domain.artifacts import ArtifactRef
from .research_runs import ResearchRunService


class ResearchWorkflowService:
    def __init__(self, runs: ResearchRunService):
        self.runs = runs

    def start(self, workflow_id: str, workflow_ref: ArtifactRef, execution_policy_ref: ArtifactRef,
              idempotency_key: str) -> AdmissionReceipt:
        return self.runs.start(AdmissionCommand(EntryPoint.WORKFLOW, workflow_ref,
                                                execution_policy_ref, idempotency_key, workflow_id=workflow_id))
