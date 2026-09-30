"""Managed admission vocabulary; distinct from legacy engine submit params.

Commands retain requested references for idempotency. Resolved inputs are checked
again inside the transaction; preflight is never authorization to skip a check.
"""
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from .artifacts import ArtifactRef, require_id
from .workflows import WorkflowKind, WorkflowPlan, workflow_plan


class EntryPoint(str, Enum):
    RESEARCH = "research"
    DATA = "data"
    WORKFLOW = "workflow"
    RETRY = "retry"


@dataclass(frozen=True)
class AdmissionCommand:
    entry: EntryPoint
    reference: ArtifactRef
    execution_policy_ref: ArtifactRef
    idempotency_key: str
    run_id: str | None = None
    workflow_id: str | None = None

    def __post_init__(self):
        if not isinstance(self.entry, EntryPoint):
            raise ValueError("entry must be an EntryPoint")
        self.execution_policy_ref.require_type("execution_policy")
        expected = {EntryPoint.DATA: "data_plan", EntryPoint.WORKFLOW: "research_workflow",
                    EntryPoint.RESEARCH: "research_definition"}
        if self.entry == EntryPoint.RETRY:
            self.reference.require_type("research_definition", "data_definition")
            require_id(self.run_id)
        else:
            self.reference.require_type(expected[self.entry])
            if self.run_id is not None:
                raise ValueError("only retry binds an existing run")
        if self.entry == EntryPoint.WORKFLOW:
            require_id(self.workflow_id)
        elif self.workflow_id is not None:
            raise ValueError("only workflow start binds a workflow entity")
        key = self.idempotency_key
        if not isinstance(key, str) or not 1 <= len(key) <= 128 or any(ord(c) < 32 or 127 <= ord(c) < 160 for c in key):
            raise ValueError("invalid idempotency key")

    @property
    def operation(self) -> str:
        if self.entry == EntryPoint.RETRY:
            return f"POST /v1/research-runs/{self.run_id}/retry"
        if self.entry == EntryPoint.WORKFLOW:
            return f"POST /v1/research-workflows/{self.workflow_id}/start"
        return {EntryPoint.DATA: "POST /v1/data-pipeline-runs",
                EntryPoint.RESEARCH: "POST /v1/research-runs"}[self.entry]

    def payload_digest(self) -> str:
        field = {EntryPoint.DATA: "plan_ref", EntryPoint.WORKFLOW: "workflow_ref",
                 EntryPoint.RESEARCH: "definition_ref", EntryPoint.RETRY: "definition_ref"}[self.entry]
        body = {"schema_version": 1, field: self.reference.as_dict(),
                "execution_policy_ref": self.execution_policy_ref.as_dict()}
        raw = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PreparedAdmission:
    kind: WorkflowKind
    experiment_id: str | None
    definition_ref: ArtifactRef
    plan_ref: ArtifactRef | None = None
    workflow_ref: ArtifactRef | None = None

    def __post_init__(self):
        if self.workflow_ref is not None:
            self.workflow_ref.require_type("research_workflow")
        if not isinstance(self.kind, WorkflowKind):
            raise ValueError("kind must be a WorkflowKind")
        if self.kind == WorkflowKind.DATA_PREPARE:
            self.definition_ref.require_type("data_definition")
            if self.experiment_id is not None or self.plan_ref is None:
                raise ValueError("data admission requires a plan and no experiment")
            self.plan_ref.require_type("data_plan")
        else:
            require_id(self.experiment_id)
            self.definition_ref.require_type("research_definition")
            if self.plan_ref is not None:
                raise ValueError("research admission cannot carry a data preparation plan")

    def validate_command(self, command: AdmissionCommand) -> None:
        if command.entry == EntryPoint.WORKFLOW:
            if self.workflow_ref != command.reference:
                raise ValueError("preflight substituted the requested workflow")
        elif self.workflow_ref is not None:
            raise ValueError("non-workflow admission cannot introduce a workflow")
        if command.entry == EntryPoint.DATA and self.plan_ref != command.reference:
            raise ValueError("preflight substituted the requested data plan")
        if command.entry in (EntryPoint.RESEARCH, EntryPoint.RETRY) and self.definition_ref != command.reference:
            raise ValueError("preflight substituted the requested definition")
        if command.entry == EntryPoint.RESEARCH and self.kind == WorkflowKind.DATA_PREPARE:
            raise ValueError("research entry cannot admit data preparation")
        if command.entry == EntryPoint.WORKFLOW and self.kind not in (
                WorkflowKind.DIRECTION_REVIEW, WorkflowKind.HYPOTHESIS_REVIEW, WorkflowKind.FORMULA_EVALUATE):
            raise ValueError("human workflow cannot automatically train or backtest")


@dataclass(frozen=True)
class AdmissionReceipt:
    run_id: str
    attempt_id: str
    attempt_no: int
    definition_ref: ArtifactRef
    plan_ref: ArtifactRef | None
    execution_policy_ref: ArtifactRef
    created: bool

    def __post_init__(self):
        require_id(self.run_id)
        require_id(self.attempt_id)
        if type(self.attempt_no) is not int or self.attempt_no < 1:
            raise ValueError("attempt_no must be positive")
        if type(self.created) is not bool:
            raise ValueError("created must be boolean")
        self.execution_policy_ref.require_type("execution_policy")
        if self.plan_ref is not None:
            self.plan_ref.require_type("data_plan")
            self.definition_ref.require_type("data_definition")
        else:
            self.definition_ref.require_type("research_definition")

    def validate_command(self, command: AdmissionCommand) -> None:
        if self.execution_policy_ref != command.execution_policy_ref:
            raise ValueError("receipt substituted execution policy")
        if command.entry == EntryPoint.DATA and self.plan_ref != command.reference:
            raise ValueError("receipt substituted data plan")
        if command.entry in (EntryPoint.RESEARCH, EntryPoint.RETRY) and self.definition_ref != command.reference:
            raise ValueError("receipt substituted definition")
        if command.entry == EntryPoint.RETRY and self.run_id != command.run_id:
            raise ValueError("retry returned a different Run")

    @property
    def replayed(self) -> bool:
        return not self.created


@dataclass(frozen=True)
class AdmissionRequest:
    command: AdmissionCommand
    prepared: PreparedAdmission
    plan: WorkflowPlan

    def __post_init__(self):
        self.prepared.validate_command(self.command)
        if self.plan != workflow_plan(self.prepared.kind):
            raise ValueError("workflow plan differs from frozen definition")
