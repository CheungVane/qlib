"""T06 interface draft: identity, reuse contract and ledger rules (RESEARCH_LIFECYCLE §2)."""

import unittest

from quant_workbench import research_lifecycle as rl


def definition(**overrides):
    payload = {"definition_id": "D1", "dataset_snapshot": {"version": "v1"},
               "universe": {"pool": "csi500"}, "features": {"set": "mom"},
               "label": {"horizon": 5}, "validation_plan": {"splits": 5},
               "model": {"kind": "lgbm", "params": {"n": 10}}, "portfolio": {"top": 50},
               "execution_scenario": {"fees": "cn"}, "evaluation": {"window": "2026"},
               "seed": 7, "code": {"commit": "abc"}}
    payload.update(overrides)
    return payload


class DefinitionTests(unittest.TestCase):
    def test_digest_is_stable_and_identity_relevant(self):
        first = rl.ExperimentDefinitionRevision.build(definition())
        self.assertEqual(first.content_digest, rl.ExperimentDefinitionRevision.build(definition()).content_digest)
        changed = rl.ExperimentDefinitionRevision.build(definition(seed=8))
        self.assertNotEqual(first.content_digest, changed.content_digest)

    def test_missing_fields_and_unsafe_ids_are_rejected(self):
        payload = definition()
        payload.pop("label")
        with self.assertRaises(rl.LifecycleError):
            rl.ExperimentDefinitionRevision.build(payload)
        with self.assertRaises(rl.LifecycleError):
            rl.ExperimentDefinitionRevision.build(definition(definition_id="../escape"))

    def test_repeat_classification(self):
        base = definition()
        self.assertEqual(rl.classify_repeat(base, definition()), "retry_same_definition")
        self.assertEqual(rl.classify_repeat(base, definition(seed=9)), "new_definition_revision")
        self.assertEqual(rl.classify_repeat(base, definition(features={"set": "rev"})),
                         "new_definition_revision")

    def test_retry_requires_a_confirmed_end(self):
        self.assertEqual(rl.is_retry_allowed("failed", False), (True, "ok"))
        self.assertEqual(rl.is_retry_allowed("succeeded", True),
                         (False, "previous_attempt_not_terminal_or_successful"))
        self.assertEqual(rl.is_retry_allowed("interrupted", False),
                         (False, "old_process_not_confirmed_ended"))


class ModelAndStrategyTests(unittest.TestCase):
    def model(self, **overrides):
        payload = {"model_id": "M1", "features": ["a", "b"], "preprocessing": {"mean": 0},
                   "label": {"horizon": 5}, "train_window": {"start": "2025-01"},
                   "validation_plan": {"splits": 5}, "code_environment": {"python": "3.14"},
                   "seed": 7, "source_run_id": "R1", "source_attempt_id": "A1"}
        payload.update(overrides)
        return payload

    def test_reuse_requires_the_full_input_contract(self):
        model = rl.ModelArtifactVersion.build(self.model())
        ok, reason = model.accepts({"features": ["a", "b"], "preprocessing": {"mean": 0},
                                    "label": {"horizon": 5}})
        self.assertTrue(ok, reason)
        bad, reason = model.accepts({"features": ["a"], "preprocessing": {"mean": 0},
                                     "label": {"horizon": 5}})
        self.assertFalse(bad)
        self.assertEqual(reason, "input_contract_mismatch:features")

    def test_strategy_can_be_rule_based_without_a_model(self):
        strategy = rl.StrategyVersion.build({
            "strategy_id": "S1", "signal": {"rule": "momentum"}, "portfolio_rules": {"top": 30},
            "risk_limits": {"dd": 0.3}, "execution_assumption": {"t_plus": 1},
            "future_data_contract": {"frequency": "daily"}})
        self.assertIsNone(strategy.model_ref)
        self.assertTrue(strategy.content_digest.startswith("sha256:"))


class LedgerTests(unittest.TestCase):
    def test_ledger_keeps_failures_and_counts_retries_in_one_trial(self):
        entry = rl.TrialLedgerEntry(trial_id="T1", search_scope_id="scope-1", status="failed")
        entry.note_attempt("A1")
        entry.note_attempt("A2")
        entry.note_attempt("A2")
        self.assertEqual(entry.attempt_ids, ["A1", "A2"])
        entry.note_test_access("selected_on_final_test")
        self.assertEqual(entry.as_dict()["test_set_access"], ["selected_on_final_test"])
        self.assertTrue(entry.as_dict()["ledger_snapshot_id"].startswith("sha256:"))

    def test_unknown_status_and_blank_reason_are_rejected(self):
        with self.assertRaises(rl.LifecycleError):
            rl.TrialLedgerEntry(trial_id="T1", search_scope_id="s", status="done")
        entry = rl.TrialLedgerEntry(trial_id="T1", search_scope_id="s", status="pending")
        with self.assertRaises(rl.LifecycleError):
            entry.note_test_access("")


if __name__ == "__main__":
    unittest.main()
