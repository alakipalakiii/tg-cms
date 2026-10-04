from __future__ import annotations

import copy
import hashlib
import inspect
import io
import json
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from publisher import artifact_contract as contracts
from publisher import proof_recovery_runner as recovery
from publisher import repository_persistence as repository
from publisher import workflow_stage_cli as cli
from publisher.test_a54_remote_lifecycle_bridge import (
    LocalBare, REVISION, SOURCE_SHA, TX, WORKER, artifact, run_git,
)
from publisher.transaction_journal import JournalConflict, journal_digest, serialize_journal


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def decision_artifact(*, tx: dict = TX, operation: str = "deploy_zero_percent",
                      attempt_id: str, intent_sha: str, result_sha: str,
                      generation: int, choice: str = "RECONCILED_APPLIED",
                      evidence_sha: str | None = None) -> dict:
    return contracts.seal_artifact({
        "artifact_type": "recovery_decision", "schema_version": contracts.SCHEMA_VERSION,
        "artifact_id": str(uuid.uuid4()), "created_at": "2026-10-02T12:00:00+00:00",
        "producer": {"workflow_run_id": "synthetic-run", "run_attempt": 1,
                     "job": "proof-recovery", "source_sha": SOURCE_SHA},
        "transaction": copy.deepcopy(tx),
        "payload": {
            "operation_id": contracts.operation_id_for(tx["logical_transaction_id"], operation),
            "attempt_id": attempt_id, "decision": choice,
            "evidence_sha256": evidence_sha or sha("fresh-readback"),
            "intent_artifact_sha256": intent_sha, "result_artifact_sha256": result_sha,
            "journal_generation": generation, "resume_allowed": choice == "RECONCILED_NOT_APPLIED",
        },
    })


class A59RemoteReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mahoon-a59-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.parent = self.root / "initial"
        self.parent.mkdir()
        self.git = LocalBare(self.parent)

    def _prepare(self, operation: str = "deploy_zero_percent") -> tuple[dict, str]:
        writer = self.git.writer()
        status, txid, generation, _digest = writer.admit_revision(
            REVISION, "synthetic", "synthetic-run", str(uuid.uuid4()))
        self.assertEqual("ADMITTED", status)
        op_id, attempt_id = contracts.operation_id_for(txid, operation), str(uuid.uuid4())
        intent_sha, result_sha = sha("intent:" + operation), sha("unknown-result:" + operation)
        writer.record_intent(txid, operation, attempt_id, intent_sha, generation + 1)
        writer.record_result(txid, op_id, attempt_id, "UNKNOWN", None, intent_sha, result_sha)
        state, generation, _ = self.git.journal().snapshot()
        decision = decision_artifact(
            operation=operation, attempt_id=attempt_id, intent_sha=intent_sha,
            result_sha=result_sha, generation=generation,
        )
        return decision, txid

    def _fresh_clone(self, name: str) -> Path:
        target = self.root / name
        subprocess.run(["git", "clone", "--branch", "main", str(self.git.bare), str(target)],
                       check=True, capture_output=True)
        run_git(target, "config", "user.name", "Synthetic A5.9")
        run_git(target, "config", "user.email", "a59@example.invalid")
        return target

    def test_applied_reconciliation_is_one_journal_only_commit_with_remote_readback(self):
        decision, _txid = self._prepare("upload_version")
        before_head = repository._remote_head(self.git.root, "origin", "main")
        before, before_generation, _ = self.git.journal().snapshot()
        receipt = self.git.writer().reconcile_recovery_decision(decision)
        state, generation, digest, head = self.git.writer()._remote_snapshot()
        op = state["active"]["operations"]["upload_version"]
        self.assertEqual("APPLIED", op["result_state"])
        self.assertEqual("RECONCILED_APPLIED", state["active"]["recovery_status"])
        self.assertEqual("operation_reported", state["active"]["state"])
        self.assertEqual(before_generation + 1, generation)
        self.assertEqual(1, len(op["attempts"]))
        self.assertNotEqual(before_head, head)
        self.assertEqual({repository.JOURNAL_PATH}, repository._commit_paths(self.git.root, head))
        self.assertEqual(digest, receipt["journal_sha256"])
        self.assertFalse(receipt["idempotent"])

    def test_not_applied_is_recorded_but_never_retried_or_reintended(self):
        decision, _ = self._prepare("deploy_zero_percent")
        decision["payload"]["decision"] = "RECONCILED_NOT_APPLIED"
        decision["payload"]["resume_allowed"] = True
        decision = contracts.seal_artifact(decision)
        before = self.git.journal().snapshot()[0]["active"]["operations"]["deploy_zero_percent"]
        receipt = self.git.writer().reconcile_recovery_decision(decision)
        after = self.git.journal().snapshot()[0]["active"]["operations"]["deploy_zero_percent"]
        self.assertEqual("NOT_APPLIED", receipt["outcome"])
        self.assertEqual("RECONCILED_NOT_APPLIED", self.git.journal().snapshot()[0]["active"]["recovery_status"])
        self.assertEqual(len(before["attempts"]), len(after["attempts"]))
        self.assertEqual(1, len(after["attempts"]))
        self.assertEqual("NOT_APPLIED", after["attempts"][0]["result_state"])

    def test_inconclusive_recovery_stays_blocked_and_does_not_create_attempt(self):
        decision, _ = self._prepare()
        decision["payload"]["decision"] = "BLOCKED_UNKNOWN"
        decision = contracts.seal_artifact(decision)
        before = self.git.journal().snapshot()[0]["active"]["operations"]["deploy_zero_percent"]
        receipt = self.git.writer().reconcile_recovery_decision(decision)
        state = self.git.journal().snapshot()[0]
        op = state["active"]["operations"]["deploy_zero_percent"]
        self.assertEqual("UNKNOWN", receipt["outcome"])
        self.assertEqual("recovery_required", state["active"]["state"])
        self.assertEqual("BLOCKED_UNKNOWN", state["active"]["recovery_status"])
        self.assertEqual(len(before["attempts"]), len(op["attempts"]))
        self.assertEqual("UNKNOWN", op["result_state"])

    def test_all_four_operations_use_the_same_generic_transition(self):
        for operation in ("upload_version", "deploy_zero_percent", "promote", "rollback"):
            with self.subTest(operation=operation):
                if operation != "upload_version":
                    self.parent = self.root / ("case-" + operation)
                    self.parent.mkdir()
                    self.git = LocalBare(self.parent)
                decision, _ = self._prepare(operation)
                result = self.git.writer().reconcile_recovery_decision(decision)
                state = self.git.journal().snapshot()[0]
                self.assertEqual(operation, result["operation_name"])
                self.assertEqual("APPLIED", state["active"]["operations"][operation]["result_state"])
                self.assertEqual("RECONCILED_APPLIED", state["active"]["recovery_status"])

    def test_upload_not_applied_is_rejected_even_if_a_forged_decision_is_well_formed(self):
        decision, _ = self._prepare("upload_version")
        decision["payload"]["decision"] = "RECONCILED_NOT_APPLIED"
        decision["payload"]["resume_allowed"] = True
        decision = contracts.seal_artifact(decision)
        with self.assertRaisesRegex(repository.RepositoryPersistenceError, "upload absence"):
            self.git.writer().reconcile_recovery_decision(decision)
        self.assertEqual("recovery_required", self.git.journal().snapshot()[0]["active"]["state"])

    def test_exact_decision_replay_is_idempotent_without_generation_or_commit_change(self):
        decision, _ = self._prepare()
        writer = self.git.writer()
        first = writer.reconcile_recovery_decision(decision)
        before = self.git.journal().snapshot()
        head = repository._remote_head(self.git.root, "origin", "main")
        second = writer.reconcile_recovery_decision(decision)
        self.assertFalse(first["idempotent"])
        self.assertTrue(second["idempotent"])
        self.assertEqual(before, self.git.journal().snapshot())
        self.assertEqual(head, repository._remote_head(self.git.root, "origin", "main"))

    def test_conflicting_decision_for_same_attempt_fails_closed(self):
        decision, _ = self._prepare()
        self.git.writer().reconcile_recovery_decision(decision)
        conflict = copy.deepcopy(decision)
        conflict["payload"]["decision"] = "BLOCKED_UNKNOWN"
        conflict["payload"]["resume_allowed"] = False
        conflict["payload"]["journal_generation"] += 1
        conflict = contracts.seal_artifact(conflict)
        before = self.git.journal().snapshot()
        with self.assertRaises(repository.RepositoryPersistenceError):
            self.git.writer().reconcile_recovery_decision(conflict)
        self.assertEqual(before, self.git.journal().snapshot())

    def test_stale_generation_and_newer_pending_revision_are_not_overwritten(self):
        decision, _ = self._prepare()
        writer = self.git.writer()
        writer.admit_revision(REVISION + 1, "synthetic-newer")
        before = self.git.journal().snapshot()
        with self.assertRaises(JournalConflict):
            writer.reconcile_recovery_decision(decision)
        self.assertEqual(before, self.git.journal().snapshot())
        self.assertEqual(REVISION + 1, before[0]["pending"]["content_revision"])

    def test_old_attempt_cannot_overwrite_a_newer_attempt(self):
        decision, txid = self._prepare()
        writer = self.git.writer()
        not_applied = copy.deepcopy(decision)
        not_applied["payload"]["decision"] = "RECONCILED_NOT_APPLIED"
        not_applied["payload"]["resume_allowed"] = True
        not_applied = contracts.seal_artifact(not_applied)
        writer.reconcile_recovery_decision(not_applied)
        state, generation, _ = self.git.journal().snapshot()
        new_attempt = str(uuid.uuid4())
        writer.record_intent(txid, "deploy_zero_percent", new_attempt, sha("new-intent"), generation + 1)
        before = self.git.journal().snapshot()
        with self.assertRaises((JournalConflict, repository.RepositoryPersistenceError)):
            writer.reconcile_recovery_decision(not_applied)
        after = self.git.journal().snapshot()
        self.assertEqual(before, after)
        self.assertEqual(new_attempt, after[0]["active"]["operations"]["deploy_zero_percent"]["attempts"][-1]["attempt_id"])

    def test_missing_unknown_operation_or_non_recovery_state_fails_closed(self):
        writer = self.git.writer()
        _decision, txid, generation, _ = writer.admit_revision(REVISION, "synthetic", "run", str(uuid.uuid4()))
        attempt = str(uuid.uuid4())
        intent_sha, result_sha = sha("intent"), sha("result")
        writer.record_intent(txid, "deploy_zero_percent", attempt, intent_sha, generation + 1)
        state, current, _ = self.git.journal().snapshot()
        decision = decision_artifact(attempt_id=attempt, intent_sha=intent_sha,
                                      result_sha=result_sha, generation=current)
        with self.assertRaises(repository.RepositoryPersistenceError):
            writer.reconcile_recovery_decision(decision)
        self.assertEqual("intent_recorded", state["active"]["state"])

    def test_worker_revision_transaction_operation_attempt_and_intent_lineage_are_bound(self):
        decision, _ = self._prepare()
        writer = self.git.writer()
        variants = []

        wrong_worker = copy.deepcopy(decision)
        wrong_worker["transaction"]["worker"] = "other-worker"
        wrong_worker["transaction"]["logical_transaction_id"] = contracts.logical_transaction_id(
            wrong_worker["transaction"]["worker"], wrong_worker["transaction"]["content_revision"])
        wrong_worker["payload"]["operation_id"] = contracts.operation_id_for(
            wrong_worker["transaction"]["logical_transaction_id"], "deploy_zero_percent")
        variants.append(("worker", wrong_worker, True))

        wrong_revision = copy.deepcopy(decision)
        wrong_revision["transaction"]["content_revision"] += 1
        wrong_revision["transaction"]["logical_transaction_id"] = contracts.logical_transaction_id(
            wrong_revision["transaction"]["worker"], wrong_revision["transaction"]["content_revision"])
        wrong_revision["payload"]["operation_id"] = contracts.operation_id_for(
            wrong_revision["transaction"]["logical_transaction_id"], "deploy_zero_percent")
        variants.append(("revision", wrong_revision, True))

        wrong_operation = copy.deepcopy(decision)
        wrong_operation["payload"]["operation_id"] = contracts.operation_id_for(
            decision["transaction"]["logical_transaction_id"], "promote")
        variants.append(("operation", wrong_operation, True))

        wrong_attempt = copy.deepcopy(decision)
        wrong_attempt["payload"]["attempt_id"] = str(uuid.uuid4())
        variants.append(("attempt", wrong_attempt, True))

        wrong_intent = copy.deepcopy(decision)
        wrong_intent["payload"]["intent_artifact_sha256"] = sha("different-intent")
        variants.append(("intent", wrong_intent, True))

        for label, value, reseal in variants:
            with self.subTest(lineage=label):
                candidate = contracts.seal_artifact(value) if reseal else value
                with self.assertRaises((contracts.ArtifactContractError,
                                        repository.RepositoryPersistenceError,
                                        JournalConflict)):
                    writer.reconcile_recovery_decision(candidate)
                state = self.git.journal().snapshot()[0]
                self.assertEqual("recovery_required", state["active"]["state"])
                self.assertEqual("UNKNOWN", state["active"]["operations"]
                                 ["deploy_zero_percent"]["result_state"])

    def test_stale_decision_generation_fails_closed(self):
        decision, _ = self._prepare()
        decision["payload"]["journal_generation"] += 1
        decision = contracts.seal_artifact(decision)
        with self.assertRaises(JournalConflict):
            self.git.writer().reconcile_recovery_decision(decision)
        self.assertEqual("recovery_required", self.git.journal().snapshot()[0]["active"]["state"])

    def test_remote_state_not_exactly_matching_local_state_is_rejected(self):
        decision, _ = self._prepare()
        path = self.git.root / repository.JOURNAL_PATH
        raw = json.loads(path.read_text(encoding="utf-8"))
        generation = raw["generation"]
        before_digest = journal_digest(raw)
        raw["active"]["trigger_sources"][0] = "different-valid-local-source"
        self.assertEqual(generation, raw["generation"])
        self.assertNotEqual(before_digest, journal_digest(raw))
        path.write_bytes(serialize_journal(raw))
        with self.assertRaises(repository.RepositoryPersistenceError):
            self.git.writer().reconcile_recovery_decision(decision)

    def test_concurrent_remote_equivalent_reconciliation_is_idempotent(self):
        decision, _ = self._prepare()
        other = self._fresh_clone("other-writer")
        second = repository.GitJournalWriter(other, WORKER).reconcile_recovery_decision(decision)
        first = self.git.writer().reconcile_recovery_decision(decision)
        self.assertFalse(second["idempotent"])
        self.assertTrue(first["idempotent"])
        self.assertEqual(second["journal_sha256"], first["journal_sha256"])
        remote, *_ = self.git.writer()._remote_journal_snapshot()
        self.assertEqual("APPLIED", remote["active"]["operations"]
                         ["deploy_zero_percent"]["result_state"])

    def test_concurrent_non_equivalent_remote_change_fails_closed(self):
        decision, _ = self._prepare()
        other = self._fresh_clone("other-writer")
        (other / "unrelated.txt").write_text("concurrent unrelated update", encoding="utf-8")
        run_git(other, "add", "unrelated.txt")
        run_git(other, "commit", "-m", "unrelated concurrent update")
        run_git(other, "push", "origin", "main")
        with self.assertRaises(repository.RepositoryPersistenceError):
            self.git.writer().reconcile_recovery_decision(decision)
        remote, _, _, _, _ = self.git.writer()._remote_journal_snapshot()
        self.assertEqual("recovery_required", remote["active"]["state"])
        self.assertEqual("UNKNOWN", remote["active"]["operations"]["deploy_zero_percent"]["result_state"])

    def test_failed_remote_readback_never_reports_success_or_replays(self):
        decision, _ = self._prepare()
        writer = self.git.writer()
        with mock.patch.object(writer, "_commit_and_verify",
                               side_effect=repository.RepositoryPersistenceError("synthetic readback mismatch")):
            with self.assertRaises(repository.RepositoryPersistenceError):
                writer.reconcile_recovery_decision(decision)
        remote, _, _, _, _ = writer._remote_journal_snapshot()
        self.assertEqual("UNKNOWN", remote["active"]["operations"]["deploy_zero_percent"]["result_state"])

    def test_decision_readback_generation_and_cas_are_bound_to_remote_journal(self):
        decision, _ = self._prepare()
        before, generation, digest, head = self.git.writer()._remote_snapshot()
        self.assertEqual(decision["payload"]["journal_generation"], generation)
        self.assertEqual(journal_digest(before), digest)
        self.assertNotIn("journal_sha256", decision["payload"])
        receipt = self.git.writer().reconcile_recovery_decision(decision)
        after, next_generation, next_digest, next_head = self.git.writer()._remote_snapshot()
        self.assertEqual(generation + 1, next_generation)
        self.assertNotEqual(digest, next_digest)
        self.assertNotEqual(head, next_head)
        self.assertEqual(next_digest, receipt["journal_sha256"])

    def test_cli_executes_sealed_decision_through_git_journal_writer(self):
        decision, _ = self._prepare("upload_version")
        decision_path = self.root / "recovery-decision.json"
        decision_path.write_text(json.dumps(decision, sort_keys=True), encoding="utf-8")
        output = io.StringIO()
        with mock.patch("sys.stdout", output):
            code = cli.main([
                "reconcile-recovery-decision", "--decision", str(decision_path),
                "--repository", str(self.git.root), "--remote", "origin", "--branch", "main",
            ])
        self.assertEqual(0, code)
        receipt = json.loads(output.getvalue())
        self.assertEqual("RECONCILED_APPLIED", receipt["status"])
        self.assertFalse(receipt["idempotent"])
        remote, *_ = self.git.writer()._remote_journal_snapshot()
        self.assertEqual("APPLIED", remote["active"]["operations"]["upload_version"]["result_state"])


class A59AuthorityAndCliTests(unittest.TestCase):
    def test_recovery_decision_schema_is_exact_and_unknown_fields_rejected(self):
        value = decision_artifact(attempt_id=str(uuid.uuid4()), intent_sha=sha("i"),
                                  result_sha=sha("r"), generation=7)
        self.assertEqual("recovery_decision", contracts.validate_artifact(value)["artifact_type"])
        self.assertEqual({"operation_id", "attempt_id", "decision", "evidence_sha256",
                          "intent_artifact_sha256", "result_artifact_sha256",
                          "journal_generation", "resume_allowed"}, set(value["payload"]))
        extra = copy.deepcopy(value)
        extra["payload"]["extra"] = True
        with self.assertRaises(contracts.ArtifactContractError):
            contracts.validate_artifact(contracts.seal_artifact(extra))
        missing = copy.deepcopy(value)
        del missing["payload"]["attempt_id"]
        with self.assertRaises(contracts.ArtifactContractError):
            contracts.validate_artifact(contracts.seal_artifact(missing))
        wrong_transaction = copy.deepcopy(value)
        wrong_transaction["transaction"]["logical_transaction_id"] = sha("wrong-transaction")
        with self.assertRaises(contracts.ArtifactContractError):
            contracts.validate_artifact(contracts.seal_artifact(wrong_transaction))

    def test_malformed_tampered_wrong_type_and_raw_values_are_rejected(self):
        good = decision_artifact(attempt_id=str(uuid.uuid4()), intent_sha=sha("i"),
                                 result_sha=sha("r"), generation=1)
        for bad in (None, "RECONCILED_APPLIED", {}, {**good, "artifact_type": "mutation_result"}):
            with self.subTest(value=type(bad).__name__):
                with self.assertRaises((contracts.ArtifactContractError, TypeError, ValueError)):
                    contracts.validate_artifact(bad)
        changed = copy.deepcopy(good)
        changed["payload"]["decision"] = "BLOCKED_UNKNOWN"
        with self.assertRaises(contracts.ArtifactContractError):
            contracts.validate_artifact(changed)

    def test_all_decision_values_and_resume_rules_are_frozen(self):
        self.assertEqual({"RECONCILED_APPLIED", "RECONCILED_NOT_APPLIED", "BLOCKED_UNKNOWN"},
                         contracts.RECOVERY_DECISIONS)
        for choice, resume in (("RECONCILED_APPLIED", False),
                               ("RECONCILED_NOT_APPLIED", True),
                               ("BLOCKED_UNKNOWN", False)):
            value = decision_artifact(attempt_id=str(uuid.uuid4()), intent_sha=sha(choice),
                                      result_sha=sha("r" + choice), generation=3, choice=choice)
            self.assertEqual(resume, contracts.validate_artifact(value)["payload"]["resume_allowed"])

    def test_cli_requires_decision_and_only_delegates_to_remote_writer(self):
        parser = cli._parser()
        args = parser.parse_args(["reconcile-recovery-decision", "--decision", "decision.json",
                                  "--repository", "repo", "--remote", "origin", "--branch", "main"])
        self.assertEqual("reconcile-recovery-decision", args.command)
        self.assertFalse(any(hasattr(args, name) for name in ("outcome", "evidence", "readback")))
        source = inspect.getsource(cli.main)
        branch = source[source.index('elif args.command == "reconcile-recovery-decision"'):]
        self.assertIn('_read(args.decision, "recovery_decision")', branch)
        self.assertIn("writer.reconcile_recovery_decision(decision)", branch)
        self.assertNotIn("args.outcome", branch)

    def test_cli_does_not_duplicate_transition_hash_or_git_logic(self):
        source = inspect.getsource(cli.main)
        branch = source[source.index('elif args.command == "reconcile-recovery-decision"'):]
        for forbidden in ("canonical_result_digest", "journal.reconcile", '"git"', "--force"):
            with self.subTest(token=forbidden):
                self.assertNotIn(forbidden, branch)

    def test_writer_uses_only_git_journal_authority_and_never_executes_cloudflare(self):
        source = inspect.getsource(repository.GitJournalWriter.reconcile_recovery_decision).lower()
        self.assertIn("contracts.validate_artifact", source)
        self.assertIn("journal.reconcile", source)
        self.assertIn("_commit_and_verify", source)
        for forbidden in ("cloudflare", "wrangler", "d1", "mutation_adapter", "dispatch(", "deploy("):
            with self.subTest(token=forbidden):
                self.assertNotIn(forbidden, source)
        self.assertNotIn("--force", inspect.getsource(repository._push))

    def test_rollback_recovery_reuses_existing_authorization_lineage_gate(self):
        source = inspect.getsource(recovery.authorize_rollback)
        self.assertIn('"rollback"', source)
        self.assertIn('"promote"', source)
        self.assertIn('"proof_state"', source)
        validator = inspect.getsource(__import__("publisher.recovery_readback", fromlist=["x"])._validate_inputs)
        self.assertIn("authorize_rollback", validator)
        self.assertIn('operation == "rollback"', validator)

    def test_applied_recovery_does_not_bypass_downstream_proof_or_final_state_gates(self):
        writer = inspect.getsource(repository.GitJournalWriter.reconcile_recovery_decision)
        self.assertNotIn("record_proof_ready(", writer)
        self.assertNotIn("mark_ready_to_persist(", writer)
        self.assertNotIn("finalize_completed(", writer)
        journal = inspect.getsource(__import__("publisher.transaction_journal", fromlist=["x"]).TransactionJournal.record_proof_ready)
        self.assertIn("REQUIRED_SUCCESSFUL_OPERATIONS", journal)
        self.assertIn("unresolved", journal)

    def test_local_journal_cli_reconcile_contract_remains_independent(self):
        source = Path(__file__).with_name("journal_cli.py").read_text(encoding="utf-8")
        self.assertIn('(\"record-result\", \"reconcile\")', source)
        self.assertIn("args.outcome", source)
        self.assertNotIn("reconcile_recovery_decision", source)

    def test_recovery_contract_has_no_legacy_authority_or_external_access(self):
        source = inspect.getsource(cli.main)
        start = source.index('elif args.command == "reconcile-recovery-decision"')
        end = source.find("elif args.command", start + 5)
        branch = source[start:end if end > 0 else None]
        for forbidden in ("production-result.json", "remote-proof-result.json",
                          "transaction.json", "CLOUDFLARE_API_TOKEN", "D1"):
            self.assertNotIn(forbidden, branch)


if __name__ == "__main__":
    unittest.main()
