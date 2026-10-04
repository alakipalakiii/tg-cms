from __future__ import annotations

import copy
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from publisher import artifact_contract as c
from publisher.cloudflare_operation_adapter import CloudflareOperationAdapter, OperationRejected


WORKER = "synthetic-worker"
SOURCE = "a" * 40
SHA, SHA2, SHA3 = "b" * 64, "c" * 64, "d" * 64
TX = {"worker": WORKER, "content_revision": 37,
      "logical_transaction_id": c.logical_transaction_id(WORKER, 37)}


def artifact(kind, payload, tx=TX, source=SOURCE, job="synthetic-job"):
    return c.seal_artifact({
        "artifact_type": kind, "schema_version": c.SCHEMA_VERSION,
        "artifact_id": str(uuid.uuid4()), "created_at": "2026-09-27T12:00:00+00:00",
        "producer": {"workflow_run_id": "synthetic-run", "run_attempt": 1,
                     "job": job, "source_sha": source},
        "transaction": copy.deepcopy(tx), "payload": payload,
    })


def gates(names, value=True):
    return {name: value for name in names}


class PrePromotionProofContractTests(unittest.TestCase):
    def setUp(self):
        self.bundle = artifact("build_bundle", {
            "admission_receipt_sha256": SHA, "files": [],
            "content_fingerprint": SHA2, "snapshot_sha256": SHA3,
            "route_manifest_sha256": SHA, "media_manifest_sha256": SHA2,
            "local_gate_evidence_sha256": SHA3,
        })
        self.deploy_intent = artifact("mutation_intent", {
            "operation_id": c.operation_id_for(TX["logical_transaction_id"], "deploy_zero_percent"),
            "operation_name": "deploy_zero_percent", "attempt_id": str(uuid.uuid4()),
            "intent_state": "RECORDED", "build_bundle_sha256": self.bundle["artifact_sha256"],
            "prerequisite_artifact_sha256": SHA,
            "journal_generation": 4,
            "desired_state": {"worker": WORKER, "candidate_version_id": "candidate-v1",
                              "baseline_version_id": "baseline-v1",
                              "expected_current_deployment_id": "deployment-before",
                              "candidate_percentage": 0, "baseline_percentage": 100},
        })
        self.deploy_result = self._deploy_result("APPLIED")
        self.proof = self._proof()
        self.references = self._proof_references()

    def _deploy_result(self, state, *, tx=TX, intent=None, bundle=None, deployment_id="deployment-zero"):
        intent = intent or self.deploy_intent
        bundle = bundle or self.bundle
        return artifact("mutation_result", {
            "operation_id": c.operation_id_for(tx["logical_transaction_id"], "deploy_zero_percent"),
            "attempt_id": intent["payload"]["attempt_id"], "result_state": state,
            "evidence_sha256": None if state == "UNKNOWN" else SHA3,
            "intent_artifact_sha256": intent["artifact_sha256"],
            "build_bundle_sha256": bundle["artifact_sha256"],
            "readback_reference": None if state == "UNKNOWN" else {
                "resource_type": "deployment", "worker": WORKER, "resource_id": deployment_id,
            },
        }, tx=tx, job="cloudflare-operation")

    def _proof(self, *, remote=None, candidate="candidate-v1", baseline="baseline-v1",
               deployment="deployment-zero", fingerprint=SHA2, passed=True,
               bundle=None, result=None, tx=TX, source=SOURCE, zero_origin=None):
        remote_gates = gates(c.REMOTE_GATES) if remote is None else remote
        remote_value = {
            "crawler_evidence_sha256": SHA, "browser_evidence_sha256": SHA2,
            "gates": remote_gates, "PASS": all(remote_gates.values()),
        }
        zero_origin = zero_origin or {
            "public_pages_checked": 5,
            "requests": {"content_api": 0, "media_api": 0, "workers_dev_content": 0,
                         "telegram": 0, "search_backend": 0},
            "PASS": True,
        }
        return artifact("pre_promotion_proof_evidence", {
            "build_bundle_artifact_sha256": (bundle or self.bundle)["artifact_sha256"],
            "deploy_zero_percent_result_artifact_sha256": (result or self.deploy_result)["artifact_sha256"],
            "candidate_identity": {"worker": WORKER, "candidate_version_id": candidate,
                                   "baseline_version_id": baseline,
                                   "zero_percent_deployment_id": deployment,
                                   "content_fingerprint": fingerprint},
            "remote": remote_value, "zero_origin_validation": zero_origin, "PASS": passed,
        }, tx=tx, source=source)

    def _proof_references(self, proof=None, *, bundle=None, intent=None, result=None):
        values = [bundle or self.bundle, intent or self.deploy_intent, result or self.deploy_result]
        if proof is not None:
            values.append(proof)
        return {value["artifact_sha256"]: value for value in values}

    def _promote_intent(self, proof=None, *, tx=TX, candidate="candidate-v1", baseline="baseline-v1",
                        deployment="deployment-zero", proof_sha=None):
        proof = proof or self.proof
        return artifact("mutation_intent", {
            "operation_id": c.operation_id_for(tx["logical_transaction_id"], "promote"),
            "operation_name": "promote", "attempt_id": str(uuid.uuid4()),
            "intent_state": "RECORDED", "build_bundle_sha256": self.bundle["artifact_sha256"],
            "prerequisite_artifact_sha256": proof_sha or proof["artifact_sha256"],
            "journal_generation": 5,
            "desired_state": {"worker": WORKER, "candidate_version_id": candidate,
                              "baseline_version_id": baseline,
                              "expected_current_deployment_id": deployment,
                              "candidate_percentage": 100, "baseline_percentage": 0},
        }, tx=tx)

    def test_01_valid_pre_promotion_evidence(self):
        self.assertEqual(self.proof, c.validate_artifact(self.proof, referenced_artifacts=self.references))

    def test_02_unknown_field_rejected(self):
        bad = copy.deepcopy(self.proof); bad["payload"]["extra"] = True; bad = c.seal_artifact(bad)
        with self.assertRaises(c.ArtifactContractError): c.validate_artifact(bad, referenced_artifacts=self.references)

    def test_03_invalid_envelope_hash_rejected(self):
        bad = copy.deepcopy(self.proof); bad["artifact_sha256"] = "0" * 64
        with self.assertRaises(c.ArtifactContractError): c.validate_artifact(bad, referenced_artifacts=self.references)

    def test_04_candidate_identity_mismatch_rejected(self):
        bad = self._proof(candidate="different-candidate")
        refs = self._proof_references(bad)
        with self.assertRaises(c.ArtifactContractError): c.validate_artifact(bad, referenced_artifacts=refs)

    def test_05_build_bundle_lineage_mismatch_rejected(self):
        bundle = copy.deepcopy(self.bundle); bundle["payload"]["content_fingerprint"] = SHA3
        bundle = c.seal_artifact(bundle)
        bad = self._proof(bundle=bundle)
        refs = self._proof_references(bad, bundle=bundle)
        with self.assertRaises(c.ArtifactContractError): c.validate_artifact(bad, referenced_artifacts=refs)

    def test_06_deployment_result_transaction_mismatch_rejected(self):
        other_tx = {"worker": WORKER, "content_revision": 38,
                    "logical_transaction_id": c.logical_transaction_id(WORKER, 38)}
        result = self._deploy_result("APPLIED", tx=other_tx)
        bad = self._proof(result=result)
        refs = self._proof_references(bad, result=result)
        with self.assertRaises(c.ArtifactContractError): c.validate_artifact(bad, referenced_artifacts=refs)

    def test_07_not_applied_deployment_cannot_authorize(self):
        result = self._deploy_result("NOT_APPLIED")
        bad = self._proof(result=result)
        refs = self._proof_references(bad, result=result)
        with self.assertRaises(c.ArtifactContractError): c.validate_artifact(bad, referenced_artifacts=refs)

    def test_08_unknown_deployment_cannot_authorize(self):
        result = self._deploy_result("UNKNOWN")
        bad = self._proof(result=result)
        refs = self._proof_references(bad, result=result)
        with self.assertRaises(c.ArtifactContractError): c.validate_artifact(bad, referenced_artifacts=refs)

    def test_09_remote_gate_false_cannot_be_claimed_as_pass(self):
        remote = gates(c.REMOTE_GATES); remote["seo"] = False
        bad = self._proof(remote=remote, passed=True)
        with self.assertRaises(c.ArtifactContractError): c.validate_artifact(bad, referenced_artifacts=self._proof_references(bad))

    def test_10_zero_origin_failure_cannot_authorize(self):
        zero = {"public_pages_checked": 5,
                "requests": {"content_api": 1, "media_api": 0, "workers_dev_content": 0,
                             "telegram": 0, "search_backend": 0}, "PASS": False}
        bad = self._proof(zero_origin=zero)
        with self.assertRaises(c.ArtifactContractError): c.validate_artifact(bad, referenced_artifacts=self._proof_references(bad))

    def test_11_promote_without_preproof_rejected(self):
        promote = self._promote_intent(proof_sha=SHA)
        with self.assertRaises(c.ArtifactContractError): c.validate_artifact(promote)

    def test_12_promote_with_invalid_proof_reference_rejected(self):
        promote = self._promote_intent(proof_sha=SHA)
        refs = dict(self.references); refs[SHA] = {"artifact_type": "remote-proof-result"}
        with self.assertRaises(c.ArtifactContractError): c.validate_artifact(promote, referenced_artifacts=refs)

    def test_13_promote_transaction_mismatch_rejected(self):
        other_tx = {"worker": WORKER, "content_revision": 38,
                    "logical_transaction_id": c.logical_transaction_id(WORKER, 38)}
        promote = self._promote_intent(tx=other_tx)
        refs = self._proof_references(self.proof); refs[promote["artifact_sha256"]] = promote
        with self.assertRaises(c.ArtifactContractError): c.validate_artifact(promote, referenced_artifacts=refs)

    def test_14_promote_candidate_mismatch_rejected(self):
        promote = self._promote_intent(candidate="other-candidate")
        with self.assertRaises(c.ArtifactContractError): c.validate_artifact(promote, referenced_artifacts=self._proof_references(self.proof))

    def test_15_matching_promote_intent_accepted(self):
        promote = self._promote_intent()
        self.assertEqual(promote, c.validate_artifact(promote, referenced_artifacts=self._proof_references(self.proof)))

    def test_16_legacy_remote_result_cannot_authorize(self):
        promote = self._promote_intent(proof_sha=SHA)
        legacy = {"transaction_id": TX["logical_transaction_id"], "PASS": True}
        with self.assertRaises(c.ArtifactContractError): c.validate_artifact(promote, referenced_artifacts={SHA: legacy})

    def test_17_post_promotion_proof_contract_remains_valid(self):
        self.assertEqual("proof_evidence", c.validate_artifact(self._post_promotion_proof())["artifact_type"])

    def _post_promotion_proof(self):
        local = {"evidence_sha256": SHA, "gates": gates(c.LOCAL_GATES), "PASS": True}
        remote = {"crawler_evidence_sha256": SHA, "browser_evidence_sha256": SHA2,
                  "gates": gates(c.REMOTE_GATES), "PASS": True}
        prod = {"crawler_evidence_sha256": SHA, "browser_evidence_sha256": SHA2,
                "route_state_evidence_sha256": SHA3, "gates": gates(c.PRODUCTION_GATES), "PASS": True}
        identity = {"worker": WORKER, "candidate_version_id": "candidate-v1",
                    "baseline_version_id": "baseline-v1", "zero_percent_deployment_id": "deployment-zero",
                    "content_fingerprint": SHA2}
        return artifact("proof_evidence", {
            "build_bundle_sha256": SHA,
            "operation_result_sha256s": {"upload_version": SHA, "deploy_zero_percent": SHA2,
                                          "promote": SHA3, "rollback": None},
            "gate_results": {"local": local, "remote": remote, "production": prod},
            "candidate_identity": identity,
            "production_validation": {"identity_confirmation": {
                "candidate_version_id": "candidate-v1", "baseline_version_id": "baseline-v1",
                "promotion_deployment_id": "promotion-deployment", "candidate_percentage": 100,
                "baseline_percentage": 0, "PASS": True},
                "gates": gates(c.PRODUCTION_GATES), "PASS": True},
            "zero_origin_validation": {"public_pages_checked": 1,
                "requests": {"content_api": 0, "media_api": 0, "workers_dev_content": 0,
                             "telegram": 0, "search_backend": 0}, "PASS": True},
            "proof_state": "PASS",
        })

    def test_18_a3_adapter_promote_requires_and_accepts_valid_preproof(self):
        promote = self._promote_intent()
        class Backend:
            def __init__(self):
                self.reads = [
                    {"desired_state_matches": False, "precondition_matches": True,
                     "current_deployment_id": "deployment-zero", "resource_type": "deployment",
                     "resource_id": "deployment-zero"},
                    {"desired_state_matches": True, "precondition_matches": False,
                     "current_deployment_id": "deployment-promoted", "resource_type": "deployment",
                     "resource_id": "deployment-promoted"},
                ]
                self.mutations = 0
            def read_state(self, _intent): return self.reads.pop(0)
            def mutate(self, _intent, _bundle): self.mutations += 1
        backend = Backend()
        result = CloudflareOperationAdapter(backend).execute(
            promote, self.bundle, self.proof,
            referenced_artifacts=self._proof_references(self.proof),
        )
        self.assertEqual("APPLIED", result["payload"]["result_state"])
        self.assertEqual(1, backend.mutations)

    def test_21_a3_adapter_fails_closed_without_preproof(self):
        promote = self._promote_intent(proof_sha=SHA)
        class Never:
            def read_state(self, _intent): raise AssertionError("must not read")
            def mutate(self, _intent, _bundle): raise AssertionError("must not mutate")
        with self.assertRaises(c.ArtifactContractError):
            CloudflareOperationAdapter(Never()).execute(promote, self.bundle, self.deploy_result)

    def _upload_result(self):
        upload_intent = artifact("mutation_intent", {
            "operation_id": c.operation_id_for(TX["logical_transaction_id"], "upload_version"),
            "operation_name": "upload_version", "attempt_id": str(uuid.uuid4()),
            "intent_state": "RECORDED", "build_bundle_sha256": self.bundle["artifact_sha256"],
            "prerequisite_artifact_sha256": SHA, "journal_generation": 3,
            "desired_state": {"worker": WORKER, "build_bundle_sha256": self.bundle["artifact_sha256"]},
        })
        return artifact("mutation_result", {
            "operation_id": upload_intent["payload"]["operation_id"],
            "attempt_id": upload_intent["payload"]["attempt_id"], "result_state": "APPLIED",
            "evidence_sha256": SHA3, "intent_artifact_sha256": upload_intent["artifact_sha256"],
            "build_bundle_sha256": self.bundle["artifact_sha256"],
            "readback_reference": {"resource_type": "version", "worker": WORKER, "resource_id": "candidate-v1"},
        }, job="cloudflare-operation")

    def test_19_a4_recovery_schema_unchanged(self):
        self.assertEqual("recovery_decision", c.validate_artifact(self._recovery())["artifact_type"])

    def _recovery(self):
        return artifact("recovery_decision", {
            "operation_id": c.operation_id_for(TX["logical_transaction_id"], "promote"),
            "attempt_id": str(uuid.uuid4()), "decision": "BLOCKED_UNKNOWN",
            "evidence_sha256": SHA, "intent_artifact_sha256": SHA2,
            "result_artifact_sha256": SHA3, "journal_generation": 5,
            "resume_allowed": False,
        })

    def test_20_a5_persistence_contract_unchanged(self):
        paths = sorted(c.STATE_FILE_PATHS)
        payload = {"build_bundle_sha256": SHA, "proof_evidence_sha256": SHA2,
                   "operation_result_sha256s": {"upload_version": SHA, "deploy_zero_percent": SHA2,
                                                 "promote": SHA3, "rollback": None},
                   "state_files": [{"path": path, "size_bytes": 1, "sha256": SHA} for path in paths],
                   "state_commit_sha": "e" * 40, "journal_generation": 8}
        self.assertEqual("final_persistence_payload", c.validate_artifact(artifact("final_persistence_payload", payload))["artifact_type"])


if __name__ == "__main__":
    unittest.main()
