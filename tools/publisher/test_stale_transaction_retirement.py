"""Offline tests for the one approved stale-admission retirement boundary."""
import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from publisher import repository_persistence as persistence
from publisher import workflow_stage_cli as cli
from publisher.transaction_journal import JournalInvalid, journal_digest, serialize_journal

ROOT = Path(__file__).resolve().parents[2]
TX = "704bdb7d7161c7c5c89ef4865788e71a67df26fd2fe4cfb695d297c3900d18d2"
WORKER = "mahoon-art-magazine"
JOURNAL = "publisher-state/production-transaction-journal.json"
JOURNAL_FIXTURE = Path(__file__).resolve().parent / "fixtures/pre-retirement-journal-v2.json"


def git(root, *args, check=True):
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    if check and result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout.strip()


class RetirementRepository:
    def __init__(self, parent):
        self.root, self.remote = parent / "repo", parent / "remote.git"
        self.root.mkdir()
        git(parent, "init", "--bare", str(self.remote))
        git(self.root, "init", "-b", "main")
        git(self.root, "config", "user.name", "Retirement test")
        git(self.root, "config", "user.email", "retirement@example.invalid")
        (self.root / JOURNAL).parent.mkdir(parents=True)
        (self.root / JOURNAL).write_bytes(JOURNAL_FIXTURE.read_bytes())
        git(self.root, "add", JOURNAL)
        git(self.root, "commit", "-m", "accepted journal fixture")
        git(self.root, "remote", "add", "origin", str(self.remote))
        git(self.root, "push", "-u", "origin", "main")

    def writer(self):
        return persistence.GitJournalWriter(self.root, WORKER, "origin", "main")

    def journal(self):
        head = git(self.root, "rev-parse", "origin/main")
        return json.loads(git(self.root, "show", f"{head}:{JOURNAL}"))


class StaleRetirementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mahoon-retire-")
        self.addCleanup(self.temp.cleanup)
        self.repo = RetirementRepository(Path(self.temp.name))

    def test_pristine_revision_109_retires_as_one_journal_only_commit(self):
        before = git(self.repo.root, "rev-parse", "HEAD")
        result = self.repo.writer().retire_stale_admitted(TX, 109)
        state = self.repo.journal()
        self.assertEqual("RETIRED_BLOCKED", result["status"])
        self.assertEqual((2, 1, None, None), (state["generation"], len(state["history"]), state["active"], state["pending"]))
        old = state["history"][0]
        self.assertEqual((109, "blocked", TX), (old["content_revision"], old["state"], old["logical_transaction_id"]))
        self.assertEqual("admitted", old["transitions"][0]["to"])
        self.assertEqual("blocked", old["transitions"][-1]["to"])
        commit = result["remote_head"]
        self.assertEqual(before, git(self.repo.root, "rev-parse", f"{commit}^"))
        self.assertEqual(JOURNAL, git(self.repo.root, "diff-tree", "--no-commit-id", "--name-only", "-r", commit))
        self.assertEqual((self.repo.root / JOURNAL).read_bytes(), subprocess.run(
            ["git", "show", f"origin/main:{JOURNAL}"], cwd=self.repo.root,
            capture_output=True, check=True,
        ).stdout)

    def test_repeated_retirement_does_not_make_another_generation(self):
        self.repo.writer().retire_stale_admitted(TX, 109)
        head = git(self.repo.root, "rev-parse", "HEAD")
        with self.assertRaises(persistence.RepositoryPersistenceError):
            self.repo.writer().retire_stale_admitted(TX, 109)
        self.assertEqual(head, git(self.repo.root, "rev-parse", "HEAD"))
        self.assertEqual(2, self.repo.journal()["generation"])

    def test_wrong_authorization_and_snapshot_reject(self):
        for tx, revision in (("f" * 64, 109), (TX, 108), (TX, 110)):
            with self.subTest(tx=tx, revision=revision), self.assertRaises(persistence.RepositoryPersistenceError):
                self.repo.writer().retire_stale_admitted(tx, revision)
        self.assertEqual(1, self.repo.journal()["generation"])

    def test_remote_advance_is_not_overwritten(self):
        racer = self.repo.root.parent / "racer"
        git(self.repo.root.parent, "clone", "--branch", "main", str(self.repo.remote), str(racer))
        git(racer, "config", "user.name", "Racer")
        git(racer, "config", "user.email", "racer@example.invalid")
        (racer / "unrelated.txt").write_text("advanced", encoding="utf-8")
        git(racer, "add", "unrelated.txt")
        git(racer, "commit", "-m", "concurrent remote advance")
        git(racer, "push", "origin", "main")
        advanced = git(racer, "rev-parse", "HEAD")
        with self.assertRaises(persistence.RepositoryPersistenceError):
            self.repo.writer().retire_stale_admitted(TX, 109)
        self.assertEqual(advanced, git(racer, "rev-parse", "origin/main"))

    def test_uncertain_push_is_reconciled_by_exact_remote_readback(self):
        real_push = persistence._push
        def push_then_lose_reply(*args, **kwargs):
            real_push(*args, **kwargs)
            raise persistence.RepositoryPersistenceError("simulated lost push response")
        with mock.patch.object(persistence, "_push", side_effect=push_then_lose_reply):
            result = self.repo.writer().retire_stale_admitted(TX, 109)
        self.assertEqual("RETIRED_BLOCKED", result["status"])
        self.assertEqual(2, self.repo.journal()["generation"])

    def test_failed_push_without_remote_change_fails_closed(self):
        with mock.patch.object(persistence, "_push", side_effect=persistence.RepositoryPersistenceError("offline")):
            with self.assertRaises(persistence.RepositoryPersistenceError):
                self.repo.writer().retire_stale_admitted(TX, 109)
        self.assertEqual(1, self.repo.journal()["generation"])

    def test_nonpristine_snapshot_variants_reject_without_remote_write(self):
        mutations = (
            lambda j: j["active"].update(state="build_ready"),
            lambda j: j["active"].update(build_bundle_sha256="a" * 64),
            lambda j: j["active"].update(proof_evidence_sha256="a" * 64),
            lambda j: j["active"].update(state_commit_sha="a" * 40),
            lambda j: j["active"].update(recovery_status="REQUIRED"),
            lambda j: j["active"]["operations"]["upload_version"].update(attempts=[{"attempt_id": "1"}]),
            lambda j: j["active"]["operations"]["upload_version"].update(intent_state="RECORDED"),
            lambda j: j["active"]["operations"]["upload_version"].update(result_state="UNKNOWN"),
            lambda j: j.update(pending=copy.deepcopy(j["active"])),
            lambda j: j["active"].update(logical_transaction_id="f" * 64),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                journal = copy.deepcopy(self.repo.journal())
                mutate(journal)
                path = self.repo.root / JOURNAL
                path.write_bytes(serialize_journal(journal))
                digest = journal_digest(journal)
                with mock.patch.object(persistence, "STALE_ADMITTED_JOURNAL_SHA256", digest):
                    with self.assertRaises((persistence.RepositoryPersistenceError, JournalInvalid)):
                        self.repo.writer().retire_stale_admitted(TX, 109)
                # Restore the accepted bytes for the next independent unsafe variant.
                path.write_bytes(JOURNAL_FIXTURE.read_bytes())
        self.assertEqual(1, self.repo.journal()["generation"])

    def test_cli_reads_live_revision_before_retirement_and_refuses_old_values(self):
        journal = self.repo.root / JOURNAL
        argv = ["retire-stale-admitted", "--repository", str(self.repo.root), "--journal", str(journal),
                "--transaction-id", TX, "--expected-revision", "109", "--remote", "origin", "--branch", "main"]
        for revision in (109, 108):
            with mock.patch.object(cli, "fetch_public_content_revision", return_value=(revision, "2026-10-06T00:00:00+00:00", {})):
                self.assertEqual(2, cli.main(argv))
            self.assertEqual(1, self.repo.journal()["generation"])

    def test_cli_records_live_revision_and_normalized_timestamp(self):
        journal = self.repo.root / JOURNAL
        argv = ["retire-stale-admitted", "--repository", str(self.repo.root), "--journal", str(journal),
                "--transaction-id", TX, "--expected-revision", "109", "--remote", "origin", "--branch", "main"]
        captured = io.StringIO()
        with mock.patch.object(cli, "fetch_public_content_revision",
                               return_value=(111, "2026-10-06T00:00:00+00:00", {"offline": True})), redirect_stdout(captured):
            self.assertEqual(0, cli.main(argv))
        evidence = json.loads(captured.getvalue())
        self.assertEqual("RETIRED_BLOCKED", evidence["status"])
        self.assertEqual(111, evidence["observed_public_revision"])
        self.assertEqual("2026-10-06T00:00:00+00:00", evidence["observed_changed_at"])
        self.assertEqual(2, self.repo.journal()["generation"])


if __name__ == "__main__":
    unittest.main()
