from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "publisher"))

from publisher import artifact_contract as contracts
from publisher import artifact_transport as transport
from publisher import production_proof_runner as proof_runner
from publisher import repository_persistence as repo_persistence
from publisher.final_persistence_runner import PersistenceBlocked, finalize
from publisher.transaction_journal import TransactionJournal, empty_journal
from publisher.workflow_stage_cli import execute_final_persistence, execute_production_proof, main
import test_proof_recovery_runner as proof_fixtures

SHA, SHA2, SHA3 = proof_fixtures.SHA, proof_fixtures.SHA2, proof_fixtures.SHA3
SOURCE_SHA, WORKER = proof_fixtures.SOURCE_SHA, proof_fixtures.WORKER


def fresh_proof_fixture():
    fixture = proof_fixtures.ProofRecoveryRunnerTests()
    fixture.setUp()
    return fixture


def observations(fixture, *, identity_pass=True, failed_gate=None):
    production_gates = {name: True for name in contracts.PRODUCTION_GATES}
    if failed_gate:
        production_gates[failed_gate] = False
    return {
        "local": {"evidence_sha256": fixture.bundle["payload"]["local_gate_evidence_sha256"],
                  "gates": {name: True for name in contracts.LOCAL_GATES}},
        "identity_confirmation": {
            "candidate_version_id": "candidate-v1", "baseline_version_id": "baseline-v1",
            "promotion_deployment_id": "dep-promoted", "candidate_percentage": 100,
            "baseline_percentage": 0, "PASS": identity_pass,
        },
        "production": {"crawler_evidence_sha256": SHA,
                       "browser_evidence_sha256": SHA2,
                       "route_state_evidence_sha256": SHA3,
                       "gates": production_gates},
    }


def create_proof(fixture, backend=None, observed=None):
    class Backend:
        calls = 0
        def collect(self, context):
            self.calls += 1
            return observed or observations(fixture)
    backend = backend or Backend()
    value = proof_runner.create_production_proof(
        build_bundle=fixture.bundle, upload_intent=fixture.upload_intent,
        upload_result=fixture.upload_result, deploy_intent=fixture.deploy_intent,
        deploy_result=fixture.deploy_result, pre_promotion_proof=fixture.prepromotion_proof,
        promote_intent=fixture.promote_intent, promote_result=fixture.promote_result,
        backend=backend, clock=lambda: "2026-09-28T12:00:00+00:00",
    )
    return value, backend


class ProductionProofExecutorTests(unittest.TestCase):
    def setUp(self):
        self.f = fresh_proof_fixture()

    def test_01_seals_pass_proof_for_exact_applied_promotion(self):
        result, _ = create_proof(self.f)
        self.assertEqual("PASS", result["payload"]["proof_state"])

    def test_02_rejects_upload_not_applied(self):
        result = copy.deepcopy(self.f.upload_result)
        result["payload"]["result_state"] = "NOT_APPLIED"
        result = contracts.seal_artifact(result)
        with self.assertRaises(proof_runner.ProductionProofRejected):
            proof_runner.create_production_proof(
                build_bundle=self.f.bundle, upload_intent=self.f.upload_intent,
                upload_result=result, deploy_intent=self.f.deploy_intent,
                deploy_result=self.f.deploy_result, pre_promotion_proof=self.f.prepromotion_proof,
                promote_intent=self.f.promote_intent, promote_result=self.f.promote_result,
                backend=proof_runner.ObservationFileBackend("missing"),
            )

    def test_03_rejects_unknown_promotion(self):
        result = self.f._result(self.f.promote_intent, "UNKNOWN", "deployment", None)
        with self.assertRaises(proof_runner.ProductionProofRejected):
            proof_runner.create_production_proof(
                build_bundle=self.f.bundle, upload_intent=self.f.upload_intent,
                upload_result=self.f.upload_result, deploy_intent=self.f.deploy_intent,
                deploy_result=self.f.deploy_result, pre_promotion_proof=self.f.prepromotion_proof,
                promote_intent=self.f.promote_intent, promote_result=result,
                backend=proof_runner.ObservationFileBackend("missing"),
            )

    def test_04_rejects_tampered_operation_result_digest(self):
        result = copy.deepcopy(self.f.promote_result)
        result["payload"]["evidence_sha256"] = SHA
        result = contracts.seal_artifact(result)
        with self.assertRaises(Exception):
            proof_runner.create_production_proof(
                build_bundle=self.f.bundle, upload_intent=self.f.upload_intent,
                upload_result=self.f.upload_result, deploy_intent=self.f.deploy_intent,
                deploy_result=self.f.deploy_result, pre_promotion_proof=self.f.prepromotion_proof,
                promote_intent=self.f.promote_intent, promote_result=result,
                backend=proof_runner.ObservationFileBackend("missing"),
            )

    def test_05_rejects_transaction_mismatch(self):
        result = copy.deepcopy(self.f.promote_result)
        result["transaction"]["content_revision"] += 1
        result = contracts.seal_artifact(result)
        with self.assertRaises(Exception):
            proof_runner.create_production_proof(
                build_bundle=self.f.bundle, upload_intent=self.f.upload_intent,
                upload_result=self.f.upload_result, deploy_intent=self.f.deploy_intent,
                deploy_result=self.f.deploy_result, pre_promotion_proof=self.f.prepromotion_proof,
                promote_intent=self.f.promote_intent, promote_result=result,
                backend=proof_runner.ObservationFileBackend("missing"),
            )

    def test_06_rejects_candidate_identity_mismatch(self):
        intent = copy.deepcopy(self.f.promote_intent)
        intent["payload"]["desired_state"]["candidate_version_id"] = "other-candidate"
        intent = contracts.seal_artifact(intent)
        with self.assertRaises(Exception):
            proof_runner.create_production_proof(
                build_bundle=self.f.bundle, upload_intent=self.f.upload_intent,
                upload_result=self.f.upload_result, deploy_intent=self.f.deploy_intent,
                deploy_result=self.f.deploy_result, pre_promotion_proof=self.f.prepromotion_proof,
                promote_intent=intent, promote_result=self.f.promote_result,
                backend=proof_runner.ObservationFileBackend("missing"),
            )

    def test_07_rejects_promotion_readback_mismatch(self):
        result = copy.deepcopy(self.f.promote_result)
        result["payload"]["readback_reference"]["resource_id"] = "other-deployment"
        result = contracts.seal_artifact(result)
        result, _ = create_proof(self.f, observed=observations(self.f))
        with self.assertRaises(Exception):
            proof_runner.create_production_proof(
                build_bundle=self.f.bundle, upload_intent=self.f.upload_intent,
                upload_result=self.f.upload_result, deploy_intent=self.f.deploy_intent,
                deploy_result=self.f.deploy_result, pre_promotion_proof=self.f.prepromotion_proof,
                promote_intent=self.f.promote_intent, promote_result=contracts.seal_artifact(
                    {**self.f.promote_result, "payload": {
                        **self.f.promote_result["payload"], "readback_reference": {
                            "resource_type": "deployment", "worker": WORKER,
                            "resource_id": "other-deployment"}}}),
                backend=proof_runner.ObservationFileBackend("missing"),
            )

    def test_08_backend_is_observation_only_and_called_once(self):
        class ReadOnly:
            calls = 0
            def collect(inner, context):
                inner.calls += 1
                self.assertEqual("dep-promoted", context["promotion_deployment_id"])
                return observations(self.f)
            def mutate(inner, *_args):
                raise AssertionError("read-only proof backend must not mutate")
        backend = ReadOnly()
        result, _ = create_proof(self.f, backend=backend)
        self.assertEqual("PASS", result["payload"]["proof_state"])
        self.assertEqual(1, backend.calls)

    def test_09_all_frozen_gates_pass(self):
        result, _ = create_proof(self.f)
        self.assertTrue(all(result["payload"]["gate_results"]["production"]["gates"].values()))

    def test_10_local_evidence_must_match_sealed_bundle(self):
        value = observations(self.f)
        value["local"]["evidence_sha256"] = SHA
        with self.assertRaises(proof_runner.ProductionProofRejected):
            create_proof(self.f, observed=value)

    def test_11_identity_gate_failure_seals_fail_proof(self):
        result, _ = create_proof(self.f, observed=observations(self.f, identity_pass=False))
        self.assertEqual("FAIL", result["payload"]["proof_state"])

    def test_12_each_production_gate_failure_fails_closed(self):
        for name in contracts.PRODUCTION_GATES:
            with self.subTest(gate=name):
                result, _ = create_proof(self.f, observed=observations(self.f, failed_gate=name))
                self.assertEqual("FAIL", result["payload"]["proof_state"])

    def test_13_invalid_gate_map_rejected(self):
        value = observations(self.f)
        value["production"]["gates"].pop(contracts.PRODUCTION_GATES[0])
        with self.assertRaises(proof_runner.ProductionProofRejected):
            create_proof(self.f, observed=value)

    def test_14_invalid_evidence_digest_rejected(self):
        value = observations(self.f)
        value["production"]["crawler_evidence_sha256"] = "bad"
        with self.assertRaises(proof_runner.ProductionProofRejected):
            create_proof(self.f, observed=value)

    def test_15_preproof_must_have_passed(self):
        pre = copy.deepcopy(self.f.prepromotion_proof)
        pre["payload"]["PASS"] = False
        pre = contracts.seal_artifact(pre)
        with self.assertRaises(Exception):
            proof_runner.create_production_proof(
                build_bundle=self.f.bundle, upload_intent=self.f.upload_intent,
                upload_result=self.f.upload_result, deploy_intent=self.f.deploy_intent,
                deploy_result=self.f.deploy_result, pre_promotion_proof=pre,
                promote_intent=self.f.promote_intent, promote_result=self.f.promote_result,
                backend=proof_runner.ObservationFileBackend("missing"),
            )

    def test_16_backend_failure_cannot_seal_proof(self):
        class Broken:
            def collect(self, _context): raise OSError("synthetic failure")
        with self.assertRaises(proof_runner.ProductionProofRejected):
            create_proof(self.f, backend=Broken())

    def test_17_module_has_no_mutation_adapter_dependency(self):
        source = Path(proof_runner.__file__).read_text(encoding="utf-8")
        self.assertNotIn("cloudflare_operation_adapter", source)
        self.assertNotIn("WranglerOperationBackend", source)


def run_git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)
    return result.stdout.strip()


class LocalGit:
    def __init__(self, parent: Path):
        self.root = parent / "work"
        self.bare = parent / "remote.git"
        self.root.mkdir()
        run_git(parent, "init", "--bare", str(self.bare))
        run_git(self.root, "init", "-b", "main")
        run_git(self.root, "config", "user.name", "Synthetic Test")
        run_git(self.root, "config", "user.email", "synthetic@example.invalid")
        (self.root / "README.md").write_text("seed", encoding="utf-8")
        for relative in contracts.STATE_FILE_PATHS:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(("seed:" + relative).encode())
        jp = self.root / repo_persistence.JOURNAL_PATH
        jp.parent.mkdir(parents=True, exist_ok=True)
        jp.write_text(json.dumps(empty_journal(WORKER), sort_keys=True), encoding="utf-8")
        run_git(self.root, "add", "--all")
        run_git(self.root, "commit", "-m", "synthetic seed")
        for relative in contracts.STATE_FILE_PATHS:
            (self.root / relative).write_bytes(("baseline:" + relative).encode())
        run_git(self.root, "add", "--", *sorted(contracts.STATE_FILE_PATHS))
        run_git(self.root, "commit", "-m", "synthetic state baseline")
        run_git(self.root, "remote", "add", "origin", str(self.bare))
        run_git(self.root, "push", "-u", "origin", "main")

    def files(self):
        return {p: ("new:" + p).encode() for p in contracts.STATE_FILE_PATHS}


class RepositoryPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mahoon-a53-git-")
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)
        self.git = LocalGit(self.parent)

    def test_18_accepts_exact_six_bytes_mapping(self):
        self.assertEqual(set(contracts.STATE_FILE_PATHS), set(repo_persistence._validate_files(self.git.files())))

    def test_19_rejects_missing_state_file(self):
        with self.assertRaises(repo_persistence.RepositoryPersistenceError):
            repo_persistence._validate_files({})

    def test_20_rejects_extra_state_file(self):
        files = self.git.files(); files["unapproved.json"] = b"x"
        with self.assertRaises(repo_persistence.RepositoryPersistenceError):
            repo_persistence._validate_files(files)

    def test_21_rejects_non_bytes_payload(self):
        files = self.git.files(); files[next(iter(files))] = "text"
        with self.assertRaises(repo_persistence.RepositoryPersistenceError):
            repo_persistence._validate_files(files)

    def test_22_rejects_path_traversal(self):
        with self.assertRaises(repo_persistence.RepositoryPersistenceError):
            repo_persistence._safe_file(self.git.root, "../secret")

    def test_23_rejects_wrong_branch(self):
        with self.assertRaises(repo_persistence.RepositoryPersistenceError):
            repo_persistence.GitRepositoryWriter(self.git.root, branch="other")

    def test_24_rejects_non_repository_root(self):
        with self.assertRaises(repo_persistence.RepositoryPersistenceError):
            repo_persistence.GitRepositoryWriter(self.git.root / "publisher-state")

    def test_25_persists_exact_state_to_local_bare_remote(self):
        writer = repo_persistence.GitRepositoryWriter(self.git.root, branch="main")
        commit = writer.persist_once(self.git.files())
        self.assertEqual(commit, repo_persistence._remote_head(self.git.root, "origin", "main"))

    def test_26_commit_scope_contains_only_allowlisted_files(self):
        writer = repo_persistence.GitRepositoryWriter(self.git.root, branch="main")
        commit = writer.persist_once(self.git.files())
        self.assertTrue(repo_persistence._commit_paths(self.git.root, commit).issubset(contracts.STATE_FILE_PATHS))

    def test_27_readback_reports_every_six_hashes(self):
        writer = repo_persistence.GitRepositoryWriter(self.git.root, branch="main")
        commit = writer.persist_once(self.git.files())
        self.assertEqual(6, len(writer.read_exact(commit)["file_hashes"]))

    def test_28_identical_request_is_idempotent(self):
        writer = repo_persistence.GitRepositoryWriter(self.git.root, branch="main")
        first = writer.persist_once(self.git.files())
        second = writer.persist_once(self.git.files())
        self.assertEqual(first, second)

    def test_29_unrelated_untracked_file_is_not_committed(self):
        unrelated = self.git.root / "unrelated.tmp"
        unrelated.write_text("leave me", encoding="utf-8")
        writer = repo_persistence.GitRepositoryWriter(self.git.root, branch="main")
        commit = writer.persist_once(self.git.files())
        self.assertNotIn("unrelated.tmp", repo_persistence._commit_paths(self.git.root, commit))
        self.assertTrue(unrelated.exists())

    def test_30_unrelated_dirty_tracked_file_is_not_committed(self):
        file = self.git.root / "README.md"; file.write_text("dirty", encoding="utf-8")
        writer = repo_persistence.GitRepositoryWriter(self.git.root, branch="main")
        commit = writer.persist_once(self.git.files())
        self.assertNotIn("README.md", repo_persistence._commit_paths(self.git.root, commit))
        self.assertIn("README.md", run_git(self.git.root, "status", "--porcelain=v1"))

    def test_31_preexisting_staged_change_blocks(self):
        other = self.git.root / "notes.txt"; other.write_text("x", encoding="utf-8")
        run_git(self.git.root, "add", "notes.txt")
        writer = repo_persistence.GitRepositoryWriter(self.git.root, branch="main")
        with self.assertRaises(repo_persistence.RepositoryPersistenceError):
            writer.persist_once(self.git.files())

    def test_32_modified_allowlisted_file_blocks_ambiguous_overwrite(self):
        state = self.git.root / next(iter(contracts.STATE_FILE_PATHS)); state.write_bytes(b"local change")
        writer = repo_persistence.GitRepositoryWriter(self.git.root, branch="main")
        with self.assertRaises(repo_persistence.RepositoryPersistenceError):
            writer.persist_once(self.git.files())

    def test_33_missing_remote_blocks_before_commit(self):
        writer = repo_persistence.GitRepositoryWriter(self.git.root, remote="missing", branch="main")
        with self.assertRaises(repo_persistence.RepositoryPersistenceError):
            writer.persist_once(self.git.files())

    def test_34_rejects_invalid_readback_commit_identity(self):
        writer = repo_persistence.GitRepositoryWriter(self.git.root, branch="main")
        with self.assertRaises(repo_persistence.RepositoryPersistenceError):
            writer.read_exact("bad")

    def test_35_rejects_unreachable_remote_readback_commit(self):
        writer = repo_persistence.GitRepositoryWriter(self.git.root, branch="main")
        with self.assertRaises(repo_persistence.RepositoryPersistenceError):
            writer.read_exact("f" * 40)

    def test_36_push_is_never_force(self):
        source = Path(repo_persistence.__file__).read_text(encoding="utf-8")
        self.assertNotIn('"--force"', source)
        self.assertNotIn('"-f"', source)

    def test_37_journal_writer_rejects_other_path(self):
        with self.assertRaises(repo_persistence.RepositoryPersistenceError):
            repo_persistence.GitJournalWriter(self.git.root, WORKER, journal_path="other.json")

    def test_38_journal_writer_requires_repository_root(self):
        with self.assertRaises(repo_persistence.RepositoryPersistenceError):
            repo_persistence.GitJournalWriter(self.git.root / "publisher-state", WORKER)

    def test_39_remote_race_fails_fast_forward_only(self):
        other = self.parent / "other"
        run_git(self.parent, "clone", "--branch", "main", str(self.git.bare), str(other))
        run_git(other, "config", "user.name", "Other")
        run_git(other, "config", "user.email", "other@example.invalid")
        (other / "unrelated.txt").write_text("advance", encoding="utf-8")
        run_git(other, "add", "unrelated.txt"); run_git(other, "commit", "-m", "advance")
        run_git(other, "push", "origin", "main")
        writer = repo_persistence.GitRepositoryWriter(self.git.root, branch="main")
        with self.assertRaises(repo_persistence.RepositoryPersistenceError):
            writer.persist_once(self.git.files())

    def test_40_journal_ready_requires_owned_active_transaction(self):
        jp = self.git.root / repo_persistence.JOURNAL_PATH
        journal = TransactionJournal.from_file(jp, WORKER)
        with self.assertRaises(Exception):
            repo_persistence.GitJournalWriter(self.git.root, WORKER, branch="main").mark_ready_to_persist(
                contracts.logical_transaction_id(WORKER, 37), SHA, 0)

    def test_41_completion_requires_ready_and_matching_commit(self):
        writer = repo_persistence.GitJournalWriter(self.git.root, WORKER, branch="main")
        with self.assertRaises(repo_persistence.RepositoryPersistenceError):
            writer.finalize_completed(contracts.logical_transaction_id(WORKER, 37), "a" * 40, 0)

    def test_42_state_commit_remote_readback_checks_hashes(self):
        writer = repo_persistence.GitRepositoryWriter(self.git.root, branch="main")
        commit = writer.persist_once(self.git.files())
        actual = writer.read_exact(commit)
        expected = {p: hashlib.sha256(data).hexdigest() for p, data in self.git.files().items()}
        self.assertEqual(expected, actual["file_hashes"])

    def test_43_finalizer_rejects_failed_proof_before_journal(self):
        f = fresh_proof_fixture()
        class Never:
            def __getattr__(self, _name): raise AssertionError("must not advance")
        files = {p: b"synthetic" for p in contracts.STATE_FILE_PATHS}
        with self.assertRaises(PersistenceBlocked):
            finalize(f._proof(failed_production=True), f.bundle, {
                "upload_version": f.upload_result, "deploy_zero_percent": f.deploy_result,
                "promote": f.promote_result}, files, 0, Never(), Never())

    def test_44_finalizer_requires_exact_six_files(self):
        f = fresh_proof_fixture()
        class Never:
            def __getattr__(self, _name): raise AssertionError("must not advance")
        with self.assertRaises(PersistenceBlocked):
            finalize(f.proof, f.bundle, {"upload_version": f.upload_result,
                     "deploy_zero_percent": f.deploy_result, "promote": f.promote_result},
                     {}, 0, Never(), Never())


class WorkflowStageCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mahoon-a53-cli-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.f = fresh_proof_fixture()
        self.artifact_paths = {}
        all_items = [
            ("build", self.f.bundle), ("upload_intent", self.f.upload_intent),
            ("upload_result", self.f.upload_result), ("deploy_intent", self.f.deploy_intent),
            ("deploy_result", self.f.deploy_result), ("preproof", self.f.prepromotion_proof),
            ("promote_intent", self.f.promote_intent), ("promote_result", self.f.promote_result),
        ]
        refs = transport.references(*(item for _, item in all_items))
        for name, item in all_items:
            path = self.root / (name + ".json")
            transport.write_artifact(path, item, referenced_artifacts=refs)
            self.artifact_paths[name] = path
        self.observation_path = self.root / "observations.json"
        self.observation_path.write_text(json.dumps(observations(self.f)), encoding="utf-8")

    def test_45_production_proof_cli_emits_sealed_artifact(self):
        out = self.root / "proof.json"
        result = execute_production_proof(
            build_path=self.artifact_paths["build"], upload_intent_path=self.artifact_paths["upload_intent"],
            upload_result_path=self.artifact_paths["upload_result"], deploy_intent_path=self.artifact_paths["deploy_intent"],
            deploy_result_path=self.artifact_paths["deploy_result"], preproof_path=self.artifact_paths["preproof"],
            promote_intent_path=self.artifact_paths["promote_intent"], promote_result_path=self.artifact_paths["promote_result"],
            observations_path=self.observation_path, output_path=out)
        self.assertEqual("PASS", result["status"])
        self.assertEqual("proof_evidence", transport.read_artifact(out)["artifact_type"])

    def test_46_proof_cli_rejects_missing_observations(self):
        with self.assertRaises(Exception):
            execute_production_proof(
                build_path=self.artifact_paths["build"], upload_intent_path=self.artifact_paths["upload_intent"],
                upload_result_path=self.artifact_paths["upload_result"], deploy_intent_path=self.artifact_paths["deploy_intent"],
                deploy_result_path=self.artifact_paths["deploy_result"], preproof_path=self.artifact_paths["preproof"],
                promote_intent_path=self.artifact_paths["promote_intent"], promote_result_path=self.artifact_paths["promote_result"],
                observations_path=self.root / "absent.json", output_path=self.root / "proof.json")

    def test_47_proof_cli_rejects_tampered_input_before_output(self):
        self.artifact_paths["promote_result"].write_text("{}", encoding="utf-8")
        with self.assertRaises(Exception):
            execute_production_proof(
                build_path=self.artifact_paths["build"], upload_intent_path=self.artifact_paths["upload_intent"],
                upload_result_path=self.artifact_paths["upload_result"], deploy_intent_path=self.artifact_paths["deploy_intent"],
                deploy_result_path=self.artifact_paths["deploy_result"], preproof_path=self.artifact_paths["preproof"],
                promote_intent_path=self.artifact_paths["promote_intent"], promote_result_path=self.artifact_paths["promote_result"],
                observations_path=self.observation_path, output_path=self.root / "proof.json")
        self.assertFalse((self.root / "proof.json").exists())

    def test_48_proof_cli_bad_gate_is_fail_artifact(self):
        value = observations(self.f, failed_gate=contracts.PRODUCTION_GATES[0])
        self.observation_path.write_text(json.dumps(value), encoding="utf-8")
        result = execute_production_proof(
            build_path=self.artifact_paths["build"], upload_intent_path=self.artifact_paths["upload_intent"],
            upload_result_path=self.artifact_paths["upload_result"], deploy_intent_path=self.artifact_paths["deploy_intent"],
            deploy_result_path=self.artifact_paths["deploy_result"], preproof_path=self.artifact_paths["preproof"],
            promote_intent_path=self.artifact_paths["promote_intent"], promote_result_path=self.artifact_paths["promote_result"],
            observations_path=self.observation_path, output_path=self.root / "fail-proof.json")
        self.assertEqual("FAIL", result["status"])

    def test_49_cli_parser_exposes_both_executor_commands(self):
        from publisher.workflow_stage_cli import _parser
        self.assertIn("production-proof", _parser()._subparsers._group_actions[0].choices)
        self.assertIn("final-persistence-execute", _parser()._subparsers._group_actions[0].choices)

    def test_50_final_persistence_cli_rejects_state_root_outside_repo(self):
        with self.assertRaises(ValueError):
            execute_final_persistence(
                proof_path=self.root / "proof.json", build_path=self.artifact_paths["build"],
                upload_result_path=self.artifact_paths["upload_result"], deploy_result_path=self.artifact_paths["deploy_result"],
                promote_result_path=self.artifact_paths["promote_result"], repository=self.root,
                state_dir=self.root / "elsewhere", journal_path=self.root / "journal.json",
                remote="origin", branch="main", output_path=self.root / "final.json")

    def test_51_final_persistence_cli_rejects_missing_proof(self):
        with self.assertRaises(Exception):
            execute_final_persistence(
                proof_path=self.root / "no-proof.json", build_path=self.artifact_paths["build"],
                upload_result_path=self.artifact_paths["upload_result"], deploy_result_path=self.artifact_paths["deploy_result"],
                promote_result_path=self.artifact_paths["promote_result"], repository=self.root,
                state_dir=self.root, journal_path=self.root / "journal.json", remote="origin", branch="main",
                output_path=self.root / "final.json")

    def test_52_cli_returns_blocked_without_printing_exception_detail(self):
        from io import StringIO
        err = StringIO()
        with patch("sys.stderr", err):
            code = main(["production-proof", "--build-bundle", "x", "--upload-intent", "x",
                "--upload-result", "x", "--deploy-intent", "x", "--deploy-result", "x",
                "--pre-promotion-proof", "x", "--promote-intent", "x", "--promote-result", "x",
                "--observations", "x", "--output", str(self.root / "out.json")])
        self.assertEqual(2, code)
        self.assertIn("WORKFLOW_STAGE_BLOCKED", err.getvalue())
        self.assertNotIn(str(self.root), err.getvalue())

    def test_53_executor_module_has_no_network_client(self):
        source = Path(proof_runner.__file__).read_text(encoding="utf-8")
        self.assertNotIn("requests.", source)
        self.assertNotIn("urllib.request", source)

    def test_54_concrete_final_persistence_completes_on_local_bare_remote(self):
        git = LocalGit(self.root)
        journal_path = git.root / repo_persistence.JOURNAL_PATH
        journal = TransactionJournal.from_file(journal_path, WORKER)
        _, txid = journal.admit(37, "synthetic")
        self.assertEqual(self.f.tx["logical_transaction_id"], txid)
        for operation in ("upload_version", "deploy_zero_percent", "promote"):
            operation_id, attempt_id = journal.record_intent(txid, operation)
            journal.record_result(txid, operation_id, attempt_id, "APPLIED", {
                "type": "synthetic-readback", "reference": operation, "sha256": SHA,
            })

        refs = transport.references(
            self.f.receipt, self.f.bundle, self.f.upload_intent, self.f.upload_result,
            self.f.deploy_intent, self.f.deploy_result, self.f.prepromotion_proof,
            self.f.promote_intent, self.f.promote_result, self.f.proof,
        )
        proof_path = self.root / "proof.json"
        bundle_path = self.root / "bundle.json"
        upload_path = self.root / "upload.json"
        deploy_path = self.root / "deploy.json"
        promote_path = self.root / "promote.json"
        for path, artifact in ((proof_path, self.f.proof), (bundle_path, self.f.bundle),
                               (upload_path, self.f.upload_result), (deploy_path, self.f.deploy_result),
                               (promote_path, self.f.promote_result)):
            transport.write_artifact(path, artifact, referenced_artifacts=refs)
        staged = self.root / "state-input"
        for relative, data in git.files().items():
            target = staged.joinpath(*relative.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        output = self.root / "final-persistence.json"
        result = execute_final_persistence(
            proof_path=proof_path, build_path=bundle_path, upload_result_path=upload_path,
            deploy_result_path=deploy_path, promote_result_path=promote_path,
            repository=git.root, state_dir=staged, journal_path=journal_path,
            remote="origin", branch="main", output_path=output,
        )
        final_artifact = transport.read_artifact(output, expected_type="final_persistence_payload")
        self.assertEqual("COMPLETED", result["status"])
        self.assertEqual(final_artifact["payload"]["state_commit_sha"], result["state_commit_sha"])
        state, _generation, _digest = journal.snapshot()
        self.assertEqual("completed", state["history"][-1]["state"])
        repeated = execute_final_persistence(
            proof_path=proof_path, build_path=bundle_path, upload_result_path=upload_path,
            deploy_result_path=deploy_path, promote_result_path=promote_path,
            repository=git.root, state_dir=staged, journal_path=journal_path,
            remote="origin", branch="main", output_path=self.root / "final-retry.json",
        )
        self.assertEqual(result["state_commit_sha"], repeated["state_commit_sha"])


if __name__ == "__main__":
    unittest.main()
