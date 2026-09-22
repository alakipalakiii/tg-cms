from __future__ import annotations

import json
import inspect
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
            "measured_local_gates": {"measured": True, "PASS": True,
                                     "gates": {"media": {
                                         "SEALED_MEDIA_INVENTORY": {"measured": True, "PASS": True},
                                         "SEMANTIC_TO_SEALED_MEDIA_PARITY": {"measured": True, "PASS": True},
                                     }}},
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
        self.assertLess(build_source.index("fetch_public_content_revision()"), build_source.index("static_build_adapter.build(out, snapshot_path)"))
        remote_source = inspect.getsource(resumable_stage_runner.run_remote)
        self.assertIn("verify_proof_bundle", remote_source)
        self.assertIn("active_deployment", remote_source)
        for forbidden in ("fetch_public_content_revision", "export_complete", "upload_version", "deploy_pair"):
            self.assertNotIn(forbidden, remote_source)

    def test_workflow_has_independent_timeouts_and_keeps_schedule_check_only(self):
        workflow = Path(".github/workflows/mahoon-static-publisher.yml").read_text(encoding="utf-8")
        transaction_job = workflow.split("  build-and-zero-percent:", 1)[1].split("  remote-proof:", 1)[0]
        promotion_job = workflow.split("  promote-and-validate:", 1)[1].split("  persist-state:", 1)[0]
        self.assertIn("BUILD_AND_ZERO_PERCENT, REMOTE_PROOF, PROMOTE_AND_VALIDATE", workflow)
        self.assertIn("timeout-minutes: 45", workflow)
        self.assertIn("timeout-minutes: 60", workflow)
        self.assertIn("timeout-minutes: 60", promotion_job)
        self.assertNotIn("timeout-minutes: 20", promotion_job)
        self.assertIn("timeout-minutes: 10", workflow)
        self.assertIn("vars.PUBLISHER_MODE_SCHEDULED != 'PUBLISH'", workflow)
        self.assertIn("vars.PUBLISHER_MODE_SCHEDULED == 'PUBLISH'", workflow)
        self.assertIn("needs.scheduled-policy-preflight.outputs.publish_allowed == 'true'", workflow)
        self.assertNotIn("vars.PUBLISHER_MODE_SCHEDULED || 'PUBLISH'", workflow)
        self.assertNotIn("Build website from the pinned transaction snapshot", workflow)
        self.assertNotIn("run: npm run build --prefix website/dreary-disk", transaction_job)
        self.assertIn("path: ${{ runner.temp }}/proof-bundle", workflow)
        self.assertIn("path: ${{ runner.temp }}/remote-proof", workflow)
        self.assertIn("path: ${{ runner.temp }}/production-result", workflow)

    def test_stale_schedule_event_uses_execution_main_sha(self):
        event_sha = "a" * 40
        execution_sha = "b" * 40
        with patch.dict(os.environ, {"GITHUB_SHA": event_sha, "MAHOON_EXECUTION_SHA": ""}, clear=False), \
             patch.object(publisher_runner, "subprocess") as subprocess_mock:
            subprocess_mock.run.return_value.stdout = execution_sha + "\n"
            source_sha, observed_event_sha = publisher_runner.execution_source_identity()
        self.assertEqual(execution_sha, source_sha)
        self.assertEqual(event_sha, observed_event_sha)

    def test_scheduled_workflow_uses_staggered_slots_and_latest_main(self):
        workflow = Path(".github/workflows/mahoon-static-publisher.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "17,47 * * * *"', workflow)
        checkout_expr = "ref: " + chr(36) + "{{ (github.event_name == 'schedule' || (github.event_name == 'workflow_dispatch' && inputs.mode == 'AUTO_TICK')) && 'main' || github.ref }}"
        self.assertEqual(2, workflow.count(checkout_expr))
        self.assertIn("SCHEDULE_EVENT_SHA=$GITHUB_SHA", workflow)
        self.assertIn("EXECUTION_MAIN_SHA=$execution_sha", workflow)
        self.assertIn("MAHOON_EXECUTION_SHA=$execution_sha", workflow)

    def test_promotion_timeout_budgets_include_rollback_reserve(self):
        workflow = Path(".github/workflows/mahoon-static-publisher.yml").read_text(encoding="utf-8")
        promotion_job = workflow.split("  promote-and-validate:", 1)[1].split("  persist-state:", 1)[0]
        timeout_line = next(line for line in promotion_job.splitlines()
                            if "timeout-minutes:" in line)
        job_seconds = int(timeout_line.split(":", 1)[1].strip()) * 60
        crawl_seconds = resumable_stage_runner.PRODUCTION_FULL_CRAWL_TIMEOUT_SECONDS
        browser_seconds = resumable_stage_runner.PRODUCTION_BROWSER_GATE_TIMEOUT_SECONDS
        reserve_seconds = 600
        self.assertEqual(3600, job_seconds)
        self.assertEqual(2400, crawl_seconds)
        self.assertEqual(300, browser_seconds)
        self.assertGreaterEqual(reserve_seconds, 600)
        self.assertGreater(job_seconds, crawl_seconds + browser_seconds + reserve_seconds)

    def test_production_validation_success_within_budget_does_not_rollback(self):
        result, rollback, crawl, browser = self._run_promotion_validation("success")
        self.assertEqual(0, result["exit_code"])
        self.assertTrue(result["production"]["PASS"])
        rollback.assert_not_called()
        self.assertEqual(2400, crawl.call_args.kwargs["timeout"])
        self.assertEqual(300, browser.call_args.kwargs["timeout"])

    def test_production_crawl_internal_timeout_rolls_back(self):
        result, rollback, crawl, browser = self._run_promotion_validation("crawl-timeout")
        self.assertEqual(1, result["exit_code"])
        self.assertTrue(result["production"]["rollback_performed"])
        self.assertTrue(result["production"]["rollback_verified"])
        rollback.assert_called_once()
        self.assertEqual(2400, crawl.call_args.kwargs["timeout"])
        browser.assert_not_called()

    def test_production_browser_timeout_rolls_back(self):
        result, rollback, crawl, browser = self._run_promotion_validation("browser-timeout")
        self.assertEqual(1, result["exit_code"])
        self.assertTrue(result["production"]["rollback_performed"])
        self.assertTrue(result["production"]["rollback_verified"])
        rollback.assert_called_once()
        self.assertEqual(2400, crawl.call_args.kwargs["timeout"])
        self.assertEqual(300, browser.call_args.kwargs["timeout"])

    def _run_promotion_validation(self, scenario):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        bundle_dir = root / "bundle"
        create_proof_bundle(bundle_dir, transaction=self.tx, routes=self.routes,
                            media_manifest=self.media, media_index=self.index,
                            seal=self.seal, local_evidence=self.evidence, posts=self.posts)
        proof_dir = root / "proof"
        proof_dir.mkdir()
        bundle_transaction, bundle_sha = verify_proof_bundle(bundle_dir)
        (proof_dir / "remote-proof-result.json").write_text(json.dumps({
            "contract": "MAHOON_REMOTE_PROOF_RESULT_V1",
            "REMOTE_PROOF_PASS": True,
            "transaction_id": bundle_transaction["transaction_id"],
            "candidate_version": bundle_transaction["candidate_static_version"],
            "bundle_sha256": bundle_sha,
        }), encoding="utf-8")

        fake_root = root / "repo"
        state_dir = fake_root / "publisher-state"
        state_dir.mkdir(parents=True)
        (state_dir / "published-static-state.json").write_text(json.dumps({
            "current_version_type": "STATIC",
            "current_version": self.tx["baseline_static_version"],
        }), encoding="utf-8")
        evidence_dir = root / "evidence"

        baseline = {"id": "baseline-deployment", "versions": [
            {"version_id": "baseline-v1", "percentage": 100},
            {"version_id": "candidate-v1", "percentage": 0},
        ]}
        promoted = {"id": "promoted-deployment", "versions": [
            {"version_id": "candidate-v1", "percentage": 100},
            {"version_id": "baseline-v1", "percentage": 0},
        ]}
        restored = {"id": "restored-deployment", "versions": [
            {"version_id": "baseline-v1", "percentage": 100},
            {"version_id": "candidate-v1", "percentage": 0},
        ]}
        crawl = patch.object(resumable_stage_runner, "_crawl")
        browser = patch.object(resumable_stage_runner, "_browser_gate")
        convergence = patch.object(resumable_stage_runner, "_production_version_convergence", return_value={
            "PASS": True, "rounds": 3, "seconds": 20, "mismatches": [],
        })
        crawl_summary = {
            "measured": True, "expected_route_count": 7, "present_route_count": 7,
            "missing_routes": [], "post_jsonld_missing": 0, "duplicate_canonicals": 0,
            "workers_dev_leaks": 0, "remote_reader_media_dependencies": 0,
            "robots_sitemap_directive": True,
            "remote_crawler_version_pinning": {
                "PASS": True, "attribution_required": "YES", "override_sent": "NO",
            },
            "gates": {key: {"measured": True, "PASS": True} for key in (
                "remote_route_parity", "remote_content_parity", "remote_listing_uniqueness",
                "remote_category_parity", "remote_latest_parity", "remote_seo", "remote_media",
            )},
        }
        browser_summary = {
            "zero_origin": {"PASS": True, "requests": {
                "content_api": 0, "media_api": 0, "workers_dev_content": 0,
                "telegram": 0, "search_backend": 0,
            }},
            "visual": {"PASS": True},
            "checks": [{"name": "admin-shell", "visual_pass": True}],
        }
        crawl_state = evidence_dir / "production-crawl" / "production-override-crawl"
        crawl_state.mkdir(parents=True)
        (crawl_state / "production-override-crawl-state.json").write_text(json.dumps({
            "routes": {
                "/rss.xml": {"http_status": 200, "content_type": "application/rss+xml"},
                "/admin": {"http_status": 200},
                "/admin/analytics": {"http_status": 200},
            },
        }), encoding="utf-8")

        active = patch.object(resumable_stage_runner, "_active_deployment_with_retry",
                              side_effect=[baseline, promoted])
        rollback = patch.object(resumable_stage_runner, "automatic_rollback", return_value=restored)
        with patch.object(resumable_stage_runner, "ROOT", fake_root), \
             patch.object(resumable_stage_runner, "EVIDENCE", evidence_dir), \
             patch.object(resumable_stage_runner, "_head_sha", return_value=self.tx["source_sha"]), \
             patch.dict(os.environ, {"MAHOON_PUBLISH_READY": "YES"}), \
             patch.object(resumable_stage_runner.deployment, "deploy_pair",
                          return_value={"id": "promoted-deployment"}), \
             patch.object(resumable_stage_runner.deployment, "wait_for_active", return_value=promoted), \
             convergence, active, rollback as rollback_mock, crawl as crawl_mock, browser as browser_mock:
            crawl_mock.side_effect = (subprocess.TimeoutExpired("crawl", 2400)
                                      if scenario == "crawl-timeout" else None)
            if scenario != "crawl-timeout":
                crawl_mock.return_value = crawl_summary
            browser_mock.side_effect = (subprocess.TimeoutExpired("browser", 300)
                                        if scenario == "browser-timeout" else None)
            if scenario != "browser-timeout":
                browser_mock.return_value = browser_summary
            exit_code = resumable_stage_runner.run_promotion(
                bundle_dir, proof_dir, self.tx["transaction_id"])
            production = json.loads((evidence_dir / "production-result.json").read_text(encoding="utf-8"))
        return {"exit_code": exit_code, "production": production}, rollback_mock, crawl_mock, browser_mock

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
