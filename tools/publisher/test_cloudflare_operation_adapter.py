from __future__ import annotations

import copy
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from publisher import artifact_contract as contracts
from publisher.cloudflare_operation_adapter import CloudflareOperationAdapter, OperationRejected


WORKER = "synthetic-worker"
REVISION = 37
SOURCE_SHA = "a" * 40
SHA = "b" * 64
SHA2 = "c" * 64
SHA3 = "d" * 64
TRANSACTION = {
    "worker": WORKER,
    "content_revision": REVISION,
    "logical_transaction_id": contracts.logical_transaction_id(WORKER, REVISION),
}


def artifact(kind, payload, job="synthetic-job"):
    return contracts.seal_artifact({
        "artifact_type": kind,
        "schema_version": contracts.SCHEMA_VERSION,
        "artifact_id": str(uuid.uuid4()),
        "created_at": "2026-09-27T12:00:00+00:00",
        "producer": {
            "workflow_run_id": "synthetic-run",
            "run_attempt": 1,
            "job": job,
            "source_sha": SOURCE_SHA,
        },
        "transaction": copy.deepcopy(TRANSACTION),
        "payload": payload,
    })


def admission():
    return artifact("admission_receipt", {
        "decision": "ADMITTED", "journal_generation": 3,
        "journal_sha256": SHA, "revision_resolution_sha256": SHA2,
        "pending_revision": None,
        "active_transaction_id": TRANSACTION["logical_transaction_id"],
    })


def bundle(receipt):
    return artifact("build_bundle", {
        "admission_receipt_sha256": receipt["artifact_sha256"],
        "files": [{"path": "dist/index.html", "size_bytes": 10, "sha256": SHA2}],
        "content_fingerprint": SHA, "snapshot_sha256": SHA2,
        "route_manifest_sha256": SHA3, "media_manifest_sha256": SHA,
        "local_gate_evidence_sha256": SHA2,
    })


def intent(operation, build, prerequisite, desired=None, attempt_id=None):
    desired = desired or {"worker": WORKER, "build_bundle_sha256": build["artifact_sha256"]}
    return artifact("mutation_intent", {
        "operation_id": contracts.operation_id_for(TRANSACTION["logical_transaction_id"], operation),
        "operation_name": operation,
        "attempt_id": attempt_id or str(uuid.uuid4()),
        "intent_state": "RECORDED",
        "build_bundle_sha256": build["artifact_sha256"],
        "prerequisite_artifact_sha256": prerequisite["artifact_sha256"],
        "journal_generation": 4,
        "desired_state": desired,
    })


class FakeBackend:
    def __init__(self, *readbacks, mutation_error=None):
        self.readbacks = list(readbacks)
        self.mutation_error = mutation_error
        self.mutation_calls = 0

    def read_state(self, _intent):
        value = self.readbacks.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def mutate(self, _intent, _bundle):
        self.mutation_calls += 1
        if self.mutation_error:
            raise self.mutation_error


def readback(desired, *, precondition=None, deployment=None, resource="candidate-version", kind="version"):
    return {
        "desired_state_matches": desired,
        "precondition_matches": precondition,
        "current_deployment_id": deployment,
        "resource_type": kind if resource is not None else None,
        "resource_id": resource,
    }


class CloudflareOperationAdapterTests(unittest.TestCase):
    def setUp(self):
        self.receipt = admission()
        self.bundle = bundle(self.receipt)
        self.upload_intent = intent("upload_version", self.bundle, self.receipt)
        self.clock = lambda: "2026-09-27T12:00:01+00:00"

    def run_upload(self, backend, operation_intent=None, prerequisite=None):
        return CloudflareOperationAdapter(backend, clock=self.clock).execute(
            operation_intent or self.upload_intent,
            self.bundle,
            prerequisite or self.receipt,
        )

    def test_applied_result_is_sealed_and_bound_to_intent(self):
        backend = FakeBackend(
            readback(False, resource="existing-version", kind="version"),
            readback(True, resource="candidate-version", kind="version"),
        )
        result = self.run_upload(backend)
        contracts.validate_intent_result_pair(self.upload_intent, result)
        self.assertEqual("APPLIED", result["payload"]["result_state"])
        self.assertEqual("candidate-version", result["payload"]["readback_reference"]["resource_id"])
        self.assertEqual(1, backend.mutation_calls)

    def test_invalid_intent_fails_before_read_or_mutation(self):
        invalid = copy.deepcopy(self.upload_intent)
        invalid["payload"]["intent_state"] = "NOT_STARTED"
        invalid = contracts.seal_artifact(invalid)
        backend = FakeBackend()
        with self.assertRaises(contracts.ArtifactContractError):
            self.run_upload(backend, invalid)
        self.assertEqual(0, backend.mutation_calls)
        self.assertEqual([], backend.readbacks)

    def test_non_admitted_prerequisite_fails_closed(self):
        deferred = copy.deepcopy(self.receipt)
        deferred["payload"]["decision"] = "DEFERRED"
        deferred = contracts.seal_artifact(deferred)
        stale_intent = intent("upload_version", self.bundle, deferred)
        backend = FakeBackend()
        with self.assertRaises(OperationRejected):
            self.run_upload(backend, stale_intent, deferred)
        self.assertEqual(0, backend.mutation_calls)

    def test_build_bundle_must_reference_its_admission_receipt(self):
        other_receipt = copy.deepcopy(self.receipt)
        other_receipt["payload"]["journal_generation"] += 1
        other_receipt = contracts.seal_artifact(other_receipt)
        mismatched_intent = intent("upload_version", self.bundle, other_receipt)
        backend = FakeBackend()
        with self.assertRaisesRegex(OperationRejected, "admission receipt mismatch"):
            self.run_upload(backend, mismatched_intent, other_receipt)
        self.assertEqual(0, backend.mutation_calls)

    def test_unmet_deployment_precondition_prevents_mutation(self):
        desired = {
            "worker": WORKER, "candidate_version_id": "candidate-v1",
            "baseline_version_id": "baseline-v1", "expected_current_deployment_id": "expected-deployment",
            "candidate_percentage": 0, "baseline_percentage": 100,
        }
        upload_result = self._upload_result("APPLIED", "candidate-v1")
        deployment_intent = intent("deploy_zero_percent", self.bundle, upload_result, desired)
        backend = FakeBackend(readback(False, precondition=False, deployment="drifted-deployment",
                                       resource="drifted-deployment", kind="deployment"))
        result = CloudflareOperationAdapter(backend, clock=self.clock).execute(
            deployment_intent, self.bundle, upload_result, prerequisite_intent=self.upload_intent,
        )
        self.assertEqual("NOT_APPLIED", result["payload"]["result_state"])
        self.assertEqual(0, backend.mutation_calls)

    def test_uncertain_mutation_returns_unknown_and_is_not_retried_in_call(self):
        backend = FakeBackend(
            readback(False, resource="existing-version", kind="version"),
            RuntimeError("SECRET_VALUE SHOULD NOT ESCAPE"),
            mutation_error=RuntimeError("request outcome unknown"),
        )
        result = self.run_upload(backend)
        self.assertEqual("UNKNOWN", result["payload"]["result_state"])
        self.assertEqual(1, backend.mutation_calls)
        self.assertNotIn("SECRET_VALUE", repr(result))
        contracts.validate_intent_result_pair(self.upload_intent, result)

    def test_pre_read_failure_returns_unknown_without_mutation(self):
        backend = FakeBackend(RuntimeError("readback unavailable"))
        result = self.run_upload(backend)
        self.assertEqual("UNKNOWN", result["payload"]["result_state"])
        self.assertIsNone(result["payload"]["readback_reference"])
        self.assertEqual(0, backend.mutation_calls)

    def test_pre_read_replay_guard_reports_applied_without_mutation(self):
        backend = FakeBackend(readback(True, resource="already-uploaded", kind="version"))
        result = self.run_upload(backend)
        self.assertEqual("APPLIED", result["payload"]["result_state"])
        self.assertEqual(0, backend.mutation_calls)

    def test_same_attempt_after_uncertain_upload_cannot_mutate_again(self):
        backend = FakeBackend(
            readback(False, resource="existing-version", kind="version"),
            RuntimeError("ambiguous post-upload readback"),
            readback(False, resource="existing-version", kind="version"),
        )
        adapter = CloudflareOperationAdapter(backend, clock=self.clock)
        first = adapter.execute(self.upload_intent, self.bundle, self.receipt)
        replay = adapter.execute(self.upload_intent, self.bundle, self.receipt)
        self.assertEqual("UNKNOWN", first["payload"]["result_state"])
        self.assertEqual("UNKNOWN", replay["payload"]["result_state"])
        self.assertEqual(1, backend.mutation_calls)

    def test_absent_upload_marker_after_mutation_is_not_claimed_not_applied(self):
        backend = FakeBackend(
            readback(False, resource="existing-version", kind="version"),
            readback(False, resource="existing-version", kind="version"),
        )
        result = self.run_upload(backend)
        self.assertEqual("UNKNOWN", result["payload"]["result_state"])
        self.assertEqual(1, backend.mutation_calls)

    def test_build_or_prerequisite_digest_mismatch_fails_before_mutation(self):
        other_bundle = copy.deepcopy(self.bundle)
        other_bundle["payload"]["content_fingerprint"] = SHA3
        other_bundle = contracts.seal_artifact(other_bundle)
        backend = FakeBackend()
        with self.assertRaises(OperationRejected):
            CloudflareOperationAdapter(backend, clock=self.clock).execute(
                self.upload_intent, other_bundle, self.receipt,
            )
        self.assertEqual(0, backend.mutation_calls)

    def _upload_result(self, state, version_id):
        return artifact("mutation_result", {
            "operation_id": self.upload_intent["payload"]["operation_id"],
            "attempt_id": self.upload_intent["payload"]["attempt_id"],
            "result_state": state, "evidence_sha256": SHA3,
            "intent_artifact_sha256": self.upload_intent["artifact_sha256"],
            "build_bundle_sha256": self.bundle["artifact_sha256"],
            "readback_reference": {"resource_type": "version", "worker": WORKER,
                                   "resource_id": version_id},
        }, job="cloudflare-operation")


if __name__ == "__main__":
    unittest.main()
