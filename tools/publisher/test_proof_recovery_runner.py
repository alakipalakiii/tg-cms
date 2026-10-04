from __future__ import annotations

import copy
import base64
import hashlib
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from publisher import artifact_contract as contracts
from publisher.final_persistence_runner import PersistenceBlocked, finalize
from publisher.proof_recovery_runner import (
    ProofRecoveryRejected,
    authorize_rollback,
    recovery_decision,
    validate_proof,
)


WORKER = "synthetic-worker"
SOURCE_SHA = "a" * 40
SHA = "b" * 64
SHA2 = "c" * 64
SHA3 = "d" * 64
PRIOR_INDEX_RAW = b'{"contract":"IMMUTABLE_MEDIA_INDEX_V1","entries":[]}\n'


def prior_index_binding():
    return {
        "repository": "synthetic-owner/tg-cms",
        "ref": "refs/heads/main",
        "commit_sha": SOURCE_SHA,
        "relative_path": contracts.PRIOR_IMMUTABLE_MEDIA_INDEX_PATH,
        "exists": True,
        "content_sha256": contracts.sha256_bytes(PRIOR_INDEX_RAW),
        "byte_length": len(PRIOR_INDEX_RAW),
        "transport_base64": base64.b64encode(PRIOR_INDEX_RAW).decode("ascii"),
    }


def artifact(kind, payload, transaction, job="synthetic-job"):
    return contracts.seal_artifact({
        "artifact_type": kind, "schema_version": contracts.SCHEMA_VERSION,
        "artifact_id": str(uuid.uuid4()), "created_at": "2026-09-27T12:00:00+00:00",
        "producer": {"workflow_run_id": "synthetic-run", "run_attempt": 1,
                     "job": job, "source_sha": SOURCE_SHA},
        "transaction": copy.deepcopy(transaction), "payload": payload,
    })


class ProofRecoveryRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tx = {"worker": WORKER, "content_revision": 37,
                   "logical_transaction_id": contracts.logical_transaction_id(WORKER, 37)}
        self.receipt = artifact("admission_receipt", {
            "decision": "ADMITTED", "journal_generation": 3, "journal_sha256": SHA,
            "revision_resolution_sha256": SHA2, "pending_revision": None,
            "active_transaction_id": self.tx["logical_transaction_id"],
        }, self.tx)
        self.bundle = artifact("build_bundle", {
            "admission_receipt_sha256": self.receipt["artifact_sha256"],
            "files": [{"path": "dist/index.html", "size_bytes": 10, "sha256": SHA2}],
            "content_fingerprint": SHA, "snapshot_sha256": SHA2,
            "route_manifest_sha256": SHA3, "media_manifest_sha256": SHA,
            "local_gate_evidence_sha256": SHA2,
            "prior_immutable_media_index": prior_index_binding(),
        }, self.tx)
        self.upload_intent = self._intent("upload_version", self.receipt, {
            "worker": WORKER, "build_bundle_sha256": self.bundle["artifact_sha256"],
        })
        self.upload_result = self._result(self.upload_intent, "APPLIED", "version", "candidate-v1")
        self.deploy_intent = self._intent("deploy_zero_percent", self.upload_result, {
            "worker": WORKER, "candidate_version_id": "candidate-v1",
            "baseline_version_id": "baseline-v1", "expected_current_deployment_id": "dep-before",
            "candidate_percentage": 0, "baseline_percentage": 100,
        })
        self.deploy_result = self._result(self.deploy_intent, "APPLIED", "deployment", "dep-zero")
        self.prepromotion_proof = self._prepromotion_proof()
        self.prepromotion_references = {
            item["artifact_sha256"]: item for item in (
                self.bundle, self.deploy_intent, self.deploy_result, self.prepromotion_proof,
            )
        }
        self.promote_intent = self._intent("promote", self.prepromotion_proof, {
            "worker": WORKER, "candidate_version_id": "candidate-v1",
            "baseline_version_id": "baseline-v1", "expected_current_deployment_id": "dep-zero",
            "candidate_percentage": 100, "baseline_percentage": 0,
        })
        self.promote_result = self._result(self.promote_intent, "APPLIED", "deployment", "dep-promoted")
        self.proof = self._proof()

    def _prepromotion_proof(self):
        return artifact("pre_promotion_proof_evidence", {
            "build_bundle_artifact_sha256": self.bundle["artifact_sha256"],
            "deploy_zero_percent_result_artifact_sha256": self.deploy_result["artifact_sha256"],
            "candidate_identity": {
                "worker": WORKER, "candidate_version_id": "candidate-v1",
                "baseline_version_id": "baseline-v1", "zero_percent_deployment_id": "dep-zero",
                "content_fingerprint": self.bundle["payload"]["content_fingerprint"],
            },
            "remote": {
                "crawler_evidence_sha256": SHA, "browser_evidence_sha256": SHA2,
                "gates": {name: True for name in contracts.REMOTE_GATES}, "PASS": True,
            },
            "zero_origin_validation": {
                "public_pages_checked": 5,
                "requests": {"content_api": 0, "media_api": 0, "workers_dev_content": 0,
                             "telegram": 0, "search_backend": 0}, "PASS": True,
            },
            "PASS": True,
        }, self.tx)

    def _intent(self, operation, prerequisite, desired):
        return artifact("mutation_intent", {
            "operation_id": contracts.operation_id_for(self.tx["logical_transaction_id"], operation),
            "operation_name": operation, "attempt_id": str(uuid.uuid4()),
            "intent_state": "RECORDED", "build_bundle_sha256": self.bundle["artifact_sha256"],
            "prerequisite_artifact_sha256": prerequisite["artifact_sha256"],
            "journal_generation": 4, "desired_state": desired,
        }, self.tx)

    def _result(self, intent, state, resource_type, resource_id):
        return artifact("mutation_result", {
            "operation_id": intent["payload"]["operation_id"],
            "attempt_id": intent["payload"]["attempt_id"], "result_state": state,
            "evidence_sha256": None if state == "UNKNOWN" else SHA3,
            "intent_artifact_sha256": intent["artifact_sha256"],
            "build_bundle_sha256": self.bundle["artifact_sha256"],
            "readback_reference": None if resource_id is None else {
                "resource_type": resource_type, "worker": WORKER, "resource_id": resource_id,
            },
        }, self.tx, job="cloudflare-operation")

    def _proof(self, failed_production=False):
        all_gates = lambda names: {name: True for name in names}
        local = {"evidence_sha256": SHA, "gates": all_gates(contracts.LOCAL_GATES), "PASS": True}
        remote = {"crawler_evidence_sha256": SHA, "browser_evidence_sha256": SHA2,
                  "gates": all_gates(contracts.REMOTE_GATES), "PASS": True}
        production_gates = all_gates(contracts.PRODUCTION_GATES)
        identity_pass = not failed_production
        production = {
            "identity_confirmation": {
                "candidate_version_id": "candidate-v1", "baseline_version_id": "baseline-v1",
                "promotion_deployment_id": "dep-promoted", "candidate_percentage": 100,
                "baseline_percentage": 0, "PASS": identity_pass,
            },
            "gates": production_gates, "PASS": identity_pass,
        }
        return artifact("proof_evidence", {
            "build_bundle_sha256": self.bundle["artifact_sha256"],
            "operation_result_sha256s": {
                "upload_version": self.upload_result["artifact_sha256"],
                "deploy_zero_percent": self.deploy_result["artifact_sha256"],
                "promote": self.promote_result["artifact_sha256"], "rollback": None,
            },
            "gate_results": {"local": local, "remote": remote, "production": {
                "crawler_evidence_sha256": SHA, "browser_evidence_sha256": SHA2,
                "route_state_evidence_sha256": SHA3,
                "gates": production_gates, "PASS": True,
            }},
            "candidate_identity": {
                "worker": WORKER, "candidate_version_id": "candidate-v1",
                "baseline_version_id": "baseline-v1", "zero_percent_deployment_id": "dep-zero",
                "content_fingerprint": SHA,
            },
            "production_validation": production,
            "zero_origin_validation": {
                "public_pages_checked": 5,
                "requests": {"content_api": 0, "media_api": 0, "workers_dev_content": 0,
                             "telegram": 0, "search_backend": 0}, "PASS": True,
            },
            "proof_state": "FAIL" if failed_production else "PASS",
        }, self.tx)

    def test_proof_requires_exact_build_and_applied_result_lineage(self):
        result = validate_proof(self.proof, self.bundle, {
            "upload_version": self.upload_result,
            "deploy_zero_percent": self.deploy_result,
            "promote": self.promote_result,
        })
        self.assertEqual("PASS", result["payload"]["proof_state"])

    def test_proof_rejects_result_digest_mismatch(self):
        changed = copy.deepcopy(self.proof)
        changed["payload"]["operation_result_sha256s"]["promote"] = SHA
        changed = contracts.seal_artifact(changed)
        with self.assertRaises(ProofRecoveryRejected):
            validate_proof(changed, self.bundle, {
                "upload_version": self.upload_result,
                "deploy_zero_percent": self.deploy_result,
                "promote": self.promote_result,
            })

    def test_unknown_applied_by_fresh_readback_never_allows_replay(self):
        unknown = self._result(self.upload_intent, "UNKNOWN", "version", "candidate-v1")
        decision = recovery_decision(
            self.upload_intent, unknown,
            {"desired_state_matches": True, "precondition_matches": None,
             "current_deployment_id": None, "resource_type": "version", "resource_id": "candidate-v1"},
            5, clock=lambda: "2026-09-27T12:01:00+00:00",
        )
        contracts.validate_artifact(decision)
        self.assertEqual("RECONCILED_APPLIED", decision["payload"]["decision"])
        self.assertFalse(decision["payload"]["resume_allowed"])

    def test_unknown_unchanged_deployment_allows_only_new_attempt(self):
        unknown = self._result(self.deploy_intent, "UNKNOWN", "deployment", "dep-before")
        decision = recovery_decision(
            self.deploy_intent, unknown,
            {"desired_state_matches": False, "precondition_matches": True,
             "current_deployment_id": "dep-before", "resource_type": "deployment",
             "resource_id": "dep-before"}, 5,
        )
        self.assertEqual("RECONCILED_NOT_APPLIED", decision["payload"]["decision"])
        self.assertTrue(decision["payload"]["resume_allowed"])
        self.assertEqual(self.deploy_intent["payload"]["attempt_id"], decision["payload"]["attempt_id"])

    def test_absent_upload_marker_stays_blocked_unknown(self):
        unknown = self._result(self.upload_intent, "UNKNOWN", "version", "baseline-v1")
        decision = recovery_decision(
            self.upload_intent, unknown,
            {"desired_state_matches": False, "precondition_matches": None,
             "current_deployment_id": None, "resource_type": "version", "resource_id": "baseline-v1"},
            5,
        )
        self.assertEqual("BLOCKED_UNKNOWN", decision["payload"]["decision"])
        self.assertFalse(decision["payload"]["resume_allowed"])

    def test_non_unknown_result_cannot_enter_reconciliation(self):
        with self.assertRaisesRegex(ProofRecoveryRejected, "only UNKNOWN"):
            recovery_decision(self.upload_intent, self.upload_result, {}, 5)

    def test_rollback_requires_failed_production_proof_and_new_intent(self):
        failed = self._proof(failed_production=True)
        rollback = self._intent("rollback", failed, {
            "worker": WORKER, "baseline_version_id": "baseline-v1",
            "failed_candidate_version_id": "candidate-v1",
            "expected_current_deployment_id": "dep-promoted",
            "baseline_percentage": 100, "candidate_percentage": 0,
        })
        checked = authorize_rollback(
            failed, self.promote_intent, self.promote_result, rollback,
            referenced_artifacts=self.prepromotion_references,
        )
        self.assertEqual(rollback["artifact_sha256"], checked["artifact_sha256"])

    def test_rollback_rejects_pass_proof_even_if_breaker_is_open(self):
        rollback = self._intent("rollback", self.proof, {
            "worker": WORKER, "baseline_version_id": "baseline-v1",
            "failed_candidate_version_id": "candidate-v1",
            "expected_current_deployment_id": "dep-promoted",
            "baseline_percentage": 100, "candidate_percentage": 0,
        })
        with self.assertRaisesRegex(ProofRecoveryRejected, "breaker or non-production"):
            authorize_rollback(
                self.proof, self.promote_intent, self.promote_result, rollback,
                referenced_artifacts=self.prepromotion_references,
            )

    def test_rollback_rejects_reused_attempt_id(self):
        failed = self._proof(failed_production=True)
        rollback = self._intent("rollback", failed, {
            "worker": WORKER, "baseline_version_id": "baseline-v1",
            "failed_candidate_version_id": "candidate-v1",
            "expected_current_deployment_id": "dep-promoted",
            "baseline_percentage": 100, "candidate_percentage": 0,
        })
        rollback["payload"]["attempt_id"] = self.promote_intent["payload"]["attempt_id"]
        rollback["payload"]["operation_id"] = contracts.operation_id_for(
            self.tx["logical_transaction_id"], "rollback",
        )
        rollback = contracts.seal_artifact(rollback)
        with self.assertRaisesRegex(ProofRecoveryRejected, "separate recorded attempt"):
            authorize_rollback(
                failed, self.promote_intent, self.promote_result, rollback,
                referenced_artifacts=self.prepromotion_references,
            )

    def _persistence_inputs(self):
        files = {path: ("synthetic:" + path).encode() for path in contracts.STATE_FILE_PATHS}
        results = {"upload_version": self.upload_result,
                   "deploy_zero_percent": self.deploy_result, "promote": self.promote_result}
        return files, results

    def test_final_persistence_orders_ready_single_commit_exact_readback_then_complete(self):
        events = []
        class Journal:
            def mark_ready_to_persist(_self, tx_id, proof_sha, generation):
                events.append(("ready", tx_id, proof_sha, generation))
                return generation + 1
            def finalize_completed(_self, tx_id, commit_sha, generation):
                events.append(("complete", tx_id, commit_sha, generation))
        class Repository:
            persist_calls = 0
            def persist_once(_self, files):
                _self.persist_calls += 1
                events.append(("persist",))
                _self.files = dict(files)
                return "e" * 40
            def read_exact(_self, commit_sha):
                events.append(("readback", commit_sha))
                return {"commit_sha": commit_sha, "file_hashes": {
                    path: hashlib.sha256(data).hexdigest()
                    for path, data in _self.files.items()
                }}
        files, results = self._persistence_inputs()
        repository = Repository()
        result = finalize(
            self.proof, self.bundle, results, files, 12, Journal(), repository,
            clock=lambda: "2026-09-27T12:02:00+00:00",
        )
        contracts.validate_artifact(result)
        self.assertEqual(["ready", "persist", "readback", "complete"],
                         [event[0] for event in events])
        self.assertEqual(1, repository.persist_calls)

    def test_persistence_uncertainty_does_not_retry_or_complete(self):
        calls = []
        class Journal:
            def mark_ready_to_persist(_self, *_args): calls.append("ready"); return 13
            def finalize_completed(_self, *_args): calls.append("complete")
        class Repository:
            count = 0
            def persist_once(_self, _files):
                _self.count += 1
                calls.append("persist")
                raise TimeoutError("fake uncertain write")
            def read_exact(_self, _sha): calls.append("readback"); return {}
        files, results = self._persistence_inputs()
        repository = Repository()
        with self.assertRaises(PersistenceBlocked):
            finalize(self.proof, self.bundle, results, files, 12, Journal(), repository)
        self.assertEqual(1, repository.count)
        self.assertEqual(["ready", "persist"], calls)

    def test_readback_mismatch_blocks_journal_completion(self):
        calls = []
        class Journal:
            def mark_ready_to_persist(_self, *_args): return 13
            def finalize_completed(_self, *_args): calls.append("complete")
        class Repository:
            def persist_once(_self, _files): return "e" * 40
            def read_exact(_self, sha): return {"commit_sha": sha, "file_hashes": {}}
        files, results = self._persistence_inputs()
        with self.assertRaisesRegex(PersistenceBlocked, "exact remote state readback"):
            finalize(self.proof, self.bundle, results, files, 12, Journal(), Repository())
        self.assertEqual([], calls)

    def test_failed_proof_or_incomplete_state_files_cannot_persist(self):
        class Never:
            def mark_ready_to_persist(self, *_args): raise AssertionError("journal must not advance")
            def finalize_completed(self, *_args): raise AssertionError("journal must not complete")
            def persist_once(self, *_args): raise AssertionError("repository must not write")
            def read_exact(self, *_args): raise AssertionError("no readback expected")
        files, results = self._persistence_inputs()
        with self.assertRaises(PersistenceBlocked):
            finalize(self._proof(failed_production=True), self.bundle, results,
                     files, 12, Never(), Never())
        with self.assertRaisesRegex(PersistenceBlocked, "complete allowlisted"):
            finalize(self.proof, self.bundle, results, {}, 12, Never(), Never())


if __name__ == "__main__":
    unittest.main()
