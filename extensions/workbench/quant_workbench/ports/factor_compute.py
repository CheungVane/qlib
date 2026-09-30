"""Deterministic formula and statistics interfaces; no Agent self-reported IC."""
from typing import Protocol
from ..domain.artifacts import ArtifactRef
from ..domain.factor_expression import CompileReport
from ..domain.worker import ExecutionContext, ProducedArtifact


class FormulaCompiler(Protocol):
    def validate(self, formula_ref: ArtifactRef, field_contract_ref: ArtifactRef,
                 operator_ref: ArtifactRef, context: ExecutionContext) -> CompileReport:
        """Return diagnostics or a valid definition; a saved draft is not executable."""
        ...


class FactorComputer(Protocol):
    def compute(self, definition_ref: ArtifactRef, prepared_ref: ArtifactRef,
                context: ExecutionContext) -> ProducedArtifact: ...


class FactorEvaluator(Protocol):
    def evaluate(self, panel_refs: tuple[ArtifactRef, ...], protocol_ref: ArtifactRef,
                 reference_set_ref: ArtifactRef, context: ExecutionContext) -> ProducedArtifact: ...
