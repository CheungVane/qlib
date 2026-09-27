"""Lifecycle object contracts (T06 interface draft, RESEARCH_LIFECYCLE §2).

This module freezes the *interface* the later storage/API work must satisfy: required
fields, opaque identity plus content digest, and the retry/re-run/new-definition rules.
It deliberately holds no database access — T06 decides the physical schema separately.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

OPAQUE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


class LifecycleError(ValueError):
    """Missing or inconsistent lifecycle object fields."""


def _require(payload: dict, keys: tuple[str, ...], label: str) -> None:
    missing = [key for key in keys if payload.get(key) in (None, "", [], {})]
    if missing:
        raise LifecycleError(f"{label} is missing {missing}")


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or OPAQUE_ID.fullmatch(value) is None:
        raise LifecycleError(f"{label} must be an opaque path-safe identifier")
    return value


def content_digest(payload: Any) -> str:
    """Stable digest for immutable revisions; `latest` and display names never enter it."""
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                         default=str)
    return "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()


@dataclass(frozen=True)
class ExperimentDefinitionRevision:
    """LIFE01: the frozen inputs a Run references. Every field is research identity."""

    definition_id: str
    content_digest: str
    dataset_snapshot: dict
    universe: dict
    features: dict
    label: dict
    validation_plan: dict
    model: dict
    portfolio: dict
    execution_scenario: dict
    evaluation: dict
    seed: int
    code: dict
    schema_version: int = 1

    @classmethod
    def build(cls, payload: dict) -> "ExperimentDefinitionRevision":
        _require(payload, ("definition_id", "dataset_snapshot", "universe", "features", "label",
                           "validation_plan", "model", "portfolio", "execution_scenario",
                           "evaluation", "seed", "code"), "definition revision")
        definition_id = _identifier(payload["definition_id"], "definition_id")
        if isinstance(payload["seed"], bool) or not isinstance(payload["seed"], int):
            raise LifecycleError("seed must be an integer")
        body = {key: payload[key] for key in
                ("dataset_snapshot", "universe", "features", "label", "validation_plan", "model",
                 "portfolio", "execution_scenario", "evaluation", "seed", "code")}
        return cls(definition_id=definition_id, content_digest=content_digest(body), **body)


@dataclass(frozen=True)
class ModelArtifactVersion:
    """LIFE01: model weights plus the fitted preprocessing and their input contract."""

    model_id: str
    content_digest: str
    features: list
    preprocessing: dict
    label: dict
    train_window: dict
    validation_plan: dict
    code_environment: dict
    seed: int
    source_run_id: str
    source_attempt_id: str
    schema_version: int = 1

    def accepts(self, request: dict) -> tuple[bool, str]:
        """Reuse is only allowed when the input contract matches; a loadable file is not enough."""
        expected = {"features": self.features, "preprocessing": self.preprocessing,
                    "label": self.label}
        for key, value in expected.items():
            if request.get(key) != value:
                return False, f"input_contract_mismatch:{key}"
        return True, "ok"

    @classmethod
    def build(cls, payload: dict) -> "ModelArtifactVersion":
        _require(payload, ("model_id", "features", "preprocessing", "label", "train_window",
                           "validation_plan", "code_environment", "seed", "source_run_id",
                           "source_attempt_id"), "model artifact version")
        body = {key: payload[key] for key in
                ("features", "preprocessing", "label", "train_window", "validation_plan",
                 "code_environment", "seed")}
        return cls(model_id=_identifier(payload["model_id"], "model_id"),
                   content_digest=content_digest(body), source_run_id=payload["source_run_id"],
                   source_attempt_id=payload["source_attempt_id"], **body)


@dataclass(frozen=True)
class StrategyVersion:
    """LIFE01: signal/portfolio rules plus the data contract they will see in the future."""

    strategy_id: str
    content_digest: str
    signal: dict
    model_ref: str | None
    portfolio_rules: dict
    risk_limits: dict
    execution_assumption: dict
    future_data_contract: dict
    schema_version: int = 1

    @classmethod
    def build(cls, payload: dict) -> "StrategyVersion":
        _require(payload, ("strategy_id", "signal", "portfolio_rules", "risk_limits",
                           "execution_assumption", "future_data_contract"), "strategy version")
        body = {key: payload.get(key) for key in
                ("signal", "model_ref", "portfolio_rules", "risk_limits",
                 "execution_assumption", "future_data_contract")}
        body["signal"] = payload["signal"]  # required, never None
        return cls(strategy_id=_identifier(payload["strategy_id"], "strategy_id"),
                   content_digest=content_digest(body), **body)


def classify_repeat(previous: dict, current: dict) -> str:
    """LIFE01 identity rule: retry / same-definition re-run / new definition revision.

    The comparison covers effective research inputs, not labels or notes.
    """
    keys = ("dataset_snapshot", "universe", "features", "label", "validation_plan", "model",
            "portfolio", "execution_scenario", "evaluation", "seed", "code")
    changed = [key for key in keys if previous.get(key) != current.get(key)]
    if not changed:
        return "retry_same_definition"
    if changed == ["seed"] or set(changed) <= {"seed", "model"}:
        # A different seed or model is still a different research identity per LIFE01.
        return "new_definition_revision"
    return "new_definition_revision"


def is_retry_allowed(previous_status: str, process_end_confirmed: bool) -> tuple[bool, str]:
    """Only failed/cancelled/interrupted may retry; interrupted needs a confirmed end first."""
    if previous_status not in ("failed", "cancelled", "interrupted"):
        return False, "previous_attempt_not_terminal_or_successful"
    if previous_status == "interrupted" and not process_end_confirmed:
        return False, "old_process_not_confirmed_ended"
    return True, "ok"


@dataclass
class TrialLedgerEntry:
    """VALIDATION §2A.6 / LIFE01: one candidate trial, kept even when it fails."""

    trial_id: str
    search_scope_id: str
    status: str
    config: dict = field(default_factory=dict)
    attempt_ids: list = field(default_factory=list)
    test_set_access: list = field(default_factory=list)

    def __post_init__(self) -> None:
        _identifier(self.trial_id, "trial_id")
        _identifier(self.search_scope_id, "search_scope_id")
        if self.status not in ("pending", "running", "succeeded", "failed", "eliminated", "selected"):
            raise LifecycleError(f"unknown trial status: {self.status}")

    def note_attempt(self, attempt_id: str) -> None:
        """A retry of the same effective configuration stays in the same trial."""
        _identifier(attempt_id, "attempt_id")
        if attempt_id not in self.attempt_ids:
            self.attempt_ids.append(attempt_id)

    def note_test_access(self, reason: str) -> None:
        """Once the final test set is used for selection it is no longer an independent test."""
        if not reason:
            raise LifecycleError("test set access needs a reason")
        self.test_set_access.append(reason)

    def as_dict(self) -> dict:
        return {"trial_id": self.trial_id, "search_scope_id": self.search_scope_id,
                "status": self.status, "config": self.config, "attempt_ids": list(self.attempt_ids),
                "test_set_access": list(self.test_set_access),
                "ledger_snapshot_id": content_digest(
                    {"trial_id": self.trial_id, "status": self.status, "config": self.config})}
