"""Fixed workflow design contracts, not executable jobs or capability claims.

A step describes ownership and dependency only. Payload schemas, persistence and
engine bindings must pass LIFE/EXEC acceptance before these plans can be run.
"""
from dataclasses import dataclass
from enum import Enum


class WorkflowKind(str, Enum):
    DATA_PREPARE = "data_prepare"
    DIRECTION_REVIEW = "direction_review"
    HYPOTHESIS_REVIEW = "hypothesis_review"
    FORMULA_EVALUATE = "formula_evaluate"
    TRAIN = "train"
    MINE = "mine"
    BACKTEST = "backtest"


@dataclass(frozen=True)
class WorkflowStep:
    key: str
    owner: str
    depends_on: tuple[str, ...] = ()

    def __post_init__(self):
        if any(not isinstance(value, str) or not value.strip() for value in (self.key, self.owner)):
            raise ValueError("step key and owner must be nonempty strings")
        if not isinstance(self.depends_on, tuple) or any(
            not isinstance(key, str) or not key.strip() for key in self.depends_on
        ):
            raise ValueError("step dependencies must be an immutable tuple of nonempty strings")


@dataclass(frozen=True)
class WorkflowPlan:
    kind: WorkflowKind
    steps: tuple[WorkflowStep, ...]

    def __post_init__(self):
        if not isinstance(self.kind, WorkflowKind):
            raise ValueError("workflow kind must be a WorkflowKind")
        if not isinstance(self.steps, tuple) or any(not isinstance(step, WorkflowStep) for step in self.steps):
            raise ValueError("workflow steps must be an immutable tuple of WorkflowStep")
        seen = set()
        for step in self.steps:
            if not step.key or step.key in seen:
                raise ValueError("step keys must be nonempty and unique")
            if not step.owner or not set(step.depends_on) <= seen:
                raise ValueError("steps require an owner and earlier dependencies")
            seen.add(step.key)
        if not seen:
            raise ValueError("a workflow requires steps")


def workflow_plan(kind: WorkflowKind | str) -> WorkflowPlan:
    """Return the canonical fixed plan; unknown kinds fail, never fall back."""
    kind = WorkflowKind(kind)
    sequences = {
        WorkflowKind.DATA_PREPARE: (("preflight", "research"), ("acquire", "source_adapter"),
                                    ("normalize", "normalizer"), ("reconcile", "reconciler"),
                                    ("validate", "data_quality"), ("publish", "snapshot_publisher"),
                                    ("report", "data_pipeline")),
        WorkflowKind.DIRECTION_REVIEW: (("prepare", "research"), ("review", "research_agent"),
                                       ("publish", "artifact_publisher")),
        WorkflowKind.HYPOTHESIS_REVIEW: (("prepare", "research"), ("review", "research_agent"),
                                        ("propose_formula", "research_agent"), ("publish", "artifact_publisher")),
        WorkflowKind.FORMULA_EVALUATE: (("prepare", "research"), ("review_compile", "formula_compiler"),
                                       ("compute", "factor_computer"), ("evaluate", "factor_analysis"),
                                       ("publish", "artifact_publisher")),
        WorkflowKind.TRAIN: (("prepare", "research"), ("train", "training_adapter"),
                             ("predict", "prediction_adapter"), ("evaluate", "validation")),
        WorkflowKind.MINE: (("prepare", "research"), ("generate", "mining_adapter"),
                            ("evaluate", "factor_analysis")),
        WorkflowKind.BACKTEST: (("prepare", "research"), ("signal", "prediction_adapter"),
                                ("portfolio", "strategy"), ("simulate", "backtest_adapter"),
                                ("evaluate", "performance")),
    }
    sequence = sequences[kind]
    return WorkflowPlan(kind, tuple(WorkflowStep(key, owner, (sequence[i - 1][0],) if i else ())
                                   for i, (key, owner) in enumerate(sequence)))
