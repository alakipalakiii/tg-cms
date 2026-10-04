from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from publisher import repository_persistence as repository
from publisher import workflow_stage_cli as cli
from publisher.transaction_journal import (
    CONTRACT, FileJournalStore, JournalInvalid, TransactionJournal,
    empty_journal, journal_digest, serialize_journal, validate_journal,
)

WORKER = "synthetic-worker"


def git(root: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(["git", *args], cwd=root, check=False,
                            capture_output=True, text=True)
    if check and result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout.strip()


class BareRemote:
    """Git-only fixture: no GitHub, network service, or production data."""

    def __init__(self, parent: Path):
        self.root, self.bare = parent / "repo", parent / "remote.git"
        self.root.mkdir()
        git(parent, "init", "--bare", str(self.bare))
        git(self.root, "init", "-b", "main")
        git(self.root, "config", "user.name", "Synthetic A5.6")
        git(self.root, "config", "user.email", "a56@example.invalid")
        (self.root / "fixture.txt").write_text("synthetic base", encoding="utf-8")
        git(self.root, "add", "fixture.txt")
        git(self.root, "commit", "-m", "synthetic repository baseline")
        git(self.root, "remote", "add", "origin", str(self.bare))
        git(self.root, "push", "-u", "origin", "main")

    def writer(self) -> repository.GitJournalWriter:
        return repository.GitJournalWriter(self.root, WORKER, "origin", "main")

    def head(self) -> str:
        return repository._remote_head(self.root, "origin", "main")

    def remote_journal(self) -> tuple[bytes, dict]:
        head = self.head()
        raw = subprocess.run(["git", "show", f"{head}:{repository.JOURNAL_PATH}"],
                             cwd=self.root, check=True, capture_output=True).stdout
        return raw, json.loads(raw.decode("utf-8"))

    def racer(self, name: str = "racer") -> Path:
        path = self.root.parent / name
        git(self.root.parent, "clone", "--branch", "main", str(self.bare), str(path))
        git(path, "config", "user.name", "Synthetic racer")
        git(path, "config", "user.email", "racer@example.invalid")
        return path


class LocalBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mahoon-a56-local-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / repository.JOURNAL_PATH

    def test_01_canonical_initial_journal_validates(self):
        self.assertEqual(CONTRACT, empty_journal(WORKER)["contract"])
        self.assertEqual(empty_journal(WORKER), validate_journal(empty_journal(WORKER), WORKER))

    def test_02_initial_digest_uses_existing_canonical_digest(self):
        value = empty_journal(WORKER)
        self.assertEqual(hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                                    separators=(",", ":")).encode()).hexdigest(),
                         journal_digest(value))

    def test_03_initial_generation_is_factory_generation_zero(self):
        self.assertEqual(0, empty_journal(WORKER)["generation"])

    def test_04_initial_state_has_no_active_transaction(self):
        self.assertIsNone(empty_journal(WORKER)["active"])

    def test_05_initial_state_has_no_pending_revision(self):
        self.assertIsNone(empty_journal(WORKER)["pending"])

    def test_06_initial_state_has_no_fabricated_history(self):
        self.assertEqual([], empty_journal(WORKER)["history"])

    def test_07_initial_state_contains_no_mutation_or_proof_authority(self):
        initial = empty_journal(WORKER)
        self.assertEqual({"contract", "schema_version", "worker", "generation",
                          "active", "pending", "history"}, set(initial))

    def test_08_absent_local_journal_initializes_and_reads_back(self):
        status, value, digest = FileJournalStore(self.path).initialize(WORKER)
        self.assertEqual("INITIALIZED", status)
        self.assertEqual(empty_journal(WORKER), value)
        self.assertEqual(journal_digest(value), digest)

    def test_09_existing_empty_local_journal_is_idempotent_without_rewrite(self):
        status, _, _ = FileJournalStore(self.path).initialize(WORKER)
        raw, mtime = self.path.read_bytes(), self.path.stat().st_mtime_ns
        again, value, _ = FileJournalStore(self.path).initialize(WORKER)
        self.assertEqual("INITIALIZED", status)
        self.assertEqual("ALREADY_INITIALIZED", again)
        self.assertEqual(raw, self.path.read_bytes())
        self.assertEqual(mtime, self.path.stat().st_mtime_ns)
        self.assertEqual(empty_journal(WORKER), value)

    def test_10_malformed_local_journal_fails_without_overwrite(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b"{broken")
        before = self.path.read_bytes()
        with self.assertRaises(JournalInvalid):
            FileJournalStore(self.path).initialize(WORKER)
        self.assertEqual(before, self.path.read_bytes())

    def test_11_wrong_worker_local_journal_fails_without_overwrite(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(serialize_journal(empty_journal("another-worker")))
        before = self.path.read_bytes()
        with self.assertRaises(JournalInvalid):
            FileJournalStore(self.path).initialize(WORKER)
        self.assertEqual(before, self.path.read_bytes())

    def test_12_progressed_local_journal_is_never_reset(self):
        store = FileJournalStore(self.path)
        store.initialize(WORKER)
        journal = TransactionJournal(store, WORKER)
        journal.admit(91, "synthetic")
        before = self.path.read_bytes()
        status, state, digest = store.initialize(WORKER)
        self.assertEqual("ALREADY_INITIALIZED", status)
        self.assertEqual(before, self.path.read_bytes())
        self.assertIsNotNone(state["active"])
        self.assertEqual(1, state["generation"])
        self.assertEqual(journal_digest(state), digest)

    def test_13_local_create_race_with_identical_initial_state_is_idempotent(self):
        original = os.link
        def compete(source, destination):
            Path(destination).write_bytes(serialize_journal(empty_journal(WORKER)))
            raise FileExistsError(destination)
        with mock.patch("publisher.transaction_journal.os.link", side_effect=compete):
            status, value, _ = FileJournalStore(self.path).initialize(WORKER)
        self.assertEqual("ALREADY_INITIALIZED", status)
        self.assertEqual(empty_journal(WORKER), value)
        self.assertTrue(callable(original))

    def test_14_local_create_race_with_progress_preserves_remote_like_state(self):
        progressed = empty_journal(WORKER)
        progressed["generation"] = 1
        def compete(_source, destination):
            Path(destination).write_bytes(serialize_journal(progressed))
            raise FileExistsError(destination)
        with mock.patch("publisher.transaction_journal.os.link", side_effect=compete):
            status, value, _ = FileJournalStore(self.path).initialize(WORKER)
        self.assertEqual("ALREADY_INITIALIZED", status)
        self.assertEqual(progressed, value)
        self.assertEqual(serialize_journal(progressed), self.path.read_bytes())

    def test_15_local_symlink_is_rejected(self):
        self.path.parent.mkdir(parents=True)
        target = self.path.parent / "target.json"
        target.write_bytes(serialize_journal(empty_journal(WORKER)))
        try:
            self.path.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("filesystem does not permit symlink fixtures")
        with self.assertRaises(JournalInvalid):
            FileJournalStore(self.path).initialize(WORKER)


class RemoteBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mahoon-a56-remote-")
        self.addCleanup(self.temp.cleanup)
        self.git = BareRemote(Path(self.temp.name))

    def test_16_missing_remote_journal_initializes_successfully(self):
        result = self.git.writer().bootstrap()
        self.assertEqual("INITIALIZED", result["status"])
        raw, value = self.git.remote_journal()
        self.assertEqual(serialize_journal(empty_journal(WORKER)), raw)
        self.assertEqual(empty_journal(WORKER), value)

    def test_17_remote_initialization_commit_contains_only_journal(self):
        result = self.git.writer().bootstrap()
        self.assertEqual({repository.JOURNAL_PATH},
                         set(git(self.git.root, "diff-tree", "--no-commit-id", "--name-only", "-r",
                                 result["remote_head"]).splitlines()))

    def test_18_remote_readback_proves_head_state_digest_and_generation(self):
        result = self.git.writer().bootstrap()
        raw, value = self.git.remote_journal()
        self.assertEqual(self.git.head(), result["remote_head"])
        self.assertEqual(0, result["generation"])
        self.assertEqual(journal_digest(value), result["journal_sha256"])
        self.assertEqual(raw, serialize_journal(value))

    def test_19_existing_valid_empty_remote_is_already_initialized_no_commit(self):
        writer = self.git.writer()
        writer.bootstrap()
        before = self.git.head()
        result = self.git.writer().bootstrap()
        self.assertEqual("ALREADY_INITIALIZED", result["status"])
        self.assertEqual(before, self.git.head())
        self.assertEqual(0, result["generation"])

    def test_20_existing_progressed_remote_is_already_initialized_no_reset(self):
        writer = self.git.writer()
        writer.bootstrap()
        writer.admit_revision(92, "synthetic")
        before, raw_before = self.git.head(), self.git.remote_journal()[0]
        result = self.git.writer().bootstrap()
        self.assertEqual("ALREADY_INITIALIZED", result["status"])
        self.assertEqual(before, self.git.head())
        self.assertEqual(raw_before, self.git.remote_journal()[0])
        self.assertEqual(1, result["generation"])

    def test_21_bootstrap_rejects_alternate_journal_path(self):
        with self.assertRaises(repository.RepositoryPersistenceError):
            repository.GitJournalWriter(self.git.root, WORKER, journal_path="publisher-state/other.json")

    def test_22_bootstrap_rejects_path_traversal(self):
        with self.assertRaises(repository.RepositoryPersistenceError):
            repository.GitJournalWriter(self.git.root, WORKER, journal_path="../journal.json")

    def test_23_stale_local_branch_cannot_initialize_missing_remote_state(self):
        racer = self.git.racer()
        (racer / "advance.txt").write_text("advance", encoding="utf-8")
        git(racer, "add", "advance.txt")
        git(racer, "commit", "-m", "advance without journal")
        git(racer, "push", "origin", "main")
        before = git(self.git.root, "rev-parse", "HEAD")
        with self.assertRaises(repository.RepositoryPersistenceError):
            self.git.writer().bootstrap()
        self.assertEqual(before, git(self.git.root, "rev-parse", "HEAD"))
        self.assertFalse((self.git.root / repository.JOURNAL_PATH).exists())

    def test_24_staged_unrelated_change_blocks_without_inclusion_or_loss(self):
        path = self.git.root / "staged.txt"
        path.write_text("staged", encoding="utf-8")
        git(self.git.root, "add", "staged.txt")
        before = git(self.git.root, "diff", "--cached", "--name-only")
        with self.assertRaises(repository.RepositoryPersistenceError):
            self.git.writer().bootstrap()
        self.assertEqual(before, git(self.git.root, "diff", "--cached", "--name-only"))
        self.assertFalse((self.git.root / repository.JOURNAL_PATH).exists())
        self.assertEqual(self.git.head(), repository._remote_head(self.git.root, "origin", "main"))

    def test_25_unrelated_dirty_and_untracked_files_are_preserved_excluded(self):
        fixture = self.git.root / "fixture.txt"
        fixture.write_text("dirty user content", encoding="utf-8")
        extra = self.git.root / "untracked.txt"
        extra.write_text("keep", encoding="utf-8")
        before = git(self.git.root, "rev-parse", "HEAD")
        result = self.git.writer().bootstrap()
        self.assertEqual("INITIALIZED", result["status"])
        self.assertEqual("dirty user content", fixture.read_text(encoding="utf-8"))
        self.assertEqual("keep", extra.read_text(encoding="utf-8"))
        self.assertEqual({repository.JOURNAL_PATH},
                         set(git(self.git.root, "diff-tree", "--no-commit-id", "--name-only", "-r",
                                 result["remote_head"]).splitlines()))
        self.assertNotEqual(before, result["remote_head"])

    def test_26_push_path_never_uses_force(self):
        original = repository._git
        calls = []
        def capture(root, *args, **kwargs):
            calls.append(args)
            return original(root, *args, **kwargs)
        with mock.patch.object(repository, "_git", side_effect=capture):
            self.git.writer().bootstrap()
        pushes = [args for args in calls if args and args[0] == "push"]
        self.assertEqual(1, len(pushes))
        self.assertFalse(any(arg in {"--force", "-f", "--force-with-lease"} for arg in pushes[0]))

    def _wrong_readback(self, transform):
        writer = self.git.writer()
        original = writer._remote_journal_snapshot
        calls = 0
        def readback():
            nonlocal calls
            calls += 1
            value = original()
            return transform(value) if calls == 2 else value
        writer._remote_journal_snapshot = readback
        with self.assertRaises(repository.RepositoryPersistenceError):
            writer.bootstrap()

    def test_27_wrong_remote_readback_head_rejected(self):
        self._wrong_readback(lambda row: (row[0], row[1], row[2], "f" * 40, row[4]))

    def test_28_wrong_remote_journal_bytes_or_state_rejected(self):
        def wrong(row):
            value = copy.deepcopy(row[0])
            value["generation"] += 1
            return value, value["generation"], journal_digest(value), row[3], serialize_journal(value)
        self._wrong_readback(wrong)

    def test_29_wrong_remote_digest_rejected(self):
        self._wrong_readback(lambda row: (row[0], row[1], "f" * 64, row[3], row[4]))

    def test_30_wrong_remote_generation_rejected(self):
        self._wrong_readback(lambda row: (row[0], row[1] + 1, row[2], row[3], row[4]))

    def _race_with(self, mutation):
        racer = self.git.racer("race")
        writer_b = repository.GitJournalWriter(racer, WORKER, "origin", "main")
        real_push = repository._push
        entered = False
        def race_push(root, remote, branch, commit):
            nonlocal entered
            if not entered:
                entered = True
                mutation(racer, writer_b)
            return real_push(root, remote, branch, commit)
        return mock.patch.object(repository, "_push", side_effect=race_push)

    def test_31_identical_concurrent_initialization_reconciles_as_already(self):
        def initialize(_racer, writer):
            self.assertEqual("INITIALIZED", writer.bootstrap()["status"])
        with self._race_with(initialize):
            result = self.git.writer().bootstrap()
        self.assertEqual("ALREADY_INITIALIZED", result["status"])
        self.assertEqual(empty_journal(WORKER), self.git.remote_journal()[1])

    def test_32_concurrent_progressed_journal_is_never_reset(self):
        def progress(_racer, writer):
            writer.bootstrap()
            writer.admit_revision(93, "synthetic-racer")
        with self._race_with(progress):
            result = self.git.writer().bootstrap()
        self.assertEqual("ALREADY_INITIALIZED", result["status"])
        state = self.git.remote_journal()[1]
        self.assertEqual(93, state["active"]["content_revision"])
        self.assertEqual(1, state["generation"])

    def test_33_malformed_concurrent_remote_state_fails_closed(self):
        def malformed(racer, _writer):
            path = racer / repository.JOURNAL_PATH
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"{malformed")
            git(racer, "add", repository.JOURNAL_PATH)
            git(racer, "commit", "-m", "synthetic malformed journal race")
            git(racer, "push", "origin", "main")
        with self._race_with(malformed):
            with self.assertRaises(repository.RepositoryPersistenceError):
                self.git.writer().bootstrap()
        raw = subprocess.run(["git", "show", f"{self.git.head()}:{repository.JOURNAL_PATH}"],
                             cwd=self.git.root, check=True, capture_output=True).stdout
        self.assertEqual(b"{malformed", raw)

    def test_34_non_fast_forward_unrelated_race_fails_without_force(self):
        def advance(racer, _writer):
            (racer / "race.txt").write_text("unrelated", encoding="utf-8")
            git(racer, "add", "race.txt")
            git(racer, "commit", "-m", "synthetic unrelated race")
            git(racer, "push", "origin", "main")
        with self._race_with(advance):
            with self.assertRaises(repository.RepositoryPersistenceError):
                self.git.writer().bootstrap()
        self.assertNotEqual(0, subprocess.run(
            ["git", "cat-file", "-e", f"{self.git.head()}:{repository.JOURNAL_PATH}"],
            cwd=self.git.root, capture_output=True,
        ).returncode)
        race_file = subprocess.run(["git", "show", f"{self.git.head()}:race.txt"],
                                   cwd=self.git.root, check=True, capture_output=True, text=True)
        self.assertEqual("unrelated", race_file.stdout.strip())

    def test_35_remote_case_alias_is_rejected(self):
        alias = self.git.root / "publisher-State" / "Production-Transaction-Journal.json"
        alias.parent.mkdir(parents=True)
        alias.write_bytes(serialize_journal(empty_journal(WORKER)))
        git(self.git.root, "add", "publisher-State/Production-Transaction-Journal.json")
        git(self.git.root, "commit", "-m", "synthetic path alias")
        git(self.git.root, "push", "origin", "main")
        with self.assertRaises(repository.RepositoryPersistenceError):
            self.git.writer().bootstrap()

    def test_36_local_remote_bootstrap_cli_returns_initialized(self):
        args = ["bootstrap-journal", "--repository", str(self.git.root), "--worker", WORKER]
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(args)
        self.assertEqual(0, code, stderr.getvalue())
        self.assertEqual("INITIALIZED", json.loads(stdout.getvalue())["status"])

    def test_37_local_remote_bootstrap_cli_returns_already_initialized(self):
        self.git.writer().bootstrap()
        head = self.git.head()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = cli.main(["bootstrap-journal", "--repository", str(self.git.root), "--worker", WORKER])
        self.assertEqual(0, code)
        self.assertEqual("ALREADY_INITIALIZED", json.loads(stdout.getvalue())["status"])
        self.assertEqual(head, self.git.head())

    def test_38_cli_failure_is_nonzero_and_does_not_echo_secrets(self):
        secret = "synthetic-never-log-token-71a2"
        path = self.git.root / repository.JOURNAL_PATH
        path.parent.mkdir(parents=True)
        path.write_bytes(b"bad journal")
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {"CLOUDFLARE_API_TOKEN": secret}), \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(["bootstrap-journal", "--repository", str(self.git.root), "--worker", WORKER])
        self.assertNotEqual(0, code)
        self.assertNotIn(secret, stdout.getvalue() + stderr.getvalue())

    def test_39_cli_bootstrap_invokes_no_admission_mutation_proof_or_persistence(self):
        forbidden = AssertionError("bootstrap called a non-bootstrap transition")
        patches = [
            mock.patch.object(repository.GitJournalWriter, "admit_revision", side_effect=forbidden),
            mock.patch.object(repository.GitJournalWriter, "record_build_ready", side_effect=forbidden),
            mock.patch.object(repository.GitJournalWriter, "record_intent", side_effect=forbidden),
            mock.patch.object(repository.GitJournalWriter, "record_result", side_effect=forbidden),
            mock.patch.object(TransactionJournal, "admit", side_effect=forbidden),
            mock.patch.object(cli, "execute_production_proof", side_effect=forbidden),
            mock.patch.object(cli, "execute_final_persistence", side_effect=forbidden),
        ]
        with contextlib.ExitStack() as stack:
            for patcher in patches:
                stack.enter_context(patcher)
            result = self.git.writer().bootstrap()
        self.assertEqual("INITIALIZED", result["status"])

    def test_40_cli_has_no_caller_controlled_journal_path(self):
        with self.assertRaises(SystemExit):
            cli._parser().parse_args(["bootstrap-journal", "--repository", str(self.git.root),
                                      "--journal", "../other.json"])

    def test_41_bootstrap_cli_requires_no_cloudflare_credentials_or_adapter(self):
        removed = {key: os.environ.pop(key) for key in list(os.environ)
                   if key.upper().startswith("CLOUDFLARE_")}
        stdout = io.StringIO()
        try:
            with mock.patch.dict(sys.modules, {"publisher.cloudflare_operation_adapter": None}), \
                 contextlib.redirect_stdout(stdout):
                code = cli.main(["bootstrap-journal", "--repository", str(self.git.root),
                                 "--worker", WORKER])
        finally:
            os.environ.update(removed)
        self.assertEqual(0, code)
        self.assertEqual("INITIALIZED", json.loads(stdout.getvalue())["status"])


if __name__ == "__main__":
    unittest.main()
