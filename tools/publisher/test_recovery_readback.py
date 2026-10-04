from __future__ import annotations

import copy
import hashlib
import inspect
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from publisher import artifact_contract as contracts
from publisher import artifact_transport as transport
from publisher import proof_observation_runner
from publisher import proof_recovery_runner
from publisher import recovery_readback as readback
from publisher import workflow_stage_cli as cli
from test_a53_executors import fresh_proof_fixture


class ReadOnlyBackend:
    def __init__(self, *, versions=None, deployment=None):
        self.versions = versions or []
        self.deployment = deployment or {"id": "dep-current", "versions": []}
        self.version_calls = 0
        self.deployment_calls = 0

    def list_versions(self, _worker):
        self.version_calls += 1
        return copy.deepcopy(self.versions)

    def read_deployment(self, _worker):
        self.deployment_calls += 1
        return copy.deepcopy(self.deployment)


class FreshRecoveryReadbackTests(unittest.TestCase):
    def setUp(self):
        self.f = fresh_proof_fixture()
        self.addCleanup(self.f.tearDown)
        self.now = datetime.now(timezone.utc)
        self.timestamp = lambda: self.now.isoformat()
        self.base_artifacts = [
            self.f.receipt, self.f.bundle,
            self.f.upload_intent, self.f.upload_result,
            self.f.deploy_intent, self.f.deploy_result,
            self.f.prepromotion_proof, self.f.promote_intent,
            self.f.promote_result, self.f.proof,
        ]

    def _refs(self, *more):
        return transport.references(*self.base_artifacts, *more)

    def _inputs(self, operation="upload_version", *, stale_reference=False):
        intent = {
            "upload_version": self.f.upload_intent,
            "deploy_zero_percent": self.f.deploy_intent,
            "promote": self.f.promote_intent,
        }.get(operation)
        extra = []
        if operation == "rollback":
            failed = self.f._proof(failed_production=True)
            intent = self.f._intent("rollback", failed, {
                "worker": self.f.tx["worker"], "baseline_version_id": "baseline-v1",
                "failed_candidate_version_id": "candidate-v1",
                "expected_current_deployment_id": "dep-promoted",
                "baseline_percentage": 100, "candidate_percentage": 0,
            })
            extra.append(failed)
        resource_type = "version" if operation == "upload_version" else "deployment"
        result = self.f._result(
            intent, "UNKNOWN", resource_type,
            "stale-resource" if stale_reference else None,
        )
        refs = self._refs(intent, result, *extra)
        return intent, result, refs

    def _collect(self, operation="upload_version", *, backend=None, stale_reference=False):
        intent, result, refs = self._inputs(operation, stale_reference=stale_reference)
        backend = backend or ReadOnlyBackend()
        value = readback.collect_fresh_readback(
            intent, result, references=refs, backend=backend, clock=self.timestamp,
        )
        return value, intent, result, refs, backend

    def _retag(self, value):
        result = dict(value)
        result.pop("evidence_sha256")
        result["evidence_sha256"] = hashlib.sha256(contracts.canonical_json_bytes(result)).hexdigest()
        return result

    def test_01_unknown_is_required_before_any_cloudflare_read(self):
        intent, _, refs = self._inputs()
        applied = self.f.upload_result
        backend = ReadOnlyBackend()
        with self.assertRaises(readback.RecoveryReadbackRejected):
            readback.collect_fresh_readback(intent, applied, references=refs, backend=backend)
        self.assertEqual(0, backend.version_calls + backend.deployment_calls)

    def test_02_applied_result_cannot_enter_unknown_observation_path(self):
        intent, _, refs = self._inputs()
        backend = ReadOnlyBackend()
        with self.assertRaises(readback.RecoveryReadbackRejected):
            readback.collect_fresh_readback(intent, self.f.upload_result, references=refs, backend=backend)
        self.assertEqual(0, backend.version_calls)

    def test_03_not_applied_result_cannot_masquerade_as_unknown(self):
        intent, _, refs = self._inputs("deploy_zero_percent")
        result = self.f._result(intent, "NOT_APPLIED", "deployment", "dep-before")
        refs = self._refs(intent, result)
        backend = ReadOnlyBackend()
        with self.assertRaises(readback.RecoveryReadbackRejected):
            readback.collect_fresh_readback(intent, result, references=refs, backend=backend)
        self.assertEqual(0, backend.deployment_calls)

    def test_04_tampered_result_is_rejected_before_read(self):
        intent, result, refs = self._inputs()
        bad = copy.deepcopy(result); bad["payload"]["attempt_id"] = "00000000-0000-4000-8000-000000000000"
        backend = ReadOnlyBackend()
        with self.assertRaises(Exception):
            readback.collect_fresh_readback(intent, bad, references=refs, backend=backend)
        self.assertEqual(0, backend.version_calls)

    def test_05_tampered_intent_is_rejected_before_read(self):
        intent, result, refs = self._inputs()
        bad = copy.deepcopy(intent); bad["payload"]["attempt_id"] = "00000000-0000-4000-8000-000000000000"
        backend = ReadOnlyBackend()
        with self.assertRaises(Exception):
            readback.collect_fresh_readback(bad, result, references=refs, backend=backend)
        self.assertEqual(0, backend.version_calls)

    def test_06_transaction_mismatch_is_rejected(self):
        intent, result, refs = self._inputs()
        bad = copy.deepcopy(result)
        bad["transaction"]["content_revision"] += 1
        bad["transaction"]["logical_transaction_id"] = contracts.logical_transaction_id(
            bad["transaction"]["worker"], bad["transaction"]["content_revision"],
        )
        bad = contracts.seal_artifact(bad)
        backend = ReadOnlyBackend()
        with self.assertRaises(Exception):
            readback.collect_fresh_readback(intent, bad, references=refs, backend=backend)
        self.assertEqual(0, backend.version_calls)

    def test_07_operation_mismatch_is_rejected(self):
        value, intent, result, refs, _ = self._collect()
        bad = dict(value); bad["operation_name"] = "promote"
        with self.assertRaises(readback.RecoveryReadbackRejected):
            readback.validate_fresh_readback(self._retag(bad), intent, result, references=refs, now=self.now)

    def test_08_operation_id_mismatch_is_rejected(self):
        value, intent, result, refs, _ = self._collect()
        bad = dict(value); bad["operation_id"] = "0" * 64
        with self.assertRaises(readback.RecoveryReadbackRejected):
            readback.validate_fresh_readback(self._retag(bad), intent, result, references=refs, now=self.now)

    def test_09_attempt_mismatch_is_rejected(self):
        value, intent, result, refs, _ = self._collect()
        bad = dict(value); bad["attempt_id"] = "00000000-0000-4000-8000-000000000000"
        with self.assertRaises(readback.RecoveryReadbackRejected):
            readback.validate_fresh_readback(self._retag(bad), intent, result, references=refs, now=self.now)

    def test_10_source_or_build_identity_mismatch_is_rejected(self):
        value, intent, result, refs, _ = self._collect()
        for field, replacement in (("source_sha", "f" * 40), ("build_bundle_sha256", "0" * 64)):
            with self.subTest(field=field):
                bad = dict(value); bad[field] = replacement
                with self.assertRaises(readback.RecoveryReadbackRejected):
                    readback.validate_fresh_readback(self._retag(bad), intent, result, references=refs, now=self.now)

    def test_11_candidate_mismatch_is_rejected(self):
        value, intent, result, refs, _ = self._collect("deploy_zero_percent")
        bad = dict(value); bad["candidate_version_id"] = "other-candidate"
        with self.assertRaises(readback.RecoveryReadbackRejected):
            readback.validate_fresh_readback(self._retag(bad), intent, result, references=refs, now=self.now)

    def test_12_baseline_mismatch_is_rejected(self):
        value, intent, result, refs, _ = self._collect("deploy_zero_percent")
        bad = dict(value); bad["baseline_version_id"] = "other-baseline"
        with self.assertRaises(readback.RecoveryReadbackRejected):
            readback.validate_fresh_readback(self._retag(bad), intent, result, references=refs, now=self.now)

    def test_13_one_fresh_cloudflare_read_is_invoked_exactly_once(self):
        value, _, _, _, backend = self._collect()
        self.assertEqual(1, backend.version_calls)
        self.assertEqual(0, backend.deployment_calls)
        self.assertEqual("MAHOON_FRESH_RECOVERY_READBACK_V1", value["evidence_type"])

    def test_14_readback_producer_exposes_no_mutation_backend_method(self):
        backend = ReadOnlyBackend()
        self.assertFalse(hasattr(backend, "mutate"))
        self.assertFalse(hasattr(readback.WranglerReadOnlyBackend(), "mutate"))

    def test_15_readback_source_has_no_cloudflare_mutation_capability(self):
        source = inspect.getsource(readback)
        for forbidden in ("cloudflare_operation_adapter", "deploy_pair(", "upload_version(",
                          "rollback_to_previous_static(", "TransactionJournal", "GitRepositoryWriter"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_16_readback_source_has_no_journal_database_git_or_dispatch_writer(self):
        source = inspect.getsource(readback)
        for forbidden in ("D1", "subprocess", "git push", "workflow dispatch", "record_result(", "record_intent("):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_17_all_four_operation_readback_shapes_are_supported(self):
        cases = {
            "upload_version": ReadOnlyBackend(versions=[]),
            "deploy_zero_percent": ReadOnlyBackend(deployment={
                "id": "dep-zero", "versions": [{"version_id": "baseline-v1", "percentage": 100},
                    {"version_id": "candidate-v1", "percentage": 0}]}),
            "promote": ReadOnlyBackend(deployment={
                "id": "dep-promoted", "versions": [{"version_id": "candidate-v1", "percentage": 100},
                    {"version_id": "baseline-v1", "percentage": 0}]}),
            "rollback": ReadOnlyBackend(deployment={
                "id": "dep-rollback", "versions": [{"version_id": "baseline-v1", "percentage": 100},
                    {"version_id": "candidate-v1", "percentage": 0}]}),
        }
        for operation, backend in cases.items():
            with self.subTest(operation=operation):
                value, intent, result, refs, _ = self._collect(operation, backend=backend)
                self.assertEqual(operation, value["operation_name"])
                contracts.validate_intent_result_pair(intent, result, referenced_artifacts=refs)

    def test_18_desired_state_and_its_digest_are_bound_exactly(self):
        value, intent, result, refs, _ = self._collect("promote")
        desired = intent["payload"]["desired_state"]
        self.assertEqual(desired, value["desired_state"])
        self.assertEqual(hashlib.sha256(contracts.canonical_json_bytes(desired)).hexdigest(),
                         value["desired_state_sha256"])
        readback.validate_fresh_readback(value, intent, result, references=refs, now=self.now)

    def test_19_precondition_and_current_deployment_are_fresh(self):
        value, intent, result, refs, _ = self._collect("deploy_zero_percent", backend=ReadOnlyBackend(
            deployment={"id": "dep-before", "versions": [{"version_id": "baseline-v1", "percentage": 100}]}))
        self.assertTrue(value["readback"]["precondition_matches"])
        self.assertEqual("dep-before", value["readback"]["current_deployment_id"])
        self.assertFalse(value["readback"]["desired_state_matches"])
        readback.validate_fresh_readback(value, intent, result, references=refs, now=self.now)

    def test_20_freshness_rejects_stale_and_future_evidence(self):
        value, intent, result, refs, _ = self._collect()
        for now in (self.now + timedelta(seconds=readback.MAX_AGE_SECONDS + 1),
                    self.now - timedelta(seconds=1)):
            with self.subTest(now=now):
                with self.assertRaises(readback.RecoveryReadbackRejected):
                    readback.validate_fresh_readback(value, intent, result, references=refs, now=now)

    def test_21_tampered_readback_body_or_digest_is_rejected(self):
        value, intent, result, refs, _ = self._collect()
        bad = copy.deepcopy(value); bad["readback"]["desired_state_matches"] = True
        with self.assertRaises(readback.RecoveryReadbackRejected):
            readback.validate_fresh_readback(bad, intent, result, references=refs, now=self.now)
        bad = dict(value); bad["readback_sha256"] = "0" * 64
        with self.assertRaises(readback.RecoveryReadbackRejected):
            readback.validate_fresh_readback(bad, intent, result, references=refs, now=self.now)

    def test_22_fresh_evidence_cannot_be_substituted_across_transactions(self):
        value, intent, result, refs, _ = self._collect()
        other_tx = {"worker": "other-worker", "content_revision": 37,
                    "logical_transaction_id": contracts.logical_transaction_id("other-worker", 37)}
        other_intent = copy.deepcopy(intent); other_intent["transaction"] = other_tx
        other_intent = contracts.seal_artifact(other_intent)
        with self.assertRaises(Exception):
            readback.validate_fresh_readback(value, other_intent, result, references=refs, now=self.now)

    def test_23_stale_mutation_result_reference_is_never_used_as_fresh_state(self):
        backend = ReadOnlyBackend(versions=[])
        value, _intent, _result, _refs, _backend = self._collect(backend=backend, stale_reference=True)
        self.assertEqual(1, backend.version_calls)
        self.assertIsNone(value["readback"]["resource_id"])
        self.assertFalse(value["readback"]["desired_state_matches"])

    def test_24_legacy_proof_and_mutation_result_json_are_not_readback_evidence(self):
        intent, result, refs = self._inputs()
        for legacy in ({"PASS": True}, {"REMOTE_PROOF_PASS": True},
                       {"readback_reference": {"resource_id": "stale"}}):
            with self.subTest(legacy=legacy):
                with self.assertRaises(readback.RecoveryReadbackRejected):
                    readback.validate_fresh_readback(legacy, intent, result, references=refs, now=self.now)

    def test_25_upload_version_matching_operation_marker_proves_applied(self):
        intent, _, _ = self._inputs()
        marker = f"MAHOON-A3:{intent['payload']['operation_id']}:{intent['payload']['attempt_id']}"
        backend = ReadOnlyBackend(versions=[{"id": "candidate-v1", "annotations": {"workers/message": marker}}])
        value, *_ = self._collect(backend=backend)
        self.assertTrue(value["readback"]["desired_state_matches"])
        self.assertEqual("candidate-v1", value["readback"]["resource_id"])

    def test_26_upload_absence_remains_inconclusive_and_never_not_applied(self):
        value, intent, result, refs, _ = self._collect(backend=ReadOnlyBackend(versions=[]))
        decision = contracts.validate_artifact(proof_recovery_runner.recovery_decision(
            intent, result, value["readback"], 5, referenced_artifacts=refs,
        ))
        self.assertEqual("BLOCKED_UNKNOWN", decision["payload"]["decision"])
        self.assertFalse(decision["payload"]["resume_allowed"])

    def test_27_each_deployment_operation_can_reconcile_applied(self):
        cases = {
            "deploy_zero_percent": ("dep-zero", [("baseline-v1", 100), ("candidate-v1", 0)]),
            "promote": ("dep-promoted", [("candidate-v1", 100), ("baseline-v1", 0)]),
            "rollback": ("dep-rollback", [("baseline-v1", 100), ("candidate-v1", 0)]),
        }
        for operation, (deployment_id, entries) in cases.items():
            with self.subTest(operation=operation):
                backend = ReadOnlyBackend(deployment={"id": deployment_id,
                    "versions": [{"version_id": version, "percentage": pct} for version, pct in entries]})
                value, intent, result, refs, _ = self._collect(operation, backend=backend)
                decision = proof_recovery_runner.recovery_decision(
                    intent, result, value["readback"], 5, referenced_artifacts=refs,
                )
                self.assertEqual("RECONCILED_APPLIED", decision["payload"]["decision"])
                self.assertFalse(decision["payload"]["resume_allowed"])

    def test_28_conclusive_not_applied_and_inconclusive_states_remain_fail_closed(self):
        backend = ReadOnlyBackend(deployment={"id": "dep-before",
            "versions": [{"version_id": "baseline-v1", "percentage": 100}]})
        value, intent, result, refs, _ = self._collect("deploy_zero_percent", backend=backend)
        decision = proof_recovery_runner.recovery_decision(
            intent, result, value["readback"], 5, referenced_artifacts=refs,
        )
        self.assertEqual("RECONCILED_NOT_APPLIED", decision["payload"]["decision"])
        self.assertTrue(decision["payload"]["resume_allowed"])
        unclear = ReadOnlyBackend(deployment={"id": "dep-other",
            "versions": [{"version_id": "other-v", "percentage": 100}]})
        value, intent, result, refs, _ = self._collect("deploy_zero_percent", backend=unclear)
        decision = proof_recovery_runner.recovery_decision(
            intent, result, value["readback"], 5, referenced_artifacts=refs,
        )
        self.assertEqual("BLOCKED_UNKNOWN", decision["payload"]["decision"])
        self.assertFalse(decision["payload"]["resume_allowed"])

    def test_29_unknown_recovery_does_not_execute_a_second_mutation(self):
        backend = ReadOnlyBackend(deployment={"id": "dep-other",
            "versions": [{"version_id": "other-v", "percentage": 100}]})
        self._collect("deploy_zero_percent", backend=backend)
        self.assertEqual(1, backend.deployment_calls)
        self.assertFalse(hasattr(backend, "mutate"))

    def test_30_output_context_binds_all_required_lineage_fields(self):
        value, intent, result, _, _ = self._collect("rollback")
        self.assertEqual(intent["transaction"], value["transaction"])
        self.assertEqual(intent["producer"]["source_sha"], value["source_sha"])
        self.assertEqual(intent["payload"]["operation_id"], value["operation_id"])
        self.assertEqual(intent["payload"]["attempt_id"], value["attempt_id"])
        self.assertEqual(result["artifact_sha256"], value["result_artifact_sha256"])
        self.assertEqual(intent["payload"]["desired_state"]["failed_candidate_version_id"],
                         value["candidate_version_id"])

    def test_31_no_new_authoritative_artifact_type_is_added(self):
        self.assertNotIn("fresh_recovery_readback", contracts.ARTIFACT_TYPES)
        self.assertEqual("MAHOON_FRESH_RECOVERY_READBACK_V1", readback.EVIDENCE_TYPE)

    def test_32_read_only_credentials_are_not_part_of_business_logic_contract(self):
        source = inspect.getsource(readback)
        self.assertNotIn("CLOUDFLARE_API_TOKEN", source)
        self.assertNotIn("CLOUDFLARE_READ_API_TOKEN", source)

    def test_33_combined_proof_runner_is_read_only_and_seals_authority(self):
        source = inspect.getsource(proof_observation_runner)
        self.assertNotIn("CloudflareOperationAdapter", source)
        self.assertNotIn("TransactionJournal", source)
        self.assertIn("pre_promotion_proof_evidence", source)
        self.assertIn("proof_evidence", source)

    def test_34_cli_is_only_orchestration_for_readback_producer(self):
        source = inspect.getsource(cli.create_recovery_readback)
        self.assertIn("collect_fresh_readback", source)
        self.assertNotIn("list_versions(", source)
        self.assertNotIn("read_deployment(", source)
        self.assertNotIn("mutate(", source)

    def test_35_cli_readback_command_writes_local_evidence_with_fake_backend(self):
        intent, result, refs = self._inputs()
        with self.subTest(command="nested"), patch.object(cli.recovery_readback, "WranglerReadOnlyBackend",
                return_value=ReadOnlyBackend(versions=[])):
            import tempfile
            with tempfile.TemporaryDirectory() as directory:
                intent_path = Path(directory) / "intent.json"
                result_path = Path(directory) / "result.json"
                output_path = Path(directory) / "fresh.json"
                transport.write_artifact(intent_path, intent, referenced_artifacts=refs)
                transport.write_artifact(result_path, result, referenced_artifacts=refs)
                ref_paths = []
                for index, ref in enumerate(refs.values()):
                    ref_path = Path(directory) / f"ref-{index}.json"
                    transport.write_artifact(ref_path, ref, referenced_artifacts=refs)
                    ref_paths.append(ref_path)
                argv = ["proof-recovery", "recovery-readback-observe", "--intent", str(intent_path),
                        "--result", str(result_path), "--output", str(output_path)]
                for path in ref_paths: argv += ["--reference", str(path)]
                self.assertEqual(0, cli.main(argv))
                checked = readback.read_evidence(output_path, intent=intent, result=result, references=refs)
                self.assertEqual("MAHOON_FRESH_RECOVERY_READBACK_V1", checked["evidence_type"])


if __name__ == "__main__":
    unittest.main()
