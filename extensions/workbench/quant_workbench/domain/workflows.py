"""Fixed workflow design contracts, not executable jobs or capability claims.

A step describes ownership and dependency only. Payload schemas, persistence and
engine bindings must pass LIFE/EXEC acceptance before these plans can be run.
"""
from dataclasses import dataclass
from enum import Enum


class WorkflowKind(str, Enum):
    TRAIN = "train"
    MINE = "mine"
    BACKTEST = "backtest"


@dataclass(frozen=True)
class WorkflowStep:
    key: str
    owner: str
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkflowPlan:
    kind: WorkflowKind
    steps: tuple[WorkflowStep, ...]

    def __post_init__(self):
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
