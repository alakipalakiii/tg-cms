from __future__ import annotations

import copy
import unittest
import uuid

from tools.publisher.artifact_contract import (
    ArtifactContractError,
    PRODUCTION_GATES,
    REMOTE_GATES,
    LOCAL_GATES,
    SCHEMA_VERSION,
    artifact_digest,
    logical_transaction_id,
    operation_id_for,
    seal_artifact,
    validate_artifact,
    validate_intent_result_pair,
)

WORKER = "synthetic-worker"
REVISION = 37
SOURCE_SHA = "a" * 40
SHA = "b" * 64
SHA2 = "c" * 64
SHA3 = "d" * 64


def _all_gates(names):
    return {name: True for name in names}


class ArtifactContractTests(unittest.TestCase):
    def setUp(self):
        self.transaction = {
            "worker": WORKER,
            "content_revision": REVISION,
            "logical_transaction_id": logical_transaction_id(WORKER, REVISION),
        }

    def _artifact(self, artifact_type: str, payload: dict):
        return seal_artifact({
            "artifact_type": artifact_type,
            "schema_version": SCHEMA_VERSION,
            "artifact_id": str(uuid.uuid4()),
            "created_at": "2026-09-26T12:00:00+00:00",
            "producer": {
                "workflow_run_id": "synthetic-run-1",
                "run_attempt": 1,
                "job": "synthetic-job",
                "source_sha": SOURCE_SHA,
            },
            "transaction": copy.deepcopy(self.transaction),
            "payload": payload,
        })

    def _valid_revision(self):
        return self._artifact("revision_resolution", {
            "revision": REVISION,
            "published_revision": 36,
            "changed_at": "2026-09-26T11:59:00+00:00",
            "endpoint_id": "mahoon-content-revision-v1",
            "request_count": 1,
            "decision": "CHANGED",
        })

    def _valid_admission(self):
        return self._artifact("admission_receipt", {
            "decision": "ADMITTED",
            "journal_generation": 3,
            "journal_sha256": SHA,
            "revision_resolution_sha256": SHA2,
            "pending_revision": None,
            "active_transaction_id": self.transaction["logical_transaction_id"],
        })

    def _valid_build(self):
        return self._artifact("build_bundle", {
            "admission_receipt_sha256": SHA,
            "files": [
                {"path": "dist/a.html", "size_bytes": 10, "sha256": SHA2},
                {"path": "dist/b.css", "size_bytes": 20, "sha256": SHA3},
            ],
            "content_fingerprint": SHA,
            "snapshot_sha256": SHA2,
            "route_manifest_sha256": SHA3,
            "media_manifest_sha256": SHA,
            "local_gate_evidence_sha256": SHA2,
        })

    def _intent(self, operation="upload_version", attempt_id=None):
        desired = {
            "upload_version": {"worker": WORKER, "build_bundle_sha256": SHA},
            "deploy_zero_percent": {
                "worker": WORKER, "candidate_version_id": "cand-v1",
                "baseline_version_id": "base-v1", "expected_current_deployment_id": "dep-0",
                "candidate_percentage": 0, "baseline_percentage": 100,
            },
            "promote": {
                "worker": WORKER, "candidate_version_id": "cand-v1",
                "baseline_version_id": "base-v1", "expected_current_deployment_id": "dep-zero",
                "candidate_percentage": 100, "baseline_percentage": 0,
            },
            "rollback": {
                "worker": WORKER, "baseline_version_id": "base-v1",
                "failed_candidate_version_id": "cand-v1", "expected_current_deployment_id": "dep-promoted",
                "baseline_percentage": 100, "candidate_percentage": 0,
            },
        }[operation]
        return self._artifact("mutation_intent", {
            "operation_id": operation_id_for(self.transaction["logical_transaction_id"], operation),
            "operation_name": operation,
            "attempt_id": attempt_id or str(uuid.uuid4()),
            "intent_state": "RECORDED",
            "build_bundle_sha256": SHA,
            "prerequisite_artifact_sha256": SHA2,
            "journal_generation": 4,
            "desired_state": desired,
        })

    def _result(self, intent, state="APPLIED"):
        op = intent["payload"]["operation_name"]
        resource = "version" if op == "upload_version" else "deployment"
        return self._artifact("mutation_result", {
            "operation_id": intent["payload"]["operation_id"],
            "attempt_id": intent["payload"]["attempt_id"],
            "result_state": state,
            "evidence_sha256": None if state == "UNKNOWN" else SHA3,
            "intent_artifact_sha256": intent["artifact_sha256"],
            "build_bundle_sha256": SHA,
            "readback_reference": {
                "resource_type": resource,
                "worker": WORKER,
                "resource_id": "readback-1",
            },
        })

    def _valid_proof(self):
        local = {"evidence_sha256": SHA, "gates": _all_gates(LOCAL_GATES), "PASS": True}
        remote = {"crawler_evidence_sha256": SHA, "browser_evidence_sha256": SHA2,
                  "gates": _all_gates(REMOTE_GATES), "PASS": True}
        production = {"crawler_evidence_sha256": SHA, "browser_evidence_sha256": SHA2,
                      "route_state_evidence_sha256": SHA3,
                      "gates": _all_gates(PRODUCTION_GATES), "PASS": True}
        return self._artifact("proof_evidence", {
            "build_bundle_sha256": SHA,
            "operation_result_sha256s": {
                "upload_version": SHA, "deploy_zero_percent": SHA2,
                "promote": SHA3, "rollback": None,
            },
            "gate_results": {"local": local, "remote": remote, "production": production},
            "candidate_identity": {
                "worker": WORKER, "candidate_version_id": "cand-v1",
                "baseline_version_id": "base-v1", "zero_percent_deployment_id": "dep-zero",
                "content_fingerprint": SHA,
            },
            "production_validation": {
                "identity_confirmation": {
                    "candidate_version_id": "cand-v1", "baseline_version_id": "base-v1",
                    "promotion_deployment_id": "dep-promoted", "candidate_percentage": 100,
                    "baseline_percentage": 0, "PASS": True,
                },
                "gates": _all_gates(PRODUCTION_GATES),
                "PASS": True,
            },
            "zero_origin_validation": {
                "public_pages_checked": 5,
                "requests": {"content_api": 0, "media_api": 0, "workers_dev_content": 0,
                             "telegram": 0, "search_backend": 0},
                "PASS": True,
            },
            "proof_state": "PASS",
        })

    def _recovery(self):
        return self._artifact("recovery_decision", {
            "operation_id": operation_id_for(self.transaction["logical_transaction_id"], "promote"),
            "attempt_id": str(uuid.uuid4()),
            "decision": "BLOCKED_UNKNOWN",
            "evidence_sha256": SHA,
            "intent_artifact_sha256": SHA2,
            "result_artifact_sha256": SHA3,
            "journal_generation": 9,
            "resume_allowed": False,
        })

    def _persistence(self):
        paths = [
            "publisher-state/current-accepted-route-manifest.json",
            "publisher-state/immutable-media-index.json",
            "publisher-state/production-content-fingerprint.json",
            "publisher-state/production-media-manifest.json",
            "publisher-state/published-route-manifest.json",
            "publisher-state/published-static-state.json",
        ]
        return self._artifact("final_persistence_payload", {
            "build_bundle_sha256": SHA,
            "proof_evidence_sha256": SHA2,
            "operation_result_sha256s": {
                "upload_version": SHA, "deploy_zero_percent": SHA2,
                "promote": SHA3, "rollback": None,
            },
            "state_files": [{"path": p, "size_bytes": 1, "sha256": SHA} for p in paths],
            "state_commit_sha": "e" * 40,
            "journal_generation": 12,
        })

    def test_all_eight_valid_artifacts_are_accepted(self):
        artifacts = [self._valid_revision(), self._valid_admission(), self._valid_build(),
                     self._intent(), self._result(self._intent()), self._valid_proof(),
                     self._recovery(), self._persistence()]
        for artifact in artifacts:
            self.assertEqual(artifact, validate_artifact(artifact))

    def test_unknown_envelope_payload_and_nested_fields_rejected(self):
        a = self._valid_revision(); a["extra"] = 1; a = seal_artifact(a)
        with self.assertRaises(ArtifactContractError): validate_artifact(a)
        a = self._valid_revision(); a["payload"]["extra"] = 1; a = seal_artifact(a)
        with self.assertRaises(ArtifactContractError): validate_artifact(a)
        a = self._valid_proof(); a["payload"]["candidate_identity"]["extra"] = 1; a = seal_artifact(a)
        with self.assertRaises(ArtifactContractError): validate_artifact(a)

    def test_recursive_float_rejected(self):
        a = self._valid_build(); a["payload"]["files"][0]["size_bytes"] = 1.5
        with self.assertRaisesRegex(ArtifactContractError, "floating-point"):
            seal_artifact(a)

    def test_digest_tamper_rejected(self):
        a = self._valid_revision(); a["artifact_sha256"] = "0" * 64
        with self.assertRaisesRegex(ArtifactContractError, "digest mismatch"):
            validate_artifact(a)

    def test_identity_and_source_binding_rejected(self):
        a = self._valid_revision(); a["transaction"]["logical_transaction_id"] = "0" * 64; a = seal_artifact(a)
        with self.assertRaises(ArtifactContractError): validate_artifact(a)
        with self.assertRaises(ArtifactContractError): validate_artifact(self._valid_revision(), expected_source_sha="f" * 40)

    def test_parent_lineage_and_journal_generation(self):
        a = self._valid_admission()
        validate_artifact(a, expected_parents={"revision_resolution_sha256": SHA2}, expected_journal_generation=3)
        with self.assertRaises(ArtifactContractError):
            validate_artifact(a, expected_parents={"revision_resolution_sha256": SHA3})
        with self.assertRaises(ArtifactContractError): validate_artifact(a, expected_journal_generation=4)

    def test_operation_id_and_operation_specific_desired_state(self):
        a = self._intent("promote"); a["payload"]["operation_id"] = "0" * 64; a = seal_artifact(a)
        with self.assertRaises(ArtifactContractError): validate_artifact(a)
        a = self._intent("promote"); a["payload"]["desired_state"]["candidate_percentage"] = 0; a = seal_artifact(a)
        with self.assertRaises(ArtifactContractError): validate_artifact(a)
        a = self._intent("upload_version"); a["payload"]["desired_state"]["candidate_version_id"] = "nope"; a = seal_artifact(a)
        with self.assertRaises(ArtifactContractError): validate_artifact(a)

    def test_intent_result_attempt_and_readback_binding(self):
        intent = self._intent("upload_version")
        result = self._result(intent)
        validate_intent_result_pair(intent, result)
        bad = copy.deepcopy(result); bad["payload"]["attempt_id"] = str(uuid.uuid4()); bad = seal_artifact(bad)
        with self.assertRaises(ArtifactContractError): validate_intent_result_pair(intent, bad)
        bad = copy.deepcopy(result); bad["payload"]["readback_reference"]["resource_type"] = "deployment"; bad = seal_artifact(bad)
        with self.assertRaises(ArtifactContractError): validate_intent_result_pair(intent, bad)

    def test_unknown_result_allows_null_evidence_but_conclusive_does_not(self):
        intent = self._intent()
        validate_artifact(self._result(intent, "UNKNOWN"))
        bad = self._result(intent, "APPLIED"); bad["payload"]["evidence_sha256"] = None; bad = seal_artifact(bad)
        with self.assertRaises(ArtifactContractError): validate_artifact(bad)

    def test_unknown_result_allows_null_readback_reference_but_conclusive_does_not(self):
        intent = self._intent("upload_version")
        unknown = self._result(intent, "UNKNOWN")
        unknown["payload"]["readback_reference"] = None
        unknown = seal_artifact(unknown)
        validate_artifact(unknown)
        validate_intent_result_pair(intent, unknown)

        applied = self._result(intent, "APPLIED")
        applied["payload"]["readback_reference"] = None
        applied = seal_artifact(applied)
        with self.assertRaises(ArtifactContractError):
            validate_artifact(applied)

    def test_gate_allowlists_and_pass_conjunction_are_closed(self):
        a = self._valid_proof(); a["payload"]["gate_results"]["remote"]["gates"]["visual"] = False; a = seal_artifact(a)
        with self.assertRaisesRegex(ArtifactContractError, "PASS"):
            validate_artifact(a)
        a = self._valid_proof(); a["payload"]["gate_results"]["remote"]["gates"]["invented"] = True; a = seal_artifact(a)
        with self.assertRaises(ArtifactContractError): validate_artifact(a)

    def test_candidate_and_production_identity_are_bound(self):
        a = self._valid_proof(); a["payload"]["production_validation"]["identity_confirmation"]["candidate_version_id"] = "other"; a = seal_artifact(a)
        with self.assertRaises(ArtifactContractError): validate_artifact(a)
        a = self._valid_proof(); a["payload"]["candidate_identity"]["baseline_version_id"] = "cand-v1"; a = seal_artifact(a)
        with self.assertRaises(ArtifactContractError): validate_artifact(a)

    def test_zero_origin_requires_pages_and_zero_counters(self):
        a = self._valid_proof(); a["payload"]["zero_origin_validation"]["requests"]["telegram"] = 1; a = seal_artifact(a)
        with self.assertRaises(ArtifactContractError): validate_artifact(a)
        a = self._valid_proof(); a["payload"]["zero_origin_validation"]["public_pages_checked"] = 0; a = seal_artifact(a)
        with self.assertRaises(ArtifactContractError): validate_artifact(a)

    def test_endpoint_allowlist_and_exact_state_file_allowlist(self):
        a = self._valid_revision(); a["payload"]["endpoint_id"] = "https://evil.invalid"; a = seal_artifact(a)
        with self.assertRaises(ArtifactContractError): validate_artifact(a)
        a = self._persistence(); a["payload"]["state_files"][0]["path"] = "publisher-state/anything.json"; a = seal_artifact(a)
        with self.assertRaises(ArtifactContractError): validate_artifact(a)

    def test_state_files_must_be_sorted_and_unique(self):
        a = self._persistence(); a["payload"]["state_files"] = list(reversed(a["payload"]["state_files"])); a = seal_artifact(a)
        with self.assertRaises(ArtifactContractError): validate_artifact(a)

    def test_recovery_unknown_cannot_resume_and_applied_cannot_replay(self):
        a = self._recovery(); a["payload"]["resume_allowed"] = True; a = seal_artifact(a)
        with self.assertRaises(ArtifactContractError): validate_artifact(a)
        a = self._recovery(); a["payload"]["decision"] = "RECONCILED_APPLIED"; a["payload"]["resume_allowed"] = True; a = seal_artifact(a)
        with self.assertRaises(ArtifactContractError): validate_artifact(a)

    def test_trusted_producer_metadata_is_checked(self):
        a = self._valid_revision()
        validate_artifact(a, trusted_producer={"workflow_run_id": "synthetic-run-1", "source_sha": SOURCE_SHA})
        with self.assertRaises(ArtifactContractError):
            validate_artifact(a, trusted_producer={"workflow_run_id": "other"})

    def test_secret_like_nested_key_is_rejected(self):
        a = self._valid_revision(); a["payload"]["authorization_token"] = "x"
        with self.assertRaises(ArtifactContractError): seal_artifact(a)

    def test_artifact_digest_is_canonical(self):
        a = self._valid_revision()
        self.assertEqual(a["artifact_sha256"], artifact_digest(a))


if __name__ == "__main__":
    unittest.main()
