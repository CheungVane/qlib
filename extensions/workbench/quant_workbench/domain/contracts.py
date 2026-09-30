"""Closed-record validation for the G1 shared contracts.

This module implements the transport/domain layers frozen in ARCHITECTURE §9.4
for the shared types of COMMAND_CONTRACT §1 and ARTIFACT_CONTRACT §1/§6. It
performs no I/O and no authorization: whether a referenced artifact is
published, a capability is ready or a pointer matches is checked by the
preflight/storage ports. Adding a payload type here requires that its contract
is already frozen in a spec; unknown types fail with
``payload_schema_not_frozen`` instead of being accepted as arbitrary JSON.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Mapping


class ContractError(ValueError):
    """One validation failure; maps to HTTP 422 / CLI exit 2 when at the edge."""

    code = "validation_error"

    def __init__(self, path: str, rule: str, message: str):
        self.path = path
        self.rule = rule
        self.message = message
        super().__init__(f"{path}: {message}")

    def details(self) -> dict[str, Any]:
        return {"errors": [{"path": self.path, "rule": self.rule, "message": self.message}]}


def _reject_constant(name: str):
    raise ContractError("$", "non_finite_number", f"{name} is not allowed in contract JSON")


def _reject_non_finite(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ContractError("$", "non_finite_number", "non-finite numbers are not allowed")
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("$", "duplicate_key", f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def loads_strict(text: str) -> dict[str, Any]:
    """Parse one contract JSON document, rejecting shapes the DTO layer forbids."""
    if not isinstance(text, str):
        raise ContractError("$", "text_required", "contract JSON must be text")
    try:
        value = json.loads(text, object_pairs_hook=_reject_duplicate_keys,
                           parse_constant=_reject_constant, parse_float=_reject_non_finite)
    except ContractError:
        raise
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exc:
        raise ContractError("$", "invalid_json", str(exc)) from None
    if not isinstance(value, dict):
        raise ContractError("$", "object_required", "the root value must be a JSON object")
    return value


ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
TIME_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z\Z")
DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
DECIMAL_RE = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?\Z")


def parse_id(value: Any, path: str = "$") -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise ContractError(path, "invalid_id", "expected an opaque identifier, not a path")
    return value


def parse_digest(value: Any, path: str = "$") -> str:
    if not isinstance(value, str) or not DIGEST_RE.fullmatch(value):
        raise ContractError(path, "invalid_digest", "expected sha256:<64 lowercase hex>")
    return value


def parse_time(value: Any, path: str = "$") -> str:
    if not isinstance(value, str) or not TIME_RE.fullmatch(value):
        raise ContractError(path, "invalid_time", "expected UTC RFC3339 with milliseconds")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ContractError(path, "invalid_time", "not a real UTC timestamp") from None
    return value


def parse_date(value: Any, path: str = "$") -> str:
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        raise ContractError(path, "invalid_date", "expected YYYY-MM-DD")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ContractError(path, "invalid_date", "not a real calendar date") from None
    return value


def parse_key(value: Any, path: str = "$") -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 128 or any(
            ord(ch) < 32 or 127 <= ord(ch) < 160 for ch in value):
        raise ContractError(path, "invalid_key", "expected 1-128 characters without control characters")
    return value


def parse_int(value: Any, path: str = "$", *, minimum: int | None = None,
              maximum: int | None = None) -> int:
    if type(value) is not int:
        raise ContractError(path, "invalid_integer", "expected an integer, not a boolean or float")
    if minimum is not None and value < minimum:
        raise ContractError(path, "out_of_range", f"must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ContractError(path, "out_of_range", f"must be <= {maximum}")
    return value


def parse_bool(value: Any, path: str = "$") -> bool:
    if type(value) is not bool:
        raise ContractError(path, "invalid_boolean", "expected a JSON boolean")
    return value


def parse_str(value: Any, path: str = "$", *, min_len: int = 0, max_len: int = 32768) -> str:
    if not isinstance(value, str):
        raise ContractError(path, "invalid_string", "expected a string")
    if not min_len <= len(value) <= max_len:
        raise ContractError(path, "invalid_length", f"length must be within {min_len}..{max_len}")
    if any(ord(ch) < 32 and ch not in "\t\n\r" for ch in value):
        raise ContractError(path, "invalid_string", "string contains unsupported control characters")
    return value


def parse_enum(*allowed: str) -> Callable[[Any, str], str]:
    ordered = tuple(allowed)

    def parser(value: Any, path: str = "$") -> str:
        if value not in ordered:
            raise ContractError(path, "invalid_enum", f"expected one of {ordered}")
        return value

    return parser


def parse_decimal_string(value: Any, path: str = "$") -> str:
    """Canonical decimal string: no exponent, no trailing zeros, no negative zero."""
    if not isinstance(value, str) or not DECIMAL_RE.fullmatch(value):
        raise ContractError(path, "invalid_decimal_string",
                            "expected a canonical decimal string without exponent or trailing zeros")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ContractError(path, "invalid_decimal_string", "not a decimal number") from None
    if value.startswith("-") and number == 0:
        raise ContractError(path, "invalid_decimal_string", "negative zero must be written as \"0\"")
    return value


def parse_scalar(value: Any, path: str = "$") -> str | int | bool | None:
    if value is None or type(value) is bool or type(value) is int:
        return value
    if isinstance(value, str):
        return value
    raise ContractError(path, "invalid_scalar", "expected string, integer, boolean or null")


def nullable(parser: Callable[[Any, str], Any]) -> Callable[[Any, str], Any]:
    def wrapped(value: Any, path: str = "$") -> Any:
        return None if value is None else parser(value, path)

    return wrapped


def parse_array(item: Callable[[Any, str], Any], *, max_len: int = 64,
                min_len: int = 0) -> Callable[[Any, str], list]:
    def parser(value: Any, path: str = "$") -> list:
        if not isinstance(value, list):
            raise ContractError(path, "invalid_array", "expected a JSON array")
        if not min_len <= len(value) <= max_len:
            raise ContractError(path, "invalid_length", f"array length must be within {min_len}..{max_len}")
        return [item(entry, f"{path}[{index}]") for index, entry in enumerate(value)]

    return parser


def parse_object(fields: Mapping[str, Callable[[Any, str], Any]], *,
                 required: set[str] | None = None) -> Callable[[Any, str], dict]:
    required_names = set(fields) if required is None else set(required)

    def parser(value: Any, path: str = "$") -> dict:
        if not isinstance(value, dict):
            raise ContractError(path, "object_required", "expected a JSON object")
        unknown = sorted(set(value) - set(fields))
        if unknown:
            raise ContractError(path, "unknown_field", "unknown field(s): " + ", ".join(unknown))
        missing = sorted(required_names - set(value))
        if missing:
            raise ContractError(path, "missing_field", "missing field(s): " + ", ".join(missing))
        return {name: fields[name](raw, f"{path}.{name}") for name, raw in value.items()}

    return parser


REF = parse_object({
    "artifact_id": parse_id,
    "artifact_type": lambda value, path: parse_str(value, path, min_len=1, max_len=128),
    "schema_version": lambda value, path: parse_int(value, path, minimum=1),
    "content_digest": parse_digest,
})


def parse_ref(value: Any, path: str = "$") -> dict:
    return REF(value, path)


def parse_snapshot_ref(value: Any, path: str = "$") -> dict:
    ref = REF(value, path)
    if ref["artifact_type"] != "dataset_snapshot" or ref["schema_version"] not in (2, 3):
        raise ContractError(path, "invalid_snapshot_ref", "expected a dataset_snapshot Ref with schema 2 or 3")
    return ref


PARENT = parse_object({
    "role": lambda value, path: parse_str(value, path, min_len=1, max_len=64),
    "ordinal": lambda value, path: parse_int(value, path, minimum=0),
    "ref": parse_ref,
})

CHECK = parse_object({
    "code": lambda value, path: parse_str(value, path, min_len=1, max_len=128),
    "status": parse_enum("pass", "warn", "fail", "not_checked", "not_applicable"),
    "message": lambda value, path: parse_str(value, path, max_len=4096),
    "field_path": nullable(lambda value, path: parse_str(value, path, max_len=512)),
    "blocking": parse_bool,
})

WRITE_META = parse_object({
    "schema_version": lambda value, path: parse_int(value, path, minimum=1, maximum=1),
    "idempotency_key": parse_key,
})

SAVE = parse_object({
    "entity_id": nullable(parse_id),
    "expected_revision": nullable(parse_ref),
    "display_name": lambda value, path: parse_str(value, path, min_len=1, max_len=200),
    "artifact_type": lambda value, path: parse_str(value, path, min_len=1, max_len=128),
    "payload": lambda value, path: value if isinstance(value, dict) else _object_needed(path),
    "parent_refs": parse_array(PARENT, max_len=64),
}, required={"entity_id", "expected_revision", "display_name", "artifact_type", "payload", "parent_refs"})


def _object_needed(path: str):
    raise ContractError(path, "object_required", "expected a JSON object")


def parse_save(value: Any, path: str = "$") -> dict:
    save = SAVE(value, path)
    if (save["entity_id"] is None) != (save["expected_revision"] is None):
        raise ContractError(path, "invalid_save_identity",
                            "entity_id and expected_revision must both be null or both be set")
    roles: dict[str, list[int]] = {}
    for index, parent in enumerate(save["parent_refs"]):
        roles.setdefault(parent["role"], []).append(parent["ordinal"])
    for role, ordinals in roles.items():
        if sorted(ordinals) != list(range(len(ordinals))):
            raise ContractError(path, "invalid_parent_ordinals",
                                f"role {role!r} ordinals must be contiguous from 0")
    return save


def parse_check(value: Any, path: str = "$") -> dict:
    return CHECK(value, path)


def parse_parent(value: Any, path: str = "$") -> dict:
    return PARENT(value, path)


def assert_same_ref(expected: Any, provided: Any, path: str = "$") -> dict:
    """All four Ref fields must match; an existing ID alone is not a match."""
    expected_ref = parse_ref(expected, path)
    provided_ref = parse_ref(provided, path)
    if expected_ref != provided_ref:
        raise ContractError(path, "reference_mismatch",
                            f"provided {provided_ref['artifact_id']} does not match the expected digest/schema")
    return provided_ref


def require_published(ref: Any, is_published: Callable[[dict], bool], path: str = "$") -> dict:
    """Storage/preflight supplies existence; this layer only enforces the refusal."""
    parsed = parse_ref(ref, path)
    if not callable(is_published):
        raise ContractError(path, "resolver_required", "a published-reference resolver is required")
    if not is_published(parsed):
        raise ContractError(path, "unpublished_reference",
                            f"artifact {parsed['artifact_id']} is not published")
    return parsed


# --- ARTIFACT_CONTRACT §6 technical payloads frozen for G1 -------------------

REFS = parse_array(parse_ref, max_len=128)
STRINGS = parse_array(lambda value, path: parse_str(value, path), max_len=256)

PARAMETER = parse_object({
    "name": lambda value, path: parse_str(value, path, min_len=1, max_len=128),
    "value": parse_scalar,
    "unit": nullable(lambda value, path: parse_str(value, path, min_len=1, max_len=64)),
})

BUDGET_LIMITS = parse_object({
    "max_hypotheses": lambda value, path: parse_int(value, path, minimum=1),
    "max_formulas_per_hypothesis": lambda value, path: parse_int(value, path, minimum=1),
    "max_numerical_evaluations": lambda value, path: parse_int(value, path, minimum=1),
    "max_agent_attempts": lambda value, path: parse_int(value, path, minimum=1),
    "max_agent_calls": lambda value, path: parse_int(value, path, minimum=1),
})

BUDGET_POLICY = parse_object({
    "limits": BUDGET_LIMITS,
    "previous_policy_ref": nullable(parse_ref),
    "decision_ref": nullable(parse_ref),
})

CODE_IDENTITY = parse_object({
    "repository": lambda value, path: parse_str(value, path, min_len=1, max_len=512),
    "commit": lambda value, path: parse_str(value, path, min_len=1, max_len=128),
    "dirty": parse_bool,
    "patch_digest": nullable(parse_digest),
})

ENVIRONMENT = parse_object({
    "runtime": lambda value, path: parse_str(value, path, min_len=1, max_len=128),
    "version": lambda value, path: parse_str(value, path, min_len=1, max_len=128),
    "dependency_lock_digest": nullable(parse_digest),
    "container_digest": nullable(lambda value, path: parse_str(value, path, min_len=1, max_len=256)),
    "observed_at": parse_time,
    "limitations": STRINGS,
})

CAPABILITY_RECORD = parse_object({
    "capability_id": parse_id,
    "provider_id": parse_id,
    "adapter_version": lambda value, path: parse_str(value, path, min_len=1, max_len=128),
    "operation": lambda value, path: parse_str(value, path, min_len=1, max_len=128),
    "components": STRINGS,
    "field_contract_refs": REFS,
    "version_lock": parse_bool,
    "pagination": lambda value, path: parse_str(value, path, max_len=256),
    "rate_policy_ref": parse_ref,
    "verified_at": nullable(parse_time),
    "evidence_refs": REFS,
    "limitations": STRINGS,
})

EXECUTION_EVIDENCE = parse_object({
    "executor_id": parse_id,
    "launch_token": parse_id,
    "process_identity": lambda value, path: parse_str(value, path, min_len=1, max_len=256),
    "observed_at": parse_time,
    "exit_code": nullable(lambda value, path: parse_int(value, path, minimum=-255, maximum=255)),
    "end_confirmed": parse_bool,
    "evidence_digest": parse_digest,
})

FEATURE_CONTRACT = parse_object({
    "features": parse_array(parse_object({
        "definition_ref": parse_ref,
        "unit": lambda value, path: parse_str(value, path, min_len=1, max_len=64),
        "position": lambda value, path: parse_int(value, path, minimum=0),
    }), max_len=4096),
    "preprocessing_ref": nullable(parse_ref),
    "label_ref": nullable(parse_ref),
})

LABEL_DEFINITION = parse_object({
    "field_name": lambda value, path: parse_str(value, path, min_len=1, max_len=128),
    "price_basis_ref": parse_ref,
    "horizons": parse_array(lambda value, path: parse_int(value, path, minimum=1), max_len=64, min_len=1),
    "formula_version": lambda value, path: parse_str(value, path, min_len=1, max_len=64),
    "entry_timing": parse_enum("next_session", "session_close"),
    "exit_timing": parse_enum("session_close"),
    "full_window_required": lambda value, path: _expect_true(value, path),
    "tradability_policy_ref": parse_ref,
})


def _expect_true(value: Any, path: str) -> bool:
    parsed = parse_bool(value, path)
    if not parsed:
        raise ContractError(path, "unsupported_value", "this contract version requires true")
    return parsed


SAMPLE_PLAN = parse_object({
    "start": parse_date,
    "end": parse_date,
    "warmup_sessions": lambda value, path: parse_int(value, path, minimum=0),
    "universe_ref": parse_ref,
    "selection_intervals": parse_array(parse_object({"start": parse_date, "end": parse_date}), max_len=64),
    "folds": parse_array(parse_object({
        "fold_id": parse_id,
        "train": parse_object({"start": parse_date, "end": parse_date}),
        "valid": nullable(parse_object({"start": parse_date, "end": parse_date})),
        "test": parse_object({"start": parse_date, "end": parse_date}),
    }), max_len=64),
    "embargo_sessions": lambda value, path: parse_int(value, path, minimum=0),
    "label_boundary_policy": parse_enum("drop_cross_partition_labels"),
})

DATE_RULE = lambda value, path: _date_rule(value, path)


def _date_rule(value: Any, path: str) -> dict:
    if not isinstance(value, dict):
        raise ContractError(path, "object_required", "expected a date_rule object")
    kind = value.get("kind")
    if kind == "absolute":
        return parse_object({"kind": parse_enum("absolute"), "start": parse_date,
                             "end": parse_date})(value, path)
    if kind == "latest_complete_session":
        return parse_object({"kind": parse_enum("latest_complete_session"),
                             "start": parse_date})(value, path)
    raise ContractError(path, "invalid_date_rule", "kind must be absolute or latest_complete_session")


INTERVAL = parse_object({"start": parse_date, "end": parse_date})

CHUNK = parse_object({
    "chunk_key": lambda value, path: parse_str(value, path, min_len=1, max_len=128),
    "instrument_ids": parse_array(parse_id, max_len=100000),
    "start": parse_date,
    "end": parse_date,
})

SOURCE_PLAN = parse_object({
    "source_id": parse_id,
    "capability_ref": parse_ref,
    "query_digest": parse_digest,
    "release_id": nullable(lambda value, path: parse_str(value, path, min_len=1, max_len=256)),
    "boundary": INTERVAL,
    "chunks": parse_array(CHUNK, max_len=100000),
    "limitations": STRINGS,
})

DATA_PLAN = parse_object({
    "definition_ref": parse_ref,
    "date_range": INTERVAL,
    "universe_ref": parse_ref,
    "calendar_ref": parse_ref,
    "source_plans": parse_array(SOURCE_PLAN, max_len=64),
    "base_snapshot_ref": nullable(parse_snapshot_ref),
    "estimated_chunks": nullable(lambda value, path: parse_int(value, path, minimum=0)),
    "estimated_bytes": nullable(lambda value, path: parse_int(value, path, minimum=0)),
    "estimated_rows": nullable(lambda value, path: parse_int(value, path, minimum=0)),
    "checks": parse_array(CHECK, max_len=512),
    "created_at": parse_time,
    "expires_at": parse_time,
})

EXECUTION_POLICY = parse_object({
    "schema_version": lambda value, path: parse_int(value, path, minimum=1, maximum=1),
    "note": lambda value, path: parse_str(value, path, max_len=4096),
    "max_concurrent": lambda value, path: parse_int(value, path, minimum=1),
    "timeout_seconds": lambda value, path: parse_int(value, path, minimum=1),
    "terminate_grace_seconds": lambda value, path: parse_int(value, path, minimum=1),
    "cpu_seconds": lambda value, path: parse_int(value, path, minimum=1),
    "memory_bytes": lambda value, path: parse_int(value, path, minimum=1),
    "enforce": parse_array(parse_enum("cpu", "memory"), max_len=2),
    "container": parse_object({"note": lambda value, path: parse_str(value, path, max_len=4096)}),
    "agent_budget": parse_object({
        "max_trials": lambda value, path: parse_int(value, path, minimum=1),
        "max_calls": lambda value, path: parse_int(value, path, minimum=1),
        "scope": parse_enum("policy_revision"),
    }),
    "supervisor_interval_seconds": lambda value, path: parse_int(value, path, minimum=1, maximum=60),
    "terminate_confirmation_seconds": lambda value, path: parse_int(value, path, minimum=1, maximum=60),
}, required={"max_concurrent", "timeout_seconds", "terminate_grace_seconds", "cpu_seconds",
             "memory_bytes", "enforce", "agent_budget"})


AGENT_BINDING = parse_object({
    "agent_id": parse_id,
    "adapter_version": lambda value, path: parse_str(value, path, min_len=1, max_len=128),
    "model_id": lambda value, path: parse_str(value, path, min_len=1, max_len=256),
    "model_version": nullable(lambda value, path: parse_str(value, path, min_len=1, max_len=256)),
    "prompt_ref": parse_ref,
    "output_schema_version": lambda value, path: parse_int(value, path, minimum=1, maximum=1),
    "capabilities": parse_array(lambda value, path: parse_str(value, path, min_len=1, max_len=64),
                                max_len=16, min_len=1),
    "allowed_tools": STRINGS,
})

REF_LIST = parse_array(parse_ref, max_len=512)

DIRECTION_INPUTS = parse_object({
    "input_ref": parse_ref,
    "agent_binding": AGENT_BINDING,
    "snapshot_ref": nullable(parse_snapshot_ref),
    "protocol_ref": nullable(parse_ref),
})

FORMULA_EVALUATE_INPUTS = parse_object({
    "input_ref": parse_ref,
    "agent_binding": AGENT_BINDING,
    "formula_ref": parse_ref,
    "preparation_ref": parse_ref,
    "protocol_ref": parse_ref,
    "reference_set_ref": parse_ref,
})

TRAIN_INPUTS = parse_object({
    "preparation_ref": parse_ref,
    "feature_refs": REF_LIST,
    "validation_plan_ref": parse_ref,
    "preprocessing_ref": parse_ref,
    "engine_binding_ref": parse_ref,
    "model_spec_ref": parse_ref,
    "evaluation_protocol_ref": parse_ref,
    "selection_evidence_refs": REF_LIST,
})

MINE_INPUTS = parse_object({
    "preparation_ref": parse_ref,
    "generator_binding_ref": parse_ref,
    "search_policy_ref": parse_ref,
    "evaluation_protocol_ref": parse_ref,
    "reference_set_ref": parse_ref,
    "trial_scope_id": parse_id,
})


def _signal_input(value: Any, path: str) -> dict:
    if not isinstance(value, dict):
        raise ContractError(path, "object_required", "expected a signal_input object")
    kind = value.get("kind")
    if kind == "prediction":
        return parse_object({"kind": parse_enum("prediction"), "prediction_ref": parse_ref})(value, path)
    if kind == "model":
        return parse_object({"kind": parse_enum("model"), "model_ref": parse_ref,
                             "inference_preparation_ref": parse_ref})(value, path)
    if kind == "factor_rule":
        return parse_object({"kind": parse_enum("factor_rule"),
                             "factor_panel_refs": REF_LIST})(value, path)
    raise ContractError(path, "invalid_signal_input",
                        "kind must be prediction, model or factor_rule")


BACKTEST_INPUTS = parse_object({
    "preparation_ref": parse_ref,
    "strategy_ref": parse_ref,
    "signal_input": _signal_input,
    "execution_scenario_ref": parse_ref,
    "evaluation_protocol_ref": parse_ref,
    "engine_binding_ref": parse_ref,
})

RESEARCH_INPUTS_BY_KIND = {
    "direction_review": DIRECTION_INPUTS,
    "hypothesis_review": DIRECTION_INPUTS,
    "formula_evaluate": FORMULA_EVALUATE_INPUTS,
    "train": TRAIN_INPUTS,
    "mine": MINE_INPUTS,
    "backtest": BACKTEST_INPUTS,
}


def _research_definition(value: Any, path: str) -> dict:
    base = parse_object({
        "experiment_id": parse_id,
        "workflow_kind": parse_enum(*RESEARCH_INPUTS_BY_KIND),
        "inputs": lambda raw, where: raw if isinstance(raw, dict) else _object_needed(where),
        "seed": lambda raw, where: parse_int(raw, where, minimum=0, maximum=2 ** 63 - 1),
        "code_ref": parse_ref,
    })(value, path)
    parser = RESEARCH_INPUTS_BY_KIND[base["workflow_kind"]]
    base["inputs"] = parser(base["inputs"], f"{path}.inputs")
    return base


COMPONENT_REQUEST = parse_object({
    "component": lambda value, path: parse_str(value, path, min_len=1, max_len=64),
    "fields": parse_array(lambda value, path: parse_str(value, path, min_len=1, max_len=64),
                          max_len=256, min_len=1),
    "required": parse_bool,
})

DATA_SOURCE_BINDING = parse_object({
    "source_id": parse_id,
    "capability_ref": parse_ref,
    "component": lambda value, path: parse_str(value, path, min_len=1, max_len=64),
    "field_group": lambda value, path: parse_str(value, path, min_len=1, max_len=64),
    "role": parse_enum("primary", "supplement", "validator"),
    "priority": lambda value, path: parse_int(value, path, minimum=0),
    "required": parse_bool,
    "fallback_allowed": parse_bool,
})

DATA_DEFINITION = parse_object({
    "market": lambda value, path: parse_str(value, path, min_len=1, max_len=32),
    "frequency": parse_enum("day"),
    "timezone": lambda value, path: parse_str(value, path, min_len=1, max_len=64),
    "universe_ref": parse_ref,
    "date_rule": DATE_RULE,
    "components": parse_array(COMPONENT_REQUEST, max_len=64, min_len=1),
    "source_bindings": parse_array(DATA_SOURCE_BINDING, max_len=64, min_len=1),
    "acquisition_mode": parse_enum("online_fetch", "registered_import"),
    "update_mode": parse_enum("full", "incremental"),
    "revision_policy_ref": parse_ref,
    "merge_policy_ref": parse_ref,
    "cleaning_policy_ref": parse_ref,
    "quality_policy_ref": parse_ref,
    "resource_policy_ref": parse_ref,
    "output_schema_version": lambda value, path: parse_int(value, path, minimum=3, maximum=3),
})


RESEARCH_INPUT = parse_object({
    "experiment_id": parse_id,
    "input_kind": parse_enum("direction", "hypothesis", "formula"),
    "content": lambda value, path: parse_str(value, path, min_len=1, max_len=32768),
    "language": lambda value, path: parse_str(value, path, min_len=1, max_len=32),
    "hypothesis_type": parse_enum("causal", "risk_premium", "behavioral", "statistical",
                                  "unspecified"),
    "market": lambda value, path: parse_str(value, path, min_len=1, max_len=32),
    "frequency": parse_enum("day"),
    "constraints": STRINGS,
    "attachments": REFS,
    "author": parse_enum("user", "agent"),
})


def _research_workflow(value: Any, path: str) -> dict:
    record = parse_object({
        "experiment_id": parse_id,
        "input_ref": parse_ref,
        "entry_kind": parse_enum("direction_review", "hypothesis_review", "formula_evaluate"),
        "mode": parse_enum("assisted", "automatic"),
        "snapshot_ref": nullable(parse_snapshot_ref),
        "protocol_ref": nullable(parse_ref),
        "reference_set_ref": nullable(parse_ref),
        "agent_binding": AGENT_BINDING,
        "budget_policy_ref": parse_ref,
        "stop_after": parse_enum("review", "factor_report"),
        "selection_rule": parse_enum("feasibility_then_source_order"),
        "code_ref": parse_ref,
    })(value, path)
    if record["mode"] == "automatic":
        if record["stop_after"] != "factor_report" or record["snapshot_ref"] is None \
                or record["protocol_ref"] is None:
            raise ContractError(path, "invalid_workflow_mode",
                                "automatic mode requires numeric inputs and stop_after=factor_report")
    return record


HUMAN_DECISION = parse_object({
    "experiment_id": parse_id,
    "subject_ref": parse_ref,
    "decision": parse_enum("accept", "revise", "reject", "defer", "explore_anyway"),
    "reason": lambda value, path: parse_str(value, path, max_len=32768),
    "actor": parse_enum("user"),
    "decided_at": parse_time,
    "followup_refs": REFS,
})

FILE_PART = parse_object({
    "part_id": parse_id,
    "object_digest": parse_digest,
    "byte_size": lambda value, path: parse_int(value, path, minimum=0),
    "row_count": nullable(lambda value, path: parse_int(value, path, minimum=0)),
    "serialization": parse_enum("parquet", "csv", "json", "binary"),
    "schema_ref": nullable(parse_ref),
    "partition": parse_object({
        "market": nullable(lambda value, path: parse_str(value, path, min_len=1, max_len=32)),
        "frequency": nullable(lambda value, path: parse_str(value, path, min_len=1, max_len=16)),
        "year": nullable(lambda value, path: parse_int(value, path, minimum=1900, maximum=9999)),
    }),
    "sort_keys": STRINGS,
})

USE_VERDICT = parse_object({
    "use": parse_enum("price_description", "exploratory_factor", "pit_training", "portfolio_backtest"),
    "status": parse_enum("available", "limited", "blocked"),
    "reasons": STRINGS,
})

DATASET_SNAPSHOT = parse_object({
    "digest_scheme": parse_enum("snapshot_manifest_v3"),
    "candidate_ref": parse_ref,
    "quality_report_ref": parse_ref,
    "raw_refs": REFS,
    "normalized_refs": REFS,
    "field_contract_ref": parse_ref,
    "calendar_ref": parse_ref,
    "membership_ref": parse_ref,
    "availability_ref": parse_ref,
    "merge_policy_ref": parse_ref,
    "cleaning_policy_ref": parse_ref,
    "parts": parse_array(FILE_PART, max_len=100000),
    "market": lambda value, path: parse_str(value, path, min_len=1, max_len=32),
    "frequency": parse_enum("day"),
    "timezone": lambda value, path: parse_str(value, path, min_len=1, max_len=64),
    "allowed_uses": parse_array(USE_VERDICT, max_len=16, min_len=1),
})


CITATION = parse_object({
    "title": lambda value, path: parse_str(value, path, min_len=1, max_len=512),
    "url": lambda value, path: parse_str(value, path, min_len=1, max_len=2048),
    "accessed_at": nullable(parse_time),
    "evidence_kind": parse_enum("retrieved", "user_supplied", "unverified"),
})

USAGE = parse_object({
    "calls": lambda value, path: parse_int(value, path, minimum=0),
    "tokens_in": nullable(lambda value, path: parse_int(value, path, minimum=0)),
    "tokens_out": nullable(lambda value, path: parse_int(value, path, minimum=0)),
    "cost_decimal": nullable(parse_decimal_string),
    "currency": nullable(lambda value, path: parse_str(value, path, min_len=1, max_len=16)),
    "measurement": parse_enum("exact", "partial", "unknown"),
})

VARIABLE = parse_object({
    "name": lambda value, path: parse_str(value, path, min_len=1, max_len=128),
    "meaning": lambda value, path: parse_str(value, path, min_len=1, max_len=4096),
    "unit": lambda value, path: parse_str(value, path, min_len=1, max_len=64),
    "field_name": nullable(lambda value, path: parse_str(value, path, min_len=1, max_len=128)),
})

REVIEW = parse_object({
    "input_ref": parse_ref,
    "review_kind": parse_enum("direction", "hypothesis", "formula"),
    "decision": parse_enum("ready_to_test", "needs_clarification", "not_supported", "rejected"),
    "intent_summary": lambda value, path: parse_str(value, path, max_len=32768),
    "mechanism_type": parse_enum("causal", "risk_premium", "behavioral", "statistical"),
    "target": lambda value, path: parse_str(value, path, max_len=512),
    "expected_sign": parse_enum("positive", "negative", "unspecified"),
    "horizons": parse_array(lambda value, path: parse_int(value, path, minimum=1), max_len=64),
    "mechanism_steps": STRINGS,
    "alternatives": STRINGS,
    "falsification": STRINGS,
    "data_requirements": STRINGS,
    "known": STRINGS,
    "unknown": STRINGS,
    "citations": parse_array(CITATION, max_len=256),
    "candidate_refs": REFS,
    "agent_binding": AGENT_BINDING,
    "usage": USAGE,
    "question": nullable(lambda value, path: parse_str(value, path, max_len=32768)),
})

HYPOTHESIS_PROPOSAL = parse_object({
    "statement": lambda value, path: parse_str(value, path, min_len=1, max_len=32768),
    "expected_sign": parse_enum("positive", "negative", "unspecified"),
    "horizons": parse_array(lambda value, path: parse_int(value, path, minimum=1), max_len=64),
    "variables": parse_array(VARIABLE, max_len=256),
    "mechanism": lambda value, path: parse_str(value, path, max_len=32768),
    "falsification": STRINGS,
    "pending_questions": STRINGS,
    "input_ref": parse_ref,
})

FORMULA_PROPOSAL = parse_object({
    "hypothesis_ref": nullable(parse_ref),
    "expression": lambda value, path: parse_str(value, path, min_len=1, max_len=32768),
    "math_explanation": lambda value, path: parse_str(value, path, max_len=32768),
    "variables": parse_array(VARIABLE, max_len=256),
    "lookback_sessions": lambda value, path: parse_int(value, path, minimum=0),
    "signal_timing": parse_enum("session_close"),
    "expected_sign": parse_enum("positive", "negative", "unspecified"),
    "missing_policy": parse_enum("propagate_null"),
    "limitations": STRINGS,
})


def _ast(value: Any, path: str) -> dict:
    if not isinstance(value, dict):
        raise ContractError(path, "object_required", "expected an AST node")
    op = value.get("op")
    if op == "field":
        return parse_object({"op": parse_enum("field"),
                             "name": lambda raw, where: parse_str(raw, where, min_len=1, max_len=128)})(value, path)
    if op == "constant":
        return parse_object({"op": parse_enum("constant"), "value": parse_decimal_string})(value, path)
    if isinstance(op, str) and op.strip() and op not in ("field", "constant"):
        return parse_object({
            "op": lambda raw, where: parse_str(raw, where, min_len=1, max_len=64),
            "args": parse_array(_ast, max_len=64, min_len=1),
            "window": nullable(lambda raw, where: parse_int(raw, where, minimum=1)),
        })(value, path)
    raise ContractError(path, "invalid_ast", "op must be field, constant or a registered operator name")


FACTOR_DEFINITION = parse_object({
    "expression": lambda value, path: parse_str(value, path, min_len=1, max_len=32768),
    "ast": _ast,
    "operator_registry_ref": parse_ref,
    "field_contract_ref": parse_ref,
    "unit": lambda value, path: parse_str(value, path, min_len=1, max_len=64),
    "lookback_sessions": lambda value, path: parse_int(value, path, minimum=0),
    "signal_timing": parse_enum("session_close"),
    "parameters": parse_array(PARAMETER, max_len=256),
    "preprocessing_ref": nullable(parse_ref),
    "compiler_ref": parse_ref,
})


PREPARED_INPUT = parse_object({
    "request_ref": parse_ref,
    "snapshot_ref": parse_snapshot_ref,
    "axis_ref": parse_ref,
    "feature_parts": parse_array(FILE_PART, max_len=100000),
    "label_parts": parse_array(FILE_PART, max_len=100000),
    "membership_mask_parts": parse_array(FILE_PART, max_len=100000),
    "feature_validity_parts": parse_array(FILE_PART, max_len=100000),
    "label_validity_parts": parse_array(FILE_PART, max_len=100000),
    "availability_parts": parse_array(FILE_PART, max_len=100000),
    "exclusions_ref": parse_ref,
    "logical_input_digest": parse_digest,
    "checks": parse_array(CHECK, max_len=512),
    "limitations": STRINGS,
})

MODEL = parse_object({
    "model_spec_ref": parse_ref,
    "engine_binding_ref": parse_ref,
    "prepared_input_ref": parse_ref,
    "fold_id": parse_id,
    "feature_contract_ref": parse_ref,
    "preprocessing_state_ref": parse_ref,
    "label_ref": parse_ref,
    "fit_interval": INTERVAL,
    "validation_plan_ref": parse_ref,
    "weights": parse_array(FILE_PART, max_len=100000),
    "code_ref": parse_ref,
    "environment_ref": parse_ref,
    "seed": lambda value, path: parse_int(value, path, minimum=0, maximum=2 ** 63 - 1),
})

PREDICTION = parse_object({
    "model_ref": parse_ref,
    "prepared_input_ref": parse_ref,
    "fold_id": nullable(lambda value, path: parse_str(value, path, min_len=1, max_len=128)),
    "parts": parse_array(FILE_PART, max_len=100000),
    "signal_availability_parts": parse_array(FILE_PART, max_len=100000),
    "feature_contract_ref": parse_ref,
    "code_ref": parse_ref,
})


def _strategy(value: Any, path: str) -> dict:
    record = parse_object({
        "signal_kind": parse_enum("model", "factor_rule"),
        "model_ref": nullable(parse_ref),
        "factor_definition_refs": REFS,
        "signal_rule_ref": parse_ref,
        "portfolio_rule_ref": parse_ref,
        "risk_rule_ref": parse_ref,
    })(value, path)
    if record["signal_kind"] == "model" and record["model_ref"] is None:
        raise ContractError(path, "invalid_strategy", "model signal requires model_ref")
    if record["signal_kind"] == "factor_rule" and record["model_ref"] is not None:
        raise ContractError(path, "invalid_strategy", "factor_rule signal must not carry model_ref")
    return record


PAYLOAD_VALIDATORS: dict[str, Callable[[Any, str], dict]] = {
    "budget_policy": BUDGET_POLICY,
    "code_identity": CODE_IDENTITY,
    "environment": ENVIRONMENT,
    "capability_record": CAPABILITY_RECORD,
    "execution_evidence": EXECUTION_EVIDENCE,
    "feature_contract": FEATURE_CONTRACT,
    "label_definition": LABEL_DEFINITION,
    "sample_plan": SAMPLE_PLAN,
    "date_rule": DATE_RULE,
    "data_plan": DATA_PLAN,
    "data_definition": DATA_DEFINITION,
    "research_definition": _research_definition,
    "research_input": RESEARCH_INPUT,
    "research_workflow": _research_workflow,
    "human_decision": HUMAN_DECISION,
    "dataset_snapshot": DATASET_SNAPSHOT,
    "review": REVIEW,
    "hypothesis_proposal": HYPOTHESIS_PROPOSAL,
    "formula_proposal": FORMULA_PROPOSAL,
    "factor_definition": FACTOR_DEFINITION,
    "prepared_input": PREPARED_INPUT,
    "model": MODEL,
    "prediction": PREDICTION,
    "strategy": _strategy,
    "execution_policy": EXECUTION_POLICY,
}

ENVELOPE = parse_object({
    "artifact_id": parse_id,
    "artifact_type": lambda value, path: parse_str(value, path, min_len=1, max_len=128),
    "schema_version": lambda value, path: parse_int(value, path, minimum=1),
    "content_digest": parse_digest,
    "entity_id": nullable(parse_id),
    "created_at": parse_time,
    "producer": parse_object({
        "run_id": nullable(parse_id),
        "attempt_id": nullable(parse_id),
        "author_kind": parse_enum("user_authored", "agent_generated", "platform_computed", "imported"),
        "author_ref": nullable(lambda value, path: parse_str(value, path, max_len=256)),
    }),
    "parent_refs": parse_array(PARENT, max_len=64),
    "payload": lambda value, path: value if isinstance(value, dict) else _object_needed(path),
    "provenance": parse_object({
        "market_data_kind": nullable(lambda value, path: parse_str(value, path, max_len=128)),
        "source_class": nullable(lambda value, path: parse_str(value, path, max_len=128)),
        "evidence_refs": REFS,
        "limitations": STRINGS,
    }),
})


def parse_envelope(value: Any, path: str = "$",
                   validators: Mapping[str, Callable[[Any, str], dict]] | None = None) -> dict:
    """Validate the shared envelope and dispatch the payload to a frozen type."""
    registry = PAYLOAD_VALIDATORS if validators is None else validators
    envelope = ENVELOPE(value, path)
    envelope["payload"] = parse_payload(envelope["artifact_type"], envelope["payload"],
                                        f"{path}.payload", validators=registry)
    return envelope


def parse_payload(artifact_type: str, payload: Any, path: str = "$.payload",
                  validators: Mapping[str, Callable[[Any, str], dict]] | None = None) -> dict:
    """Validate one payload against its frozen type; unknown types are refused."""
    registry = PAYLOAD_VALIDATORS if validators is None else validators
    if not isinstance(payload, dict):
        raise ContractError(path, "object_required", "expected a JSON object")
    parser = registry.get(artifact_type)
    if parser is None:
        raise ContractError(path, "payload_schema_not_frozen",
                            f"artifact_type {artifact_type!r} has no frozen payload validator")
    return parser(payload, path)
