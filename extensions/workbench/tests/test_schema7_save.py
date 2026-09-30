"""G1-2b save_revision head CAS, idempotency and the default snapshot pointer."""
import tempfile
import unittest
from pathlib import Path

from quant_workbench.adapters.storage import migrations
from quant_workbench.adapters.storage.schema7 import (Schema7Store, artifact_content_digest,
                                                      utc_now)
from quant_workbench.adapters.storage.storage import LocalResultRepository
from quant_workbench.domain.artifacts import ArtifactRef
from quant_workbench.domain.contracts import ContractError
from quant_workbench.domain.errors import (IdempotencyConflict, PreconditionFailed,
                                           RevisionConflict, VersionConflict)


def ref(artifact_id, artifact_type, digit="a", schema_version=1):
    return ArtifactRef(artifact_id, artifact_type, schema_version, "sha256:" + digit * 64)


def envelope(artifact_id, artifact_type, payload, schema_version=1):
    provenance = {"market_data_kind": None, "source_class": None, "evidence_refs": [],
                  "limitations": []}
    return {
        "artifact_id": artifact_id, "artifact_type": artifact_type,
        "schema_version": schema_version,
        "content_digest": artifact_content_digest(artifact_type, schema_version, [], payload,
                                                  provenance),
        "entity_id": None, "created_at": utc_now(),
        "producer": {"run_id": None, "attempt_id": None, "author_kind": "platform_computed",
                     "author_ref": None},
        "parent_refs": [], "payload": payload, "provenance": provenance,
    }


class Schema7SaveTests(unittest.TestCase):
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

    def input_payload(self, content="momentum should predict returns"):
        return {"experiment_id": self.experiment, "input_kind": "direction", "content": content,
                "language": "zh", "hypothesis_type": "unspecified", "market": "cn",
                "frequency": "day", "constraints": [], "attachments": [], "author": "user"}

    def save(self, key, payload=None, entity_id=None, expected=None):
        return self.store.save_revision(
            operation="POST /v1/research-inputs", idempotency_key=key,
            artifact_type="research_input", payload=payload or self.input_payload(),
            entity_id=entity_id, expected_revision=expected, display_name="input")

    def counts(self):
        conn = self.store._connect()
        try:
            names = ("entities", "artifacts", "commands", "pointers")
            return {name: int(conn.execute(f"SELECT count(*) FROM {name}").fetchone()[0])
                    for name in names}
        finally:
            conn.close()

    def test_new_save_creates_entity_and_artifact_then_replays(self):
        receipt = self.save("s1")
        self.assertTrue(receipt["created"])
        self.assertFalse(receipt["replayed"])
        self.assertEqual("research_input", receipt["artifact_ref"]["artifact_type"])
        conn = self.store._connect()
        try:
            entity = conn.execute("SELECT * FROM entities WHERE entity_id=?",
                                  (receipt["entity_id"],)).fetchone()
            self.assertEqual("research_input", entity["entity_kind"])
            self.assertEqual(self.experiment, entity["experiment_id"])
            self.assertEqual(receipt["artifact_ref"]["artifact_id"], entity["head_artifact_id"])
            self.assertEqual(1, entity["row_version"])
        finally:
            conn.close()
        replay = self.save("s1")
        self.assertFalse(replay["created"])
        self.assertTrue(replay["replayed"])
        self.assertEqual(receipt["entity_id"], replay["entity_id"])
        self.assertEqual(receipt["artifact_ref"], replay["artifact_ref"])
        self.assertEqual({"entities": 2, "artifacts": 1, "commands": 1, "pointers": 0},
                         self.counts())

    def test_same_key_different_payload_is_a_conflict(self):
        self.save("s1")
        with self.assertRaises(IdempotencyConflict):
            self.save("s1", payload=self.input_payload("another direction"))
        self.assertEqual(1, self.counts()["artifacts"])

    def test_update_requires_current_head_and_stale_cas_writes_nothing(self):
        first = self.save("s1")
        head = ArtifactRef(**first["artifact_ref"])
        second = self.save("s2", payload=self.input_payload("revised direction"),
                           entity_id=first["entity_id"], expected=head)
        self.assertFalse(second["created"])
        self.assertEqual(first["entity_id"], second["entity_id"])
        self.assertNotEqual(first["artifact_ref"]["artifact_id"], second["artifact_ref"]["artifact_id"])
        conn = self.store._connect()
        try:
            entity = conn.execute("SELECT head_artifact_id,row_version FROM entities WHERE entity_id=?",
                                  (first["entity_id"],)).fetchone()
            self.assertEqual(second["artifact_ref"]["artifact_id"], entity["head_artifact_id"])
            self.assertEqual(2, entity["row_version"])
        finally:
            conn.close()
        before = self.counts()
        with self.assertRaises(RevisionConflict):
            self.save("s3", payload=self.input_payload("third"), entity_id=first["entity_id"],
                      expected=head)
        self.assertEqual(before, self.counts())

    def test_update_without_expected_revision_is_rejected_before_writing(self):
        first = self.save("s1")
        with self.assertRaises(ValueError):
            self.save("s2", entity_id=first["entity_id"])
        with self.assertRaises(ValueError):
            self.save("s2", expected=ArtifactRef(**first["artifact_ref"]))

    def test_unregistered_or_invalid_payload_is_refused(self):
        with self.assertRaises(PreconditionFailed):
            self.store.save_revision(operation="POST /v1/rules", idempotency_key="r1",
                                     artifact_type="rule", payload={}, display_name="rule")
        with self.assertRaises(ContractError):
            self.store.save_revision(operation="POST /v1/research-inputs", idempotency_key="s9",
                                     artifact_type="research_input", payload={"experiment_id": "x"},
                                     display_name="input")
        self.assertEqual(0, self.counts()["artifacts"])

    def test_default_snapshot_pointer_cas(self):
        def snapshot_payload(candidate):
            return {"digest_scheme": "snapshot_manifest_v3",
                    "candidate_ref": ref(candidate, "candidate_data").as_dict(),
                    "quality_report_ref": ref("qr-" + candidate, "quality_report").as_dict(),
                    "raw_refs": [], "normalized_refs": [],
                    "field_contract_ref": ref("fc", "field_contract").as_dict(),
                    "calendar_ref": ref("cal", "calendar").as_dict(),
                    "membership_ref": ref("mem", "membership").as_dict(),
                    "availability_ref": ref("av", "availability").as_dict(),
                    "merge_policy_ref": ref("merge", "rule").as_dict(),
                    "cleaning_policy_ref": ref("clean", "rule").as_dict(),
                    "parts": [], "market": "cn", "frequency": "day", "timezone": "Asia/Shanghai",
                    "allowed_uses": [{"use": "exploratory_factor", "status": "limited",
                                      "reasons": ["fixture"]}]}
        first = self.store.save_artifact(envelope("snap1", "dataset_snapshot",
                                                  snapshot_payload("cand1"), schema_version=3))
        second = self.store.save_artifact(envelope("snap2", "dataset_snapshot",
                                                   snapshot_payload("cand2"), schema_version=3))
        self.assertNotEqual(first.artifact_id, second.artifact_id)
        view = self.store.set_default_snapshot(first, 0)
        self.assertEqual(1, view["row_version"])
        with self.assertRaises(VersionConflict):
            self.store.set_default_snapshot(second, 0)
        updated = self.store.set_default_snapshot(second, 1)
        self.assertEqual(2, updated["row_version"])
        conn = self.store._connect()
        try:
            row = conn.execute("SELECT artifact_id,row_version FROM pointers WHERE pointer_name=?",
                               ("default_research_snapshot",)).fetchone()
            self.assertEqual(second.artifact_id, row["artifact_id"])
            self.assertEqual(2, row["row_version"])
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
