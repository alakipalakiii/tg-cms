from __future__ import annotations

import base64
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from publisher import artifact_contract as contracts
from publisher import final_persistence_runner, media_bootstrap, repository_persistence


WORKER = "synthetic-worker"
REVISION = 731
SOURCE_SHA = "a" * 40
RAW_INDEX = (json.dumps({"contract": "IMMUTABLE_MEDIA_INDEX_V1", "entries": [
    {"source_identifier": "old-media", "immutable_path": "/media/aa/old.jpg",
     "sha256": "b" * 64, "mime": "image/jpeg", "media_type": "photo", "fallback": False},
]}, separators=(",", ":")) + "\n").encode("utf-8")


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _make_repo(root: Path, raw: bytes | None = RAW_INDEX) -> tuple[Path, Path]:
    work, remote = root / "work", root / "origin.git"
    work.mkdir(parents=True)
    _git(work, "init", "-b", "main")
    _git(work, "config", "user.name", "Synthetic Test")
    _git(work, "config", "user.email", "test@example.invalid")
    (work / "baseline.txt").write_text("synthetic\n", encoding="utf-8")
    remote.mkdir()
    _git(remote, "init", "--bare")
    if raw is not None:
        state = work / "publisher-state" / "immutable-media-index.json"
        state.parent.mkdir(parents=True)
        state.write_bytes(raw)
    _git(work, "add", "--all")
    _git(work, "commit", "-m", "synthetic initial state")
    _git(work, "remote", "add", "origin", str(remote))
    _git(work, "push", "origin", "main:main")
    return work, remote


def _binding(raw: bytes = RAW_INDEX, *, commit: str = "1" * 40,
             exists: bool = True) -> dict:
    return {
        "repository": "synthetic-owner/tg-cms",
        "ref": "refs/heads/main",
        "commit_sha": commit,
        "relative_path": contracts.PRIOR_IMMUTABLE_MEDIA_INDEX_PATH,
        "exists": exists,
        "content_sha256": contracts.sha256_bytes(raw),
        "byte_length": len(raw),
        "transport_base64": base64.b64encode(raw).decode("ascii"),
    }


def _bundle(binding: dict | None = None, *, worker: str = WORKER,
            revision: int = REVISION, source_sha: str = SOURCE_SHA) -> dict:
    transaction = {
        "worker": worker,
        "content_revision": revision,
        "logical_transaction_id": contracts.logical_transaction_id(worker, revision),
    }
    payload = {
        "admission_receipt_sha256": "c" * 64,
        "files": [{"path": "dist/index.html", "size_bytes": 1,
                   "sha256": contracts.sha256_bytes(b"x")}],
        "content_fingerprint": "d" * 64,
        "snapshot_sha256": "e" * 64,
        "route_manifest_sha256": "f" * 64,
        "media_manifest_sha256": "0" * 64,
        "local_gate_evidence_sha256": "1" * 64,
    }
    if binding is not None:
        payload["prior_immutable_media_index"] = copy.deepcopy(binding)
    return contracts.seal_artifact({
        "artifact_type": "build_bundle",
        "schema_version": contracts.SCHEMA_VERSION,
        "artifact_id": "00000000-0000-4000-8000-000000000001",
        "created_at": "2026-09-30T00:00:00+00:00",
        "producer": {"workflow_run_id": "synthetic-run", "run_attempt": 1,
                     "job": "build-validate", "source_sha": source_sha},
        "transaction": transaction,
        "payload": payload,
    })


class PinnedIndexReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work, self.remote = _make_repo(Path(self.temp.name))
        self.reader = repository_persistence.GitRepositoryReader(
            self.work, "synthetic-owner/tg-cms",
        )

    def _advance_remote(self, raw: bytes) -> str:
        path = self.work / "publisher-state" / "immutable-media-index.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        _git(self.work, "add", "--all")
        _git(self.work, "commit", "-m", "synthetic later state")
        _git(self.work, "push", "origin", "main:main")
        return _git(self.work, "rev-parse", "HEAD")

    def test_reads_raw_index_from_exact_remote_commit_and_binds_metadata(self):
        before_head = _git(self.work, "rev-parse", "HEAD")
        before_status = _git(self.work, "status", "--porcelain=v1", "--untracked-files=all")
        snapshot = self.reader.read_immutable_media_index()
        self.assertEqual(snapshot["content_bytes"], RAW_INDEX)
        self.assertEqual(snapshot["commit_sha"], before_head)
        self.assertEqual(snapshot["relative_path"], "publisher-state/immutable-media-index.json")
        self.assertEqual(snapshot["content_sha256"], hashlib.sha256(RAW_INDEX).hexdigest())
        self.assertEqual(snapshot["byte_length"], len(RAW_INDEX))
        self.assertEqual(snapshot["ref"], "refs/heads/main")
        self.assertEqual(_git(self.work, "rev-parse", "HEAD"), before_head)
        self.assertEqual(_git(self.work, "status", "--porcelain=v1", "--untracked-files=all"), before_status)

    def test_dirty_worktree_cannot_replace_the_pinned_remote_snapshot(self):
        state = self.work / "publisher-state" / "immutable-media-index.json"
        state.write_bytes(b'{"entries":[]}\n')
        snapshot = self.reader.read_immutable_media_index()
        self.assertEqual(snapshot["content_bytes"], RAW_INDEX)
        self.assertNotEqual(snapshot["content_bytes"], state.read_bytes())

    def test_mutable_main_ref_resolves_once_to_immutable_commit(self):
        snapshot = self.reader.read_immutable_media_index()
        self.assertRegex(snapshot["commit_sha"], r"^[0-9a-f]{40}$")
        self.assertEqual(snapshot["commit_sha"], _git(self.work, "rev-parse", "HEAD"))

    def test_pin_precedes_blob_read_and_branch_advance_does_not_change_snapshot(self):
        pinned = _git(self.work, "rev-parse", "HEAD")
        advanced_bytes = b'{"contract":"IMMUTABLE_MEDIA_INDEX_V1","entries":[]}\n'
        original = repository_persistence._remote_head

        def resolve_then_advance(root, remote, branch):
            commit = original(root, remote, branch)
            self._advance_remote(advanced_bytes)
            return commit

        with patch.object(repository_persistence, "_remote_head", side_effect=resolve_then_advance):
            snapshot = self.reader.read_immutable_media_index()
        self.assertEqual(snapshot["commit_sha"], pinned)
        self.assertEqual(snapshot["content_bytes"], RAW_INDEX)
        self.assertNotEqual(snapshot["content_bytes"], advanced_bytes)

    def test_missing_index_uses_proven_absent_state_without_inventing_raw_bytes(self):
        root = Path(self.temp.name) / "absent"
        work, _remote = _make_repo(root, raw=None)
        snapshot = repository_persistence.GitRepositoryReader(
            work, "synthetic-owner/tg-cms",
        ).read_immutable_media_index()
        self.assertFalse(snapshot["exists"])
        self.assertEqual(snapshot["content_bytes"], b"")
        self.assertEqual(snapshot["byte_length"], 0)
        self.assertEqual(snapshot["content_sha256"], hashlib.sha256(b"").hexdigest())

    def test_reader_has_no_path_parameter_or_repository_write_side_effects(self):
        self.assertNotIn("relative_path", repository_persistence.GitRepositoryReader.read_immutable_media_index.__code__.co_varnames)
        self.assertFalse((self.work / ".git" / "FETCH_HEAD").exists())
        before = _git(self.work, "rev-parse", "HEAD")
        self.reader.read_immutable_media_index()
        self.assertEqual(_git(self.work, "rev-parse", "HEAD"), before)
        self.assertFalse((self.work / ".git" / "FETCH_HEAD").exists())


class SealedIndexBindingTests(unittest.TestCase):
    def test_new_bundle_contains_sealed_binding_and_matching_raw_transport(self):
        bundle = _bundle(_binding())
        checked = contracts.validate_artifact(bundle)
        self.assertIn("prior_immutable_media_index", checked["payload"])
        self.assertEqual(contracts.validate_prior_index_transport(bundle, RAW_INDEX), _binding())

    def test_legacy_build_bundle_remains_readable_but_cannot_authorize_transport(self):
        legacy = _bundle()
        self.assertEqual(contracts.validate_artifact(legacy)["artifact_type"], "build_bundle")
        with self.assertRaises(contracts.ArtifactContractError):
            contracts.validate_prior_index_transport(legacy, RAW_INDEX)

    def test_any_binding_field_tamper_invalidates_original_seal(self):
        for field, changed in (("commit_sha", "2" * 40), ("relative_path", "publisher-state/other.json"),
                               ("content_sha256", "3" * 64), ("byte_length", len(RAW_INDEX) + 1)):
            with self.subTest(field=field):
                artifact = _bundle(_binding())
                artifact["payload"]["prior_immutable_media_index"][field] = changed
                with self.assertRaises(contracts.ArtifactContractError):
                    contracts.validate_artifact(artifact)

    def test_path_traversal_alternate_and_absolute_paths_rejected_even_when_resealed(self):
        for path in ("publisher-state/../secret.json", "publisher-state/production-result.json",
                     "C:/publisher-state/immutable-media-index.json"):
            with self.subTest(path=path):
                artifact = _bundle(_binding())
                artifact["payload"]["prior_immutable_media_index"]["relative_path"] = path
                artifact = contracts.seal_artifact(artifact)
                with self.assertRaisesRegex(contracts.ArtifactContractError, "exact path"):
                    contracts.validate_artifact(artifact)

    def test_matching_altered_and_truncated_raw_snapshots_are_distinguished(self):
        bundle = _bundle(_binding())
        self.assertEqual(contracts.validate_prior_index_transport(bundle, RAW_INDEX)["commit_sha"], "1" * 40)
        for raw in (RAW_INDEX + b"x", RAW_INDEX[:-1]):
            with self.subTest(length=len(raw)):
                with self.assertRaises(contracts.ArtifactContractError):
                    contracts.validate_prior_index_transport(bundle, raw)

    def test_other_commit_snapshot_bytes_cannot_substitute(self):
        other = b'{"contract":"IMMUTABLE_MEDIA_INDEX_V1","entries":[]}\n'
        bundle = _bundle(_binding())
        with self.assertRaises(contracts.ArtifactContractError):
            contracts.validate_prior_index_transport(bundle, other)

    def test_cross_transaction_or_source_substitution_is_rejected(self):
        bundle = _bundle(_binding())
        other_tx = {
            "worker": WORKER, "content_revision": REVISION + 1,
            "logical_transaction_id": contracts.logical_transaction_id(WORKER, REVISION + 1),
        }
        with self.assertRaises(contracts.ArtifactContractError):
            contracts.validate_prior_index_transport(bundle, RAW_INDEX, expected_transaction=other_tx)
        with self.assertRaises(contracts.ArtifactContractError):
            contracts.validate_prior_index_transport(bundle, RAW_INDEX, expected_source_sha="9" * 40)

    def test_legacy_transaction_result_and_proof_files_are_not_authority(self):
        for value in (None, {}, {"transaction": "legacy"}, {"production_result": True}, {"remote_proof": True}):
            with self.subTest(value=value):
                with self.assertRaises(contracts.ArtifactContractError):
                    contracts.validate_prior_index_transport(value, RAW_INDEX)

    def test_absent_index_first_state_is_sealed_as_absence_not_empty_json(self):
        raw = b""
        binding = _binding(raw, exists=False)
        bundle = _bundle(binding)
        checked = contracts.validate_artifact(bundle)
        self.assertFalse(checked["payload"]["prior_immutable_media_index"]["exists"])
        self.assertEqual(contracts.validate_prior_index_transport(bundle, b"")["byte_length"], 0)

    def test_source_reader_has_no_cloudflare_d1_or_mutation_dependencies(self):
        source = Path(repository_persistence.__file__).read_text(encoding="utf-8")
        reader = source.split("class GitRepositoryReader:", 1)[1].split("class GitRepositoryWriter:", 1)[0]
        for forbidden in ("cloudflare_operation_adapter", "wrangler", "D1", "deploy(", "dispatch", "TOKEN", "SECRET"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden.lower(), reader.lower())
        self.assertNotIn("cloudflare", source.lower())

    def test_workflow_cli_owns_no_raw_hash_or_canonicalization_logic(self):
        source = Path(repository_persistence.__file__).parents[0].joinpath("workflow_stage_cli.py").read_text(encoding="utf-8")
        self.assertNotIn("import hashlib", source)
        self.assertNotIn("canonical_json_bytes", source)
        self.assertNotIn("artifact_digest(", source)

    def test_first_state_and_cumulative_merge_keep_historical_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prior = root / "prior-index.json"
            prior.write_bytes(RAW_INDEX)
            media_bootstrap.bootstrap([], index_path=prior, store=root / "store",
                                      output_manifest=root / "manifest.json", output_index=root / "next.json")
            retained = json.loads((root / "next.json").read_text(encoding="utf-8"))
            self.assertEqual(retained["entries"][0]["source_identifier"], "old-media")
            missing = root / "does-not-exist.json"
            media_bootstrap.bootstrap([], index_path=missing, store=root / "store2",
                                      output_manifest=root / "manifest2.json", output_index=root / "empty.json")
            first = json.loads((root / "empty.json").read_text(encoding="utf-8"))
            self.assertEqual(first, {"contract": "IMMUTABLE_MEDIA_INDEX_V1", "entries": []})

    def test_final_persistence_fails_closed_without_new_bundle_binding(self):
        proof = {"payload": {
            "proof_state": "PASS", "production_validation": {"PASS": True},
            "candidate_identity": {"content_fingerprint": "d" * 64},
        }}
        state_files = {path: b"{}" for path in contracts.STATE_FILE_PATHS}
        with patch.object(final_persistence_runner, "validate_proof", return_value=proof):
            with self.assertRaisesRegex(final_persistence_runner.PersistenceBlocked, "authority binding"):
                final_persistence_runner.validate_finalization_inputs(
                    proof, _bundle(), {}, state_files, 0,
                )

    def test_final_persistence_accepts_only_a_validly_bound_new_bundle(self):
        proof = {"payload": {
            "proof_state": "PASS", "production_validation": {"PASS": True},
            "candidate_identity": {"content_fingerprint": "d" * 64},
        }}
        state_files = {path: b"{}" for path in contracts.STATE_FILE_PATHS}
        with patch.object(final_persistence_runner, "validate_proof", return_value=proof):
            result = final_persistence_runner.validate_finalization_inputs(
                proof, _bundle(_binding()), {}, state_files, 0,
            )
        self.assertIn("prior_immutable_media_index", result[1]["payload"])


if __name__ == "__main__":
    unittest.main()
