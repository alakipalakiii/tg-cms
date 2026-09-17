from __future__ import annotations

import json
import inspect
import tempfile
import unittest
from pathlib import Path

from tools.publisher.resumable_transaction import (
    create_proof_bundle,
    canonical_hash,
    remote_expectations,
    split_is_baseline_zero,
    transaction_id,
    verify_production_result,
    verify_proof_bundle,
    verify_remote_result,
)
from tools.m9 import publisher_runner, resumable_stage_runner


class ResumableTransactionTests(unittest.TestCase):
    def setUp(self):
        self.posts = [
            {"id": 10, "slug": "new", "created_at": "2026-09-17T10:00:00Z",
             "text": "متن تازه #شعر", "media_type": ""},
            {"id": 9, "slug": "older", "created_at": "2026-09-17T09:00:00Z",
             "text": "متن کهنه #کتاب", "media_type": "audio"},
        ]
        self.routes = {"contract": "CURRENT_CANDIDATE_SEALED_ROUTE_MANIFEST_V1",
                       "route_count": 7,
                       "routes": ["/", "/posts", "/category/شعر", "/post/new",
                                  "/post/older", "/admin", "/admin/analytics"]}
        self.media = {"contract": "CURRENT_MEDIA_RESOLUTION_V1", "records": [],
                      "stats": {"unresolved": 0, "required_distinct": 0}}
        self.index = {"contract": "IMMUTABLE_MEDIA_INDEX_V1", "entries": []}
        self.tx = {
            "transaction_id": "revision-42-run-123456-attempt-1",
            "source_sha": "a" * 40,
            "source_revision": 42,
            "revision_requests": 1,
            "full_v2_exports": 1,
            "snapshot_api_starts": 0,
            "single_snapshot_reuse": "YES",
            "candidate_static_version": "candidate-v1",
            "baseline_static_version": "baseline-v1",
            "target_worker": "mahoon-art-magazine",
            "content_fingerprint": "content-hash",
            "candidate_split": {"baseline-v1": 100, "candidate-v1": 0},
            "preexisting_zero_versions": [],
        }
        self.seal = {"contract": "MAHOON_STATIC_ARTIFACT_SEAL_V1",
                     "content_fingerprint": "content-hash",
                     "route_hash": canonical_hash(self.routes)}
        self.seal["artifact_sha256"] = canonical_hash(self.seal)
        self.evidence = {
            "transaction_start_static_baseline": {"PASS": True},
            "filesystem_gate": {"PASS": True},
            "measured_local_gates": {"measured": True, "PASS": True},
            "pre_upload_live_baseline": {"PASS": True},
            "pre_zero_percent_live_read": {"PASS": True},
            "rollback_anchor": {"static_version": "baseline-v1"},
        }

    def test_stable_transaction_identity(self):
        self.assertEqual("revision-42-run-123-attempt-2", transaction_id(42, "123", "2"))
        with self.assertRaises(ValueError):
            transaction_id(0, "123", "2")

    def test_expectations_are_sanitized_and_measured(self):
        expected = remote_expectations(self.posts, self.routes, self.media)
        self.assertEqual([10, 9], expected["listing_ids"])
        self.assertEqual([10], expected["category_ids"]["شعر و متن"])
        self.assertEqual([9], expected["category_ids"]["کتاب"])
        self.assertNotIn("text", expected["posts"][0])
        self.assertEqual("/post/older", next(row["route"] for row in expected["visual_routes"] if row["name"] == "old-post"))
        self.assertIn("audio-post", {row["name"] for row in expected["visual_routes"]})

    def test_build_bundle_is_content_minimized_and_hash_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "bundle"
            info = create_proof_bundle(root, transaction=self.tx, routes=self.routes,
                                       media_manifest=self.media, media_index=self.index,
                                       seal=self.seal, local_evidence=self.evidence,
                                       posts=self.posts)
            transaction, bundle_hash = verify_proof_bundle(root, self.tx["transaction_id"], self.tx["source_sha"])
            self.assertEqual(info["bundle_sha256"], bundle_hash)
            self.assertEqual("candidate-v1", transaction["candidate_static_version"])
            self.assertFalse((root / "current-v2-snapshot.json").exists())
            expectations = json.loads((root / "remote-expectations.json").read_text(encoding="utf-8"))
            self.assertNotIn("text", expectations["posts"][0])
            (root / "candidate-route-manifest.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                verify_proof_bundle(root)

    def test_remote_proof_is_bound_to_candidate_transaction_and_bundle(self):
        transaction, digest = self._bundle()
        result = {"contract": "MAHOON_REMOTE_PROOF_RESULT_V1", "REMOTE_PROOF_PASS": True,
                  "transaction_id": transaction["transaction_id"],
                  "candidate_version": transaction["candidate_static_version"], "bundle_sha256": digest}
        verify_remote_result(result, transaction, digest)
        result["transaction_id"] = "another-transaction"
        with self.assertRaisesRegex(ValueError, "remote-proof"):
            verify_remote_result(result, transaction, digest)

    def test_remote_timeout_or_failure_cannot_authorize_promotion(self):
        transaction, digest = self._bundle()
        result = {"contract": "MAHOON_REMOTE_PROOF_RESULT_V1", "REMOTE_PROOF_PASS": False,
                  "transaction_id": transaction["transaction_id"],
                  "candidate_version": transaction["candidate_static_version"], "bundle_sha256": digest}
        with self.assertRaisesRegex(ValueError, "remote-proof"):
            verify_remote_result(result, transaction, digest)

    def test_remote_proof_rerun_is_read_only_and_baseline_split_is_required(self):
        transaction, _ = self._bundle()
        state = {"versions": [{"version_id": "baseline-v1", "percentage": 100},
                               {"version_id": "candidate-v1", "percentage": 0}]}
        self.assertTrue(split_is_baseline_zero(state, transaction))
        self.assertFalse(split_is_baseline_zero({"versions": [{"version_id": "candidate-v1", "percentage": 1}]}, transaction))

    def test_failed_remote_artifact_can_name_every_route_not_proven(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "production-override-crawl"
            root.mkdir()
            (root / "production-override-crawl-state.json").write_text(
                json.dumps({"routes": {"/seen": {"http_status": 503, "error_class": "HTTP_ERROR"}}}),
                encoding="utf-8",
            )
            failures = resumable_stage_runner._failed_routes(Path(tmp), ["/seen", "/not-attempted"])
            self.assertEqual({"/seen", "/not-attempted"}, {item["route"] for item in failures})
            self.assertEqual("HTTP_ERROR", next(item["error_class"] for item in failures if item["route"] == "/seen"))
            self.assertEqual("NOT_CRAWLED", next(item["error_class"] for item in failures if item["route"] == "/not-attempted"))

    def test_build_has_one_export_call_and_remote_stage_cannot_rebuild_or_deploy(self):
        build_source = inspect.getsource(publisher_runner.main)
        self.assertEqual(1, build_source.count("export_content(snapshot_path)"))
        remote_source = inspect.getsource(resumable_stage_runner.run_remote)
        self.assertIn("verify_proof_bundle", remote_source)
        self.assertIn("active_deployment", remote_source)
        for forbidden in ("fetch_public_content_revision", "export_complete", "upload_version", "deploy_pair"):
            self.assertNotIn(forbidden, remote_source)

    def test_workflow_has_independent_timeouts_and_keeps_schedule_check_only(self):
        workflow = Path(".github/workflows/mahoon-static-publisher.yml").read_text(encoding="utf-8")
        self.assertIn("BUILD_AND_ZERO_PERCENT, REMOTE_PROOF, PROMOTE_AND_VALIDATE", workflow)
        self.assertIn("timeout-minutes: 45", workflow)
        self.assertIn("timeout-minutes: 60", workflow)
        self.assertIn("timeout-minutes: 20", workflow)
        self.assertIn("timeout-minutes: 10", workflow)
        self.assertIn("vars.PUBLISHER_MODE_SCHEDULED != 'PUBLISH'", workflow)
        self.assertIn("vars.PUBLISHER_MODE_SCHEDULED == 'PUBLISH'", workflow)
        self.assertIn("github.event_name == 'schedule' && (vars.PUBLISHER_MODE_SCHEDULED == 'PUBLISH' && 'PUBLISH' || 'CHECK_ONLY')", workflow)
        self.assertNotIn("vars.PUBLISHER_MODE_SCHEDULED || 'PUBLISH'", workflow)
        self.assertIn("path: ${{ runner.temp }}/proof-bundle", workflow)
        self.assertIn("path: ${{ runner.temp }}/remote-proof", workflow)
        self.assertIn("path: ${{ runner.temp }}/production-result", workflow)

    def test_remote_failure_logger_prints_sanitized_json_to_stderr(self):
        source = inspect.getsource(resumable_stage_runner.main)
        self.assertIn('print(json.dumps({"stage": args.stage, "failure": type(exc).__name__ + ": " + _safe_failure(exc)}), file=sys.stderr)', source)
        self.assertNotIn('json.dumps({"stage": args.stage, "failure": type(exc).__name__ + ": " + _safe_failure(exc)}, file=sys.stderr)', source)
        self.assertEqual("token=[REDACTED]", resumable_stage_runner._safe_failure(Exception("token=secret")))

    def test_promotion_state_requires_successful_matching_production_result(self):
        transaction, digest = self._bundle()
        result = {"contract": "MAHOON_PRODUCTION_RESULT_V1", "PASS": True,
                  "transaction_id": transaction["transaction_id"],
                  "candidate_version": transaction["candidate_static_version"], "bundle_sha256": digest}
        verify_production_result(result, transaction, digest)
        result["PASS"] = False
        with self.assertRaisesRegex(ValueError, "production result"):
            verify_production_result(result, transaction, digest)

    def _bundle(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "bundle"
        create_proof_bundle(root, transaction=self.tx, routes=self.routes,
                            media_manifest=self.media, media_index=self.index,
                            seal=self.seal, local_evidence=self.evidence,
                            posts=self.posts)
        transaction, digest = verify_proof_bundle(root)
        return transaction, digest


if __name__ == "__main__":
    unittest.main()
