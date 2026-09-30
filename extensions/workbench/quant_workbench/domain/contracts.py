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
    artifact_type = envelope["artifact_type"]
    parser = registry.get(artifact_type)
    if parser is None:
        raise ContractError(f"{path}.payload", "payload_schema_not_frozen",
                            f"artifact_type {artifact_type!r} has no frozen payload validator")
    envelope["payload"] = parser(envelope["payload"], f"{path}.payload")
    return envelope
