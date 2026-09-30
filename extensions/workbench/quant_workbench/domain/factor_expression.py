"""Compile result contract, not a DSL implementation or permission to use eval."""
from dataclasses import dataclass
from .worker import ProducedArtifact


@dataclass(frozen=True)
class CompileDiagnostic:
    code: str
    message: str
    field_path: str | None = None


@dataclass(frozen=True)
class CompileReport:
    definition: ProducedArtifact | None
    errors: tuple[CompileDiagnostic, ...]

    def __post_init__(self):
        if not isinstance(self.errors, tuple):
            raise ValueError('diagnostics must be immutable')
        if self.definition is None:
            if not self.errors:
                raise ValueError('invalid formula requires diagnostics')
        else:
            self.definition.ref.require_type('factor_definition')
            if self.errors:
                raise ValueError('failed compilation cannot expose an executable definition')

    @property
    def valid(self) -> bool:
        return self.definition is not None
