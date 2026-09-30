"""G1-2c: agent/proposal validators plus at-most-once workflow edges and trial events."""
import queue
import tempfile
import threading
import unittest
from pathlib import Path

from quant_workbench.adapters.storage import migrations
from quant_workbench.adapters.storage.schema7 import Schema7Store, artifact_content_digest, utc_now
from quant_workbench.adapters.storage.storage import LocalResultRepository
from quant_workbench.domain.artifacts import ArtifactRef
from quant_workbench.domain.errors import IdempotencyConflict


def ref(artifact_id, artifact_type, digit="a"):
    return ArtifactRef(artifact_id, artifact_type, 1, "sha256:" + digit * 64)


def envelope(artifact_id, artifact_type, payload):
    provenance = {"market_data_kind": None, "source_class": None, "evidence_refs": [],
                  "limitations": []}
    return {"artifact_id": artifact_id, "artifact_type": artifact_type, "schema_version": 1,
            "content_digest": artifact_content_digest(artifact_type, 1, [], payload, provenance),
            "entity_id": None, "created_at": utc_now(),
            "producer": {"run_id": None, "attempt_id": None, "author_kind": "agent_generated",
                         "author_ref": "agent"},
            "parent_refs": [], "payload": payload, "provenance": provenance}


def agent_binding():
    return {"agent_id": "rdagent", "adapter_version": "1", "model_id": "deepseek",
            "model_version": None, "prompt_ref": ref("prompt", "rule").as_dict(),
            "output_schema_version": 1, "capabilities": ["factor_review"], "allowed_tools": []}


class Schema7LedgerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.root = self.base / "store"
        LocalResultRepository(self.root)
        migrations.migrate(self.root, self.base / "backup.sqlite3")
        self.store = Schema7Store(self.root)
        self.experiment = self.store.save_experiment("experiment")

    def tearDown(self):
        self._tmp.cleanup()

    def counts(self, table):
        conn = self.store._connect()
        try:
            return int(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
        finally:
            conn.close()

    def workflow_fixture(self):
        payload = {"experiment_id": self.experiment,
                   "input_ref": ref("input", "research_input").as_dict(),
                   "entry_kind": "direction_review", "mode": "assisted", "snapshot_ref": None,
                   "protocol_ref": None, "reference_set_ref": None, "agent_binding": agent_binding(),
                   "budget_policy_ref": ref("budget", "budget_policy").as_dict(),
                   "stop_after": "review", "selection_rule": "feasibility_then_source_order",
                   "code_ref": ref("code", "code_identity").as_dict()}
        artifact = self.store.save_artifact(envelope("wfa", "research_workflow", payload))
        conn = self.store._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            now = utc_now()
            conn.execute("INSERT INTO entities(entity_id,entity_kind,experiment_id,display_name,"
                         "description,head_artifact_id,row_version,created_at,updated_at) "
                         "VALUES('wf-entity','research_workflow',?,?, '',?,0,?,?)",
                         (self.experiment, "wf", artifact.artifact_id, now, now))
            conn.execute("INSERT INTO workflow_instances(workflow_id,workflow_revision_id,enabled,"
                         "row_version,created_at) VALUES('wf-entity',?,1,0,?)",
                         (artifact.artifact_id, now))
            for run_id in ("child-run", "child-run-2"):
                conn.execute("INSERT INTO runs(run_id,origin,created_at) VALUES(?,'imported',?)",
                             (run_id, now))
            conn.execute("COMMIT")
        finally:
            conn.close()
        return artifact

    def test_review_proposal_and_factor_payloads_are_closed(self):
        review = {"input_ref": ref("input", "research_input").as_dict(), "review_kind": "direction",
                  "decision": "ready_to_test", "intent_summary": "momentum",
                  "mechanism_type": "causal", "target": "forward return",
                  "expected_sign": "positive", "horizons": [1, 5], "mechanism_steps": ["demand"],
                  "alternatives": [], "falsification": ["no IC"], "data_requirements": ["close"],
                  "known": [], "unknown": [], "citations": [], "candidate_refs": [],
                  "agent_binding": agent_binding(),
                  "usage": {"calls": 1, "tokens_in": None, "tokens_out": None,
                            "cost_decimal": None, "currency": None, "measurement": "unknown"},
                  "question": None}
        self.store.save_artifact(envelope("review1", "review", review))
        factor = {"expression": "close", "ast": {"op": "field", "name": "close"},
                  "operator_registry_ref": ref("ops", "operator_registry").as_dict(),
                  "field_contract_ref": ref("fc", "feature_contract").as_dict(), "unit": "price",
                  "lookback_sessions": 0, "signal_timing": "session_close", "parameters": [],
                  "preprocessing_ref": None, "compiler_ref": ref("comp", "compiler_identity").as_dict()}
        self.store.save_artifact(envelope("factor1", "factor_definition", factor))
        self.assertEqual(2, self.counts("artifacts"))

    def test_workflow_edge_is_at_most_once(self):
        artifact = self.workflow_fixture()
        first = self.store.record_workflow_edge(
            workflow_id="wf-entity", workflow_revision_ref=artifact, parent_ref=artifact,
            child_kind="hypothesis_review", child_run_id="child-run")
        self.assertTrue(first["created"])
        again = self.store.record_workflow_edge(
            workflow_id="wf-entity", workflow_revision_ref=artifact, parent_ref=artifact,
            child_kind="hypothesis_review", child_run_id="child-run")
        self.assertFalse(again["created"])
        self.assertTrue(again["replayed"])
        self.assertEqual(1, self.counts("workflow_edges"))

    def test_concurrent_duplicate_edge_admits_once(self):
        artifact = self.workflow_fixture()
        barrier = threading.Barrier(2)
        results = queue.Queue()

        def worker():
            try:
                store = Schema7Store(self.root)
                barrier.wait(timeout=10)
                results.put(store.record_workflow_edge(
                    workflow_id="wf-entity", workflow_revision_ref=artifact, parent_ref=artifact,
                    child_kind="formula_evaluate", child_run_id="child-run-2"))
            except Exception as exc:  # noqa: BLE001
                results.put(exc)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        outcome = [results.get() for _ in range(2)]
        created = [item for item in outcome if isinstance(item, dict) and item["created"]]
        replayed = [item for item in outcome if isinstance(item, dict) and item["replayed"]]
        self.assertEqual(1, len(created), outcome)
        self.assertEqual(1, len(replayed), outcome)
        self.assertEqual(1, self.counts("workflow_edges"))

    def test_trial_event_is_at_most_once_and_idempotent(self):
        candidate = self.store.save_artifact(envelope("cand", "formula_proposal", {
            "hypothesis_ref": None, "expression": "close", "math_explanation": "x",
            "variables": [], "lookback_sessions": 0, "signal_timing": "session_close",
            "expected_sign": "unspecified", "missing_policy": "propagate_null", "limitations": []}))
        first = self.store.record_trial_event(event_id="e1", experiment_id=self.experiment,
                                              candidate_ref=candidate,
                                              event_kind="candidate_registered",
                                              details={"ordinal": 1})
        self.assertTrue(first["created"])
        again = self.store.record_trial_event(event_id="e1", experiment_id=self.experiment,
                                             candidate_ref=candidate,
                                             event_kind="candidate_registered",
                                             details={"ordinal": 1})
        self.assertTrue(again["replayed"])
        with self.assertRaises(IdempotencyConflict):
            self.store.record_trial_event(event_id="e1", experiment_id=self.experiment,
                                          candidate_ref=candidate,
                                          event_kind="candidate_registered",
                                          details={"ordinal": 2})
        self.assertEqual(1, self.counts("trial_events"))


if __name__ == "__main__":
    unittest.main()
