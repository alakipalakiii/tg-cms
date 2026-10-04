from __future__ import annotations

import copy
import json
import sys
import tempfile
import uuid
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from publisher import artifact_contract as c
from publisher import artifact_transport as transport


TX = {"worker": "synthetic-worker", "content_revision": 19,
      "logical_transaction_id": c.logical_transaction_id("synthetic-worker", 19)}
SOURCE = "a" * 40
SHA = "b" * 64


def artifact():
    return c.seal_artifact({
        "artifact_type": "admission_receipt", "schema_version": c.SCHEMA_VERSION,
        "artifact_id": str(uuid.uuid4()), "created_at": "2026-09-28T00:00:00+00:00",
        "producer": {"workflow_run_id": "synthetic-run", "run_attempt": 1,
                     "job": "synthetic-test", "source_sha": SOURCE},
        "transaction": copy.deepcopy(TX),
        "payload": {"decision": "ADMITTED", "journal_generation": 1,
                    "journal_sha256": SHA, "revision_resolution_sha256": SHA,
                    "pending_revision": None, "active_transaction_id": TX["logical_transaction_id"]},
    })


class ArtifactTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.value = artifact()

    def tearDown(self):
        self.temp.cleanup()

    def test_valid_sealed_transport_round_trip(self):
        path = self.root / "receipt.json"
        transport.write_artifact(path, self.value, expected_type="admission_receipt")
        self.assertEqual(self.value, transport.read_artifact(path, expected_type="admission_receipt"))

    def test_tampered_artifact_rejected(self):
        path = self.root / "tampered.json"
        changed = copy.deepcopy(self.value)
        changed["payload"]["journal_generation"] = 2
        path.write_text(json.dumps(changed), encoding="utf-8")
        with self.assertRaises(c.ArtifactContractError):
            transport.read_artifact(path)

    def test_malformed_json_rejected(self):
        path = self.root / "malformed.json"
        path.write_text("{not-json", encoding="utf-8")
        with self.assertRaises(c.ArtifactContractError):
            transport.read_artifact(path)

    def test_truncated_json_rejected(self):
        path = self.root / "truncated.json"
        path.write_text('{"artifact_type":', encoding="utf-8")
        with self.assertRaises(c.ArtifactContractError):
            transport.read_artifact(path)

    def test_wrong_artifact_type_rejected(self):
        path = self.root / "receipt.json"
        transport.write_artifact(path, self.value)
        with self.assertRaises(c.ArtifactContractError):
            transport.read_artifact(path, expected_type="build_bundle")

    def test_unknown_field_rejected(self):
        bad = copy.deepcopy(self.value)
        bad["payload"]["extra"] = True
        bad = c.seal_artifact(bad)
        with self.assertRaises(c.ArtifactContractError):
            transport.write_artifact(self.root / "bad.json", bad)

    def test_artifact_sha_mismatch_rejected(self):
        bad = copy.deepcopy(self.value)
        bad["artifact_sha256"] = "0" * 64
        with self.assertRaises(c.ArtifactContractError):
            transport.write_artifact(self.root / "bad.json", bad)

    def test_transaction_mismatch_rejected(self):
        path = self.root / "receipt.json"
        transport.write_artifact(path, self.value)
        other = {"worker": "synthetic-worker", "content_revision": 20,
                 "logical_transaction_id": c.logical_transaction_id("synthetic-worker", 20)}
        with self.assertRaises(c.ArtifactContractError):
            transport.read_artifact(path, expected_transaction=other)

    def test_atomic_output_success_leaves_no_staging_file(self):
        path = self.root / "nested" / "receipt.json"
        transport.write_artifact(path, self.value)
        self.assertTrue(path.is_file())
        self.assertEqual([], list(path.parent.glob("*.tmp")))
        self.assertEqual(self.value["artifact_sha256"], transport.read_artifact(path)["artifact_sha256"])

    def test_validation_failure_leaves_no_final_output(self):
        bad = copy.deepcopy(self.value)
        bad["payload"]["decision"] = "UNTRUSTED"
        with self.assertRaises(c.ArtifactContractError):
            transport.write_artifact(self.root / "absent.json", c.seal_artifact(bad))
        self.assertFalse((self.root / "absent.json").exists())

    def test_existing_unrelated_output_is_not_overwritten(self):
        path = self.root / "occupied.json"
        path.write_bytes(b"keep-existing")
        with self.assertRaises((FileExistsError, c.ArtifactContractError)):
            transport.write_artifact(path, self.value, allow_identical=True)
        self.assertEqual(b"keep-existing", path.read_bytes())

    def test_identical_idempotent_output_is_explicit(self):
        path = self.root / "receipt.json"
        first = transport.write_artifact(path, self.value)
        with self.assertRaises(FileExistsError):
            transport.write_artifact(path, self.value)
        again = transport.write_artifact(path, self.value, allow_identical=True)
        self.assertEqual(first["artifact_sha256"], again["artifact_sha256"])

    def test_reference_map_revalidates_artifact(self):
        self.assertEqual({self.value["artifact_sha256"]: self.value}, transport.references(self.value))


if __name__ == "__main__":
    unittest.main()
