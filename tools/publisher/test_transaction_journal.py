from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.publisher.transaction_journal import (
    CONTRACT,
    DuplicateMutation,
    FileJournalStore,
    JournalConflict,
    JournalInvalid,
    RecoveryRequired,
    TransactionJournal,
    empty_journal,
    journal_digest,
    logical_transaction_id,
    validate_journal,
)

WORKER = "synthetic-worker"
EVIDENCE = {"type": "synthetic", "reference": "test-proof-1", "sha256": "a" * 64}
BUILD = "b" * 64
PROOF = "c" * 64
COMMIT = "d" * 40


class ConflictOnceStore(FileJournalStore):
    def __init__(self, path: Path):
        super().__init__(path)
        self.conflict_once = True

    def compare_and_swap(self, expected: str, value: dict) -> str:
        if self.conflict_once:
            self.conflict_once = False
            current, current_hash = self.read()
            current["generation"] += 1
            super().compare_and_swap(current_hash, current)
            raise JournalConflict("synthetic competing writer")
        return super().compare_and_swap(expected, value)


class TransactionJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "journal.json"
        self.path.write_text(json.dumps(empty_journal(WORKER)), encoding="utf-8")
        self.tick = 0

        def clock() -> str:
            self.tick += 1
            return f"2026-09-26T00:00:{self.tick:02d}+00:00"

        self.journal = TransactionJournal(FileJournalStore(self.path), WORKER, clock)

    def _state(self):
        return validate_journal(json.loads(self.path.read_text(encoding="utf-8")), WORKER)

    def _admit(self, revision=10):
        status, tx_id = self.journal.admit(revision, "synthetic", "run-1", "attempt-1")
        self.assertEqual("ADMITTED", status)
        return tx_id

    def _apply(self, tx_id: str, operation: str):
        op_id, attempt_id = self.journal.record_intent(tx_id, operation)
        self.journal.record_result(tx_id, op_id, attempt_id, "APPLIED", EVIDENCE)
        return op_id, attempt_id

    def _ready_to_persist(self, revision=10):
        tx_id = self._admit(revision)
        self.journal.record_build_ready(tx_id, BUILD)
        for operation in ("upload_version", "deploy_zero_percent", "promote"):
            self._apply(tx_id, operation)
        self.journal.record_proof_ready(tx_id, PROOF)
        self.journal.mark_ready_to_persist(tx_id)
        return tx_id

    def test_schema_v2_identity_and_empty_state(self):
        value = empty_journal(WORKER)
        self.assertEqual(CONTRACT, value["contract"])
        self.assertEqual(2, value["schema_version"])
        validate_journal(value, WORKER)
        self.assertNotEqual(logical_transaction_id(WORKER, 10), logical_transaction_id(WORKER, 11))

    def test_same_revision_coalesces(self):
        tx_id = self._admit(10)
        status, duplicate = self.journal.admit(10, "heartbeat", "run-2", "attempt-1")
        self.assertEqual("COALESCED_ACTIVE", status)
        self.assertEqual(tx_id, duplicate)
        self.assertEqual(["synthetic", "heartbeat"], self._state()["active"]["trigger_sources"])

    def test_new_revision_pending_and_newer_replaces_it(self):
        self._admit(10)
        status, _ = self.journal.admit(11, "github")
        self.assertEqual("PENDING", status)
        status, _ = self.journal.admit(12, "github")
        self.assertEqual("PENDING_REPLACED", status)
        value = self._state()
        self.assertEqual(12, value["pending"]["content_revision"])
        old = [x for x in value["history"] if x["content_revision"] == 11][0]
        self.assertEqual("superseded", old["state"])

    def test_older_pending_cannot_replace_latest(self):
        self._admit(10)
        self.journal.admit(12, "github")
        status, _ = self.journal.admit(11, "heartbeat")
        self.assertEqual("SUPERSEDED", status)
        self.assertEqual(12, self._state()["pending"]["content_revision"])

    def test_build_ready_records_digest(self):
        tx = self._admit()
        self.journal.record_build_ready(tx, BUILD)
        value = self._state()["active"]
        self.assertEqual("build_ready", value["state"])
        self.assertEqual(BUILD, value["build_bundle_sha256"])

    def test_intent_precedes_result_and_attempt_is_uuid(self):
        tx = self._admit()
        op_id = self._state()["active"]["operations"]["promote"]["operation_id"]
        with self.assertRaises(JournalInvalid):
            self.journal.record_result(tx, op_id, "00000000-0000-0000-0000-000000000000", "APPLIED", EVIDENCE)
        op_id, attempt = self.journal.record_intent(tx, "promote")
        self.assertEqual(36, len(attempt))
        self.journal.record_result(tx, op_id, attempt, "APPLIED", EVIDENCE)
        self.assertEqual("operation_reported", self._state()["active"]["state"])

    def test_unknown_enters_recovery_and_cannot_replay(self):
        tx = self._admit()
        op_id, attempt = self.journal.record_intent(tx, "promote")
        self.journal.record_result(tx, op_id, attempt, "UNKNOWN")
        value = self._state()["active"]
        self.assertEqual("recovery_required", value["state"])
        with self.assertRaises(RecoveryRequired):
            self.journal.record_intent(tx, "promote")

    def test_reconciled_not_applied_requires_new_attempt(self):
        tx = self._admit()
        op_id, attempt = self.journal.record_intent(tx, "upload_version")
        self.journal.record_result(tx, op_id, attempt, "UNKNOWN")
        self.journal.reconcile(tx, op_id, "NOT_APPLIED", EVIDENCE)
        op_id2, attempt2 = self.journal.record_intent(tx, "upload_version")
        self.assertEqual(op_id, op_id2)
        self.assertNotEqual(attempt, attempt2)
        value = self._state()["active"]["operations"]["upload_version"]
        self.assertEqual("NOT_APPLIED", value["attempts"][0]["result_state"])
        self.assertEqual("NOT_REPORTED", value["attempts"][1]["result_state"])

    def test_reconciled_applied_does_not_allow_same_operation_again(self):
        tx = self._admit()
        op_id, attempt = self.journal.record_intent(tx, "upload_version")
        self.journal.record_result(tx, op_id, attempt, "UNKNOWN")
        self.journal.reconcile(tx, op_id, "APPLIED", EVIDENCE)
        with self.assertRaises(DuplicateMutation):
            self.journal.record_intent(tx, "upload_version")

    def test_identical_result_is_idempotent_conflicting_second_result_fails(self):
        tx = self._admit()
        op_id, attempt = self.journal.record_intent(tx, "upload_version")
        self.journal.record_result(tx, op_id, attempt, "APPLIED", EVIDENCE)
        self.journal.record_result(tx, op_id, attempt, "APPLIED", EVIDENCE)
        with self.assertRaises(DuplicateMutation):
            self.journal.record_result(tx, op_id, attempt, "NOT_APPLIED", EVIDENCE)

    def test_expected_generation_and_digest_fail_closed(self):
        current, generation, digest = self.journal.snapshot()
        self.assertEqual(0, generation)
        self.assertEqual(digest, journal_digest(current))
        self.journal.admit(10, "synthetic", expected_generation=generation, expected_digest=digest)
        with self.assertRaises(JournalConflict):
            self.journal.admit(11, "synthetic", expected_generation=generation, expected_digest=digest)

    def test_compare_and_swap_conflict_reloads_at_most_bounded_retry(self):
        store = ConflictOnceStore(self.path)
        journal = TransactionJournal(store, WORKER)
        status, _ = journal.admit(20, "synthetic")
        self.assertEqual("ADMITTED", status)
        self.assertEqual(2, validate_journal(json.loads(self.path.read_text()), WORKER)["generation"])

    def test_malformed_or_v1_journal_fails_closed(self):
        original = '{"contract":"MAHOON_PUBLISHER_TRANSACTION_JOURNAL_V1"}'
        self.path.write_text(original, encoding="utf-8")
        with self.assertRaises(JournalInvalid): self.journal.admit(10, "synthetic")
        self.assertEqual(original, self.path.read_text(encoding="utf-8"))
        self.path.write_text("{bad json", encoding="utf-8")
        with self.assertRaises(JournalInvalid): self.journal.admit(10, "synthetic")

    def test_ready_to_persist_prevents_promotion_replay(self):
        tx = self._ready_to_persist()
        self.assertEqual("ready_to_persist", self._state()["active"]["state"])
        with self.assertRaises(JournalInvalid):
            self.journal.record_intent(tx, "promote")

    def test_completed_requires_confirmed_state_commit(self):
        tx = self._ready_to_persist()
        with self.assertRaises(JournalInvalid): self.journal.finalize_completed(tx, "bad")
        self.journal.finalize_completed(tx, COMMIT)
        value = self._state()
        completed = value["history"][-1]
        self.assertEqual("completed", completed["state"])
        self.assertEqual(COMMIT, completed["state_commit_sha"])
        status, duplicate = self.journal.admit(10, "heartbeat")
        self.assertEqual("COALESCED_COMPLETED", status)
        self.assertEqual(tx, duplicate)

    def test_finalization_promotes_latest_pending_only(self):
        tx = self._ready_to_persist(10)
        self.journal.admit(11, "github")
        self.journal.admit(12, "github")
        self.journal.finalize_completed(tx, COMMIT)
        value = self._state()
        self.assertEqual(12, value["active"]["content_revision"])
        self.assertEqual("admitted", value["active"]["state"])

    def test_legacy_complete_method_cannot_skip_state_commit(self):
        tx = self._admit()
        with self.assertRaisesRegex(JournalInvalid, "disabled"):
            self.journal.complete(tx)


if __name__ == "__main__":
    unittest.main()
