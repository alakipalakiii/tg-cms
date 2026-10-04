from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from publisher import artifact_contract as contracts
from publisher import final_state_materializer as materializer
from publisher import media_bootstrap, seal_artifact
from publisher.core import fingerprint
from publisher.final_persistence_runner import validate_finalization_inputs
from publisher import workflow_stage_cli as cli
import test_proof_recovery_runner as proof_fixtures


OLD_INDEX = (json.dumps({"contract": "IMMUTABLE_MEDIA_INDEX_V1", "entries": [
    {"source_identifier": "old-media", "immutable_path": "/media/aa/first.jpg",
     "sha256": "1" * 64, "mime": "image/jpeg", "media_type": "photo", "fallback": False},
    {"source_identifier": "retired-media", "immutable_path": "/media/bb/retired.jpg",
     "sha256": "3" * 64, "mime": "image/jpeg", "media_type": "photo", "fallback": False},
    {"source_identifier": "old-media", "immutable_path": "/media/cc/canonical.jpg",
     "sha256": "2" * 64, "mime": "image/jpeg", "media_type": "photo", "fallback": False},
]}, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def _fixture(root: Path):
    f = proof_fixtures.ProofRecoveryRunnerTests()
    f.setUp()
    f.posts = [
        {"id": 3, "slug": "one", "text": "one", "media_file_id": "old-media", "media_type": "photo"},
        {"id": 4, "slug": "two", "text": "two", "media_file_id": "new-media", "media_type": "photo"},
        {"id": 5, "slug": "three", "text": "three", "media_file_id": "old-media", "media_type": "photo"},
        {"id": 6, "slug": "four", "text": "four", "media_file_id": "missing-media", "media_type": "photo"},
    ]
    f.snapshot = {
        "contract": "POSTS_FULL_PUBLIC_SNAPSHOT_V2",
        "snapshot_total_count": len(f.posts), "payload": {"posts": f.posts},
    }
    f.snapshot_bytes = json.dumps(f.snapshot, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    f.content_fingerprint = fingerprint({
        "contract": "PUBLISHED_CONTENT_DELTA_CONTRACT_V2", "count": len(f.posts), "posts": f.posts,
    })
    f.route_manifest = {
        "contract": "CURRENT_CANDIDATE_SEALED_ROUTE_MANIFEST_V1",
        "route_count": 2, "routes": ["/post/one", "/post/two"],
    }
    f.route_bytes = (json.dumps(f.route_manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    f.media_manifest = {
        "contract": "CURRENT_MEDIA_RESOLUTION_V1", "records": [
            {"source_identifier": "missing-media", "post_ids": [6], "fallback": True,
             "fallback_reason": "SOURCE_HTTP_404"},
            {"source_identifier": "new-media", "immutable_path": "/media/aa/new.jpg",
             "sha256": "4" * 64, "mime": "image/jpeg", "media_type": "photo",
             "fallback": False, "post_ids": [4], "detected_mime": "image/jpeg"},
            {"source_identifier": "old-media", "immutable_path": "/media/dd/replacement.jpg",
             "sha256": "5" * 64, "mime": "image/jpeg", "media_type": "photo",
             "fallback": False, "post_ids": [3, 5], "detected_mime": "image/jpeg"},
        ], "stats": {"required_distinct": 3, "fallback": 1},
    }
    f.media_bytes = (json.dumps(f.media_manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    f.prior_bytes = OLD_INDEX
    f.binding = {
        "repository": "synthetic-owner/tg-cms", "ref": "refs/heads/main",
        "commit_sha": "7" * 40,
        "relative_path": contracts.PRIOR_IMMUTABLE_MEDIA_INDEX_PATH,
        "exists": True, "content_sha256": contracts.sha256_bytes(f.prior_bytes),
        "byte_length": len(f.prior_bytes),
        "transport_base64": base64.b64encode(f.prior_bytes).decode("ascii"),
    }
    f.site = root / "site"
    f.site.mkdir(parents=True)
    site_file = f.site / "index.html"
    site_file.write_bytes(b"synthetic sealed site\n")
    site_inventory = [{"path": "index.html", "size_bytes": site_file.stat().st_size,
                       "sha256": hashlib.sha256(site_file.read_bytes()).hexdigest()}]
    f.seal = seal_artifact.create_seal(
        f.site, content_fingerprint=f.content_fingerprint,
        route_hash=fingerprint(f.route_manifest),
    )
    payload = {
        "admission_receipt_sha256": f.receipt["artifact_sha256"],
        "files": site_inventory, "content_fingerprint": f.content_fingerprint,
        "snapshot_sha256": contracts.sha256_bytes(f.snapshot_bytes),
        "route_manifest_sha256": contracts.sha256_bytes(f.route_bytes),
        "media_manifest_sha256": contracts.sha256_bytes(f.media_bytes),
        "local_gate_evidence_sha256": proof_fixtures.SHA2,
        "prior_immutable_media_index": f.binding,
    }
    f.bundle = proof_fixtures.artifact("build_bundle", payload, f.tx)
    f.upload_intent = f._intent("upload_version", f.receipt, {
        "worker": proof_fixtures.WORKER, "build_bundle_sha256": f.bundle["artifact_sha256"],
    })
    f.upload_result = f._result(f.upload_intent, "APPLIED", "version", "candidate-v1")
    f.deploy_intent = f._intent("deploy_zero_percent", f.upload_result, {
        "worker": proof_fixtures.WORKER, "candidate_version_id": "candidate-v1",
        "baseline_version_id": "baseline-v1", "expected_current_deployment_id": "dep-before",
        "candidate_percentage": 0, "baseline_percentage": 100,
    })
    f.deploy_result = f._result(f.deploy_intent, "APPLIED", "deployment", "dep-zero")
    f.prepromotion_proof = f._prepromotion_proof()
    f.promote_intent = f._intent("promote", f.prepromotion_proof, {
        "worker": proof_fixtures.WORKER, "candidate_version_id": "candidate-v1",
        "baseline_version_id": "baseline-v1", "expected_current_deployment_id": "dep-zero",
        "candidate_percentage": 100, "baseline_percentage": 0,
    })
    f.promote_result = f._result(f.promote_intent, "APPLIED", "deployment", "dep-promoted")
    proof_payload = f._proof()["payload"]
    proof_payload["candidate_identity"]["content_fingerprint"] = f.content_fingerprint
    f.proof = proof_fixtures.artifact("proof_evidence", proof_payload, f.tx)
    f.intents = {"upload_version": f.upload_intent,
                 "deploy_zero_percent": f.deploy_intent, "promote": f.promote_intent}
    f.results = {"upload_version": f.upload_result,
                 "deploy_zero_percent": f.deploy_result, "promote": f.promote_result}
    values = [f.receipt, f.bundle, f.upload_intent, f.upload_result, f.deploy_intent,
              f.deploy_result, f.prepromotion_proof, f.promote_intent, f.promote_result, f.proof]
    f.references = {value["artifact_sha256"]: value for value in values}
    f.output = materializer.materialize_final_state(
        proof=f.proof, build_bundle=f.bundle, operation_intents=f.intents,
        operation_results=f.results, snapshot_bytes=f.snapshot_bytes,
        media_manifest_bytes=f.media_bytes, route_manifest_bytes=f.route_bytes,
        sealed_root=f.site, artifact_seal=f.seal, referenced_artifacts=f.references,
    )
    return f


class FinalStateMaterializerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = _fixture(Path(self.temp.name))

    def materialize(self, **changes):
        args = {
            "proof": self.f.proof, "build_bundle": self.f.bundle,
            "operation_intents": self.f.intents, "operation_results": self.f.results,
            "snapshot_bytes": self.f.snapshot_bytes,
            "media_manifest_bytes": self.f.media_bytes,
            "route_manifest_bytes": self.f.route_bytes,
            "sealed_root": self.f.site, "artifact_seal": self.f.seal,
            "referenced_artifacts": self.f.references,
        }
        args.update(changes)
        return materializer.materialize_final_state(**args)

    def test_exact_six_bytes_and_repeat_are_deterministic(self):
        self.assertEqual(set(contracts.STATE_FILE_PATHS), set(self.f.output))
        self.assertTrue(all(type(value) is bytes for value in self.f.output.values()))
        self.assertEqual(self.f.output, self.materialize())
        state = json.loads(self.f.output["publisher-state/production-content-fingerprint.json"])
        self.assertEqual({"fingerprint": self.f.content_fingerprint, "count": 4,
                          "published_content_revision": 37}, state)
        self.assertEqual(self.f.media_bytes, self.f.output["publisher-state/production-media-manifest.json"])
        self.assertEqual(self.f.route_bytes, self.f.output["publisher-state/published-route-manifest.json"])
        self.assertEqual(self.f.route_bytes, self.f.output["publisher-state/current-accepted-route-manifest.json"])
        self.assertEqual("STATIC", json.loads(self.f.output["publisher-state/published-static-state.json"])["current_version_type"])

    def test_cumulative_merge_preserves_old_duplicate_winner_and_adds_only_successful_new_media(self):
        value = json.loads(self.f.output["publisher-state/immutable-media-index.json"])
        rows = value["entries"]
        self.assertEqual("IMMUTABLE_MEDIA_INDEX_V1", value["contract"])
        self.assertEqual(["new-media", "old-media", "retired-media"],
                         [row["source_identifier"] for row in rows])
        by_id = {row["source_identifier"]: row for row in rows}
        self.assertEqual("2" * 64, by_id["old-media"]["sha256"])
        self.assertEqual("4" * 64, by_id["new-media"]["sha256"])
        self.assertNotIn("missing-media", by_id)
        self.assertEqual(media_bootstrap.serialize_index({row["source_identifier"]: row for row in rows}),
                         self.f.output["publisher-state/immutable-media-index.json"])

    def test_final_persistence_preflight_accepts_exact_materialized_mapping(self):
        proof, bundle, files, hashes = validate_finalization_inputs(
            self.f.proof, self.f.bundle, self.f.results, self.f.output, 0,
        )
        self.assertEqual("PASS", proof["payload"]["proof_state"])
        self.assertEqual(set(contracts.STATE_FILE_PATHS), set(files))
        self.assertEqual(set(contracts.STATE_FILE_PATHS), set(hashes))
        self.assertEqual(self.f.bundle["artifact_sha256"], bundle["artifact_sha256"])

    def test_failed_or_tampered_proof_is_rejected(self):
        with self.assertRaises(materializer.MaterializationRejected):
            self.materialize(proof=self.f._proof(failed_production=True))
        tampered = copy.deepcopy(self.f.proof)
        tampered["payload"]["proof_state"] = "FAIL"
        with self.assertRaises(materializer.MaterializationRejected):
            self.materialize(proof=tampered)
        with self.assertRaises(materializer.MaterializationRejected):
            self.materialize(proof=None)

    def test_wrong_transaction_worker_revision_source_build_or_candidate_is_rejected(self):
        variants = []
        proof = copy.deepcopy(self.f.proof)
        proof["transaction"]["content_revision"] += 1
        proof["transaction"]["logical_transaction_id"] = contracts.logical_transaction_id(
            proof["transaction"]["worker"], proof["transaction"]["content_revision"])
        variants.append(("revision", contracts.seal_artifact(proof), self.f.bundle))
        proof = copy.deepcopy(self.f.proof)
        proof["transaction"]["worker"] = "other-worker"
        proof["transaction"]["logical_transaction_id"] = contracts.logical_transaction_id(
            proof["transaction"]["worker"], proof["transaction"]["content_revision"])
        variants.append(("worker", contracts.seal_artifact(proof), self.f.bundle))
        bundle = copy.deepcopy(self.f.bundle)
        bundle["producer"]["source_sha"] = "9" * 40
        variants.append(("source", self.f.proof, contracts.seal_artifact(bundle)))
        proof = copy.deepcopy(self.f.proof)
        proof["payload"]["build_bundle_sha256"] = "8" * 64
        variants.append(("build", contracts.seal_artifact(proof), self.f.bundle))
        proof = copy.deepcopy(self.f.proof)
        proof["payload"]["candidate_identity"]["candidate_version_id"] = "other-candidate"
        proof["payload"]["production_validation"]["identity_confirmation"]["candidate_version_id"] = "other-candidate"
        variants.append(("candidate", contracts.seal_artifact(proof), self.f.bundle))
        for label, candidate_proof, candidate_bundle in variants:
            with self.subTest(label=label), self.assertRaises(materializer.MaterializationRejected):
                self.materialize(proof=candidate_proof, build_bundle=candidate_bundle)

    def test_operation_result_readback_and_proof_lineage_must_match(self):
        result = copy.deepcopy(self.f.promote_result)
        result["payload"]["readback_reference"]["resource_id"] = "other-deployment"
        result = contracts.seal_artifact(result)
        results = dict(self.f.results, promote=result)
        with self.assertRaises(materializer.MaterializationRejected):
            self.materialize(operation_results=results)
        proof = copy.deepcopy(self.f.proof)
        proof["payload"]["operation_result_sha256s"]["promote"] = "0" * 64
        with self.assertRaises(materializer.MaterializationRejected):
            self.materialize(proof=contracts.seal_artifact(proof))

    def test_missing_and_tampered_prior_binding_fail_closed(self):
        bundle = copy.deepcopy(self.f.bundle)
        del bundle["payload"]["prior_immutable_media_index"]
        with self.assertRaises(materializer.MaterializationRejected):
            self.materialize(build_bundle=contracts.seal_artifact(bundle))
        for field, changed in (("commit_sha", "8" * 40),
                               ("relative_path", "publisher-state/other.json"),
                               ("content_sha256", "9" * 64),
                               ("byte_length", len(self.f.prior_bytes) + 1)):
            with self.subTest(field=field), self.assertRaises(materializer.MaterializationRejected):
                changed_bundle = copy.deepcopy(self.f.bundle)
                changed_bundle["payload"]["prior_immutable_media_index"][field] = changed
                self.materialize(build_bundle=contracts.seal_artifact(changed_bundle))

    def test_prior_snapshot_bytes_are_transport_not_authority(self):
        binding = self.f.bundle["payload"]["prior_immutable_media_index"]
        for data in (self.f.prior_bytes + b"x", self.f.prior_bytes[:-1], b"{}\n"):
            with self.subTest(length=len(data)), self.assertRaises(contracts.ArtifactContractError):
                contracts.validate_prior_index_transport(self.f.bundle, data,
                    expected_transaction=self.f.tx, expected_source_sha=proof_fixtures.SOURCE_SHA)
        other_tx = {"worker": self.f.tx["worker"], "content_revision": self.f.tx["content_revision"] + 1}
        other_tx["logical_transaction_id"] = contracts.logical_transaction_id(other_tx["worker"], other_tx["content_revision"])
        with self.assertRaises(contracts.ArtifactContractError):
            contracts.validate_prior_index_transport(self.f.bundle, self.f.prior_bytes,
                expected_transaction=other_tx, expected_source_sha=proof_fixtures.SOURCE_SHA)
        self.assertEqual(len(self.f.prior_bytes), binding["byte_length"])

    def test_first_state_is_absence_and_uses_historical_empty_index_serialization(self):
        empty = b""
        binding = {**self.f.binding, "exists": False,
                   "content_sha256": contracts.sha256_bytes(empty), "byte_length": 0,
                   "transport_base64": ""}
        posts = [{"id": 4, "media_file_id": "new-media", "media_type": "photo"},
                 {"id": 6, "media_file_id": "missing-media", "media_type": "photo"}]
        media = {"records": [self.f.media_manifest["records"][0], self.f.media_manifest["records"][1]]}
        output = materializer._merge_media_index(empty, binding, posts, media)
        expected = media_bootstrap.serialize_index({"new-media": {
            "source_identifier": "new-media", "immutable_path": "/media/aa/new.jpg",
            "sha256": "4" * 64, "mime": "image/jpeg", "media_type": "photo", "fallback": False,
        }})
        self.assertEqual(expected, output)

    def test_legacy_files_are_not_accepted_as_proof_or_bundle_authority(self):
        for value in (None, {}, {"transaction": "legacy"}, {"production_result": True},
                      {"remote_proof": True}, {"bundle-index": True}):
            with self.subTest(value=value), self.assertRaises(materializer.MaterializationRejected):
                self.materialize(proof=value)

    def test_core_has_no_git_network_cloudflare_d1_or_journal_mutation_path(self):
        source = Path(materializer.__file__).read_text(encoding="utf-8")
        for forbidden in ("subprocess", "urllib", "cloudflare_operation_adapter", "TransactionJournal",
                          "GitRepositoryWriter", "GitJournalWriter", "sqlite3", "D1"):
            self.assertNotIn(forbidden, source)

    def test_materializer_and_cli_do_not_own_artifact_hashing(self):
        source = Path(cli.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import hashlib", source)
        self.assertNotIn("canonical_json_bytes", source)
        self.assertNotIn("artifact_digest(", source)

    def test_atomic_staging_writes_exact_six_and_is_idempotent(self):
        root = Path(self.temp.name) / "runner-temp"
        root.mkdir()
        with patch.dict(os.environ, {"RUNNER_TEMP": str(root)}):
            staged = cli._stage_materialized_state(self.f.output, self.f.tx["logical_transaction_id"])
            self.assertEqual(self.f.output, cli._staged_state_files(staged))
            self.assertEqual(staged, cli._stage_materialized_state(self.f.output, self.f.tx["logical_transaction_id"]))
            with self.assertRaises(ValueError):
                cli._stage_materialized_state(dict(list(self.f.output.items())[:-1]), self.f.tx["logical_transaction_id"])
            with self.assertRaises(ValueError):
                cli._stage_materialized_state({**self.f.output, "publisher-state/extra.json": b"x"}, self.f.tx["logical_transaction_id"])

    def test_partial_existing_target_is_rejected_without_overwrite(self):
        root = Path(self.temp.name) / "runner-temp"
        base = root / "mahoon-final-state"
        target = base / self.f.tx["logical_transaction_id"]
        state = target / "publisher-state"
        state.mkdir(parents=True)
        marker = state / "partial.json"
        marker.write_bytes(b"keep")
        with patch.dict(os.environ, {"RUNNER_TEMP": str(root)}), self.assertRaises(ValueError):
            cli._stage_materialized_state(self.f.output, self.f.tx["logical_transaction_id"])
        self.assertEqual(b"keep", marker.read_bytes())

    def test_cli_materialize_command_is_orchestration_only_and_stages_exact_files(self):
        root = Path(self.temp.name)
        artifacts = {
            "proof": self.f.proof, "bundle": self.f.bundle,
            "upload_intent": self.f.upload_intent, "upload_result": self.f.upload_result,
            "deploy_intent": self.f.deploy_intent, "deploy_result": self.f.deploy_result,
            "preproof": self.f.prepromotion_proof,
            "promote_intent": self.f.promote_intent, "promote_result": self.f.promote_result,
            "receipt": self.f.receipt,
        }
        paths = {}
        for name, value in artifacts.items():
            path = root / f"{name}.json"
            path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            paths[name] = path
        for name, value in (("snapshot", self.f.snapshot_bytes), ("media", self.f.media_bytes),
                            ("routes", self.f.route_bytes)):
            path = root / f"{name}.json"
            path.write_bytes(value)
            paths[name] = path
        seal_path = root / "seal.json"
        seal_path.write_text(json.dumps(self.f.seal), encoding="utf-8")
        references = [paths[name] for name in ("receipt", "bundle", "upload_intent", "upload_result",
                                                "deploy_intent", "deploy_result", "preproof",
                                                "promote_intent", "promote_result")]
        runner_temp = root / "runner-temp"
        runner_temp.mkdir()
        args = ["materialize-final-state", "--proof", str(paths["proof"]),
                "--build-bundle", str(paths["bundle"]), "--upload-version-intent", str(paths["upload_intent"]),
                "--upload-version-result", str(paths["upload_result"]),
                "--deploy-zero-percent-intent", str(paths["deploy_intent"]),
                "--deploy-zero-percent-result", str(paths["deploy_result"]),
                "--promote-intent", str(paths["promote_intent"]), "--promote-result", str(paths["promote_result"]),
                "--sealed-root", str(self.f.site), "--artifact-seal", str(seal_path),
                "--snapshot", str(paths["snapshot"]), "--media-manifest", str(paths["media"]),
                "--route-manifest", str(paths["routes"])]
        for reference in references:
            args.extend(("--reference", str(reference)))
        stdout = io.StringIO()
        with patch.dict(os.environ, {"RUNNER_TEMP": str(runner_temp)}), redirect_stdout(stdout):
            self.assertEqual(0, cli.main(args))
        response = json.loads(stdout.getvalue())
        self.assertEqual("FINAL_STATE_MATERIALIZED", response["status"])
        self.assertEqual(6, response["file_count"])
        self.assertEqual(self.f.output, cli._staged_state_files(Path(response["state_dir"])))


if __name__ == "__main__":
    unittest.main()
