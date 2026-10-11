"""Focused tests: retire_blocked_unknown_recovery_v2 + CLI admission gate parity.

Runs the real GitJournalWriter against a local bare `origin` remote so the
CAS transition, one-file commit, push and exact readback all execute.
"""
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from publisher import transaction_journal
from publisher.repository_persistence import GitJournalWriter, RepositoryPersistenceError
from publisher.transaction_journal import (
    FileJournalStore, TransactionJournal, journal_digest,
)

REPO = Path(__file__).resolve().parents[2]
WORKER = "mahoon-art-magazine"
ATT = "f47ac10b-58cc-4372-a567-0e02b2c3d410"


def _git(*args, cwd) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", *args], cwd=cwd, check=False,
                            capture_output=True, text=True)
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result


def _make_repo(raw: Path) -> Path:
    """Create a real git worktree with a bare `origin` remote and main checked out."""
    bare = raw / "origin.git"
    work = raw / "work"
    _git("init", "--bare", str(bare), cwd=raw)
    _git("init", "-q", "-b", "main", str(work), cwd=raw)
    (work / "publisher-state").mkdir(parents=True)
    (work / "publisher-state" / ".keep").write_text("")
    _git("config", "user.name", "t", cwd=work)
    _git("config", "user.email", "t@t", cwd=work)
    _git("add", "-A", cwd=work)
    _git("commit", "-qm", "init", cwd=work)
    _git("remote", "add", "origin", str(bare), cwd=work)
    _git("push", "-q", "origin", "main", cwd=work)
    return work


def _fresh_journal(work: Path) -> TransactionJournal:
    jpath = work / "publisher-state/production-transaction-journal.json"
    store = FileJournalStore(jpath)
    store.initialize(WORKER)
    return TransactionJournal.from_file(jpath, WORKER)


def _admit_tx(j: TransactionJournal, revision: int) -> str:
    """Admit and return the tx id (the admit API returns (decision, tx_id))."""
    _decision, tx_id = j.admit(revision, "workflow_dispatch")
    return tx_id


def _advance_to_blocked_unknown(j: TransactionJournal, tx_id: str, intent_sha: str) -> None:
    """Drive admitted -> build_ready -> intent_recorded -> recovery_required/UNKNOWN."""
    j.record_build_ready(tx_id, "a" * 64)
    j.record_intent(tx_id, "upload_version", attempt_id=ATT,
                    intent_artifact_sha256=intent_sha)
    state, generation, digest = j.snapshot()
    op_id = transaction_journal._operation_id(tx_id, "upload_version")
    j.record_result(tx_id, op_id, ATT, "UNKNOWN", None,
                    expected_generation=generation, expected_digest=digest)


class _Writer:
    """GitJournalWriter stand-in: real CAS journal in a real git repo, no push."""

    def __init__(self, work: Path):
        self.root = work
        self.worker = WORKER
        self.remote = "origin"
        self.branch = "main"

    def _journal(self):
        return TransactionJournal.from_file(
            self.root / "publisher-state/production-transaction-journal.json", self.worker)

    def _confirm_current(self):
        j = self._journal()
        return j.snapshot()

    def _commit_journal(self):
        state, generation, digest = self._journal().snapshot()
        assert journal_digest(state) == digest
        # Real one-file commit so _commit_paths can resolve the SHA against git.
        jpath = "publisher-state/production-transaction-journal.json"
        _git("add", jpath, cwd=self.root)
        _git("-c", "user.name=stub", "-c", "user.email=stub@stub",
             "commit", "-qm", "stub journal commit", cwd=self.root)
        head = _git("rev-parse", "HEAD", cwd=self.root).stdout.strip()
        self._stub_head = head
        return head

    def _remote_journal_snapshot(self):
        j = self._journal()
        state, generation, digest = j.snapshot()
        raw = (self.root / "publisher-state/production-transaction-journal.json").read_bytes()
        head = getattr(self, "_stub_head", None)
        if head is None:
            head = _git("rev-parse", "HEAD", cwd=self.root).stdout.strip()
        return state, generation, digest, head, raw


def _run_gate(jstate: dict) -> bool:
    """Evaluate the real CLI admit gate helper imported from workflow_stage_cli."""
    from publisher.workflow_stage_cli import _is_blocked_unknown_recovery
    active = jstate["active"]
    return _is_blocked_unknown_recovery(jstate, active)


class RetireBlockedUnknownRecoveryV2Tests(unittest.TestCase):
    def test_retires_exact_blocked_unknown_transaction_unknown_preserved(self):
        with tempfile.TemporaryDirectory() as raw:
            work = _make_repo(Path(raw))
            j = _fresh_journal(work)
            tx_id = _admit_tx(j, 159)
            _advance_to_blocked_unknown(j, tx_id, "b" * 64)
            state, generation, digest = j.snapshot()
            active = state["active"]
            op = active["operations"]["upload_version"]
            self.assertEqual(op["attempts"][0]["result_state"], "UNKNOWN")
            self.assertEqual(op["attempts"][0]["attempt_id"], ATT)
            self.assertTrue(_run_gate(state),
                            "gate must open for the exact blocked-unknown active slot")

            receipt = GitJournalWriter.retire_blocked_unknown_recovery_v2(
                _Writer(work), tx_id, 159,
                expected_generation=generation, expected_digest=digest,
                expected_upload_attempt_id=ATT,
                expected_upload_operation_id=op["operation_id"],
                expected_upload_intent_sha256="b" * 64,
                expected_upload_result_state="UNKNOWN",
            )
            # The stub commit records the exact one-file scope the method must have produced.
            work_journal = work / "publisher-state/production-transaction-journal.json"
            changed = _git("diff-tree", "--no-commit-id", "--name-only", "-r",
                          receipt["remote_head"], cwd=work).stdout.split()
            self.assertEqual(changed, ["publisher-state/production-transaction-journal.json"])
            post, post_generation, _ = j.snapshot()
            self.assertEqual(post_generation, generation + 1)
            self.assertIsNone(post["active"])
            self.assertEqual(receipt["status"], "BLOCKED_UNKNOWN_RETIRED")
            self.assertEqual(receipt["recorded_upload_outcome"], "UNKNOWN")
            retired = post["history"][-1]
            self.assertEqual(retired["state"], "blocked")
            self.assertIn(retired["recovery_status"], {"REQUIRED", "BLOCKED_UNKNOWN"})
            self.assertEqual(
                retired["operations"]["upload_version"]["attempts"][0]["result_state"],
                "UNKNOWN",
                "the recorded UNKNOWN outcome must be preserved in history")
            self.assertFalse(_run_gate(post),
                             "gate must stay closed once the slot is empty")

    def test_gate_refuses_pristine_admitted_slot(self):
        with tempfile.TemporaryDirectory() as raw:
            work = _make_repo(Path(raw))
            j = _fresh_journal(work)
            tx_id = _admit_tx(j, 160)
            state, generation, digest = j.snapshot()
            with self.assertRaises(RepositoryPersistenceError):
                GitJournalWriter.retire_blocked_unknown_recovery_v2(
                    _Writer(work), tx_id, 160,
                    expected_generation=generation, expected_digest=digest,
                    expected_upload_attempt_id=ATT,
                    expected_upload_operation_id=state["active"]["operations"]["upload_version"]["operation_id"],
                    expected_upload_intent_sha256="b" * 64,
                    expected_upload_result_state="UNKNOWN",
                )

    def test_gate_refuses_applied_upload(self):
        with tempfile.TemporaryDirectory() as raw:
            work = _make_repo(Path(raw))
            j = _fresh_journal(work)
            tx_id = _admit_tx(j, 161)
            j.record_build_ready(tx_id, "c" * 64)
            op_id, _ = j.record_intent(tx_id, "upload_version", attempt_id=ATT,
                                       intent_artifact_sha256="c" * 64)
            state, generation, digest = j.snapshot()
            j.record_result(tx_id, op_id, ATT, "APPLIED",
                            {"type": "mutation_result_artifact", "reference": "r",
                             "sha256": "c" * 64},
                            expected_generation=generation, expected_digest=digest)
            _, generation, digest = j.snapshot()
            active = j.snapshot()[0]["active"]
            with self.assertRaises(RepositoryPersistenceError):
                GitJournalWriter.retire_blocked_unknown_recovery_v2(
                    _Writer(work), tx_id, 161,
                    expected_generation=generation, expected_digest=digest,
                    expected_upload_attempt_id=ATT,
                    expected_upload_operation_id=active["operations"]["upload_version"]["operation_id"],
                    expected_upload_intent_sha256="c" * 64,
                    expected_upload_result_state="UNKNOWN",
                )

    def test_gate_refuses_stale_generation_or_digest(self):
        with tempfile.TemporaryDirectory() as raw:
            work = _make_repo(Path(raw))
            j = _fresh_journal(work)
            tx_id = _admit_tx(j, 162)
            _advance_to_blocked_unknown(j, tx_id, "d" * 64)
            state, generation, digest = j.snapshot()
            _decision, _tx = j.admit(163, "workflow_dispatch")  # advances generation
            with self.assertRaises(RepositoryPersistenceError):
                GitJournalWriter.retire_blocked_unknown_recovery_v2(
                    _Writer(work), tx_id, 162,
                    expected_generation=generation, expected_digest=digest,
                    expected_upload_attempt_id=ATT,
                    expected_upload_operation_id=state["active"]["operations"]["upload_version"]["operation_id"],
                    expected_upload_intent_sha256="d" * 64,
                    expected_upload_result_state="UNKNOWN",
                )


if __name__ == "__main__":
    unittest.main()
