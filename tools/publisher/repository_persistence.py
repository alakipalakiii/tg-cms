"""Fail-closed Git adapters for the accepted journal and six-file persistence set."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Mapping

from publisher import artifact_contract as contracts
from publisher.final_persistence_runner import PersistenceBlocked
from publisher.transaction_journal import (
    DuplicateMutation, FileJournalStore, JournalConflict, JournalInvalid, OPERATIONS, RecoveryRequired,
    TransactionJournal, canonical_result_digest, empty_journal, journal_digest,
    serialize_journal, validate_journal,
)


JOURNAL_PATH = "publisher-state/production-transaction-journal.json"
STALE_ADMITTED_TX = "704bdb7d7161c7c5c89ef4865788e71a67df26fd2fe4cfb695d297c3900d18d2"
STALE_ADMITTED_JOURNAL_SHA256 = "b9d56d850e4cfb9c08dd00ced87a0a8ca3e77874a78bf64953579fc9c2a19859"
_SHA40 = frozenset("0123456789abcdef")


class RepositoryPersistenceError(PersistenceBlocked):
    """Repository state could not be committed or verified without overwriting."""


def _sha40(value: object) -> bool:
    return isinstance(value, str) and len(value) == 40 and all(ch in _SHA40 for ch in value)


def _sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(ch in _SHA40 for ch in value)


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            ["git", *args], cwd=root, check=False, capture_output=True, text=True,
        )
    except OSError as exc:
        raise RepositoryPersistenceError("git executable is unavailable") from exc
    if check and result.returncode:
        raise RepositoryPersistenceError("git persistence command failed")
    return result


def _remote_head(root: Path, remote: str, branch: str) -> str:
    result = _git(root, "ls-remote", "--heads", remote, f"refs/heads/{branch}")
    rows = [line.split() for line in result.stdout.splitlines() if line.strip()]
    if len(rows) != 1 or len(rows[0]) != 2 or rows[0][1] != f"refs/heads/{branch}" or not _sha40(rows[0][0]):
        raise RepositoryPersistenceError("remote branch identity is missing or ambiguous")
    return rows[0][0]


def _commit_paths(root: Path, commit: str) -> set[str]:
    result = _git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", commit)
    return {line.replace("\\", "/") for line in result.stdout.splitlines() if line}


def _blob(root: Path, commit: str, path: str) -> bytes:
    raw = subprocess.run(["git", "show", f"{commit}:{path}"], cwd=root,
                         check=False, capture_output=True)
    if raw.returncode:
        raise RepositoryPersistenceError("persisted state file is missing from commit")
    return raw.stdout


def _hashes_at(root: Path, commit: str, paths: set[str]) -> dict[str, str]:
    return {path: hashlib.sha256(_blob(root, commit, path)).hexdigest() for path in sorted(paths)}


class GitRepositoryReader:
    """Read one allowlisted state blob from a commit pinned before blob access."""

    def __init__(self, repository: str | Path, repository_identity: str,
                 remote: str = "origin", branch: str = "main"):
        if (not isinstance(repository_identity, str) or repository_identity.count("/") != 1
                or any(ch.isspace() or ord(ch) < 32 for ch in repository_identity)):
            raise RepositoryPersistenceError("repository identity is invalid")
        self.root = Path(repository).resolve()
        self.repository_identity = repository_identity
        self.remote, self.branch = remote, branch
        top = _git(self.root, "rev-parse", "--show-toplevel").stdout.strip()
        if Path(top).resolve() != self.root:
            raise RepositoryPersistenceError("repository root is not the Git worktree root")
        if _git(self.root, "check-ref-format", f"refs/heads/{branch}", check=False).returncode:
            raise RepositoryPersistenceError("state branch name is invalid")

    def read_immutable_media_index(self) -> dict:
        path = contracts.PRIOR_IMMUTABLE_MEDIA_INDEX_PATH
        commit = _remote_head(self.root, self.remote, self.branch)
        if not _sha40(commit):
            raise RepositoryPersistenceError("pinned state commit SHA is invalid")
        present = _git(self.root, "cat-file", "-e", f"{commit}^{{commit}}", check=False).returncode == 0
        if not present:
            _git(self.root, "fetch", "--no-tags", "--no-write-fetch-head", self.remote, commit)
        tree = subprocess.run(
            ["git", "ls-tree", "-z", commit, "--", path], cwd=self.root,
            check=False, capture_output=True,
        )
        if tree.returncode:
            raise RepositoryPersistenceError("pinned state tree could not be read")
        rows = [row for row in tree.stdout.split(b"\0") if row]
        if not rows:
            raw = b""
            exists = False
        else:
            if len(rows) != 1 or b"\t" not in rows[0]:
                raise RepositoryPersistenceError("pinned index path is ambiguous")
            metadata, returned_path = rows[0].split(b"\t", 1)
            fields = metadata.split()
            if (returned_path.decode("utf-8", "strict") != path or len(fields) != 3
                    or fields[0] != b"100644" or fields[1] != b"blob"):
                raise RepositoryPersistenceError("pinned index path is not a regular file")
            blob = subprocess.run(
                ["git", "cat-file", "blob", fields[2].decode("ascii")], cwd=self.root,
                check=False, capture_output=True,
            )
            if blob.returncode:
                raise RepositoryPersistenceError("pinned index blob could not be read")
            raw = blob.stdout
            exists = True
        return {
            "repository": self.repository_identity,
            "ref": f"refs/heads/{self.branch}",
            "commit_sha": commit,
            "relative_path": path,
            "exists": exists,
            "content_sha256": contracts.sha256_bytes(raw),
            "byte_length": len(raw),
            "content_bytes": raw,
        }


def _safe_file(root: Path, relative: str) -> Path:
    if relative not in contracts.STATE_FILE_PATHS:
        raise RepositoryPersistenceError("state path is not allowlisted")
    path = root.joinpath(*relative.split("/"))
    current = root
    for part in relative.split("/"):
        current = current / part
        if current.is_symlink():
            raise RepositoryPersistenceError("symlink in state path is forbidden")
    if not path.resolve().is_relative_to(root):
        raise RepositoryPersistenceError("state path escapes repository")
    return path


def _safe_journal_file(root: Path) -> Path:
    current = root
    for part in JOURNAL_PATH.split("/"):
        current = current / part
        if current.is_symlink():
            raise RepositoryPersistenceError("symlink in journal path is forbidden")
    if not current.resolve().is_relative_to(root):
        raise RepositoryPersistenceError("journal path escapes repository")
    return current


def _validate_files(files: Mapping[str, bytes]) -> dict[str, bytes]:
    if not isinstance(files, Mapping) or set(files) != set(contracts.STATE_FILE_PATHS):
        raise RepositoryPersistenceError("exact six-file publisher state is required")
    if any(not isinstance(path, str) or not isinstance(data, bytes) for path, data in files.items()):
        raise RepositoryPersistenceError("state files must map exact paths to bytes")
    return {path: bytes(files[path]) for path in sorted(contracts.STATE_FILE_PATHS)}


def _branch_head(root: Path, branch: str) -> str:
    if _git(root, "branch", "--show-current").stdout.strip() != branch:
        raise RepositoryPersistenceError("repository is not on the expected branch")
    head = _git(root, "rev-parse", "HEAD").stdout.strip()
    if not _sha40(head):
        raise RepositoryPersistenceError("local HEAD is invalid")
    return head


def _push(root: Path, remote: str, branch: str, commit: str) -> None:
    # No force option, retry, or ref rewrite is permitted.
    _git(root, "push", remote, f"{commit}:refs/heads/{branch}")
    if _remote_head(root, remote, branch) != commit:
        raise RepositoryPersistenceError("remote did not read back the exact pushed commit")


class GitRepositoryWriter:
    """Commit exactly the six state files, push fast-forward only, then read back."""

    def __init__(self, repository: str | Path, remote: str = "origin", branch: str = "main"):
        self.root = Path(repository).resolve()
        self.remote, self.branch = remote, branch
        top = _git(self.root, "rev-parse", "--show-toplevel").stdout.strip()
        if Path(top).resolve() != self.root:
            raise RepositoryPersistenceError("repository root is not the Git worktree root")
        _branch_head(self.root, branch)

    def _expected_commit(self, files: Mapping[str, bytes]) -> str:
        desired = {path: hashlib.sha256(data).hexdigest() for path, data in files.items()}
        commit = _git(self.root, "log", "-1", "--format=%H", "--",
                      *sorted(contracts.STATE_FILE_PATHS)).stdout.strip()
        if not _sha40(commit):
            raise RepositoryPersistenceError("prior exact-scope persistence commit is unavailable")
        paths = _commit_paths(self.root, commit)
        if not paths or not paths.issubset(contracts.STATE_FILE_PATHS):
            raise RepositoryPersistenceError("no prior exact-scope persistence commit can be reused")
        if _hashes_at(self.root, commit, set(contracts.STATE_FILE_PATHS)) != desired:
            raise RepositoryPersistenceError("prior persistence commit does not match requested state")
        return commit

    def persist_once(self, files: Mapping[str, bytes]) -> str:
        checked = _validate_files(files)
        head = _branch_head(self.root, self.branch)
        remote_head = _remote_head(self.root, self.remote, self.branch)
        status = _git(self.root, "status", "--porcelain=v1", "--untracked-files=all").stdout.splitlines()
        staged = _git(self.root, "diff", "--cached", "--name-only").stdout.splitlines()
        if staged:
            raise RepositoryPersistenceError("pre-existing staged changes prevent isolated persistence")
        target_changes = [line for line in status if line[3:].replace("\\", "/") in contracts.STATE_FILE_PATHS]
        if target_changes:
            raise RepositoryPersistenceError("pre-existing state-file changes prevent persistence")

        if head != remote_head:
            parents = _git(self.root, "rev-list", "--parents", "-n", "1", head).stdout.split()
            paths = _commit_paths(self.root, head)
            if (len(parents) != 2 or parents[1] != remote_head
                    or not paths or not paths.issubset(contracts.STATE_FILE_PATHS)
                    or _hashes_at(self.root, head, set(contracts.STATE_FILE_PATHS))
                    != {path: hashlib.sha256(data).hexdigest() for path, data in checked.items()}):
                raise RepositoryPersistenceError("local or remote branch advanced unexpectedly")
            _push(self.root, self.remote, self.branch, head)
            return head

        current_hashes = _hashes_at(self.root, head, set(contracts.STATE_FILE_PATHS))
        wanted_hashes = {path: hashlib.sha256(data).hexdigest() for path, data in checked.items()}
        if current_hashes == wanted_hashes:
            commit = self._expected_commit(checked)
            _git(self.root, "fetch", "--no-tags", "--quiet", self.remote, f"refs/heads/{self.branch}")
            fetched = _git(self.root, "rev-parse", "FETCH_HEAD").stdout.strip()
            if fetched != head:
                raise RepositoryPersistenceError("remote readback moved during idempotent persistence")
            return commit

        for relative, data in checked.items():
            path = _safe_file(self.root, relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            _safe_file(self.root, relative)
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".mahoon-state-", delete=False) as staged_file:
                temp = Path(staged_file.name)
                staged_file.write(data)
                staged_file.flush()
                os.fsync(staged_file.fileno())
            os.replace(temp, path)

        paths = sorted(contracts.STATE_FILE_PATHS)
        _git(self.root, "add", "--", *paths)
        staged_paths = {line.replace("\\", "/") for line in
                        _git(self.root, "diff", "--cached", "--name-only").stdout.splitlines() if line}
        if not staged_paths or not staged_paths.issubset(contracts.STATE_FILE_PATHS):
            raise RepositoryPersistenceError("staged persistence scope is empty or unauthorized")
        for relative, expected in wanted_hashes.items():
            blob_id = _git(self.root, "rev-parse", f":{relative}").stdout.strip()
            raw = subprocess.run(["git", "cat-file", "blob", blob_id], cwd=self.root,
                                 check=False, capture_output=True)
            if raw.returncode or hashlib.sha256(raw.stdout).hexdigest() != expected:
                raise RepositoryPersistenceError("staged state hash differs from the validated payload")
        _git(self.root, "-c", "user.name=MAHOON Publisher", "-c",
             "user.email=mahoon-publisher@users.noreply.github.com",
             "commit", "-m", "chore: persist verified MAHOON publisher state")
        commit = _branch_head(self.root, self.branch)
        parent = _git(self.root, "rev-list", "--parents", "-n", "1", commit).stdout.split()
        committed_paths = _commit_paths(self.root, commit)
        if (len(parent) != 2 or parent[1] != head or committed_paths != staged_paths
                or not committed_paths.issubset(contracts.STATE_FILE_PATHS)
                or _hashes_at(self.root, commit, set(contracts.STATE_FILE_PATHS)) != wanted_hashes):
            raise RepositoryPersistenceError("created persistence commit failed scope or hash verification")
        _push(self.root, self.remote, self.branch, commit)
        return commit

    def read_exact(self, commit_sha: str) -> Mapping[str, object]:
        if not _sha40(commit_sha):
            raise RepositoryPersistenceError("persistence commit identity is invalid")
        _git(self.root, "fetch", "--no-tags", "--quiet", self.remote, f"refs/heads/{self.branch}")
        remote_head = _git(self.root, "rev-parse", "FETCH_HEAD").stdout.strip()
        ancestor = _git(self.root, "merge-base", "--is-ancestor", commit_sha, remote_head, check=False)
        if ancestor.returncode:
            raise RepositoryPersistenceError("persistence commit is not present in the remote branch history")
        hashes = _hashes_at(self.root, commit_sha, set(contracts.STATE_FILE_PATHS))
        return {"commit_sha": commit_sha, "file_hashes": hashes}


class GitJournalWriter:
    """Persist each accepted journal transition in a separate one-file commit."""

    def __init__(self, repository: str | Path, worker: str,
                 remote: str = "origin", branch: str = "main",
                 journal_path: str = JOURNAL_PATH):
        if journal_path != JOURNAL_PATH:
            raise RepositoryPersistenceError("journal path is not the accepted path")
        self.root = Path(repository).resolve()
        self.worker, self.remote, self.branch = worker, remote, branch
        top = _git(self.root, "rev-parse", "--show-toplevel").stdout.strip()
        if Path(top).resolve() != self.root:
            raise RepositoryPersistenceError("repository root is not the Git worktree root")
        _branch_head(self.root, branch)

    def _journal(self) -> TransactionJournal:
        return TransactionJournal.from_file(self.root / JOURNAL_PATH, self.worker)

    def _remote_snapshot(self, *, require_current_head: bool = True) -> tuple[dict, int, str, str]:
        local_head = _branch_head(self.root, self.branch)
        remote_head = _remote_head(self.root, self.remote, self.branch)
        if require_current_head and remote_head != local_head:
            raise RepositoryPersistenceError("remote journal head changed; reread and retry from a fresh checkout")
        try:
            raw = subprocess.run(["git", "show", f"{remote_head}:{JOURNAL_PATH}"], cwd=self.root,
                                 check=False, capture_output=True)
            if raw.returncode:
                raise ValueError("remote journal blob is missing")
            value = json.loads(raw.stdout.decode("utf-8"))
            validate_journal(value, self.worker)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, JournalInvalid) as exc:
            raise RepositoryPersistenceError("remote journal is invalid or unreadable") from exc
        return value, value["generation"], journal_digest(value), remote_head

    def _remote_journal_snapshot(self) -> tuple[dict, int, str, str, bytes] | tuple[None, None, None, str, None]:
        """Read a stable remote ref, validating the exact journal path if present."""
        for _ in range(3):
            _git(self.root, "fetch", "--no-tags", "--quiet", self.remote, f"refs/heads/{self.branch}")
            fetched = _git(self.root, "rev-parse", "FETCH_HEAD").stdout.strip()
            remote_head = _remote_head(self.root, self.remote, self.branch)
            if fetched != remote_head:
                continue

            paths = _git(self.root, "ls-tree", "-r", "--name-only", "-z", remote_head).stdout.split("\0")
            aliases = [path for path in paths if path and path.casefold() == JOURNAL_PATH.casefold()
                       and path != JOURNAL_PATH]
            if aliases:
                raise RepositoryPersistenceError("remote journal path has a case/path alias")

            spec = f"{remote_head}:{JOURNAL_PATH}"
            raw_result = subprocess.run(["git", "show", spec], cwd=self.root,
                                        check=False, capture_output=True)
            if raw_result.returncode:
                exists = _git(self.root, "cat-file", "-e", spec, check=False)
                if exists.returncode:
                    if _remote_head(self.root, self.remote, self.branch) == remote_head:
                        return None, None, None, remote_head, None
                    continue
                raise RepositoryPersistenceError("remote journal blob could not be read")

            raw = raw_result.stdout
            try:
                value = json.loads(raw.decode("utf-8"))
                validate_journal(value, self.worker)
            except (UnicodeDecodeError, json.JSONDecodeError, JournalInvalid) as exc:
                raise RepositoryPersistenceError("remote journal is malformed or incompatible") from exc
            if _remote_head(self.root, self.remote, self.branch) != remote_head:
                continue
            return value, value["generation"], journal_digest(value), remote_head, raw
        raise JournalConflict("remote journal ref changed during bounded readback")

    def bootstrap(self) -> dict:
        """Create the canonical remote journal only when absent; never reset existing state."""
        value, generation, digest, remote_head, raw = self._remote_journal_snapshot()
        if value is not None:
            return {"status": "ALREADY_INITIALIZED", "remote_head": remote_head,
                    "generation": generation, "journal_sha256": digest}

        local_head = _branch_head(self.root, self.branch)
        if local_head != remote_head:
            raise RepositoryPersistenceError("local branch is stale while remote journal is absent")
        path = _safe_journal_file(self.root)
        if path.exists() or path.is_symlink():
            raise RepositoryPersistenceError("local journal exists while the remote journal is absent")

        store = FileJournalStore(path)
        status, initial, initial_digest = store.initialize(self.worker)
        if status != "INITIALIZED":
            raise RepositoryPersistenceError("local journal appeared before remote bootstrap")
        initial_bytes = serialize_journal(initial)
        if path.read_bytes() != initial_bytes:
            raise RepositoryPersistenceError("local initial journal bytes differ from canonical serialization")

        try:
            commit = self._commit_journal()
        except RepositoryPersistenceError:
            try:
                raced, raced_generation, raced_digest, raced_head, _raced_raw = self._remote_journal_snapshot()
            except RepositoryPersistenceError:
                if _branch_head(self.root, self.branch) == local_head and path.read_bytes() == initial_bytes:
                    path.unlink()
                raise
            if raced is not None:
                return {"status": "ALREADY_INITIALIZED", "remote_head": raced_head,
                        "generation": raced_generation, "journal_sha256": raced_digest}
            if _branch_head(self.root, self.branch) == local_head and path.read_bytes() == initial_bytes:
                path.unlink()
            raise

        installed, installed_generation, installed_digest, installed_head, installed_raw = self._remote_journal_snapshot()
        if (installed is None or installed_head != commit or installed_raw != initial_bytes
                or installed != initial or installed_generation != initial["generation"]
                or installed_digest != initial_digest or installed_digest != journal_digest(initial)):
            raise RepositoryPersistenceError("remote bootstrap readback differs from the canonical initial journal")
        return {"status": "INITIALIZED", "remote_head": installed_head,
                "generation": installed_generation, "journal_sha256": installed_digest}

    def _commit_and_verify(self) -> tuple[int, str, str]:
        journal, generation, digest = self._journal().snapshot()
        commit = self._commit_journal()
        remote, remote_generation, remote_digest, remote_head = self._remote_snapshot()
        if (remote_head != commit or remote_generation != generation or remote_digest != digest
                or remote != journal):
            raise RepositoryPersistenceError("remote journal readback differs from the committed transition")
        return generation, digest, commit

    def _confirm_current(self) -> tuple[dict, int, str]:
        remote, generation, digest, _head = self._remote_snapshot()
        local, local_generation, local_digest = self._journal().snapshot()
        if local != remote or local_generation != generation or local_digest != digest:
            raise RepositoryPersistenceError("local journal does not exactly match the remote journal")
        return remote, generation, digest

    def admit_revision(self, revision: int, source: str, run_id: str = "",
                       attempt_id: str = "") -> tuple[str, str, int, str]:
        self._confirm_current()
        journal = self._journal()
        state, generation, digest = journal.snapshot()
        decision, transaction_id = journal.admit(
            revision, source, run_id, attempt_id,
            expected_generation=generation, expected_digest=digest,
        )
        next_generation, next_digest, _commit = self._commit_and_verify()
        return decision, transaction_id, next_generation, next_digest

    def retire_stale_admitted(self, transaction_id: str, revision: int) -> dict:
        """Retire only the reviewed pristine revision-109 admission, once."""
        state, generation, digest = self._confirm_current()
        approved_head = _branch_head(self.root, self.branch)
        active = state["active"]
        if (transaction_id != STALE_ADMITTED_TX or revision != 109
                or self.worker != "mahoon-art-magazine"
                or generation != 1 or digest != STALE_ADMITTED_JOURNAL_SHA256
                or state["pending"] is not None or active is None
                or active["logical_transaction_id"] != STALE_ADMITTED_TX
                or active["worker"] != "mahoon-art-magazine"
                or active["content_revision"] != 109 or active["state"] != "admitted"
                or active["build_bundle_sha256"] is not None
                or active["proof_evidence_sha256"] is not None
                or active["state_commit_sha"] is not None
                or active["recovery_status"] != "NONE"):
            raise RepositoryPersistenceError("journal differs from the approved pristine retirement snapshot")
        if set(active["operations"]) != set(OPERATIONS):
            raise RepositoryPersistenceError("retirement operation identities are incomplete")
        for operation in active["operations"].values():
            if (operation["attempts"] != [] or operation["intent_state"] != "NOT_STARTED"
                    or operation["result_state"] != "NOT_REPORTED"):
                raise RepositoryPersistenceError("retirement is blocked after any mutation evidence")

        journal = self._journal()
        journal.mark_terminal(STALE_ADMITTED_TX, "blocked")
        expected, next_generation, next_digest = journal.snapshot()
        try:
            commit = self._commit_journal()
        except RepositoryPersistenceError:
            # A lost push response may be reconciled only by exact remote state and one-file commit readback.
            remote, remote_generation, remote_digest, remote_head, remote_raw = self._remote_journal_snapshot()
            parent = _git(self.root, "rev-list", "--parents", "-n", "1", remote_head).stdout.split()
            if (remote != expected or remote_generation != next_generation == 2
                    or remote_digest != next_digest or remote_raw != (self.root / JOURNAL_PATH).read_bytes()
                    or len(parent) != 2 or parent[1] != approved_head
                    or _commit_paths(self.root, remote_head) != {JOURNAL_PATH}):
                raise RepositoryPersistenceError("retirement push was not confirmed by exact remote readback")
            commit = remote_head
        installed, installed_generation, installed_digest, installed_head, raw = self._remote_journal_snapshot()
        if (installed != expected or installed_generation != 2 or installed_digest != next_digest
                or installed_head != commit or raw != (self.root / JOURNAL_PATH).read_bytes()
                or _commit_paths(self.root, commit) != {JOURNAL_PATH}):
            raise RepositoryPersistenceError("retirement remote readback is not exact")
        return {"status": "RETIRED_BLOCKED", "generation": installed_generation,
                "journal_sha256": installed_digest, "remote_head": installed_head}

    def retire_stale_admitted_v2(self, transaction_id: str, revision: int, *,
                                 expected_generation: int, expected_digest: str) -> dict:
        """Retire a caller-authorized pristine admission by exact caller-supplied identity.

        Unlike retire_stale_admitted (locked to the reviewed revision-109 snapshot), this path
        accepts the expected transaction id, revision, generation and journal digest from the
        caller and verifies the same pristine guarantees before a single journal-only commit.
        """
        state, generation, digest = self._confirm_current()
        if not isinstance(expected_generation, int) or isinstance(expected_generation, bool) \
                or expected_generation != generation:
            raise RepositoryPersistenceError("expected journal generation does not match the remote journal")
        if digest != expected_digest:
            raise RepositoryPersistenceError("expected journal digest does not match the remote journal")
        approved_head = _branch_head(self.root, self.branch)
        active = state["active"]
        if active is None:
            raise RepositoryPersistenceError("journal has no active transaction to retire")
        if (transaction_id != active["logical_transaction_id"] or revision != active["content_revision"]
                or active["state"] != "admitted"
                or state["pending"] is not None
                or active["build_bundle_sha256"] is not None
                or active["proof_evidence_sha256"] is not None
                or active["state_commit_sha"] is not None
                or active["recovery_status"] != "NONE"):
            raise RepositoryPersistenceError("active journal slot is not the pristine admitted transaction to be retired")
        if set(active["operations"]) != set(OPERATIONS):
            raise RepositoryPersistenceError("retirement operation identities are incomplete")
        for operation in active["operations"].values():
            if (operation["attempts"] != [] or operation["intent_state"] != "NOT_STARTED"
                    or operation["result_state"] != "NOT_REPORTED"):
                raise RepositoryPersistenceError("retirement is blocked after any mutation evidence")

        journal = self._journal()
        journal.mark_terminal(transaction_id, "blocked")
        expected, next_generation, next_digest = journal.snapshot()
        try:
            commit = self._commit_journal()
        except RepositoryPersistenceError:
            # A lost push response may be reconciled only by exact remote state and one-file commit readback.
            remote, remote_generation, remote_digest, remote_head, remote_raw = self._remote_journal_snapshot()
            parent = _git(self.root, "rev-list", "--parents", "-n", "1", remote_head).stdout.split()
            if (remote != expected or remote_generation != next_generation == generation + 1
                    or remote_digest != next_digest or remote_raw != (self.root / JOURNAL_PATH).read_bytes()
                    or len(parent) != 2 or parent[1] != approved_head
                    or _commit_paths(self.root, remote_head) != {JOURNAL_PATH}):
                raise RepositoryPersistenceError("retirement push was not confirmed by exact remote readback")
            commit = remote_head
        installed, installed_generation, installed_digest, installed_head, raw = self._remote_journal_snapshot()
        if (installed != expected or installed_generation != next_generation
                or installed_digest != next_digest
                or installed_head != commit or raw != (self.root / JOURNAL_PATH).read_bytes()
                or _commit_paths(self.root, commit) != {JOURNAL_PATH}):
            raise RepositoryPersistenceError("retirement remote readback is not exact")
        return {"status": "RETIRED_BLOCKED", "generation": installed_generation,
                "journal_sha256": installed_digest, "remote_head": installed_head,
                "retired_transaction_id": transaction_id, "retired_revision": revision}

    def record_build_ready(self, transaction_id: str, build_bundle_sha256: str) -> tuple[int, str]:
        state, generation, digest = self._confirm_current()
        active = state["active"]
        if not active or active["logical_transaction_id"] != transaction_id:
            raise RepositoryPersistenceError("journal does not own the build transaction")
        if active["state"] == "build_ready":
            if active["build_bundle_sha256"] != build_bundle_sha256:
                raise RepositoryPersistenceError("conflicting build bundle is already recorded")
            return generation, digest
        journal = self._journal()
        journal.record_build_ready(transaction_id, build_bundle_sha256,
                                   expected_generation=generation, expected_digest=digest)
        next_generation, next_digest, _commit = self._commit_and_verify()
        return next_generation, next_digest

    def record_intent(self, transaction_id: str, operation_name: str, attempt_id: str,
                      intent_artifact_sha256: str, expected_generation: int) -> tuple[int, str, bool]:
        if not _sha256(intent_artifact_sha256):
            raise RepositoryPersistenceError("intent artifact digest is invalid")
        if not isinstance(expected_generation, int) or isinstance(expected_generation, bool):
            raise RepositoryPersistenceError("intent journal generation is invalid")
        state, generation, digest = self._confirm_current()
        active = state["active"]
        if not active or active["logical_transaction_id"] != transaction_id:
            raise RepositoryPersistenceError("journal does not own the intent transaction")
        operation = active["operations"].get(operation_name)
        if not operation:
            raise RepositoryPersistenceError("journal operation is invalid")
        prior = next((item for item in operation["attempts"] if item["attempt_id"] == attempt_id), None)
        if prior:
            if prior.get("intent_artifact_sha256") != intent_artifact_sha256:
                raise RepositoryPersistenceError("attempt identity conflicts with its recorded intent")
            return generation, digest, True
        if expected_generation != generation + 1:
            raise JournalConflict("sealed intent generation is stale")
        journal = self._journal()
        journal.record_intent(
            transaction_id, operation_name, attempt_id=attempt_id,
            intent_artifact_sha256=intent_artifact_sha256,
            expected_generation=generation, expected_digest=digest,
        )
        next_generation, next_digest, _commit = self._commit_and_verify()
        return next_generation, next_digest, False

    def record_result(self, transaction_id: str, operation_id: str, attempt_id: str,
                      outcome: str, evidence_sha256: str | None,
                      intent_artifact_sha256: str, result_artifact_sha256: str) -> tuple[int, str, bool]:
        if outcome not in {"APPLIED", "NOT_APPLIED", "UNKNOWN"}:
            raise RepositoryPersistenceError("mutation result state is invalid")
        if not _sha256(intent_artifact_sha256) or not _sha256(result_artifact_sha256):
            raise RepositoryPersistenceError("mutation artifact digest is invalid")
        if evidence_sha256 is not None and not _sha256(evidence_sha256):
            raise RepositoryPersistenceError("mutation evidence digest is invalid")
        if outcome in {"APPLIED", "NOT_APPLIED"} and evidence_sha256 is None:
            raise RepositoryPersistenceError("conclusive mutation result requires evidence")
        state, generation, digest = self._confirm_current()
        active = state["active"]
        operation = next((item for item in active["operations"].values()
                          if item["operation_id"] == operation_id), None) if active else None
        if not active or active["logical_transaction_id"] != transaction_id or not operation:
            raise RepositoryPersistenceError("result does not match the active journal operation")
        attempt = next((item for item in operation["attempts"] if item["attempt_id"] == attempt_id), None)
        if (not attempt or attempt is not operation["attempts"][-1]
                or attempt.get("intent_artifact_sha256") != intent_artifact_sha256):
            raise RepositoryPersistenceError("result does not match the latest durable intent")
        result_evidence = ({"type": "mutation_result_artifact", "reference": result_artifact_sha256,
                           "sha256": evidence_sha256} if evidence_sha256 else None)
        result_digest = canonical_result_digest(outcome, result_evidence)
        if attempt["result_state"] != "NOT_REPORTED":
            if attempt["result_state"] == outcome and attempt["result_digest"] == result_digest:
                return generation, digest, True
            raise DuplicateMutation("conflicting result for the same mutation attempt")
        journal = self._journal()
        journal.record_result(transaction_id, operation_id, attempt_id, outcome, result_evidence,
                              expected_generation=generation, expected_digest=digest)
        next_generation, next_digest, _commit = self._commit_and_verify()
        return next_generation, next_digest, False

    def reconcile_recovery_decision(self, decision: object) -> dict:
        """Persist one accepted sealed recovery decision; never execute an operation."""
        try:
            value = contracts.validate_artifact(decision)
        except (TypeError, ValueError) as exc:
            raise RepositoryPersistenceError("recovery decision artifact is invalid") from exc
        if value["artifact_type"] != "recovery_decision":
            raise RepositoryPersistenceError("a sealed recovery_decision is required")

        transaction = value["transaction"]
        payload = value["payload"]
        if transaction["worker"] != self.worker:
            raise RepositoryPersistenceError("recovery decision worker differs from the journal writer")
        outcome = {
            "RECONCILED_APPLIED": "APPLIED",
            "RECONCILED_NOT_APPLIED": "NOT_APPLIED",
            "BLOCKED_UNKNOWN": "UNKNOWN",
        }[payload["decision"]]
        if payload["resume_allowed"] != (outcome == "NOT_APPLIED"):
            raise RepositoryPersistenceError("recovery decision resume flag conflicts with its outcome")
        tx_id = transaction["logical_transaction_id"]
        operation_id = payload["operation_id"]
        attempt_id = payload["attempt_id"]
        evidence = {
            "type": "recovery_decision",
            "reference": value["artifact_sha256"],
            "sha256": payload["evidence_sha256"],
        }
        result_digest = canonical_result_digest(outcome, evidence)
        operation_names = [name for name in OPERATIONS
                           if contracts.operation_id_for(tx_id, name) == operation_id]
        if len(operation_names) != 1:
            raise RepositoryPersistenceError("recovery decision operation identity is invalid")
        operation_name = operation_names[0]

        def already_reconciled(remote: dict, remote_generation: int,
                               remote_digest: str, remote_head: str) -> dict | None:
            tx = remote["active"] if (
                remote["active"] and remote["active"]["logical_transaction_id"] == tx_id
            ) else next((item for item in remote["history"]
                         if item["logical_transaction_id"] == tx_id), None)
            if (tx is None or tx["worker"] != transaction["worker"]
                    or tx["content_revision"] != transaction["content_revision"]):
                return None
            op = tx["operations"].get(operation_name)
            if (op is None or op["operation_id"] != operation_id
                    or op["result_state"] != outcome):
                return None
            prior = next((item for item in op["attempts"]
                          if item["attempt_id"] == attempt_id), None)
            if (prior is None or prior.get("intent_artifact_sha256") != payload["intent_artifact_sha256"]
                    or prior["result_state"] != outcome or prior["result_digest"] != result_digest):
                return None
            return {"status": payload["decision"], "outcome": outcome,
                    "transaction_id": tx_id, "operation_name": operation_name,
                    "operation_id": operation_id, "attempt_id": attempt_id,
                    "generation": remote_generation, "journal_sha256": remote_digest,
                    "remote_head": remote_head, "idempotent": True}

        try:
            state, generation, digest, remote_head = self._remote_snapshot()
        except RepositoryPersistenceError as exc:
            remote, remote_generation, remote_digest, head, _raw = self._remote_journal_snapshot()
            receipt = already_reconciled(remote, remote_generation, remote_digest, head)
            if receipt is not None:
                return receipt
            raise RepositoryPersistenceError(
                "remote advanced before reconciliation; exact equivalent result is absent",
            ) from exc
        local, local_generation, local_digest = self._journal().snapshot()
        if (local != state or local_generation != generation or local_digest != digest):
            raise RepositoryPersistenceError("local journal does not exactly match the remote journal")

        transaction_state = state["active"] if (
            state["active"] and state["active"]["logical_transaction_id"] == tx_id
        ) else next((item for item in state["history"]
                     if item["logical_transaction_id"] == tx_id), None)
        if transaction_state is None or transaction_state["worker"] != transaction["worker"] \
                or transaction_state["content_revision"] != transaction["content_revision"]:
            raise RepositoryPersistenceError("recovery decision transaction is not in the authoritative journal")

        matched = [(name, operation) for name, operation in transaction_state["operations"].items()
                   if contracts.operation_id_for(tx_id, name) == operation_id
                   and operation["operation_id"] == operation_id]
        if len(matched) != 1:
            raise RepositoryPersistenceError("recovery decision operation identity is invalid")
        operation_name, operation = matched[0]
        if operation_name == "upload_version" and outcome == "NOT_APPLIED":
            raise RepositoryPersistenceError("upload absence cannot prove that mutation was not applied")
        attempts = operation["attempts"]
        attempt = next((item for item in attempts if item["attempt_id"] == attempt_id), None)
        if attempt is None or attempt.get("intent_artifact_sha256") != payload["intent_artifact_sha256"]:
            raise RepositoryPersistenceError("recovery decision does not match the durable intent")

        if (attempt["result_state"] == outcome and attempt.get("result_digest") == result_digest
                and operation["result_state"] == outcome):
            return {"status": payload["decision"], "outcome": outcome,
                    "transaction_id": tx_id, "operation_name": operation_name,
                    "operation_id": operation_id, "attempt_id": attempt_id,
                    "generation": generation, "journal_sha256": digest,
                    "remote_head": remote_head, "idempotent": True}

        if payload["journal_generation"] != generation:
            raise JournalConflict("recovery decision generation is stale")
        if (state["active"] is None or state["active"]["logical_transaction_id"] != tx_id
                or transaction_state["state"] != "recovery_required"
                or transaction_state["recovery_status"] not in {"REQUIRED", "BLOCKED_UNKNOWN"}
                or operation["result_state"] != "UNKNOWN"
                or not attempts or attempts[-1]["attempt_id"] != attempt_id
                or attempt["result_state"] != "UNKNOWN"):
            raise RepositoryPersistenceError("journal is not awaiting this exact UNKNOWN operation")

        journal = self._journal()
        journal.reconcile(tx_id, operation_id, outcome, evidence,
                          expected_generation=generation, expected_digest=digest)
        try:
            next_generation, next_digest, commit = self._commit_and_verify()
        except RepositoryPersistenceError as exc:
            remote, remote_generation, remote_digest, head, _raw = self._remote_journal_snapshot()
            receipt = already_reconciled(remote, remote_generation, remote_digest, head)
            if receipt is not None:
                return receipt
            raise RepositoryPersistenceError(
                "remote did not confirm this reconciliation and contains no exact equivalent result",
            ) from exc
        return {"status": payload["decision"], "outcome": outcome,
                "transaction_id": tx_id, "operation_name": operation_name,
                "operation_id": operation_id, "attempt_id": attempt_id,
                "generation": next_generation, "journal_sha256": next_digest,
                "remote_head": commit, "idempotent": False}

    def read_reconciled_applied_result(self, decision: object, intent: object,
                                       original_result: object, *,
                                       referenced_artifacts: Mapping[str, Any] | None = None) -> dict:
        """Read-only proof that this exact recovery decision is committed remotely."""
        try:
            decision_v = contracts.validate_artifact(
                decision, referenced_artifacts=referenced_artifacts,
            )
            intent_v = contracts.validate_artifact(intent, referenced_artifacts=referenced_artifacts)
            result_v = contracts.validate_artifact(
                original_result, expected_transaction=intent_v["transaction"],
                expected_source_sha=intent_v["producer"]["source_sha"],
                referenced_artifacts=referenced_artifacts,
            )
            contracts.validate_intent_result_pair(
                intent_v, result_v, referenced_artifacts=referenced_artifacts,
            )
        except (TypeError, ValueError) as exc:
            raise RepositoryPersistenceError("recovery readback inputs are invalid") from exc
        if (decision_v["artifact_type"] != "recovery_decision"
                or decision_v["payload"]["decision"] != "RECONCILED_APPLIED"
                or result_v["artifact_type"] != "mutation_result"
                or result_v["payload"]["result_state"] != "UNKNOWN"):
            raise RepositoryPersistenceError("exact UNKNOWN and RECONCILED_APPLIED inputs are required")
        tx, ip, dp = intent_v["transaction"], intent_v["payload"], decision_v["payload"]
        if (self.worker != tx["worker"] or decision_v["transaction"] != tx
                or dp["operation_id"] != ip["operation_id"]
                or dp["attempt_id"] != ip["attempt_id"]
                or dp["intent_artifact_sha256"] != intent_v["artifact_sha256"]
                or dp["result_artifact_sha256"] != result_v["artifact_sha256"]
                or dp["resume_allowed"] is not False):
            raise RepositoryPersistenceError("recovery decision does not match the exact mutation attempt")
        evidence = {"type": "recovery_decision", "reference": decision_v["artifact_sha256"],
                    "sha256": dp["evidence_sha256"]}
        expected_result_digest = canonical_result_digest("APPLIED", evidence)
        remote, generation, digest, head, _raw = self._remote_journal_snapshot()
        state = remote["active"] if remote["active"] else None
        if (state is None or state["logical_transaction_id"] != tx["logical_transaction_id"]
                or state["worker"] != tx["worker"]
                or state["content_revision"] != tx["content_revision"]
                or state["state"] == "recovery_required"
                or state["recovery_status"] != "RECONCILED_APPLIED"
                or generation != dp["journal_generation"] + 1):
            raise RepositoryPersistenceError("remote journal is not the exact reconciled transaction state")
        operation = state["operations"].get(ip["operation_name"])
        attempt = next((item for item in operation["attempts"]
                        if item["attempt_id"] == ip["attempt_id"]), None) if operation else None
        if (operation is None or operation["operation_id"] != ip["operation_id"]
                or operation["result_state"] != "APPLIED"
                or attempt is None or attempt is not operation["attempts"][-1]
                or attempt["intent_artifact_sha256"] != intent_v["artifact_sha256"]
                or attempt["result_state"] != "APPLIED"
                or attempt["evidence"] != evidence
                or attempt["result_digest"] != expected_result_digest):
            raise RepositoryPersistenceError("remote journal lacks this exact applied reconciliation")
        return {
            "worker": tx["worker"], "logical_transaction_id": tx["logical_transaction_id"],
            "content_revision": tx["content_revision"],
            "operation_name": ip["operation_name"], "operation_id": ip["operation_id"],
            "attempt_id": ip["attempt_id"], "outcome": "APPLIED",
            "recovery_status": state["recovery_status"],
            "result_digest": expected_result_digest, "journal_generation": generation,
            "journal_sha256": digest, "remote_head": head,
        }

    def _commit_journal(self) -> str:
        if _git(self.root, "diff", "--cached", "--name-only").stdout.splitlines():
            raise RepositoryPersistenceError("pre-existing staged changes block journal commit")
        before_head = _branch_head(self.root, self.branch)
        if _remote_head(self.root, self.remote, self.branch) != before_head:
            raise RepositoryPersistenceError("remote journal head changed before commit")
        _safe_journal_file(self.root)
        _git(self.root, "add", "--", JOURNAL_PATH)
        paths = {line.replace("\\", "/") for line in
                 _git(self.root, "diff", "--cached", "--name-only").stdout.splitlines() if line}
        if paths != {JOURNAL_PATH}:
            raise RepositoryPersistenceError("journal commit must contain only the journal file")
        before = _git(self.root, "rev-parse", "HEAD").stdout.strip()
        _git(self.root, "-c", "user.name=MAHOON Publisher", "-c",
             "user.email=mahoon-publisher@users.noreply.github.com",
             "commit", "-m", "chore: persist MAHOON publisher journal")
        commit = _branch_head(self.root, self.branch)
        parent = _git(self.root, "rev-list", "--parents", "-n", "1", commit).stdout.split()
        if len(parent) != 2 or parent[1] != before or _commit_paths(self.root, commit) != {JOURNAL_PATH}:
            raise RepositoryPersistenceError("journal commit scope or ancestry is invalid")
        _push(self.root, self.remote, self.branch, commit)
        if _remote_head(self.root, self.remote, self.branch) != commit:
            raise RepositoryPersistenceError("journal remote ref differs from the exact commit")
        local = (self.root / JOURNAL_PATH).read_bytes()
        remote_blob = subprocess.run(["git", "show", f"{commit}:{JOURNAL_PATH}"], cwd=self.root,
                                     check=False, capture_output=True)
        if remote_blob.returncode or remote_blob.stdout != local:
            raise RepositoryPersistenceError("journal remote readback differs from local journal")
        try:
            remote_value = json.loads(remote_blob.stdout.decode("utf-8"))
            validate_journal(remote_value, self.worker)
        except (UnicodeDecodeError, json.JSONDecodeError, JournalInvalid) as exc:
            raise RepositoryPersistenceError("committed remote journal failed validation") from exc
        return commit

    def _confirm_journal_remote(self) -> None:
        head = _branch_head(self.root, self.branch)
        _git(self.root, "fetch", "--no-tags", "--quiet", self.remote, f"refs/heads/{self.branch}")
        remote_head = _git(self.root, "rev-parse", "FETCH_HEAD").stdout.strip()
        ancestor = _git(self.root, "merge-base", "--is-ancestor", head, remote_head, check=False)
        if ancestor.returncode:
            parent = _git(self.root, "rev-list", "--parents", "-n", "1", head).stdout.split()
            if (len(parent) != 2 or parent[1] != remote_head
                    or _commit_paths(self.root, head) != {JOURNAL_PATH}):
                raise RepositoryPersistenceError("journal commit is not confirmed by the remote")
            _push(self.root, self.remote, self.branch, head)
            remote_head = _remote_head(self.root, self.remote, self.branch)
            if remote_head != head:
                raise RepositoryPersistenceError("journal retry did not read back its exact commit")
        local_hash = hashlib.sha256((self.root / JOURNAL_PATH).read_bytes()).hexdigest()
        remote_blob = subprocess.run(["git", "show", f"{remote_head}:{JOURNAL_PATH}"],
                                     cwd=self.root, check=False, capture_output=True)
        if remote_blob.returncode or hashlib.sha256(remote_blob.stdout).hexdigest() != local_hash:
            raise RepositoryPersistenceError("journal remote readback differs from local state")

    def mark_ready_to_persist(self, transaction_id: str, proof_sha256: str,
                              expected_generation: int) -> int:
        journal = self._journal()
        state, generation, _digest = journal.snapshot()
        if generation != expected_generation:
            raise RepositoryPersistenceError("journal generation changed before persistence readiness")
        active = state["active"]
        if active and active["logical_transaction_id"] == transaction_id:
            if active["state"] == "ready_to_persist" and active["proof_evidence_sha256"] == proof_sha256:
                self._confirm_journal_remote()
                return generation
            journal.mark_ready_to_persist(
                transaction_id, proof_sha256, expected_generation=generation,
            )
            state, ready_generation, _ = journal.snapshot()
            ready = state["active"]
            if (not ready or ready["state"] != "ready_to_persist"
                    or ready["proof_evidence_sha256"] != proof_sha256):
                raise RepositoryPersistenceError("journal did not enter READY_TO_PERSIST")
            self._commit_journal()
            return ready_generation
        completed = next((item for item in state["history"]
                          if item["logical_transaction_id"] == transaction_id), None)
        if (completed and completed["state"] == "completed"
                and completed["proof_evidence_sha256"] == proof_sha256
                and completed["state_commit_sha"]):
            self._confirm_journal_remote()
            return generation
        raise RepositoryPersistenceError("journal does not own the proof transaction")

    def finalize_completed(self, transaction_id: str, state_commit_sha: str,
                           expected_generation: int) -> None:
        if not _sha40(state_commit_sha):
            raise RepositoryPersistenceError("state commit SHA is invalid")
        journal = self._journal()
        state, generation, _digest = journal.snapshot()
        if generation != expected_generation:
            raise RepositoryPersistenceError("journal generation changed before completion")
        active = state["active"]
        if not active:
            completed = next((item for item in state["history"]
                              if item["logical_transaction_id"] == transaction_id), None)
            if completed and completed["state"] == "completed" and completed["state_commit_sha"] == state_commit_sha:
                return
            raise RepositoryPersistenceError("completed journal record conflicts with persistence commit")
        if (active["logical_transaction_id"] != transaction_id
                or active["state"] != "ready_to_persist"):
            raise RepositoryPersistenceError("journal is not READY_TO_PERSIST for this transaction")
        journal.finalize_completed(
            transaction_id, state_commit_sha, expected_generation=generation,
        )
        state, _new_generation, _digest = journal.snapshot()
        if not any(item["logical_transaction_id"] == transaction_id
                   and item["state"] == "completed"
                   and item["state_commit_sha"] == state_commit_sha
                   for item in state["history"]):
            raise RepositoryPersistenceError("journal completion readback is missing")
        self._commit_journal()
