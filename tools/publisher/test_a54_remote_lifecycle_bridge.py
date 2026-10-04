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
import uuid
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from publisher import artifact_contract as contracts
from publisher import artifact_transport as transport
from publisher import repository_persistence as repository
from publisher import workflow_stage_cli as cli
from publisher.transaction_journal import JournalConflict, TransactionJournal, empty_journal

WORKER = "mahoon-art-magazine"
REVISION = 41
SOURCE_SHA = "a" * 40
TX = {"worker": WORKER, "content_revision": REVISION,
      "logical_transaction_id": contracts.logical_transaction_id(WORKER, REVISION)}
SHA = lambda value: hashlib.sha256(value.encode()).hexdigest()


def artifact(kind: str, payload: dict, tx: dict = TX) -> dict:
    return contracts.seal_artifact({
        "artifact_type": kind, "schema_version": contracts.SCHEMA_VERSION,
        "artifact_id": str(uuid.uuid4()), "created_at": "2026-09-28T10:00:00+00:00",
        "producer": {"workflow_run_id": "synthetic-run", "run_attempt": 1,
                     "job": "synthetic-test", "source_sha": SOURCE_SHA},
        "transaction": copy.deepcopy(tx), "payload": payload,
    })


def run_git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True,
                          text=True).stdout.strip()


class LocalBare:
    """All commits and pushes in this fixture stay inside a temporary directory."""

    def __init__(self, parent: Path):
        self.root, self.bare = parent / "repo", parent / "remote.git"
        self.root.mkdir()
        run_git(parent, "init", "--bare", str(self.bare))
        run_git(self.root, "init", "-b", "main")
        run_git(self.root, "config", "user.name", "Synthetic A5.4")
        run_git(self.root, "config", "user.email", "a54@example.invalid")
        journal_path = self.root / repository.JOURNAL_PATH
        journal_path.parent.mkdir(parents=True)
        journal_path.write_text(json.dumps(empty_journal(WORKER), sort_keys=True), encoding="utf-8")
        (self.root / "unrelated.txt").write_text("stay outside lifecycle commits", encoding="utf-8")
        run_git(self.root, "add", "--all")
        run_git(self.root, "commit", "-m", "synthetic seed")
        run_git(self.root, "remote", "add", "origin", str(self.bare))
        run_git(self.root, "push", "-u", "origin", "main")

    def writer(self) -> repository.GitJournalWriter:
        return repository.GitJournalWriter(self.root, WORKER, remote="origin", branch="main")

    def journal(self) -> TransactionJournal:
        return TransactionJournal.from_file(self.root / repository.JOURNAL_PATH, WORKER)


class RemoteLifecycleBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mahoon-a54-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git = LocalBare(self.root)

    def _revision(self, revision: int = REVISION, published: int = REVISION - 1) -> dict:
        tx = {"worker": WORKER, "content_revision": revision,
              "logical_transaction_id": contracts.logical_transaction_id(WORKER, revision)}
        return artifact("revision_resolution", {
            "revision": revision, "published_revision": published,
            "changed_at": "2026-09-28T10:00:00+00:00",
            "endpoint_id": "mahoon-content-revision-v1", "request_count": 1,
            "decision": "CHANGED" if revision != published else "UNCHANGED",
        }, tx)

    def _admit(self, revision: int = REVISION, source: str = "github-schedule"):
        return self.git.writer().admit_revision(revision, source, "synthetic-run", str(uuid.uuid4()))

    def _intent(self, *, revision: int = REVISION, build_digest: str | None = None,
                generation: int | None = None) -> dict:
        tx = {"worker": WORKER, "content_revision": revision,
              "logical_transaction_id": contracts.logical_transaction_id(WORKER, revision)}
        return artifact("mutation_intent", {
            "operation_id": contracts.operation_id_for(tx["logical_transaction_id"], "upload_version"),
            "operation_name": "upload_version", "attempt_id": str(uuid.uuid4()),
            "intent_state": "RECORDED", "build_bundle_sha256": build_digest or SHA("bundle"),
            "prerequisite_artifact_sha256": SHA("admission"),
            "journal_generation": generation if generation is not None else self.git.journal().snapshot()[1] + 1,
            "desired_state": {"worker": WORKER, "build_bundle_sha256": build_digest or SHA("bundle")},
        }, tx)

    def _prepare_intent(self, *, outcome: str | None = None) -> tuple[dict, dict | None]:
        self._admit()
        journal = self.git.journal()
        state, generation, _ = journal.snapshot()
        txid = state["active"]["logical_transaction_id"]
        self.git.writer().record_build_ready(txid, SHA("bundle"))
        current, generation, _ = journal.snapshot()
        intent = self._intent(generation=generation + 1)
        generation, _digest, duplicate = self.git.writer().record_intent(
            txid, "upload_version", intent["payload"]["attempt_id"],
            intent["artifact_sha256"], intent["payload"]["journal_generation"],
        )
        self.assertFalse(duplicate)
        result = None
        if outcome:
            payload = {"operation_id": intent["payload"]["operation_id"],
                       "attempt_id": intent["payload"]["attempt_id"], "result_state": outcome,
                       "evidence_sha256": None if outcome == "UNKNOWN" else SHA("evidence"),
                       "intent_artifact_sha256": intent["artifact_sha256"],
                       "build_bundle_sha256": intent["payload"]["build_bundle_sha256"],
                       "readback_reference": None if outcome == "UNKNOWN" else {
                           "resource_type": "version", "worker": WORKER, "resource_id": "synthetic-version"}}
            result = artifact("mutation_result", payload)
        return intent, result

    def _write_json(self, name: str, value: dict) -> Path:
        path = self.root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_revision_resolution_calls_accepted_endpoint_once_and_derives_identity(self):
        state = self._write_json("published.json", {"published_content_revision": 40})
        calls = []
        def fetcher(endpoint):
            calls.append(endpoint)
            return {"revision": 41, "changed_at": "2026-09-28T10:00:00+00:00"}, {"synthetic": True}
        value = cli.create_revision_resolution(state, source_sha=SOURCE_SHA, fetcher=fetcher)
        self.assertEqual([cli.REVISION_ENDPOINT], calls)
        self.assertEqual(1, value["payload"]["request_count"])
        self.assertEqual(TX["logical_transaction_id"], value["transaction"]["logical_transaction_id"])
        self.assertEqual("CHANGED", value["payload"]["decision"])

    def test_revision_resolution_rejects_worker_endpoint_and_invalid_source(self):
        state = self._write_json("published.json", {"published_content_revision": 40})
        fetcher = mock.Mock(return_value=({"revision": 41, "changed_at": "2026-09-28T10:00:00+00:00"}, {}))
        with self.assertRaises(ValueError):
            cli.create_revision_resolution(state, worker="other-worker", source_sha=SOURCE_SHA, fetcher=fetcher)
        with self.assertRaises(ValueError):
            cli.create_revision_resolution(state, source_sha="bad", fetcher=fetcher)
        with self.assertRaises(ValueError):
            cli.create_revision_resolution(state, source_sha=SOURCE_SHA,
                                           endpoint="https://invalid.example", fetcher=fetcher)
        fetcher.assert_not_called()

    def test_revision_resolution_tampering_is_rejected(self):
        value = self._revision()
        value["payload"]["revision"] += 1
        with self.assertRaises(contracts.ArtifactContractError):
            contracts.validate_artifact(value)

    def test_resolver_cli_writes_no_partial_output_when_resolution_fails(self):
        state = self._write_json("published.json", {"published_content_revision": 40})
        output = self.root / "revision-out.json"
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(cli, "create_revision_resolution", side_effect=ValueError("synthetic failure")), \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(["resolve-revision", "--published-state", str(state), "--output", str(output)])
        self.assertEqual(2, code)
        self.assertFalse(output.exists())
        self.assertNotIn("synthetic failure", stderr.getvalue())

    def test_remote_admission_commits_exact_journal_and_readback(self):
        before = repository._remote_head(self.git.root, "origin", "main")
        decision, txid, generation, digest = self.git.writer().admit_revision(
            REVISION, "heartbeat", "synthetic-run", str(uuid.uuid4()))
        self.assertEqual("ADMITTED", decision)
        self.assertEqual(TX["logical_transaction_id"], txid)
        self.assertEqual(1, generation)
        remote, remote_generation, remote_digest, head = self.git.writer()._remote_snapshot()
        self.assertNotEqual(before, head)
        self.assertEqual((generation, digest), (remote_generation, remote_digest))
        self.assertEqual(txid, remote["active"]["logical_transaction_id"])
        self.assertEqual({repository.JOURNAL_PATH}, repository._commit_paths(self.git.root, head))
        self.assertTrue((self.git.root / "unrelated.txt").exists())

    def test_admission_coalesces_and_latest_pending_replaces_older(self):
        writer = self.git.writer()
        self.assertEqual("ADMITTED", writer.admit_revision(REVISION, "heartbeat")[0])
        self.assertEqual("COALESCED_ACTIVE", writer.admit_revision(REVISION, "github")[0])
        self.assertEqual("PENDING", writer.admit_revision(REVISION + 1, "github")[0])
        self.assertEqual("PENDING_REPLACED", writer.admit_revision(REVISION + 2, "heartbeat")[0])
        value = self.git.journal().snapshot()[0]
        self.assertEqual(REVISION + 2, value["pending"]["content_revision"])
        self.assertIn("superseded", [item["state"] for item in value["history"]])

    def test_cli_admit_invokes_durable_remote_writer_and_seals_receipt(self):
        revision_file = self._write_json("revision.json", self._revision())
        receipt_file = self.root / "receipt.json"
        stdout, stderr = io.StringIO(), io.StringIO()
        args = ["admit", "--revision", str(revision_file), "--repository", str(self.git.root),
                "--source", "github-schedule", "--run-id", "synthetic-run",
                "--trigger-attempt", str(uuid.uuid4()), "--remote", "origin", "--branch", "main",
                "--output", str(receipt_file)]
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(args)
        self.assertEqual(0, code, stderr.getvalue())
        receipt = transport.read_artifact(receipt_file, expected_type="admission_receipt")
        self.assertEqual("ADMITTED", receipt["payload"]["decision"])
        self.assertEqual(1, receipt["payload"]["journal_generation"])
        self.assertEqual(receipt["payload"]["journal_sha256"], self.git.journal().snapshot()[2])

    def test_lifecycle_cli_runs_admit_build_intent_result_against_only_local_remote(self):
        revision_path = self._write_json("revision.json", self._revision())
        receipt_path, bundle_path = self.root / "receipt.json", self.root / "bundle.json"
        intent_path, result_path = self.root / "intent.json", self.root / "result.json"
        journal_path = self.git.root / repository.JOURNAL_PATH
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(["admit", "--revision", str(revision_path), "--repository", str(self.git.root),
                             "--source", "github-schedule", "--output", str(receipt_path)])
        self.assertEqual(0, code, stderr.getvalue())
        receipt = transport.read_artifact(receipt_path, expected_type="admission_receipt")
        bundle = artifact("build_bundle", {
            "admission_receipt_sha256": receipt["artifact_sha256"], "files": [],
            "content_fingerprint": SHA("fingerprint"), "snapshot_sha256": SHA("snapshot"),
            "route_manifest_sha256": SHA("routes"), "media_manifest_sha256": SHA("media"),
            "local_gate_evidence_sha256": SHA("gates"),
        })
        transport.write_artifact(bundle_path, bundle, referenced_artifacts=transport.references(receipt))
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(["record-build-ready", "--build-bundle", str(bundle_path),
                             "--admission", str(receipt_path), "--journal", str(journal_path),
                             "--repository", str(self.git.root), "--remote", "origin", "--branch", "main"])
        self.assertEqual(0, code, stderr.getvalue())
        state, generation, _ = self.git.journal().snapshot()
        intent = artifact("mutation_intent", {
            "operation_id": contracts.operation_id_for(TX["logical_transaction_id"], "upload_version"),
            "operation_name": "upload_version", "attempt_id": str(uuid.uuid4()),
            "intent_state": "RECORDED", "build_bundle_sha256": bundle["artifact_sha256"],
            "prerequisite_artifact_sha256": receipt["artifact_sha256"],
            "journal_generation": generation + 1,
            "desired_state": {"worker": WORKER, "build_bundle_sha256": bundle["artifact_sha256"]},
        })
        transport.write_artifact(intent_path, intent)
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(["record-intent", "--journal", str(journal_path), "--intent", str(intent_path),
                             "--repository", str(self.git.root), "--remote", "origin", "--branch", "main"])
        self.assertEqual(0, code, stderr.getvalue())
        result = artifact("mutation_result", {
            "operation_id": intent["payload"]["operation_id"],
            "attempt_id": intent["payload"]["attempt_id"], "result_state": "APPLIED",
            "evidence_sha256": SHA("result-evidence"),
            "intent_artifact_sha256": intent["artifact_sha256"],
            "build_bundle_sha256": bundle["artifact_sha256"],
            "readback_reference": {"resource_type": "version", "worker": WORKER,
                                   "resource_id": "synthetic-version"},
        })
        transport.write_artifact(result_path, result)
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(["record-result", "--journal", str(journal_path), "--intent", str(intent_path),
                             "--result", str(result_path), "--repository", str(self.git.root),
                             "--remote", "origin", "--branch", "main"])
        self.assertEqual(0, code, stderr.getvalue())
        remote, remote_gen, remote_digest, remote_head = self.git.writer()._remote_snapshot()
        local, local_gen, local_digest = self.git.journal().snapshot()
        self.assertEqual((local, local_gen, local_digest), (remote, remote_gen, remote_digest))
        self.assertEqual("APPLIED", local["active"]["operations"]["upload_version"]["result_state"])
        self.assertEqual({repository.JOURNAL_PATH}, repository._commit_paths(self.git.root, remote_head))

    def test_intent_attempt_reuse_with_different_digest_is_rejected(self):
        intent, _ = self._prepare_intent()
        payload = intent["payload"]
        with self.assertRaises(repository.RepositoryPersistenceError):
            self.git.writer().record_intent(
                TX["logical_transaction_id"], "upload_version", payload["attempt_id"], SHA("different-intent"),
                payload["journal_generation"],
            )

    def test_no_receipt_is_emitted_if_remote_admission_persistence_fails(self):
        revision_file = self._write_json("revision.json", self._revision())
        output = self.root / "receipt.json"
        writer = mock.Mock()
        writer.root = self.git.root
        writer.admit_revision.side_effect = repository.RepositoryPersistenceError("synthetic block")
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(cli, "_writer", return_value=writer), \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(["admit", "--revision", str(revision_file), "--repository", str(self.git.root),
                             "--source", "github", "--output", str(output)])
        self.assertEqual(2, code)
        self.assertFalse(output.exists())

    def test_build_ready_requires_admission_and_is_idempotent(self):
        decision, txid, _, _ = self._admit()
        self.assertEqual("ADMITTED", decision)
        generation, digest = self.git.writer().record_build_ready(txid, SHA("bundle"))
        again = self.git.writer().record_build_ready(txid, SHA("bundle"))
        self.assertEqual((generation, digest), again)
        with self.assertRaises(repository.RepositoryPersistenceError):
            self.git.writer().record_build_ready("f" * 64, SHA("different"))

    def test_intent_is_durable_idempotent_and_requires_fresh_generation(self):
        intent, _ = self._prepare_intent()
        writer = self.git.writer()
        generation = intent["payload"]["journal_generation"]
        op = intent["payload"]
        state, _, _ = self.git.journal().snapshot()
        # Replaying the same operation receipt after commit is a read-only idempotent result.
        new_generation, _digest, duplicate = writer.record_intent(
            TX["logical_transaction_id"], "upload_version", op["attempt_id"],
            intent["artifact_sha256"], generation)
        self.assertTrue(duplicate)
        self.assertEqual(generation, new_generation)
        self.assertEqual("NOT_REPORTED", state["active"]["operations"]["upload_version"]["result_state"])

    def test_intent_rejects_stale_generation_and_conflicting_attempt_identity(self):
        self._admit()
        state, generation, _ = self.git.journal().snapshot()
        txid = state["active"]["logical_transaction_id"]
        self.git.writer().record_build_ready(txid, SHA("bundle"))
        intent = self._intent(generation=generation + 1)
        with self.assertRaises(JournalConflict):
            self.git.writer().record_intent(txid, "upload_version", intent["payload"]["attempt_id"],
                                            intent["artifact_sha256"], intent["payload"]["journal_generation"])

    def test_result_applied_not_applied_unknown_and_idempotent_readback(self):
        for outcome in ("APPLIED", "NOT_APPLIED", "UNKNOWN"):
            with self.subTest(outcome=outcome):
                # Independent temporary local remote per result state.
                child = self.root / outcome
                child.mkdir()
                local = LocalBare(child)
                prior_git = self.git
                self.git = local
                try:
                    intent, result = self._prepare_intent(outcome=outcome)
                    rp = result["payload"]
                    writer = self.git.writer()
                    gen, digest, duplicate = writer.record_result(
                        TX["logical_transaction_id"], rp["operation_id"], rp["attempt_id"], outcome,
                        rp["evidence_sha256"], intent["artifact_sha256"], result["artifact_sha256"])
                    self.assertFalse(duplicate)
                    self.assertEqual((gen, digest), writer.record_result(
                        TX["logical_transaction_id"], rp["operation_id"], rp["attempt_id"], outcome,
                        rp["evidence_sha256"], intent["artifact_sha256"], result["artifact_sha256"])[:2])
                    active = self.git.journal().snapshot()[0]["active"]
                    self.assertEqual(outcome.lower() == "unknown", active["state"] == "recovery_required")
                    if outcome == "UNKNOWN":
                        with self.assertRaises(Exception):
                            self.git.writer().record_intent(
                                TX["logical_transaction_id"], "upload_version", str(uuid.uuid4()),
                                SHA("retry-intent"), self.git.journal().snapshot()[1] + 1)
                finally:
                    self.git = prior_git

    def test_conflicting_duplicate_result_is_rejected(self):
        intent, result = self._prepare_intent(outcome="APPLIED")
        rp = result["payload"]
        writer = self.git.writer()
        writer.record_result(TX["logical_transaction_id"], rp["operation_id"], rp["attempt_id"],
                             "APPLIED", rp["evidence_sha256"], intent["artifact_sha256"], result["artifact_sha256"])
        with self.assertRaises(Exception):
            writer.record_result(TX["logical_transaction_id"], rp["operation_id"], rp["attempt_id"],
                                 "NOT_APPLIED", SHA("other-evidence"), intent["artifact_sha256"], SHA("other-result"))

    def test_stale_remote_race_fails_before_local_journal_or_receipt_changes(self):
        writer = self.git.writer()
        other = self.root / "other-clone"
        run_git(self.root, "clone", "--branch", "main", str(self.git.bare), str(other))
        run_git(other, "config", "user.name", "Synthetic Racer")
        run_git(other, "config", "user.email", "racer@example.invalid")
        (other / "racer.txt").write_text("advance", encoding="utf-8")
        run_git(other, "add", "racer.txt")
        run_git(other, "commit", "-m", "synthetic remote race")
        run_git(other, "push", "origin", "main")
        old_head = run_git(self.git.root, "rev-parse", "HEAD")
        old_journal = (self.git.root / repository.JOURNAL_PATH).read_bytes()
        with self.assertRaises(repository.RepositoryPersistenceError):
            writer.admit_revision(REVISION, "heartbeat")
        self.assertEqual(old_head, run_git(self.git.root, "rev-parse", "HEAD"))
        self.assertEqual(old_journal, (self.git.root / repository.JOURNAL_PATH).read_bytes())

    def test_lifecycle_cli_result_commits_without_loading_cloudflare_adapter(self):
        intent, result = self._prepare_intent(outcome="APPLIED")
        intent_path = self._write_json("intent.json", intent)
        result_path = self._write_json("result.json", result)
        journal_path = self.git.root / repository.JOURNAL_PATH
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(["record-result", "--journal", str(journal_path), "--intent", str(intent_path),
                             "--result", str(result_path), "--repository", str(self.git.root),
                             "--remote", "origin", "--branch", "main"])
        self.assertEqual(0, code, stderr.getvalue())
        self.assertIn('"status": "APPLIED"', stdout.getvalue())

    def test_lifecycle_import_does_not_load_cloudflare_mutation_backend(self):
        code = ("import sys; import publisher.workflow_stage_cli; "
                "assert 'publisher.cloudflare_operation_adapter' not in sys.modules")
        subprocess.run([sys.executable, "-B", "-c", code], cwd=Path(__file__).resolve().parents[1],
                       check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
