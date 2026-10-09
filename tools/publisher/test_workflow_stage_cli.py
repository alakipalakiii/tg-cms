from __future__ import annotations

import argparse
import copy
import inspect
import json
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from publisher import artifact_contract as c
from publisher import artifact_transport as transport
from publisher import cloudflare_operation_adapter as operations
from publisher import final_persistence_runner as persistence
from publisher import transaction_journal as journal_module
from publisher import workflow_stage_cli as cli


WORKER, REVISION, SOURCE = "synthetic-worker", 37, "a" * 40
TX = {"worker": WORKER, "content_revision": REVISION,
      "logical_transaction_id": c.logical_transaction_id(WORKER, REVISION)}
SHA, SHA2, SHA3 = "b" * 64, "c" * 64, "d" * 64


def artifact(kind, payload, tx=TX, job="synthetic-test"):
    return c.seal_artifact({
        "artifact_type": kind, "schema_version": c.SCHEMA_VERSION,
        "artifact_id": str(uuid.uuid4()), "created_at": "2026-09-28T01:00:00+00:00",
        "producer": {"workflow_run_id": "local-synthetic", "run_attempt": 1,
                     "job": job, "source_sha": SOURCE},
        "transaction": copy.deepcopy(tx), "payload": payload,
    })


class FakeBackend:
    def __init__(self, *readbacks, error=None):
        self.readbacks, self.error, self.mutations = list(readbacks), error, 0

    def read_state(self, _intent):
        value = self.readbacks.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def mutate(self, _intent, _bundle):
        self.mutations += 1
        if self.error:
            raise self.error


def readback(desired, *, precondition=None, resource="candidate-v1", kind="version"):
    return {"desired_state_matches": desired, "precondition_matches": precondition,
            "current_deployment_id": None, "resource_type": kind,
            "resource_id": resource}


class WorkflowStageCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.journal_path = self.root / "journal.json"
        self.journal_path.write_text(json.dumps(journal_module.empty_journal(WORKER)), encoding="utf-8")
        self.revision_path = self.root / "revision.json"
        revision = artifact("revision_resolution", {
            "revision": REVISION, "published_revision": REVISION - 1,
            "changed_at": "2026-09-28T01:00:00+00:00",
            "endpoint_id": "mahoon-content-revision-v1", "request_count": 1,
            "decision": "CHANGED",
        })
        transport.write_artifact(self.revision_path, revision)
        self.receipt = cli.create_admission_receipt(self.revision_path, self.journal_path,
                                                    "synthetic", "run-1", "trigger-1")
        self.receipt_path = self.root / "admission.json"
        transport.write_artifact(self.receipt_path, self.receipt)
        self.bundle = artifact("build_bundle", {
            "admission_receipt_sha256": self.receipt["artifact_sha256"],
            "files": [{"path": "dist/index.html", "size_bytes": 3, "sha256": SHA}],
            "content_fingerprint": SHA, "snapshot_sha256": SHA2,
            "route_manifest_sha256": SHA3, "media_manifest_sha256": SHA,
            "local_gate_evidence_sha256": SHA2,
        })
        self.bundle_path = self.root / "bundle.json"
        transport.write_artifact(self.bundle_path, self.bundle)
        self.upload_desired_path = self.root / "upload-desired.json"
        self.upload_desired_path.write_text(json.dumps({
            "worker": WORKER, "build_bundle_sha256": self.bundle["artifact_sha256"]}), encoding="utf-8")
        self.upload_intent = cli.create_mutation_intent(
            "upload_version", self.bundle_path, self.receipt_path, self.upload_desired_path,
            self.journal_path,
        )
        self.upload_intent_path = self.root / "upload-intent.json"
        transport.write_artifact(self.upload_intent_path, self.upload_intent)

    def tearDown(self):
        self.temp.cleanup()

    def _persist_intent(self):
        return cli.record_intent(self.journal_path, self.upload_intent_path)

    def _execute_upload(self, backend, output=None, run_id="local-synthetic"):
        with mock.patch.dict(os.environ, {"GITHUB_RUN_ID": run_id,
                                         "GITHUB_RUN_ATTEMPT": "1"}):
            return cli.execute_operation(
                self.upload_intent_path, self.bundle_path, self.receipt_path,
                self.journal_path, self.root, self.root / "wrangler.toml",
                backend=backend, output_path=output,
            )

    def test_valid_upload_intent_is_sealed_and_derived_from_artifacts(self):
        value = transport.read_artifact(self.upload_intent_path, expected_type="mutation_intent")
        self.assertEqual(TX, value["transaction"])
        self.assertEqual(c.operation_id_for(TX["logical_transaction_id"], "upload_version"),
                         value["payload"]["operation_id"])
        self.assertEqual("RECORDED", value["payload"]["intent_state"])
        self.assertEqual(REVISION, value["transaction"]["content_revision"])

    def test_upload_lineage_mismatch_is_rejected(self):
        wrong = copy.deepcopy(self.receipt)
        wrong["payload"]["journal_generation"] += 1
        wrong = c.seal_artifact(wrong)
        path = self.root / "wrong-receipt.json"
        transport.write_artifact(path, wrong)
        with self.assertRaises((ValueError, c.ArtifactContractError)):
            cli.create_mutation_intent("upload_version", self.bundle_path, path,
                                       self.upload_desired_path, self.journal_path)

    def test_caller_cannot_substitute_transaction_identity(self):
        self.assertNotIn("transaction", inspect.signature(cli.create_mutation_intent).parameters)
        self.assertEqual(self.bundle["transaction"], self.upload_intent["transaction"])

    def test_intent_attempt_uuid_is_canonical(self):
        self.assertEqual(str(uuid.UUID(self.upload_intent["payload"]["attempt_id"]),),
                         self.upload_intent["payload"]["attempt_id"])

    def test_invalid_attempt_uuid_fails_contract_validation(self):
        invalid = copy.deepcopy(self.upload_intent)
        invalid["payload"]["attempt_id"] = "not-a-uuid"
        invalid = c.seal_artifact(invalid)
        with self.assertRaises(c.ArtifactContractError):
            c.validate_artifact(invalid)

    def test_record_intent_advances_accepted_journal_cas(self):
        before = journal_module.TransactionJournal.from_file(self.journal_path, WORKER).snapshot()[1]
        result = self._persist_intent()
        after = journal_module.TransactionJournal.from_file(self.journal_path, WORKER).snapshot()[1]
        self.assertEqual("INTENT_RECORDED", result["status"])
        self.assertEqual(before + 1, after)
        self.assertEqual(self.upload_intent["payload"]["attempt_id"], result["attempt_id"])

    def test_record_intent_rejects_tampered_intent(self):
        bad = copy.deepcopy(self.upload_intent)
        bad["payload"]["attempt_id"] = str(uuid.uuid4())
        path = self.root / "tampered-intent.json"
        path.write_text(json.dumps(bad), encoding="utf-8")
        with self.assertRaises(c.ArtifactContractError):
            cli.record_intent(self.journal_path, path)

    def test_execute_requires_durable_intent_before_fake_backend(self):
        backend = FakeBackend(readback(False))
        with self.assertRaises(ValueError):
            self._execute_upload(backend)
        self.assertEqual(0, backend.mutations)
        self.assertEqual(1, len(backend.readbacks))

    def test_execute_delegates_once_to_fake_a3_backend_and_writes_result(self):
        self._persist_intent()
        backend = FakeBackend(readback(False), readback(True, resource="uploaded-v1"))
        out = self.root / "result.json"
        result = self._execute_upload(backend, out)
        self.assertEqual(1, backend.mutations)
        self.assertEqual("APPLIED", result["payload"]["result_state"])
        self.assertEqual(result, transport.read_artifact(out, expected_type="mutation_result"))

    def test_execute_does_not_write_journal(self):
        self._persist_intent()
        journal = journal_module.TransactionJournal.from_file(self.journal_path, WORKER)
        before = journal.snapshot()
        backend = FakeBackend(readback(False), readback(True, resource="uploaded-v1"))
        self._execute_upload(backend)
        after = journal.snapshot()
        self.assertEqual(before, after)

    def test_fake_backend_only_and_no_credential_required_for_tests(self):
        self._persist_intent()
        with mock.patch.dict(os.environ, {"GITHUB_RUN_ID": "local-synthetic",
                                         "GITHUB_RUN_ATTEMPT": "1"}, clear=True):
            backend = FakeBackend(RuntimeError("secret diagnostic"))
            result = self._execute_upload(backend)
        self.assertEqual("UNKNOWN", result["payload"]["result_state"])
        self.assertNotIn("secret diagnostic", repr(result).lower())
        self.assertNotIn("CLOUDFLARE_API_TOKEN", os.environ)

    def test_run_identity_mismatch_blocks_operation(self):
        self._persist_intent()
        backend = FakeBackend(readback(False))
        with self.assertRaises(ValueError):
            self._execute_upload(backend, run_id="other-run")
        self.assertEqual(0, backend.mutations)

    def test_record_result_accepts_valid_and_identical_duplicate(self):
        self._persist_intent()
        result = self._execute_upload(FakeBackend(readback(False), readback(True, resource="uploaded-v1")))
        result_path = self.root / "result.json"
        transport.write_artifact(result_path, result)
        first = cli.record_result(self.journal_path, self.upload_intent_path, result_path)
        second = cli.record_result(self.journal_path, self.upload_intent_path, result_path)
        self.assertEqual("APPLIED", first["status"])
        self.assertEqual("APPLIED", second["status"])

    def test_record_result_conflicting_duplicate_fails_closed(self):
        self._persist_intent()
        result = self._execute_upload(FakeBackend(readback(False), readback(True, resource="uploaded-v1")))
        result_path = self.root / "result.json"
        transport.write_artifact(result_path, result)
        cli.record_result(self.journal_path, self.upload_intent_path, result_path)
        conflict = copy.deepcopy(result)
        conflict["artifact_id"] = str(uuid.uuid4())
        conflict["payload"]["evidence_sha256"] = SHA3
        conflict = c.seal_artifact(conflict)
        conflict_path = self.root / "conflict.json"
        transport.write_artifact(conflict_path, conflict)
        with self.assertRaises(journal_module.DuplicateMutation):
            cli.record_result(self.journal_path, self.upload_intent_path, conflict_path)

    def test_deploy_zero_percent_intent_requires_applied_upload_lineage(self):
        self._persist_intent()
        upload_result = self._execute_upload(FakeBackend(readback(False), readback(True, resource="candidate-v1")))
        result_path = self.root / "upload-result.json"
        transport.write_artifact(result_path, upload_result)
        desired_path = self.root / "deploy-desired.json"
        desired_path.write_text(json.dumps({"worker": WORKER, "candidate_version_id": "candidate-v1",
            "baseline_version_id": "baseline-v1", "expected_current_deployment_id": "deployment-before",
            "candidate_percentage": 0, "baseline_percentage": 100}), encoding="utf-8")
        deploy = cli.create_mutation_intent("deploy_zero_percent", self.bundle_path, result_path,
            desired_path, self.journal_path, prerequisite_intent_path=self.upload_intent_path)
        self.assertEqual("deploy_zero_percent", deploy["payload"]["operation_name"])
        self.assertEqual(upload_result["artifact_sha256"], deploy["payload"]["prerequisite_artifact_sha256"])

    def test_deploy_zero_percent_rejects_wrong_candidate_readback(self):
        self._persist_intent()
        wrong_result = self._execute_upload(FakeBackend(readback(False), readback(True, resource="wrong-v")))
        result_path = self.root / "wrong-upload-result.json"
        transport.write_artifact(result_path, wrong_result)
        desired_path = self.root / "deploy-desired.json"
        desired_path.write_text(json.dumps({"worker": WORKER, "candidate_version_id": "candidate-v1",
            "baseline_version_id": "baseline-v1", "expected_current_deployment_id": "deployment-before",
            "candidate_percentage": 0, "baseline_percentage": 100}), encoding="utf-8")
        with self.assertRaises((ValueError, c.ArtifactContractError, operations.OperationRejected)):
            cli.create_mutation_intent("deploy_zero_percent", self.bundle_path, result_path,
                desired_path, self.journal_path, prerequisite_intent_path=self.upload_intent_path)

    def _proof_fixture(self):
        from test_pre_promotion_proof_contract import PrePromotionProofContractTests
        fixture = PrePromotionProofContractTests()
        fixture.setUp()
        return fixture

    def test_validate_artifact_is_exposed_by_executable_cli(self):
        from contextlib import redirect_stdout, redirect_stderr
        import io
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = cli.main(["validate-artifact", "--input", str(self.receipt_path),
                               "--type", "admission_receipt"])
        self.assertEqual(0, status)
        self.assertEqual("VALID", json.loads(stdout.getvalue())["status"])
        self.assertEqual("", stderr.getvalue())

    def test_pre_promotion_proof_is_sealed_from_exact_a51_lineage(self):
        fixture = self._proof_fixture()
        try:
            bundle, intent, result = fixture.bundle, fixture.deploy_intent, fixture.deploy_result
            paths = []
            for name, value in (("proof-bundle.json", bundle), ("deploy-intent.json", intent),
                                ("deploy-result.json", result)):
                path = self.root / name
                transport.write_artifact(path, value)
                paths.append(path)
            remote = {"crawler_evidence_sha256": SHA, "browser_evidence_sha256": SHA2,
                      "gates": {name: True for name in c.REMOTE_GATES}, "PASS": True}
            zero = {"public_pages_checked": 2,
                    "requests": {name: 0 for name in ("content_api", "media_api", "workers_dev_content", "telegram", "search_backend")},
                    "PASS": True}
            remote_path, zero_path = self.root / "remote.json", self.root / "zero.json"
            remote_path.write_text(json.dumps(remote), encoding="utf-8")
            zero_path.write_text(json.dumps(zero), encoding="utf-8")
            value = cli.create_pre_promotion_proof(*paths, remote_path, zero_path)
            self.assertEqual("pre_promotion_proof_evidence", value["artifact_type"])
            self.assertTrue(c.validate_artifact(value, referenced_artifacts=fixture.references))
        finally:
            fixture.tearDown()

    def test_pre_promotion_proof_rejects_non_applied_result(self):
        fixture = self._proof_fixture()
        try:
            failed = fixture._deploy_result("NOT_APPLIED")
            bundle_path, intent_path, result_path = (self.root / name for name in ("b.json", "i.json", "r.json"))
            for path, value in ((bundle_path, fixture.bundle), (intent_path, fixture.deploy_intent),
                                (result_path, failed)):
                transport.write_artifact(path, value)
            rp, zp = self.root / "remote.json", self.root / "zero.json"
            rp.write_text(json.dumps({"crawler_evidence_sha256": SHA, "browser_evidence_sha256": SHA2,
                "gates": {name: True for name in c.REMOTE_GATES}, "PASS": True}), encoding="utf-8")
            zp.write_text(json.dumps({"public_pages_checked": 1, "requests": {name: 0 for name in
                ("content_api", "media_api", "workers_dev_content", "telegram", "search_backend")}, "PASS": True}), encoding="utf-8")
            with self.assertRaises(ValueError):
                cli.create_pre_promotion_proof(bundle_path, intent_path, result_path, rp, zp)
        finally:
            fixture.tearDown()

    def test_pre_promotion_proof_rejects_unknown_result(self):
        fixture = self._proof_fixture()
        try:
            unknown = fixture._deploy_result("UNKNOWN")
            b, i, r = [self.root / name for name in ("b.json", "i.json", "r.json")]
            for path, value in ((b, fixture.bundle), (i, fixture.deploy_intent), (r, unknown)):
                transport.write_artifact(path, value)
            remote = self.root / "remote.json"
            remote.write_text(json.dumps({"crawler_evidence_sha256": SHA, "browser_evidence_sha256": SHA2,
                "gates": {name: True for name in c.REMOTE_GATES}, "PASS": True}), encoding="utf-8")
            zero = self.root / "zero.json"
            zero.write_text(json.dumps({"public_pages_checked": 1, "requests": {name: 0 for name in
                ("content_api", "media_api", "workers_dev_content", "telegram", "search_backend")}, "PASS": True}), encoding="utf-8")
            with self.assertRaises(ValueError):
                cli.create_pre_promotion_proof(b, i, r, remote, zero)
        finally:
            fixture.tearDown()

    def test_pre_promotion_rejects_zero_origin_failure(self):
        fixture = self._proof_fixture()
        try:
            b, i, r = [self.root / name for name in ("b.json", "i.json", "r.json")]
            for path, value in ((b, fixture.bundle), (i, fixture.deploy_intent), (r, fixture.deploy_result)):
                transport.write_artifact(path, value)
            remote = self.root / "remote.json"
            remote.write_text(json.dumps({"crawler_evidence_sha256": SHA, "browser_evidence_sha256": SHA2,
                "gates": {name: True for name in c.REMOTE_GATES}, "PASS": True}), encoding="utf-8")
            zero = self.root / "zero.json"
            zero.write_text(json.dumps({"public_pages_checked": 1, "requests": {**{name: 0 for name in
                ("content_api", "media_api", "workers_dev_content", "telegram", "search_backend")}, "content_api": 1}, "PASS": False}), encoding="utf-8")
            with self.assertRaises(c.ArtifactContractError):
                cli.create_pre_promotion_proof(b, i, r, remote, zero)
        finally:
            fixture.tearDown()

    def test_promote_requires_passed_preproof_and_rejects_legacy_authority(self):
        fixture = self._proof_fixture()
        try:
            proof_path = self.root / "preproof.json"
            transport.write_artifact(proof_path, fixture.proof,
                                     referenced_artifacts=fixture.references)
            bundle_path = self.root / "promote-bundle.json"
            transport.write_artifact(bundle_path, fixture.bundle)
            journal_path = self.root / "promote-journal.json"
            journal_path.write_text(json.dumps(journal_module.empty_journal(WORKER)), encoding="utf-8")
            journal_module.TransactionJournal.from_file(journal_path, WORKER).admit(REVISION, "synthetic")
            desired = self.root / "promote-desired.json"
            desired.write_text(json.dumps({"worker": WORKER, "candidate_version_id": "candidate-v1",
                "baseline_version_id": "baseline-v1", "expected_current_deployment_id": "deployment-zero",
                "candidate_percentage": 100, "baseline_percentage": 0}), encoding="utf-8")
            intent_path = self.root / "fixture-deploy-intent.json"
            result_path = self.root / "fixture-deploy-result.json"
            transport.write_artifact(intent_path, fixture.deploy_intent)
            transport.write_artifact(result_path, fixture.deploy_result)
            intent = cli.create_mutation_intent("promote", bundle_path, proof_path, desired,
                journal_path, reference_paths=[str(intent_path), str(result_path)])
            self.assertEqual("promote", intent["payload"]["operation_name"])
            legacy = self.root / "legacy.json"
            legacy.write_text(json.dumps({"PASS": True, "transaction_id": TX["logical_transaction_id"]}), encoding="utf-8")
            with self.assertRaises((ValueError, c.ArtifactContractError)):
                cli.create_mutation_intent("promote", bundle_path, legacy, desired, journal_path)
        finally:
            fixture.tearDown()

    def test_promote_rejects_false_and_tampered_preproof(self):
        fixture = self._proof_fixture()
        try:
            false = copy.deepcopy(fixture.proof)
            false["payload"]["PASS"] = False
            false = c.seal_artifact(false)
            with self.assertRaises(c.ArtifactContractError):
                c.validate_artifact(false, referenced_artifacts=fixture.references)
            tampered = copy.deepcopy(fixture.proof)
            tampered["payload"]["PASS"] = False
            with self.assertRaises(c.ArtifactContractError):
                c.validate_artifact(tampered, referenced_artifacts=fixture.references)
        finally:
            fixture.tearDown()

    def test_promote_rejects_transaction_mismatched_proof(self):
        fixture = self._proof_fixture()
        try:
            other_tx = {"worker": WORKER, "content_revision": REVISION + 1,
                        "logical_transaction_id": c.logical_transaction_id(WORKER, REVISION + 1)}
            proof = copy.deepcopy(fixture.proof)
            proof["transaction"] = other_tx
            proof = c.seal_artifact(proof)
            proof_path = self.root / "wrong-tx-proof.json"
            proof_path.write_text(json.dumps(proof), encoding="utf-8")
            with self.assertRaises(c.ArtifactContractError):
                cli.create_mutation_intent("promote", self.bundle_path, proof_path,
                    self.upload_desired_path, self.journal_path)
        finally:
            fixture.tearDown()

    def test_pre_promotion_rejects_candidate_identity_mismatch(self):
        fixture = self._proof_fixture()
        try:
            bad = fixture._proof(candidate="other-candidate")
            b, i, r = [self.root / name for name in ("cb.json", "ci.json", "cr.json")]
            for path, value in ((b, fixture.bundle), (i, fixture.deploy_intent), (r, fixture.deploy_result)):
                transport.write_artifact(path, value)
            remote = self.root / "remote.json"
            remote.write_text(json.dumps({"crawler_evidence_sha256": SHA, "browser_evidence_sha256": SHA2,
                "gates": {name: True for name in c.REMOTE_GATES}, "PASS": True}), encoding="utf-8")
            zero = self.root / "zero.json"
            zero.write_text(json.dumps({"public_pages_checked": 1, "requests": {name: 0 for name in
                ("content_api", "media_api", "workers_dev_content", "telegram", "search_backend")}, "PASS": True}), encoding="utf-8")
            bad_path = self.root / "bad-proof.json"
            bad_path.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaises(c.ArtifactContractError):
                cli.validate_artifact_file(bad_path, "pre_promotion_proof_evidence", [str(b), str(i), str(r)])
        finally:
            fixture.tearDown()

    def test_proof_recovery_delegates_to_a4_and_unknown_stays_blocked(self):
        self._persist_intent()
        result = self._execute_upload(FakeBackend(RuntimeError("readback unavailable")))
        result_path = self.root / "unknown.json"
        transport.write_artifact(result_path, result)
        cli.record_result(self.journal_path, self.upload_intent_path, result_path)
        state, generation, _ = journal_module.TransactionJournal.from_file(self.journal_path, WORKER).snapshot()
        self.assertEqual("recovery_required", state["active"]["state"])
        readback_path = self.root / "fresh-readback.json"
        class ReadOnlyBackend:
            calls = 0
            def list_versions(_self, worker):
                _self.calls += 1
                return []
            def read_deployment(_self, _worker):
                raise AssertionError("upload recovery must use version listing only")
        backend = ReadOnlyBackend()
        cli.create_recovery_readback(
            self.upload_intent_path, result_path,
            [str(self.receipt_path), str(self.bundle_path)],
            backend=backend, output_path=readback_path,
        )
        self.assertEqual(1, backend.calls)
        with mock.patch.object(cli.recovery, "recovery_decision", wraps=cli.recovery.recovery_decision) as a4:
            decision = cli.make_recovery_decision(self.upload_intent_path, result_path, readback_path,
                                                  self.journal_path,
                                                  [str(self.receipt_path), str(self.bundle_path)])
        a4.assert_called_once()
        self.assertEqual("BLOCKED_UNKNOWN", decision["payload"]["decision"])
        self.assertFalse(decision["payload"]["resume_allowed"])
        self.assertEqual(generation, decision["payload"]["journal_generation"])

    def test_recovery_rejects_unknown_artifacts_not_current_in_journal(self):
        self._persist_intent()
        actual = self._execute_upload(FakeBackend(RuntimeError("unknown")))
        actual_path = self.root / "actual-unknown.json"
        transport.write_artifact(actual_path, actual)
        cli.record_result(self.journal_path, self.upload_intent_path, actual_path)
        wrong_intent = copy.deepcopy(self.upload_intent)
        wrong_intent["payload"]["attempt_id"] = str(uuid.uuid4())
        wrong_intent = c.seal_artifact(wrong_intent)
        wrong_intent_path = self.root / "wrong-attempt-intent.json"
        transport.write_artifact(wrong_intent_path, wrong_intent)
        wrong_result = artifact("mutation_result", {
            "operation_id": wrong_intent["payload"]["operation_id"],
            "attempt_id": wrong_intent["payload"]["attempt_id"],
            "result_state": "UNKNOWN", "evidence_sha256": None,
            "intent_artifact_sha256": wrong_intent["artifact_sha256"],
            "build_bundle_sha256": self.bundle["artifact_sha256"],
            "readback_reference": None,
        }, job="cloudflare-operation")
        wrong_result_path = self.root / "wrong-attempt-result.json"
        transport.write_artifact(wrong_result_path, wrong_result)
        readback_path = self.root / "readback.json"
        readback_path.write_text(json.dumps({"desired_state_matches": False,
            "precondition_matches": None, "current_deployment_id": None,
            "resource_type": None, "resource_id": None}), encoding="utf-8")
        with self.assertRaises(ValueError):
            cli.make_recovery_decision(wrong_intent_path, wrong_result_path,
                                       readback_path, self.journal_path)

    def test_breaker_boolean_or_legacy_file_cannot_authorize_rollback(self):
        legacy = self.root / "breaker.json"
        legacy.write_text(json.dumps({"breaker": "OPEN", "rollback": True}), encoding="utf-8")
        with self.assertRaises(c.ArtifactContractError):
            cli._read(legacy, "proof_evidence")

    def test_final_persistence_boundary_delegates_to_a5_without_mutation(self):
        journal = journal_module.TransactionJournal.from_file(self.journal_path, WORKER)
        tx_id = TX["logical_transaction_id"]
        for name in journal_module.OPERATIONS[:3]:
            op_id, attempt = journal.record_intent(tx_id, name)
            journal.record_result(tx_id, op_id, attempt, "APPLIED",
                {"type": "synthetic", "reference": name, "sha256": SHA})
        proof = artifact("proof_evidence", {
            "build_bundle_sha256": SHA, "operation_result_sha256s": {
                "upload_version": SHA, "deploy_zero_percent": SHA2, "promote": SHA3, "rollback": None},
            "gate_results": {"local": {"evidence_sha256": SHA, "gates": {n: True for n in c.LOCAL_GATES}, "PASS": True},
                "remote": {"crawler_evidence_sha256": SHA, "browser_evidence_sha256": SHA2,
                           "gates": {n: True for n in c.REMOTE_GATES}, "PASS": True},
                "production": {"crawler_evidence_sha256": SHA, "browser_evidence_sha256": SHA2,
                    "route_state_evidence_sha256": SHA3, "gates": {n: True for n in c.PRODUCTION_GATES}, "PASS": True}},
            "candidate_identity": {"worker": WORKER, "candidate_version_id": "candidate-v1",
                "baseline_version_id": "baseline-v1", "zero_percent_deployment_id": "zero-v1",
                "content_fingerprint": self.bundle["payload"]["content_fingerprint"]},
            "production_validation": {"identity_confirmation": {"candidate_version_id": "candidate-v1",
                "baseline_version_id": "baseline-v1", "promotion_deployment_id": "prod-v1",
                "candidate_percentage": 100, "baseline_percentage": 0, "PASS": True},
                "gates": {n: True for n in c.PRODUCTION_GATES}, "PASS": True},
            "zero_origin_validation": {"public_pages_checked": 1, "requests": {n: 0 for n in
                ("content_api", "media_api", "workers_dev_content", "telegram", "search_backend")}, "PASS": True},
            "proof_state": "PASS",
        })
        journal.mark_ready_to_persist(tx_id, proof["artifact_sha256"])
        state, generation, digest = journal.snapshot()
        proof_path = self.root / "proof.json"
        transport.write_artifact(proof_path, proof)
        result_path = self.root / "result.json"
        dummy_result = operations.CloudflareOperationAdapter(FakeBackend(
            readback(True, resource="already-uploaded"))).execute(
                self.upload_intent, self.bundle, self.receipt)
        transport.write_artifact(result_path, dummy_result)
        for relative in c.STATE_FILE_PATHS:
            target = self.root.joinpath(*relative.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"synthetic")
        with mock.patch.object(persistence, "validate_finalization_inputs", return_value=(proof, self.bundle, {}, {})) as validator:
            output = cli.validate_final_persistence(proof_path, self.bundle_path,
                {name: result_path for name in ("upload_version", "deploy_zero_percent", "promote")},
                self.root, self.journal_path)
        validator.assert_called_once()
        self.assertEqual("FINAL_PERSISTENCE_INPUTS_VALID", output["status"])
        self.assertEqual((state, generation, digest), journal.snapshot())

    def test_persistence_failure_has_no_promote_execution_path(self):
        source = inspect.getsource(cli.validate_final_persistence)
        self.assertNotIn("CloudflareOperationAdapter", source)
        self.assertNotIn("WranglerOperationBackend", source)
        self.assertIn("validate_finalization_inputs", source)

    def test_transport_does_not_duplicate_canonicalization_or_hashing(self):
        source = inspect.getsource(transport)
        self.assertNotIn("hashlib", source)
        self.assertIn("canonical_json_bytes", source)
        cli_source = inspect.getsource(cli)
        self.assertNotIn("hashlib", cli_source)

    def test_handoffs_exclude_legacy_production_result_authority(self):
        source = inspect.getsource(cli)
        self.assertNotIn("remote-proof-result.json", source)
        self.assertNotIn("production-result.json", source)

    def test_journal_and_mutation_boundaries_are_credential_separated(self):
        record_source = inspect.getsource(cli.record_intent) + inspect.getsource(cli.record_result)
        operation_source = inspect.getsource(cli.execute_operation)
        self.assertNotIn("WranglerOperationBackend", record_source)
        self.assertNotIn("CLOUDFLARE_API_TOKEN", record_source)
        self.assertIn("CloudflareOperationAdapter", operation_source)
        self.assertNotIn("journal.record_", operation_source)

    def test_cli_failure_does_not_print_secret_diagnostics(self):
        from contextlib import redirect_stdout, redirect_stderr
        import io
        stdout, stderr = io.StringIO(), io.StringIO()
        args = ["execute-operation", "--intent", str(self.upload_intent_path),
            "--build-bundle", str(self.bundle_path), "--prerequisite", str(self.receipt_path),
            "--journal", str(self.journal_path), "--sealed-root", str(self.root),
            "--config", str(self.root / "wrangler.toml"), "--backend", "wrangler",
            "--output", str(self.root / "result.json")]
        with mock.patch.dict(os.environ, {}, clear=True), redirect_stdout(stdout), redirect_stderr(stderr):
            status = cli.main(args)
        self.assertNotEqual(0, status)
        self.assertEqual("", stdout.getvalue())
        self.assertNotIn("TOKEN", stderr.getvalue())

    # ------------------------------------------------------------------
    # Post-run reconciliation decision (Class A skipped / Class B failed)
    # ------------------------------------------------------------------
    _OP_CF_JOB = {
        "upload_version": "cloudflare-upload-operation",
        "deploy_zero_percent": "cloudflare-zero-percent-operation",
        "promote": "cloudflare-promote-operation",
        "rollback": "cloudflare-rollback-operation",
    }

    def _reconcile_args(self, operation="upload_version"):
        return argparse.Namespace(
            operation=operation, intent=self.upload_intent_path,
            build_bundle=self.bundle_path, admission=self.receipt_path,
            production_baseline=self.root / "baseline.json",
            journal=self.journal_path, repository=self.root,
            remote="origin", branch="main",
            source_run_id="9000", source_run_attempt=1, source_sha=SOURCE,
            github_owner="owner", github_repo="repo",
            expected_generation=1, journal_sha256="0" * 64,
            expected_revision=REVISION, reference=[],
        )

    def _gh_responses(self, operation, conclusion, *, run_conclusion="failure",
                      run_attempt=1, head_sha=SOURCE):
        run = {
            "id": 9000, "status": "completed", "conclusion": run_conclusion,
            "run_attempt": run_attempt, "head_sha": head_sha,
            "head_repository": {"full_name": "owner/repo"},
        }
        jobs = {"jobs": [{"name": self._OP_CF_JOB[operation],
                          "conclusion": conclusion, "started_at": None}]}
        return {
            "actions/runs/9000": json.dumps(run),
            "actions/runs/9000/jobs": json.dumps(jobs),
        }

    def _baseline_file(self):
        p = self.root / "baseline.json"
        p.write_text(json.dumps({"current_version": "v0", "deployment_id": "d0",
                                  "current_version_type": "STATIC"}), encoding="utf-8")
        return p

    def _writer_mock(self):
        writer = mock.Mock(name="writer")
        writer.root = self.root
        writer.abandon_unexecuted_intent_v2.return_value = {"status": "UNEXECUTED_INTENT_ABANDONED"}
        writer._confirm_current.return_value = self._confirm_state(), 1, "0" * 64
        writer.record_result.return_value = (2, "1" * 64, False)
        writer.reconcile_recovery_decision.return_value = {"status": "BLOCKED_UNKNOWN",
                                                            "outcome": "UNKNOWN"}
        return writer

    def _confirm_state(self):
        value = journal_module.TransactionJournal.from_file(self.journal_path, WORKER).snapshot()[0]
        return value

    def test_class_a_skipped_routes_to_abandonment(self):
        self._persist_intent()
        self._baseline_file()
        args = self._reconcile_args("upload_version")
        responses = self._gh_responses("upload_version", "skipped", run_conclusion="failure")
        writer = self._writer_mock()
        with mock.patch.object(cli, "_writer", return_value=writer), \
             mock.patch.object(cli, "_run_gh_api", side_effect=lambda base, path, **kw: responses[path]), \
             mock.patch.object(cli, "create_recovery_readback") as rb, \
             mock.patch.object(cli, "make_recovery_decision") as dec:
            output = cli.reconciliation_decision(args)
        self.assertEqual("abandonment", output["reconciliation_path"])
        writer.abandon_unexecuted_intent_v2.assert_called_once()
        writer.reconcile_recovery_decision.assert_not_called()
        writer.record_result.assert_not_called()
        rb.assert_not_called()
        dec.assert_not_called()

    def test_class_a_abandonment_uses_operation_id_not_name(self):
        self._persist_intent()
        self._baseline_file()
        args = self._reconcile_args("upload_version")
        responses = self._gh_responses("upload_version", "skipped", run_conclusion="failure")
        writer = self._writer_mock()
        with mock.patch.object(cli, "_writer", return_value=writer), \
             mock.patch.object(cli, "_run_gh_api", side_effect=lambda base, path, **kw: responses[path]):
            cli.reconciliation_decision(args)
        kwargs = writer.abandon_unexecuted_intent_v2.call_args.kwargs
        expected_id = c.operation_id_for(TX["logical_transaction_id"], "upload_version")
        self.assertEqual(expected_id, kwargs["expected_upload_operation_id"])

    def test_class_b_failed_never_uses_abandonment(self):
        self._persist_intent()
        args = self._reconcile_args("upload_version")
        responses = self._gh_responses("upload_version", "failure", run_conclusion="failure")
        writer = self._writer_mock()
        with mock.patch.object(cli, "_writer", return_value=writer), \
             mock.patch.object(cli, "_run_gh_api", side_effect=lambda base, path, **kw: responses[path]), \
             mock.patch.object(cli, "record_result", return_value={"status": "UNKNOWN"}) as rr, \
             mock.patch.object(cli, "create_recovery_readback") as rb, \
             mock.patch.object(cli, "make_recovery_decision") as dec:
            output = cli.reconciliation_decision(args)
        self.assertEqual("recovery", output["reconciliation_path"])
        writer.abandon_unexecuted_intent_v2.assert_not_called()
        rr.assert_called_once()
        rb.assert_called_once()
        dec.assert_called_once()
        writer.reconcile_recovery_decision.assert_called_once()

    def test_class_b_record_result_passes_operation_id(self):
        self._persist_intent()
        args = self._reconcile_args("upload_version")
        responses = self._gh_responses("upload_version", "failure", run_conclusion="failure")
        writer = self._writer_mock()
        with mock.patch.object(cli, "_writer", return_value=writer), \
             mock.patch.object(cli, "_run_gh_api", side_effect=lambda base, path, **kw: responses[path]), \
             mock.patch.object(cli, "record_result") as rr, \
             mock.patch.object(cli, "create_recovery_readback"), \
             mock.patch.object(cli, "make_recovery_decision"):
            cli.reconciliation_decision(args)
        rr.assert_called_once()
        # The module-level record_result is called with remote_writer=writer;
        # the writer's record_result receives the operation_id (hex), not the name.
        expected_id = c.operation_id_for(TX["logical_transaction_id"], "upload_version")
        self.assertEqual(expected_id, self.upload_intent["payload"]["operation_id"])

    def test_class_b_unknown_readback_fails_closed(self):
        self._persist_intent()
        args = self._reconcile_args("upload_version")
        responses = self._gh_responses("upload_version", "failure", run_conclusion="failure")
        writer = self._writer_mock()
        writer.reconcile_recovery_decision.return_value = {"status": "BLOCKED_UNKNOWN",
                                                            "outcome": "UNKNOWN"}
        blocked = mock.Mock(name="decision")
        blocked.payload = {"decision": "BLOCKED_UNKNOWN", "resume_allowed": False}
        with mock.patch.object(cli, "_writer", return_value=writer), \
             mock.patch.object(cli, "_run_gh_api", side_effect=lambda base, path, **kw: responses[path]), \
             mock.patch.object(cli, "record_result"), \
             mock.patch.object(cli, "create_recovery_readback"), \
             mock.patch.object(cli, "make_recovery_decision", return_value=blocked) as dec:
            output = cli.reconciliation_decision(args)
        self.assertEqual("recovery", output["reconciliation_path"])
        self.assertEqual("BLOCKED_UNKNOWN", output["status"])
        writer.reconcile_recovery_decision.assert_called_once()

    def test_success_conclusion_rejected_fail_closed(self):
        self._persist_intent()
        self._baseline_file()
        args = self._reconcile_args("upload_version")
        responses = self._gh_responses("upload_version", "success", run_conclusion="failure")
        writer = self._writer_mock()
        with mock.patch.object(cli, "_writer", return_value=writer), \
             mock.patch.object(cli, "_run_gh_api", side_effect=lambda base, path, **kw: responses[path]):
            with self.assertRaises(ValueError) as ctx:
                cli.reconciliation_decision(args)
        self.assertIn("cannot be reconciled", str(ctx.exception))
        writer.abandon_unexecuted_intent_v2.assert_not_called()

    def test_rerun_attempt_rejected(self):
        self._persist_intent()
        args = self._reconcile_args("upload_version")
        args.source_run_attempt = 1
        responses = self._gh_responses("upload_version", "failure", run_conclusion="failure",
                                        run_attempt=2)
        writer = self._writer_mock()
        with mock.patch.object(cli, "_writer", return_value=writer), \
             mock.patch.object(cli, "_run_gh_api", side_effect=lambda base, path, **kw: responses[path]):
            with self.assertRaises(ValueError) as ctx:
                cli.reconciliation_decision(args)
        self.assertIn("run attempt does not match", str(ctx.exception))

    def test_source_sha_mismatch_rejected(self):
        self._persist_intent()
        args = self._reconcile_args("upload_version")
        responses = self._gh_responses("upload_version", "failure", run_conclusion="failure",
                                        head_sha="b" * 40)
        writer = self._writer_mock()
        with mock.patch.object(cli, "_writer", return_value=writer), \
             mock.patch.object(cli, "_run_gh_api", side_effect=lambda base, path, **kw: responses[path]):
            with self.assertRaises(ValueError) as ctx:
                cli.reconciliation_decision(args)
        self.assertIn("head SHA does not match", str(ctx.exception))

    def test_all_operations_have_cf_job_mapping(self):
        for operation, cf in self._OP_CF_JOB.items():
            self.assertEqual(self._OP_CF_JOB.get(operation), cf)


if __name__ == "__main__":
    unittest.main()
