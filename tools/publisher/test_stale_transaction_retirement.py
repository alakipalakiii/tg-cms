"""Offline tests for the approved stale-admission retirement boundaries."""
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
TX118 = "d21d07fcbde817aa63195837c167f03c99c85752af7d7ef878009b9dd450be5f"
WORKER = "mahoon-art-magazine"
JOURNAL = "publisher-state/production-transaction-journal.json"
JOURNAL_FIXTURE = Path(__file__).resolve().parent / "fixtures/pre-retirement-journal-v2.json"
JOURNAL_118_FIXTURE = Path(__file__).resolve().parent / "fixtures/pre-retirement-revision-118-journal-v2.json"


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


class Revision118RetirementRepository:
    """Build a git repo whose journal is the pristine revision-118 admission (gen 3)."""

    def __init__(self, parent):
        self.root, self.remote = parent / "repo", parent / "remote.git"
        self.root.mkdir()
        git(parent, "init", "--bare", str(self.remote))
        git(self.root, "init", "-b", "main")
        git(self.root, "config", "user.name", "Retirement test")
        git(self.root, "config", "user.email", "retirement@example.invalid")
        (self.root / JOURNAL).parent.mkdir(parents=True)
        (self.root / JOURNAL).write_bytes(JOURNAL_118_FIXTURE.read_bytes())
        git(self.root, "add", JOURNAL)
        git(self.root, "commit", "-m", "accepted revision-118 journal fixture")
        git(self.root, "remote", "add", "origin", str(self.remote))
        git(self.root, "push", "-u", "origin", "main")

    def writer(self):
        return persistence.GitJournalWriter(self.root, WORKER, "origin", "main")

    def journal(self):
        head = git(self.root, "rev-parse", "origin/main")
        return json.loads(git(self.root, "show", f"{head}:{JOURNAL}"))

    def gen_and_digest(self):
        value = self.journal()
        return value["generation"], journal_digest(value)

    def digest(self):
        return self.gen_and_digest()[1]

    def gen_and_digest_of(self, value):
        return value["generation"], journal_digest(value)


class StaleRetirementV2Tests(unittest.TestCase):
    """Regression coverage for the generic retire_stale_admitted_v2 path."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mahoon-retire-v2-")
        self.addCleanup(self.temp.cleanup)
        self.repo = Revision118RetirementRepository(Path(self.temp.name))

    def _argv(self, **overrides):
        base = {"repository": str(self.repo.root), "journal": str(self.repo.root / JOURNAL),
                "transaction_id": TX118, "expected_revision": 118, "remote": "origin", "branch": "main"}
        base.update(overrides)
        args = ["retire-stale-admitted"]
        for key, value in base.items():
            args += [f"--{key.replace('_', '-')}", str(value)]
        return args

    def test_pristine_revision_118_retires_as_one_journal_only_commit(self):
        before = git(self.repo.root, "rev-parse", "HEAD")
        generation, digest = self.repo.gen_and_digest()
        self.assertEqual((3, digest), (generation, "6b76afcfc128d2d6bdfdb9a7ee8dd6f782b6dbc7a2f1e7f230c84fd898c6537b"))
        result = self.repo.writer().retire_stale_admitted_v2(
            TX118, 118, expected_generation=generation, expected_digest=digest)
        state = self.repo.journal()
        self.assertEqual("RETIRED_BLOCKED", result["status"])
        self.assertEqual(4, state["generation"])
        self.assertIsNone(state["active"])
        self.assertIsNone(state["pending"])
        old = next(item for item in state["history"] if item["logical_transaction_id"] == TX118)
        self.assertEqual((118, "blocked"), (old["content_revision"], old["state"]))
        self.assertEqual("admitted", old["transitions"][0]["to"])
        self.assertEqual("blocked", old["transitions"][-1]["to"])
        # The earlier blocked revision-109 history entry must be preserved unchanged.
        prior_109 = next(item for item in state["history"] if item["content_revision"] == 109)
        self.assertEqual("blocked", prior_109["state"])
        self.assertEqual(TX, prior_109["logical_transaction_id"])
        commit = result["remote_head"]
        self.assertEqual(before, git(self.repo.root, "rev-parse", f"{commit}^"))
        self.assertEqual(JOURNAL, git(self.repo.root, "diff-tree", "--no-commit-id", "--name-only", "-r", commit))
        self.assertEqual(result["retired_transaction_id"], TX118)
        self.assertEqual(result["retired_revision"], 118)
        # The pushed remote blob must equal the locally serialized journal exactly.
        self.assertEqual((self.repo.root / JOURNAL).read_bytes(), subprocess.run(
            ["git", "show", f"origin/main:{JOURNAL}"], cwd=self.repo.root,
            capture_output=True, check=True,
        ).stdout)

    def test_repeated_v2_retirement_does_not_make_another_generation(self):
        generation, digest = self.repo.gen_and_digest()
        self.repo.writer().retire_stale_admitted_v2(TX118, 118,
                                                    expected_generation=generation, expected_digest=digest)
        head = git(self.repo.root, "rev-parse", "HEAD")
        state = self.repo.journal()
        new_generation, new_digest = self.repo.gen_and_digest_of(state)
        with self.assertRaises(persistence.RepositoryPersistenceError):
            self.repo.writer().retire_stale_admitted_v2(
                TX118, 118,
                expected_generation=new_generation,
                expected_digest=new_digest,
            )
        self.assertEqual(head, git(self.repo.root, "rev-parse", "HEAD"))
        self.assertEqual(4, self.repo.journal()["generation"])

    def test_v2_rejects_wrong_transaction_id_or_revision(self):
        generation, digest = self.repo.gen_and_digest()
        for tx, revision in (("f" * 64, 118), (TX118, 117), (TX118, 119)):
            with self.subTest(tx=tx, revision=revision), self.assertRaises(persistence.RepositoryPersistenceError):
                self.repo.writer().retire_stale_admitted_v2(
                    tx, revision, expected_generation=generation, expected_digest=digest)
        self.assertEqual(3, self.repo.journal()["generation"])

    def test_v2_rejects_wrong_generation(self):
        _, digest = self.repo.gen_and_digest()
        with self.assertRaises(persistence.RepositoryPersistenceError):
            self.repo.writer().retire_stale_admitted_v2(
                TX118, 118, expected_generation=2, expected_digest=digest)
        self.assertEqual(3, self.repo.journal()["generation"])

    def test_v2_rejects_wrong_digest(self):
        generation, _ = self.repo.gen_and_digest()
        with self.assertRaises(persistence.RepositoryPersistenceError):
            self.repo.writer().retire_stale_admitted_v2(
                TX118, 118, expected_generation=generation, expected_digest="a" * 64)
        self.assertEqual(3, self.repo.journal()["generation"])

    def test_v2_refuses_retirement_when_build_bundle_or_mutation_evidence_exists(self):
        variants = (
            lambda j: j["active"].update(build_bundle_sha256="b" * 64),
            lambda j: j["active"].update(proof_evidence_sha256="b" * 64),
            lambda j: j["active"]["operations"]["upload_version"].update(attempts=[
                {"attempt_number": 1, "attempt_id": "11111111-1111-1111-1111-111111111111",
                 "intent_state": "RECORDED", "result_state": "NOT_REPORTED", "intent_at": "x"}]),
            lambda j: j["active"]["operations"]["promote"].update(intent_state="RECORDED"),
            lambda j: j["active"].update(recovery_status="REQUIRED"),
            lambda j: j["active"].update(state="build_ready"),
        )
        for mutate in variants:
            with self.subTest():
                journal = json.loads(JOURNAL_118_FIXTURE.read_text(encoding="utf-8"))
                mutate(journal)
                path = self.repo.root / JOURNAL
                path.write_bytes(serialize_journal(journal))
                git(self.repo.root, "add", JOURNAL)
                git(self.repo.root, "commit", "-m", "mutate journal")
                git(self.repo.root, "push", "origin", "main")
                generation, digest = self.repo.gen_and_digest()
                with self.assertRaises(persistence.RepositoryPersistenceError):
                    self.repo.writer().retire_stale_admitted_v2(
                        TX118, 118, expected_generation=generation, expected_digest=digest)
                # Restore the pristine bytes so each variant starts from the same baseline.
                path.write_bytes(JOURNAL_118_FIXTURE.read_bytes())
                git(self.repo.root, "add", JOURNAL)
                git(self.repo.root, "commit", "-m", "restore pristine")
                git(self.repo.root, "push", "origin", "main")
        generation, digest = self.repo.gen_and_digest()
        self.assertEqual("RETIRED_BLOCKED", self.repo.writer().retire_stale_admitted_v2(
            TX118, 118, expected_generation=generation, expected_digest=digest)["status"])

    def test_v2_uncertain_push_is_reconciled_by_exact_remote_readback(self):
        real_push = persistence._push
        def push_then_lose_reply(*args, **kwargs):
            real_push(*args, **kwargs)
            raise persistence.RepositoryPersistenceError("simulated lost push response")
        generation, digest = self.repo.gen_and_digest()
        with mock.patch.object(persistence, "_push", side_effect=push_then_lose_reply):
            result = self.repo.writer().retire_stale_admitted_v2(
                TX118, 118, expected_generation=generation, expected_digest=digest)
        self.assertEqual("RETIRED_BLOCKED", result["status"])
        self.assertEqual(4, self.repo.journal()["generation"])

    def test_v2_failed_push_without_remote_change_fails_closed(self):
        with mock.patch.object(persistence, "_push", side_effect=persistence.RepositoryPersistenceError("offline")):
            generation, digest = self.repo.gen_and_digest()
            with self.assertRaises(persistence.RepositoryPersistenceError):
                self.repo.writer().retire_stale_admitted_v2(
                    TX118, 118, expected_generation=generation, expected_digest=digest)
        self.assertEqual(3, self.repo.journal()["generation"])

    def test_cli_v2_routes_by_generation_and_digest(self):
        generation, digest = self.repo.gen_and_digest()
        argv = self._argv(expected_generation=generation, journal_sha256=digest)
        captured = io.StringIO()
        with mock.patch.object(cli, "fetch_public_content_revision",
                               return_value=(119, "2026-10-06T21:12:24+00:00", {"offline": True})), \
                redirect_stdout(captured):
            self.assertEqual(0, cli.main(argv))
        evidence = json.loads(captured.getvalue())
        self.assertEqual("RETIRED_BLOCKED", evidence["status"])
        self.assertEqual(TX118, evidence["retired_transaction_id"])
        self.assertEqual(118, evidence["retired_revision"])
        self.assertEqual(119, evidence["observed_public_revision"])
        self.assertEqual(4, self.repo.journal()["generation"])

    def test_cli_v2_requires_both_generation_and_digest(self):
        generation, digest = self.repo.gen_and_digest()
        for argv in (self._argv(expected_generation=generation), self._argv(journal_sha256=digest)):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(2, cli.main(argv))
        self.assertEqual(3, self.repo.journal()["generation"])

    def test_cli_without_generation_uses_legacy_109_path_and_rejects_118(self):
        # The legacy path is still wired to the revision-109 transaction only.
        argv = self._argv(transaction_id=TX118, expected_revision=118)
        with mock.patch.object(cli, "fetch_public_content_revision",
                               return_value=(119, "2026-10-06T21:12:24+00:00", {"offline": True})):
            self.assertEqual(2, cli.main(argv))
        self.assertEqual(3, self.repo.journal()["generation"])


if __name__ == "__main__":
    unittest.main()
