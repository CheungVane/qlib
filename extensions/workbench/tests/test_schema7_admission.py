"""G1-2 schema7 admission slice: one transaction, idempotency, slots and budget."""
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from quant_workbench.adapters.storage import migrations
from quant_workbench.adapters.storage.schema7 import (Schema7Store, Schema7VersionError,
                                                      artifact_content_digest, utc_now)
from quant_workbench.adapters.storage.storage import LocalResultRepository
from quant_workbench.domain.admission import (AdmissionCommand, AdmissionRequest, EntryPoint,
                                              PreparedAdmission)
from quant_workbench.domain.artifacts import ArtifactRef
from quant_workbench.domain.errors import (BudgetExhausted, CapacityExceeded, IdempotencyConflict,
                                           LedgerScopeMissing, PlanExpired, ReferenceMismatch)
from quant_workbench.domain.workflows import WorkflowKind, workflow_plan


def ref(artifact_id, artifact_type, digit="a"):
    return ArtifactRef(artifact_id, artifact_type, 1, "sha256:" + digit * 64)


def envelope(artifact_id, artifact_type, payload, sibling=None):
    parent_refs = []
    if sibling is not None:
        parent_refs = [{"role": "parent", "ordinal": 0, "ref": sibling}]
    provenance = {"market_data_kind": None, "source_class": None, "evidence_refs": [],
                  "limitations": []}
    return {
        "artifact_id": artifact_id, "artifact_type": artifact_type, "schema_version": 1,
        "content_digest": artifact_content_digest(artifact_type, 1, parent_refs, payload, provenance),
        "entity_id": None, "created_at": utc_now(),
        "producer": {"run_id": None, "attempt_id": None, "author_kind": "platform_computed",
                     "author_ref": None},
        "parent_refs": parent_refs, "payload": payload, "provenance": provenance,
    }


def policy_payload(max_concurrent):
    return {"max_concurrent": max_concurrent, "timeout_seconds": 3600,
            "terminate_grace_seconds": 10, "cpu_seconds": 3600, "memory_bytes": 2147483648,
            "enforce": ["cpu", "memory"],
            "agent_budget": {"max_trials": 2, "max_calls": 10, "scope": "policy_revision"}}


def train_definition_payload():
    inputs = {"preparation_ref": ref("prep", "prepared_input").as_dict(),
              "feature_refs": [], "validation_plan_ref": ref("val", "validation_plan").as_dict(),
              "preprocessing_ref": ref("pp", "preprocessing_state").as_dict(),
              "engine_binding_ref": ref("eng", "engine_binding").as_dict(),
              "model_spec_ref": ref("spec", "model_spec").as_dict(),
              "evaluation_protocol_ref": ref("proto", "evaluation_protocol").as_dict(),
              "selection_evidence_refs": []}
    return {"experiment_id": "exp", "workflow_kind": "train", "inputs": inputs, "seed": 1,
            "code_ref": ref("code", "code_identity").as_dict()}


def data_definition_payload():
    return {"market": "cn", "frequency": "day", "timezone": "Asia/Shanghai",
            "universe_ref": ref("uni", "membership").as_dict(),
            "date_rule": {"kind": "absolute", "start": "2015-01-05", "end": "2026-09-24"},
            "components": [{"component": "bar", "fields": ["close"], "required": True}],
            "source_bindings": [{"source_id": "finv", "capability_ref": ref("cap", "capability_record").as_dict(),
                                 "component": "bar", "field_group": "ohlcv", "role": "primary",
                                 "priority": 0, "required": True, "fallback_allowed": False}],
            "acquisition_mode": "registered_import", "update_mode": "full",
            "revision_policy_ref": ref("rev", "rule").as_dict(),
            "merge_policy_ref": ref("merge", "rule").as_dict(),
            "cleaning_policy_ref": ref("clean", "rule").as_dict(),
            "quality_policy_ref": ref("quality", "rule").as_dict(),
            "resource_policy_ref": ref("res", "data_resource_policy").as_dict(),
            "output_schema_version": 3}


class Schema7AdmissionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.root = self.base / "store"
        LocalResultRepository(self.root)
        migrations.migrate(self.root, self.base / "backup.sqlite3")
        self.store = Schema7Store(self.root)
        self.policy = self.store.save_artifact(
            envelope("policy", "execution_policy", policy_payload(1)))
        self.experiment = self.store.save_experiment("experiment")
        self.definition = self.store.save_artifact(
            envelope("def", "research_definition", train_definition_payload()))

    def tearDown(self):
        self._tmp.cleanup()

    def research_request(self, key, definition=None, policy=None, run_id=None):
        definition, policy = definition or self.definition, policy or self.policy
        entry = EntryPoint.RETRY if run_id else EntryPoint.RESEARCH
        command = AdmissionCommand(entry, definition, policy, key, run_id=run_id)
        prepared = PreparedAdmission(WorkflowKind.TRAIN, self.experiment, definition)
        return AdmissionRequest(command, prepared, workflow_plan(WorkflowKind.TRAIN))

    def counts(self):
        conn = self.store._connect()
        try:
            names = ("runs", "attempts", "stages", "resource_leases", "attempt_events", "commands")
            return {name: int(conn.execute(f"SELECT count(*) FROM {name}").fetchone()[0])
                    for name in names}
        finally:
            conn.close()

    def test_schema7_store_refuses_schema6(self):
        plain = self.base / "schema6"
        LocalResultRepository(plain)
        with self.assertRaises(Schema7VersionError):
            Schema7Store(plain)

    def test_admission_commits_run_attempt_stages_lease_event_and_receipt(self):
        request = self.research_request("k1")
        receipt = self.store.admit_run(request)
        self.assertTrue(receipt.created)
        self.assertEqual(1, receipt.attempt_no)
        self.assertEqual(1, self.counts()["runs"])
        self.assertEqual(1, self.counts()["attempts"])
        self.assertEqual(len(workflow_plan(WorkflowKind.TRAIN).steps), self.counts()["stages"])
        self.assertEqual(1, self.store.open_lease_count())
        self.assertEqual(1, self.counts()["attempt_events"])
        attempt = self.store.attempt_row(receipt.attempt_id)
        self.assertEqual("queued", attempt["status"])
        self.assertEqual(receipt.run_id, attempt["run_id"])
        self.assertTrue(attempt["launch_token"])
        replay = self.store.replay(request.command)
        self.assertFalse(replay.created)
        self.assertEqual(receipt.run_id, replay.run_id)
        self.assertEqual(receipt.attempt_id, replay.attempt_id)

    def test_same_key_different_payload_is_a_conflict_and_does_not_admit(self):
        self.store.admit_run(self.research_request("k1"))
        other = self.store.save_artifact(envelope("policy2", "execution_policy", policy_payload(2)))
        with self.assertRaises(IdempotencyConflict):
            self.store.admit_run(self.research_request("k1", policy=other))
        self.assertEqual(1, self.counts()["runs"])

    def test_concurrency_slot_blocks_until_released(self):
        first = self.store.admit_run(self.research_request("k1"))
        with self.assertRaises(CapacityExceeded) as caught:
            self.store.admit_run(self.research_request("k2"))
        self.assertEqual(1, caught.exception.as_details()["limit"])
        self.assertEqual(1, self.store.release_lease(first.attempt_id))
        second = self.store.admit_run(self.research_request("k2"))
        self.assertNotEqual(first.run_id, second.run_id)

    def test_independent_connections_race_for_the_last_slot(self):
        barrier = threading.Barrier(2)
        results = queue.Queue()

        def worker(key):
            try:
                store = Schema7Store(self.root)
                barrier.wait(timeout=10)
                results.put(("ok", store.admit_run(self.research_request(key)).run_id))
            except Exception as exc:  # noqa: BLE001 - the test asserts the exact class below
                results.put(("error", exc))

        threads = [threading.Thread(target=worker, args=(f"race{i}",)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        outcome = [results.get() for _ in range(2)]
        self.assertEqual(1, len([item for item in outcome if item[0] == "ok"]), outcome)
        errors = [item[1] for item in outcome if item[0] == "error"]
        self.assertEqual(1, len(errors), outcome)
        self.assertIsInstance(errors[0], CapacityExceeded)
        self.assertEqual(1, self.store.open_lease_count())

    def test_reserve_usage_is_atomic_idempotent_and_never_overdraws(self):
        scope = f"global:{self.policy.artifact_id}"
        self.store.set_budget_scope(scope, "calls", self.policy, 3)
        first = self.store.reserve_usage("call-1", None, [{"scope_id": scope, "dimension": "calls", "amount": 2}])
        self.assertEqual(2, first["items"][0]["used"])
        replay = self.store.reserve_usage("call-1", None, [{"scope_id": scope, "dimension": "calls", "amount": 2}])
        self.assertEqual(2, replay["items"][0]["used"])
        with self.assertRaises(IdempotencyConflict):
            self.store.reserve_usage("call-1", None, [{"scope_id": scope, "dimension": "calls", "amount": 1}])
        self.store.reserve_usage("call-2", None, [{"scope_id": scope, "dimension": "calls", "amount": 1}])
        with self.assertRaises(BudgetExhausted):
            self.store.reserve_usage("call-3", None, [{"scope_id": scope, "dimension": "calls", "amount": 1}])
        self.assertEqual(3, self.store.reserve_usage(
            "call-2", None, [{"scope_id": scope, "dimension": "calls", "amount": 1}])["items"][0]["used"])
        with self.assertRaises(LedgerScopeMissing):
            self.store.reserve_usage("call-4", None, [{"scope_id": "absent", "dimension": "calls", "amount": 1}])

    def test_independent_connections_race_for_the_last_budget_unit(self):
        scope = f"global:{self.policy.artifact_id}"
        self.store.set_budget_scope(scope, "calls", self.policy, 1)
        barrier = threading.Barrier(2)
        results = queue.Queue()

        def worker(key):
            try:
                store = Schema7Store(self.root)
                barrier.wait(timeout=10)
                results.put(("ok", store.reserve_usage(key, None,
                                                       [{"scope_id": scope, "dimension": "calls", "amount": 1}])))
            except Exception as exc:  # noqa: BLE001
                results.put(("error", exc))

        threads = [threading.Thread(target=worker, args=(f"budget-{i}",)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        outcome = [results.get() for _ in range(2)]
        self.assertEqual(1, len([item for item in outcome if item[0] == "ok"]), outcome)
        errors = [item[1] for item in outcome if item[0] == "error"]
        self.assertEqual(1, len(errors), outcome)
        self.assertIsInstance(errors[0], BudgetExhausted)

    def test_every_write_point_fault_rolls_back_completely(self):
        request = self.research_request("fault")
        methods = ["_insert_run", "_insert_attempt", "_insert_stages", "_acquire_lease",
                   "_insert_event", "_insert_command"]
        for name in methods:
            with self.subTest(point=name):
                with patch.object(self.store, name, side_effect=RuntimeError(name)):
                    with self.assertRaises(RuntimeError):
                        self.store.admit_run(request)
                self.assertEqual({key: 0 for key in self.counts()}, self.counts())

    def test_before_commit_hook_rolls_back(self):
        def explode():
            raise RuntimeError("before commit")

        hooked = Schema7Store(self.root, before_commit=explode)
        with self.assertRaises(RuntimeError):
            hooked.admit_run(self.research_request("hook"))
        self.assertEqual({key: 0 for key in self.counts()}, self.counts())

    def test_expired_plan_and_wrong_digest_are_refused(self):
        data_definition = self.store.save_artifact(
            envelope("ddef", "data_definition", data_definition_payload()))
        past = "2026-09-01T00:00:00.000Z"
        plan_payload = {"definition_ref": data_definition.as_dict(),
                        "date_range": {"start": "2015-01-05", "end": "2026-09-24"},
                        "universe_ref": ref("uni", "membership").as_dict(),
                        "calendar_ref": ref("cal", "calendar").as_dict(),
                        "source_plans": [], "base_snapshot_ref": None,
                        "estimated_chunks": None, "estimated_bytes": None, "estimated_rows": None,
                        "checks": [], "created_at": "2026-08-01T00:00:00.000Z", "expires_at": past}
        plan = self.store.save_artifact(envelope("plan", "data_plan", plan_payload))
        command = AdmissionCommand(EntryPoint.DATA, plan, self.policy, "data-1")
        request = AdmissionRequest(command, PreparedAdmission(WorkflowKind.DATA_PREPARE, None,
                                                              data_definition, plan),
                                   workflow_plan(WorkflowKind.DATA_PREPARE))
        with self.assertRaises(PlanExpired):
            self.store.admit_run(request)
        bad = ArtifactRef(plan.artifact_id, plan.artifact_type, plan.schema_version,
                          "sha256:" + "b" * 64)
        with self.assertRaises(ReferenceMismatch):
            self.store.resolve_ref(bad)

    def test_retry_reuses_run_and_increments_attempt_number(self):
        first = self.store.admit_run(self.research_request("k1"))
        with self.assertRaises(Exception) as caught:
            self.store.admit_run(self.research_request("k2", run_id=first.run_id))
        self.assertEqual("retry_not_allowed", getattr(caught.exception, "code", None))
        conn = self.store._connect()
        try:
            conn.execute("UPDATE attempts SET end_confirmed_at=? WHERE attempt_id=?",
                         (utc_now(), first.attempt_id))
            conn.execute("UPDATE resource_leases SET released_at=? WHERE attempt_id=?",
                         (utc_now(), first.attempt_id))
        finally:
            conn.close()
        retry = self.store.admit_run(self.research_request("k2", run_id=first.run_id))
        self.assertEqual(first.run_id, retry.run_id)
        self.assertEqual(2, retry.attempt_no)
        self.assertEqual(1, self.counts()["runs"])
        self.assertEqual(2, self.counts()["attempts"])

    def test_execution_service_uses_the_real_store_as_managed_admission(self):
        from unittest.mock import Mock

        from quant_workbench.domain.admission import AdmissionCommand, EntryPoint, PreparedAdmission
        from quant_workbench.services.execution import ExecutionService
        from quant_workbench.services.research_runs import ResearchRunService

        preflight = Mock()
        preflight.prepare_admission.return_value = PreparedAdmission(
            WorkflowKind.TRAIN, self.experiment, self.definition)
        service = ExecutionService(Mock(), executors=[], policy=object(),
                                   managed_admission=self.store, managed_preflight=preflight)
        command = AdmissionCommand(EntryPoint.RESEARCH, self.definition, self.policy, "svc-1")
        receipt = ResearchRunService(service).start(command)
        self.assertTrue(receipt.created)
        self.assertEqual(1, self.counts()["runs"])
        self.assertEqual(1, preflight.prepare_admission.call_count)
        replayed = ResearchRunService(service).start(command)
        self.assertFalse(replayed.created)
        self.assertEqual(1, preflight.prepare_admission.call_count)


if __name__ == "__main__":
    unittest.main()
