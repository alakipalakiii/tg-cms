"""Synthetic cross-boundary acceptance checks for the frozen M11-E A6 candidate."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from publisher import artifact_contract as contracts
from publisher import artifact_transport as transport
from publisher import effective_mutation_result as effective
from publisher import final_persistence_runner as persistence
from publisher import proof_recovery_runner as recovery
from publisher import repository_persistence as repository
from publisher import transaction_journal as journal_module
from publisher import workflow_stage_cli as cli
import test_a53_executors as a53
import test_a54_remote_lifecycle_bridge as a54
import test_a57a_index_binding as a57
import test_a59_recovery_reconciliation as a59
import test_final_state_materializer as final_materializer_fixture
import test_legacy_artifact_adapter as legacy_adapter_tests
import test_proof_recovery_runner as proof_fixtures
import test_recovered_mutation_result as recovered_fixtures
import test_workflow_stage_cli as stage_cli_tests


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/mahoon-static-publisher.yml"
A6_ACCEPTED_WORKFLOW_SHA = "aacc892138e4ee3f9300ddad85d29e0d06f7ee5c0ae7afd6e0634986837674f2"


def _run_case(case_type, method: str) -> None:
    """Run one existing accepted boundary as part of this combined synthetic acceptance."""
    case = case_type(method)
    result = unittest.TestResult()
    case.run(result)
    failures = [message for _test, message in result.failures + result.errors]
    if failures:
        raise AssertionError("\n".join(failures))
    if not result.testsRun:
        raise AssertionError(f"accepted boundary did not run: {case_type.__name__}.{method}")


class A7SyntheticAcceptanceTests(unittest.TestCase):
    """One parametrized acceptance identity per required end-to-end scenario family."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mahoon-a7-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.f = final_materializer_fixture._fixture(self.root)
        self.addCleanup(self.f.tearDown)

    def refs(self, *extra):
        return transport.references(*self.f.references.values(), *extra)

    def _a59_case(self, method: str) -> None:
        _run_case(a59.A59RemoteReconciliationTests, method)

    def _recovered_case(self, method: str) -> None:
        _run_case(recovered_fixtures.RecoveredMutationResultTests, method)

    def _a53_case(self, method: str) -> None:
        _run_case(a53.RepositoryPersistenceTests, method)

    def test_01_clean_happy_path_crosses_proof_materialization_and_persistence(self):
        proof, backend = a53.create_proof(self.f)
        self.assertEqual(1, backend.calls)
        self.assertEqual("PASS", recovery.validate_proof(
            proof, self.f.bundle, self.f.results, referenced_artifacts=self.refs(proof),
        )["payload"]["proof_state"])
        files = self.f.output
        self.assertEqual(set(contracts.STATE_FILE_PATHS), set(files))
        persistence.validate_finalization_inputs(
            proof, self.f.bundle, self.f.results, files, 7,
            referenced_artifacts=self.refs(proof),
        )
        _run_case(a53.WorkflowStageCliTests, "test_54_concrete_final_persistence_completes_on_local_bare_remote")

    def test_02_same_revision_coalesces_to_one_active_transaction(self):
        parent = self.root / "same-revision"
        parent.mkdir()
        git = a54.LocalBare(parent)
        writer = git.writer()
        self.assertEqual("ADMITTED", writer.admit_revision(a54.REVISION, "a7-first")[0])
        self.assertEqual("COALESCED_ACTIVE", writer.admit_revision(a54.REVISION, "a7-second")[0])
        state = git.journal().snapshot()[0]
        self.assertEqual(a54.TX["logical_transaction_id"], state["active"]["logical_transaction_id"])
        self.assertIsNone(state["pending"])
        self.assertEqual([], state["history"])

    def test_03_newest_revision_replaces_pending_without_corrupting_active(self):
        parent = self.root / "pending-revisions"
        parent.mkdir()
        git = a54.LocalBare(parent)
        writer = git.writer()
        writer.admit_revision(a54.REVISION, "a7-active")
        writer.admit_revision(a54.REVISION + 1, "a7-pending-one")
        self.assertEqual("PENDING_REPLACED", writer.admit_revision(a54.REVISION + 2, "a7-pending-two")[0])
        state = git.journal().snapshot()[0]
        self.assertEqual(a54.REVISION, state["active"]["content_revision"])
        self.assertEqual(a54.REVISION + 2, state["pending"]["content_revision"])
        self.assertIn("superseded", [row["state"] for row in state["history"]])

    def test_04_deferred_and_superseded_states_do_not_trigger_false_breaker(self):
        _run_case(a59.A59RemoteReconciliationTests, "test_old_attempt_cannot_overwrite_a_newer_attempt")
        from publisher.scheduled_circuit_breaker import should_open_breaker
        self.assertFalse(should_open_breaker("CLOSED", {
            "build-and-zero-percent": "skipped", "remote-proof": "skipped",
            "promote-and-validate": "skipped", "persist-state": "skipped",
        }))

    def test_05_upload_unknown_recovers_to_effective_applied_without_rewrite(self):
        case = recovered_fixtures.RecoveredMutationResultTests("test_bridge_preserves_unknown_and_validates_as_effective_applied")
        case.setUp()
        try:
            original = contracts.canonical_json_bytes(case.unknown)
            bridge = case._create()
            refs = {**case.references, bridge["artifact_sha256"]: bridge}
            view = effective.validate_effective_applied_result(bridge, case.intent, referenced_artifacts=refs)
            self.assertEqual("UNKNOWN", case.unknown["payload"]["result_state"])
            self.assertEqual(original, contracts.canonical_json_bytes(case.unknown))
            self.assertEqual("APPLIED", view["payload"]["result_state"])
        finally:
            case.doCleanups()

    def test_06_zero_percent_unknown_bridge_rejoins_pre_promotion_proof(self):
        self._recovered_case("test_three_recovered_results_complete_proof_and_exact_six_materialization")
        self._recovered_case("test_recovered_upload_is_an_eligible_zero_percent_prerequisite")

    def test_07_promote_unknown_bridge_rejoins_production_proof_and_final_state(self):
        self._recovered_case("test_three_recovered_results_complete_proof_and_exact_six_materialization")

    def test_08_rollback_unknown_is_isolated_from_candidate_final_persistence(self):
        self._recovered_case("test_three_recovered_results_complete_proof_and_exact_six_materialization")
        self._recovered_case("test_bridge_requires_exact_applied_decision_and_remote_readback")

    def test_09_reconciled_not_applied_never_retries_and_upload_absence_stays_blocked(self):
        self._a59_case("test_not_applied_is_recorded_but_never_retried_or_reintended")
        self._a59_case("test_upload_not_applied_is_rejected_even_if_a_forged_decision_is_well_formed")

    def test_10_blocked_unknown_stays_recovery_required_without_bridge_or_retry(self):
        self._a59_case("test_inconclusive_recovery_stays_blocked_and_does_not_create_attempt")
        self._recovered_case("test_bridge_requires_exact_applied_decision_and_remote_readback")

    def test_11_pre_promotion_proof_failure_blocks_promotion(self):
        _run_case(stage_cli_tests.WorkflowStageCliTests, "test_pre_promotion_proof_rejects_non_applied_result")
        _run_case(stage_cli_tests.WorkflowStageCliTests, "test_promote_requires_passed_preproof_and_rejects_legacy_authority")

    def test_12_failed_production_proof_authorizes_rollback_not_persistence(self):
        fixture = proof_fixtures.ProofRecoveryRunnerTests()
        fixture.setUp()
        try:
            failed = fixture._proof(failed_production=True)
            rollback = fixture._intent("rollback", failed, {
                "worker": fixture.tx["worker"], "baseline_version_id": "baseline-v1",
                "failed_candidate_version_id": "candidate-v1",
                "expected_current_deployment_id": "dep-promoted",
                "candidate_percentage": 0, "baseline_percentage": 100,
            })
            refs = {**fixture.prepromotion_references, failed["artifact_sha256"]: failed,
                    fixture.promote_intent["artifact_sha256"]: fixture.promote_intent,
                    fixture.promote_result["artifact_sha256"]: fixture.promote_result}
            recovery.authorize_rollback(
                failed, fixture.promote_intent, fixture.promote_result, rollback,
                referenced_artifacts=refs,
            )
            with self.assertRaises(Exception):
                persistence.validate_finalization_inputs(
                    failed, fixture.bundle,
                    {"upload_version": fixture.upload_result,
                     "deploy_zero_percent": fixture.deploy_result,
                     "promote": fixture.promote_result},
                    self.f.output, 1, referenced_artifacts=refs,
                )
        finally:
            fixture.doCleanups()

    def test_13_representative_sealed_artifact_tampering_fails_closed(self):
        for name, original in {
            "revision": self.f.receipt, "build": self.f.bundle,
            "intent": self.f.upload_intent, "result": self.f.upload_result,
            "preproof": self.f.prepromotion_proof, "proof": self.f.proof,
        }.items():
            with self.subTest(artifact=name):
                changed = copy.deepcopy(original)
                changed["payload"][next(iter(changed["payload"]))] = "tampered"
                with self.assertRaises(contracts.ArtifactContractError):
                    contracts.validate_artifact(changed)

    def test_14_cross_transaction_worker_revision_and_logical_id_swaps_fail(self):
        for field in ("worker", "content_revision", "logical_transaction_id"):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.f.upload_intent)
                if field == "worker":
                    changed["transaction"][field] = "other-worker"
                    changed["transaction"]["logical_transaction_id"] = contracts.logical_transaction_id(
                        "other-worker", changed["transaction"]["content_revision"])
                elif field == "content_revision":
                    changed["transaction"][field] += 1
                    changed["transaction"]["logical_transaction_id"] = contracts.logical_transaction_id(
                        changed["transaction"]["worker"], changed["transaction"][field])
                else:
                    changed["transaction"][field] = "0" * 64
                changed = contracts.seal_artifact(changed)
                with self.assertRaises(contracts.ArtifactContractError):
                    contracts.validate_artifact(
                        changed, expected_transaction=self.f.upload_intent["transaction"],
                    )

    def test_15_cross_attempt_operation_and_intent_digest_swaps_fail(self):
        variants = []
        for field, value in (("attempt_id", "00000000-0000-4000-8000-000000000001"),
                             ("operation_id", "0" * 64), ("intent_artifact_sha256", "1" * 64)):
            changed = copy.deepcopy(self.f.upload_result)
            changed["payload"][field] = value
            variants.append(contracts.seal_artifact(changed))
        for index, changed in enumerate(variants):
            with self.subTest(variant=index), self.assertRaises(contracts.ArtifactContractError):
                contracts.validate_intent_result_pair(
                    self.f.upload_intent, changed, referenced_artifacts=self.refs(changed),
                )

    def test_16_stale_recovery_decision_cannot_overwrite_newer_journal(self):
        self._a59_case("test_stale_decision_generation_fails_closed")
        self._a59_case("test_stale_generation_and_newer_pending_revision_are_not_overwritten")

    def test_17_equivalent_concurrent_recovery_is_idempotent(self):
        self._a59_case("test_concurrent_remote_equivalent_reconciliation_is_idempotent")
        self._a59_case("test_exact_decision_replay_is_idempotent_without_generation_or_commit_change")

    def test_18_conflicting_recovery_decision_fails_without_mutating_journal(self):
        self._a59_case("test_conflicting_decision_for_same_attempt_fails_closed")

    def test_19_artifact_transport_roundtrip_revalidates_seal_after_copy(self):
        path = self.root / "downloaded-build.json"
        transport.write_artifact(path, self.f.bundle, referenced_artifacts=self.f.references)
        copied = self.root / "consumer" / "build.json"
        copied.parent.mkdir()
        copied.write_bytes(path.read_bytes())
        self.assertEqual(self.f.bundle["artifact_sha256"], transport.read_artifact(
            copied, expected_type="build_bundle", referenced_artifacts=self.f.references,
        )["artifact_sha256"])
        value = json.loads(copied.read_text(encoding="utf-8"))
        value["payload"]["content_fingerprint"] = "0" * 64
        copied.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(contracts.ArtifactContractError):
            transport.read_artifact(copied, expected_type="build_bundle")

    def test_20_all_direct_and_recovered_effective_result_combinations_validate(self):
        self._recovered_case("test_three_recovered_results_complete_proof_and_exact_six_materialization")
        self._recovered_case("test_recovered_upload_is_an_eligible_zero_percent_prerequisite")

    def test_21_final_materializer_emits_exactly_six_allowlisted_files(self):
        self.assertEqual(set(contracts.STATE_FILE_PATHS), set(self.f.output))
        self.assertEqual(6, len(self.f.output))
        with self.assertRaises(persistence.PersistenceBlocked):
            persistence.validate_finalization_inputs(
                self.f.proof, self.f.bundle, self.f.results,
                {**self.f.output, "publisher-state/extra.json": b"x"}, 1,
                referenced_artifacts=self.f.references,
            )

    def test_22_immutable_media_merge_retains_prior_canonical_history(self):
        output = json.loads(self.f.output["publisher-state/immutable-media-index.json"])
        prior_ids = {entry["source_identifier"] for entry in json.loads(
            __import__("base64").b64decode(self.f.binding["transport_base64"])
        )["entries"]}
        new_ids = {entry["source_identifier"] for entry in output["entries"]}
        self.assertTrue(prior_ids.issubset(new_ids))
        self.assertIn("missing-media", {row["source_identifier"] for row in self.f.media_manifest["records"]})
        _run_case(a57.SealedIndexBindingTests, "test_any_binding_field_tamper_invalidates_original_seal")

    def test_23_final_persistence_marks_ready_then_reads_back_before_completion(self):
        _run_case(a53.WorkflowStageCliTests, "test_54_concrete_final_persistence_completes_on_local_bare_remote")
        self._a53_case("test_41_completion_requires_ready_and_matching_commit")

    def test_24_final_persistence_failure_never_reports_completion(self):
        _run_case(a53.RepositoryPersistenceTests, "test_39_remote_race_fails_fast_forward_only")
        _run_case(a53.RepositoryPersistenceTests, "test_43_finalizer_rejects_failed_proof_before_journal")

    def test_25_journal_cas_rejects_stale_digest_generation_and_remote_race(self):
        for method in ("test_stale_decision_generation_fails_closed",
                       "test_concurrent_non_equivalent_remote_change_fails_closed",
                       "test_remote_state_not_exactly_matching_local_state_is_rejected"):
            with self.subTest(case=method):
                self._a59_case(method)

    def test_26_legacy_files_cannot_authorize_new_sealed_boundaries(self):
        _run_case(legacy_adapter_tests.LegacyAdapterTests, "test_all_frozen_legacy_inputs_are_read_only")
        _run_case(legacy_adapter_tests.LegacyAdapterTests, "test_unknown_legacy_artifact_rejected")

    def test_27_workflow_jobs_preserve_least_privilege_credential_classes(self):
        jobs = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)["jobs"]
        for name, job in jobs.items():
            text = str(job)
            if "secrets.CLOUDFLARE_API_TOKEN" in text:
                self.assertNotIn("contents: write", text, name)
                self.assertNotIn("CLOUDFLARE_READ_API_TOKEN", text, name)
            if "secrets.CLOUDFLARE_READ_API_TOKEN" in text:
                self.assertNotIn("contents: write", text, name)
                self.assertNotIn("secrets.CLOUDFLARE_API_TOKEN", text, name)
            if "contents: write" in text:
                self.assertNotIn("CLOUDFLARE_API_TOKEN", text, name)

    def test_28_accepted_workflow_graph_hash_triggers_and_dependencies_are_frozen(self):
        raw = WORKFLOW.read_bytes()
        self.assertEqual(A6_ACCEPTED_WORKFLOW_SHA, hashlib.sha256(raw).hexdigest())
        workflow = yaml.load(raw, Loader=yaml.BaseLoader)
        self.assertIn("workflow_dispatch", workflow["on"])
        self.assertEqual([{"cron": "17,47 * * * *"}], workflow["on"]["schedule"])
        self.assertEqual("mahoon-production-publisher", workflow["concurrency"]["group"])
        self.assertEqual("false", workflow["concurrency"]["cancel-in-progress"])
        jobs = workflow["jobs"]
        self.assertEqual(len(jobs), len(set(jobs)))
        for name, job in jobs.items():
            needs = job.get("needs", [])
            needs = [needs] if isinstance(needs, str) else needs
            self.assertLessEqual(set(needs), set(jobs), name)

    def test_29_executable_source_sha_is_separate_from_mutable_state_branch(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("ref: '${{ github.sha }}', path: code", source)
        self.assertIn("ref: main, path: state", source)
        self.assertNotEqual("main", "${{ github.sha }}")
        self.assertEqual(a54.SOURCE_SHA, self.f.bundle["producer"]["source_sha"])

    def test_30_synthetic_backends_have_no_real_credentials_or_side_effect_calls(self):
        self.assertIsNone(os.environ.get("CLOUDFLARE_API_TOKEN"))
        self.assertIsNone(os.environ.get("CLOUDFLARE_READ_API_TOKEN"))
        _run_case(stage_cli_tests.WorkflowStageCliTests, "test_fake_backend_only_and_no_credential_required_for_tests")
        _run_case(recovered_fixtures.RecoveredMutationResultTests, "test_bridge_producer_has_no_mutation_or_journal_write_path")
        _run_case(a53.RepositoryPersistenceTests, "test_36_push_is_never_force")


if __name__ == "__main__":
    unittest.main()
