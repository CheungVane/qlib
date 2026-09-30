"""Separate fit, inference, portfolio and simulation responsibilities.

Backtest never owns training. Every method returns a staged artifact for central publication;
engine-specific schemas and verified runtime adapters are still required.
"""
from typing import Protocol
from ..domain.artifacts import ArtifactRef
from ..domain.worker import ExecutionContext, ProducedArtifact


class TrainingPort(Protocol):
    def fit(self, prepared_ref: ArtifactRef, definition_ref: ArtifactRef,
            context: ExecutionContext) -> ProducedArtifact:
        """Return model binding fold-only preprocessing state and training evidence."""
        ...


class PredictionPort(Protocol):
    def predict(self, model_ref: ArtifactRef, prepared_ref: ArtifactRef,
                context: ExecutionContext) -> ProducedArtifact:
        """Validate input contract; transform only, never refit."""
        ...


class PortfolioPort(Protocol):
    def construct(self, signal_ref: ArtifactRef, strategy_ref: ArtifactRef,
                  context: ExecutionContext) -> ProducedArtifact: ...


class BacktestPort(Protocol):
    def simulate(self, portfolio_ref: ArtifactRef, prepared_ref: ArtifactRef,
                 scenario_ref: ArtifactRef, context: ExecutionContext) -> ProducedArtifact: ...
