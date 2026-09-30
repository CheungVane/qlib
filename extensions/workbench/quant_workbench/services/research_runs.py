"""Single Run admission entry used by data and human research services.

Run persistence is performed only inside ExecutionService's atomic admission
port. Domain entry services must not create their own Run/Attempt repositories.
"""
from ..domain.admission import AdmissionCommand, AdmissionReceipt
from ..domain.errors import ManagedExecutionUnavailable
from ..ports.research import ManagedExecutionPort


class ResearchRunService:
    def __init__(self, execution: ManagedExecutionPort | None):
        self.execution = execution

    def start(self, command: AdmissionCommand) -> AdmissionReceipt:
        if self.execution is None:
            raise ManagedExecutionUnavailable("managed execution is not configured")
        return self.execution.admit_managed(command)
