"""Atomic managed-run admission, not a second execution/state engine.

No production implementation is provided until PHYSICAL_CONTRACT migration and
EXEC13 protection pass. A protocol or successful fake is not a capability claim.
"""
from typing import Protocol
from ..domain.artifacts import ArtifactRef
from ..domain.worker import ExecutionContext, ProducedArtifact
from ..domain.admission import AdmissionCommand, PreparedAdmission, AdmissionRequest, AdmissionReceipt


class AdmissionPreflightPort(Protocol):
    def prepare_admission(self, command: AdmissionCommand) -> PreparedAdmission:
        """Read-only: verify published refs, types, capability and required components.

        Resolve the frozen workflow/definition, not 'latest'. Must not start a
        worker, reserve a budget, mutate a head or publish a generated definition.
        Missing workflow definition preparation must fail explicitly until the
        storage adapter supports its atomic creation in admit_run.
        """
        ...


class ManagedAdmissionPort(Protocol):
    def replay(self, command: AdmissionCommand) -> AdmissionReceipt | None:
        """Return committed identity; raise on key/payload/legacy proof conflict.

        Must run before preflight (expired plans can still be replayed).
        A replayed receipt has created=False. This read reserves nothing.
        """
        ...

    def admit_run(self, request: AdmissionRequest) -> AdmissionReceipt:
        """One atomic boundary: recheck replay, refs, expiry, retry end proof,
        workflow enabled/edge, quotas and slots; commit Run/Attempt/stages,
        budgets, edge, launch intent and response together. A racing replay is
        returned, not admitted twice. No network or engine start under SQL lock.
        New definition creation (when needed) belongs in this same transaction.
        Recovery/dispatch consumes the durable launch intent outside this call.
        """
        ...


class ManagedExecutionPort(Protocol):
    def admit_managed(self, command: AdmissionCommand) -> AdmissionReceipt: ...


class UsageBudgetPort(Protocol):
    def reserve_usage(self, event_key: str, attempt_id: str | None,
                      items: tuple[dict, ...] | list[dict]) -> dict:
        """Atomically check and consume one or more scope/dimension increments.

        The scope/limit must already be registered from a frozen policy; this
        port never invents a limit. The same event_key with the same amounts is
        a replay, with different amounts it is an idempotency conflict, and any
        refusal leaves all dimensions unchanged (PHYSICAL_CONTRACT §3).
        """
        ...


class ArtifactPublicationPort(Protocol):
    def publish_stage(self, context: "ExecutionContext", stage_id: str,
                      outputs: tuple["ProducedArtifact", ...]) -> tuple["ArtifactRef", ...]:
        """Verify staged envelope bytes/schema/parents and producer identity, then
        atomically publish artifacts, stage outputs and receipt. Only returned
        refs may be passed as inputs to later stages; engines never write tables.
        A racing cancellation/publication follows the committed receipt fact.
        """
        ...
