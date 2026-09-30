"""Worker boundary carries frozen identities, never SDK objects or host paths."""
from dataclasses import dataclass
from datetime import datetime
import re
from .artifacts import ArtifactRef, require_id


@dataclass(frozen=True)
class ExecutionContext:
    run_id: str
    attempt_id: str
    launch_token: str
    definition_ref: ArtifactRef
    execution_policy_ref: ArtifactRef
    workflow_id: str | None
    budget_scope_ids: tuple[str, ...]
    deadline_at: str
    cancellation_token_id: str
    output_namespace: str

    def __post_init__(self):
        for value in (self.run_id, self.attempt_id, self.launch_token,
                      self.cancellation_token_id, self.output_namespace):
            require_id(value)
        if self.workflow_id is not None:
            require_id(self.workflow_id)
        self.execution_policy_ref.require_type("execution_policy")
        if not isinstance(self.budget_scope_ids, tuple) or not self.budget_scope_ids:
            raise ValueError("worker requires immutable budget scope IDs")
        for scope in self.budget_scope_ids:
            require_id(scope)
        if not isinstance(self.deadline_at, str) or not re.fullmatch(
                r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z", self.deadline_at):
            raise ValueError("deadline requires UTC")
        datetime.fromisoformat(self.deadline_at.replace("Z", "+00:00"))


@dataclass(frozen=True)
class ProducedArtifact:
    """Validated worker output, still NOT published or usable as a parent.

    object_digest locates the staged envelope in the controlled output namespace.
    Only the central publisher verifies bytes/schema/parents and registers it.
    This distinction prevents an engine adapter from becoming a registry writer.
    """
    ref: ArtifactRef
    object_digest: str

    def __post_init__(self):
        if not isinstance(self.ref, ArtifactRef):
            raise ValueError("output requires an ArtifactRef")
        if not isinstance(self.object_digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", self.object_digest):
            raise ValueError("output requires an envelope byte digest")
