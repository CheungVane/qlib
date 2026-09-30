"""G1 shared contract validators: strict JSON, scalars, Ref/Save and envelope."""
import unittest

from quant_workbench.domain import contracts as c


def ref(artifact_id="A1", artifact_type="research_definition", schema_version=1, digit="a"):
    return {"artifact_id": artifact_id, "artifact_type": artifact_type,
            "schema_version": schema_version, "content_digest": "sha256:" + digit * 64}


class StrictJsonTests(unittest.TestCase):
    def test_rejects_duplicate_keys_and_non_finite_numbers(self):
        for text in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}', '{"a":-Infinity}',
                     '{"a":1e999}', '[1,2]', 'not json'):
            with self.subTest(text=text), self.assertRaises(c.ContractError):
                c.loads_strict(text)

    def test_accepts_one_object_and_keeps_nested_duplicate_detection(self):
        self.assertEqual({"a": {"b": 1}}, c.loads_strict('{"a":{"b":1}}'))
        with self.assertRaisesRegex(c.ContractError, "duplicate"):
            c.loads_strict('{"a":{"b":1,"b":2}}')


class ScalarTests(unittest.TestCase):
    def test_identifiers_digests_times_dates(self):
        self.assertEqual("A1.b:c", c.parse_id("A1.b:c"))
        for bad in ("", "../x", "/tmp/x", "a" * 129, "a b"):
            with self.subTest(bad=bad), self.assertRaises(c.ContractError):
                c.parse_id(bad)
        self.assertEqual("sha256:" + "a" * 64, c.parse_digest("sha256:" + "a" * 64))
        for bad in ("sha256:" + "A" * 64, "latest", "sha256:" + "a" * 63):
            with self.subTest(bad=bad), self.assertRaises(c.ContractError):
                c.parse_digest(bad)
        self.assertEqual("2026-09-30T00:00:00.000Z", c.parse_time("2026-09-30T00:00:00.000Z"))
        for bad in ("2026-09-30T00:00:00Z", "2026-02-30T00:00:00.000Z", "2026-09-30"):
            with self.subTest(bad=bad), self.assertRaises(c.ContractError):
                c.parse_time(bad)
        self.assertEqual("2026-09-30", c.parse_date("2026-09-30"))
        for bad in ("2026-2-3", "2026-02-30", "20260930"):
            with self.subTest(bad=bad), self.assertRaises(c.ContractError):
                c.parse_date(bad)

    def test_canonical_decimal_strings(self):
        for good in ("0", "10", "-0.5", "1.25", "0.0001"):
            self.assertEqual(good, c.parse_decimal_string(good))
        for bad in ("01", "1.0", "1.", "-0", "1e2", "+1", ".5", "1.10"):
            with self.subTest(bad=bad), self.assertRaises(c.ContractError):
                c.parse_decimal_string(bad)

    def test_integer_rejects_boolean_and_float(self):
        self.assertEqual(1, c.parse_int(1, minimum=1))
        for bad in (True, 1.0, "1"):
            with self.subTest(bad=bad), self.assertRaises(c.ContractError):
                c.parse_int(bad)
        with self.assertRaises(c.ContractError):
            c.parse_int(0, minimum=1)


class SaveAndRefTests(unittest.TestCase):
    def save(self, **changes):
        value = {"entity_id": None, "expected_revision": None, "display_name": "experiment",
                 "artifact_type": "research_definition", "payload": {}, "parent_refs": []}
        value.update(changes)
        return value

    def test_save_identity_and_parent_ordinals(self):
        self.assertIsNone(c.parse_save(self.save())["entity_id"])
        with self.assertRaises(c.ContractError):
            c.parse_save(self.save(entity_id="E1"))
        parent = {"role": "input", "ordinal": 1, "ref": ref()}
        with self.assertRaises(c.ContractError):
            c.parse_save(self.save(parent_refs=[parent]))
        self.assertEqual(1, len(c.parse_save(self.save(parent_refs=[
            {"role": "input", "ordinal": 0, "ref": ref()}]) )["parent_refs"]))

    def test_save_rejects_unknown_fields_and_bad_payload(self):
        with self.assertRaises(c.ContractError):
            c.parse_save(self.save(extra=1))
        with self.assertRaises(c.ContractError):
            c.parse_save(self.save(payload="not-object"))

    def test_ref_mismatch_is_not_an_id_match(self):
        c.assert_same_ref(ref(), ref())
        with self.assertRaises(c.ContractError) as caught:
            c.assert_same_ref(ref(), ref(digit="b"))
        self.assertEqual("reference_mismatch", caught.exception.rule)

    def test_unpublished_reference_is_refused_by_the_storage_callback(self):
        with self.assertRaises(c.ContractError) as caught:
            c.require_published(ref(), lambda parsed: False)
        self.assertEqual("unpublished_reference", caught.exception.rule)
        self.assertEqual(ref(), c.require_published(ref(), lambda parsed: True))
        with self.assertRaises(c.ContractError):
            c.require_published(ref(), None)


class EnvelopeTests(unittest.TestCase):
    def envelope(self, artifact_type="budget_policy", payload=None, **changes):
        value = {
            "artifact_id": "A1", "artifact_type": artifact_type, "schema_version": 1,
            "content_digest": "sha256:" + "a" * 64, "entity_id": None,
            "created_at": "2026-09-30T00:00:00.000Z",
            "producer": {"run_id": None, "attempt_id": None, "author_kind": "platform_computed",
                         "author_ref": None},
            "parent_refs": [],
            "payload": payload if payload is not None else {
                "limits": {"max_hypotheses": 3, "max_formulas_per_hypothesis": 3,
                           "max_numerical_evaluations": 3, "max_agent_attempts": 13,
                           "max_agent_calls": 26},
                "previous_policy_ref": None, "decision_ref": None},
            "provenance": {"market_data_kind": None, "source_class": None,
                           "evidence_refs": [], "limitations": []},
        }
        value.update(changes)
        return value

    def test_frozen_payload_passes_and_unknown_payload_is_refused(self):
        self.assertEqual("budget_policy", c.parse_envelope(self.envelope())["artifact_type"])
        with self.assertRaises(c.ContractError) as caught:
            c.parse_envelope(self.envelope(artifact_type="model_spec", payload={}))
        self.assertEqual("payload_schema_not_frozen", caught.exception.rule)

    def test_payload_unknown_field_and_missing_envelope_field(self):
        payload = self.envelope()["payload"] | {"unexpected": 1}
        with self.assertRaises(c.ContractError) as caught:
            c.parse_envelope(self.envelope(payload=payload))
        self.assertEqual("unknown_field", caught.exception.rule)
        value = self.envelope()
        del value["provenance"]
        with self.assertRaises(c.ContractError) as caught:
            c.parse_envelope(value)
        self.assertEqual("missing_field", caught.exception.rule)


class PayloadRegistryTests(unittest.TestCase):
    def test_prepared_model_prediction_and_strategy_payloads(self):
        snapshot = {"artifact_id": "S1", "artifact_type": "dataset_snapshot", "schema_version": 3,
                    "content_digest": "sha256:" + "c" * 64}
        prepared = {"request_ref": ref(), "snapshot_ref": snapshot, "axis_ref": ref(),
                    "feature_parts": [], "label_parts": [], "membership_mask_parts": [],
                    "feature_validity_parts": [], "label_validity_parts": [],
                    "availability_parts": [], "exclusions_ref": ref(),
                    "logical_input_digest": "sha256:" + "d" * 64, "checks": [], "limitations": []}
        c.parse_payload("prepared_input", prepared)
        model = {"model_spec_ref": ref(), "engine_binding_ref": ref(), "prepared_input_ref": ref(),
                 "fold_id": "fold1", "feature_contract_ref": ref(), "preprocessing_state_ref": ref(),
                 "label_ref": ref(), "fit_interval": {"start": "2020-01-01", "end": "2020-12-31"},
                 "validation_plan_ref": ref(), "weights": [], "code_ref": ref(),
                 "environment_ref": ref(), "seed": 1}
        c.parse_payload("model", model)
        prediction = {"model_ref": ref(), "prepared_input_ref": ref(), "fold_id": None, "parts": [],
                      "signal_availability_parts": [], "feature_contract_ref": ref(), "code_ref": ref()}
        c.parse_payload("prediction", prediction)
        rule = {"signal_kind": "factor_rule", "model_ref": None, "factor_definition_refs": [ref()],
                "signal_rule_ref": ref(), "portfolio_rule_ref": ref(), "risk_rule_ref": ref()}
        c.parse_payload("strategy", rule)
        with self.assertRaises(c.ContractError):
            c.parse_payload("strategy", rule | {"model_ref": ref()})
        with self.assertRaises(c.ContractError):
            c.parse_payload("strategy", {"signal_kind": "model", "model_ref": None,
                                         "factor_definition_refs": [], "signal_rule_ref": ref(),
                                         "portfolio_rule_ref": ref(), "risk_rule_ref": ref()})


if __name__ == "__main__":
    unittest.main()
