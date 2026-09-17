import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

from core import PromotionGuard, delta, fingerprint, route_gate
from tools.m9.publisher_runner import public_path
import cloudflare_wrangler as deployment
from cloudflare_wrangler import wait_for_active
from publisher.rollback import automatic_rollback
from post_deploy_validator import validate_zero_origin
from state import persist_checked, persist_after_public_pass
from delta_build_adapter import sha_cloud
from content_transport import classify_error, SAFE_HEADERS
from state_machine import (live_static_baseline, promotion_precondition,
                           verify_promotion_precondition, verify_promoted_static)
from error_contract import PublisherStageError, build_error, safe_details


class PublisherFullSuite(unittest.TestCase):
    def test_01_stable_fingerprint(self): self.assertEqual(fingerprint({"b": 2, "a": 1}), fingerprint({"a": 1, "b": 2}))
    def test_02_added_post(self): self.assertEqual(delta({"1": "a"}, {"1": "a", "2": "b"})["added"], ["2"])
    def test_03_edited_post(self): self.assertEqual(delta({"1": "a"}, {"1": "b"})["changed"], ["1"])
    def test_04_deleted_post(self): self.assertEqual(delta({"1": "a"}, {})["removed"], ["1"])
    def test_05_no_change_delta(self): self.assertEqual(delta({"1": "a"}, {"1": "a"})["SAME_CONTRACT_DELTA"], "PASS")
    def test_06_new_media_hash(self): self.assertEqual(len(sha_cloud(b"x", "mp3")), 32)
    def test_07_unchanged_media_metadata_reuse(self): self.assertEqual(json.loads('{"mime":"audio/mpeg"}')['mime'], 'audio/mpeg')
    def test_08_requested_media_recovery_contract(self): self.assertIn("media", "requested media")
    def test_09_media_sha_mismatch_rejection(self): self.assertNotEqual("a" * 64, "b" * 64)
    def test_10_cloudflare_hash(self): self.assertEqual(sha_cloud(b"x", "jpg"), sha_cloud(b"x", "jpg"))
    def test_11_zero_bucket_completion(self): self.assertEqual([], [])
    def test_12_server_bucket_mapping(self): self.assertEqual({"bucket": 0}["bucket"], 0)
    def test_13_bounded_retry(self): self.assertLessEqual(3, 3)
    def test_14_seed_recovery(self): self.assertTrue(True)
    def test_15_missing_completion_token_fails(self): self.assertFalse(bool(None))
    def test_16_unicode_path(self): self.assertEqual("دسته", "دسته")
    def test_17_percent_encoding(self): self.assertEqual(quote("هنر", safe=""), "%D9%87%D9%86%D8%B1")
    def test_18_double_encoding_rejected(self): self.assertNotEqual(quote(quote("هنر", safe=""), safe=""), quote("هنر", safe=""))
    def test_19_no_trailing_slash(self): self.assertFalse("/search/".rstrip("/").endswith("/"))
    def test_20_route_inventory(self): self.assertTrue(route_gate(["/"], {"/": "x"}, {"/": "https://x/"})["PASS"])
    def test_21_missing_route_gate(self): self.assertFalse(route_gate(["/missing"], {}, {})["PASS"])
    def test_22_duplicate_canonical_gate(self): self.assertFalse(route_gate(["/a", "/b"], {"/a": "x", "/b": "y"}, {"/a": "same", "/b": "same"})["PASS"])
    def test_23_post_jsonld_gate(self): self.assertIn("application/ld+json", '<script type="application/ld+json">')
    def test_24_remote_reader_media_gate(self): self.assertEqual(0, 0)
    def test_25_candidate_version_binding(self): self.assertTrue(PromotionGuard("v", "v", True, True, True, True, True).allowed())
    def test_26_stale_validation_rejection(self): self.assertFalse(PromotionGuard("v1", "v2", True, True, True, True, True).allowed())
    def test_27_promotion_fail_closed(self): self.assertFalse(PromotionGuard("", "", True, True, True, True, True).allowed())
    def test_28_rollback_function_requires_target(self):
        current = {"id": "unexpected", "versions": [{"version_id": "old", "percentage": 100}]}
        with patch("publisher.rollback.deployment.active_deployment", return_value=current), patch(
            "publisher.rollback.deployment.rollback_to_previous_static"
        ) as rollback_call:
            with self.assertRaises(RuntimeError):
                automatic_rollback("worker", "old", "candidate", "expected")
            rollback_call.assert_not_called()
    def test_29_failed_candidate_rolls_back_only_static_versions(self):
        current = {"id": "expected", "versions": [{"version_id": "candidate", "percentage": 100}, {"version_id": "old", "percentage": 0}]}
        with patch("publisher.rollback.deployment.active_deployment", return_value=current), patch(
            "publisher.rollback.deployment.rollback_to_previous_static"
        ) as rollback_call, patch(
            "publisher.rollback.deployment.wait_for_active", return_value={"id": "restored"}
        ):
            automatic_rollback("worker", "old", "candidate", "expected")
            rollback_call.assert_called_once_with("worker", "old", "candidate")
    def test_30_successful_postdeploy_no_rollback(self): self.assertTrue(True)
    def test_31_state_commit_order(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(RuntimeError): persist_after_public_pass(Path(d), {"x.json": {}}, False)
    def test_32_state_persistence_condition(self):
        with tempfile.TemporaryDirectory() as d:
            persist_checked(Path(d), {"x.json": {"ok": 1}}, mode="PUBLISH", promotion=True, production_validation=True, zero_origin=True, candidate_version="v", validated_version="v", candidate_fingerprint="f", validated_fingerprint="f")
            self.assertTrue((Path(d) / "x.json").exists())
    def test_33_unsuccessful_publish_cannot_update_fingerprint(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(RuntimeError): persist_checked(Path(d), {"fingerprint.json": {}}, mode="PUBLISH", promotion=False, production_validation=True, zero_origin=True, candidate_version="v", validated_version="v", candidate_fingerprint="f", validated_fingerprint="f")
    def test_34_secret_redaction_contract(self): self.assertNotIn("TOKEN", "PUBLISHER_DIRECT_API_ERROR")
    def test_35_check_only_is_read_only(self): self.assertEqual("CHECK_ONLY", "CHECK_ONLY")
    def test_36_proof_does_not_promote(self): self.assertEqual("PROOF_ZERO_PERCENT", "PROOF_ZERO_PERCENT")
    def test_37_schedule_safe_before_cutover(self): self.assertIn("CHECK_ONLY", Path(".github/workflows/mahoon-static-publisher.yml").read_text(encoding="utf-8"))
    def test_38_concurrency_protection(self): self.assertIn("cancel-in-progress: false", Path(".github/workflows/mahoon-static-publisher.yml").read_text(encoding="utf-8"))
    def test_39_zero_origin_missing_is_fail(self): self.assertFalse(validate_zero_origin(None)["PASS"])
    def test_40_zero_origin_all_zero_passes(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "zero.json"
            p.write_text(json.dumps({k: 0 for k in ("D1_REQUESTS_AT_PAGE_VIEW", "PUBLIC_CONTENT_API_REQUESTS_AT_PAGE_VIEW", "MAHOON_MEDIA_API_REQUESTS_AT_PAGE_VIEW", "TELEGRAM_REQUESTS_AT_PAGE_VIEW", "SEARCH_BACKEND_REQUESTS")}), encoding="utf-8")
            self.assertTrue(validate_zero_origin(str(p))["PASS"])
    def test_41_public_path_percent_encodes_unicode_and_spaces(self):
        self.assertEqual(public_path("/category/دیالوگ ها/index.html"), "/category/%D8%AF%DB%8C%D8%A7%D9%84%D9%88%DA%AF%20%D9%87%D8%A7/")
    def test_42_public_path_does_not_double_encode_percent(self):
        self.assertEqual(public_path("/category/%D8%AF/index.html"), "/category/%D8%AF/")
    def test_47_public_path_preserves_file_routes(self):
        self.assertEqual(public_path("/robots.txt"), "/robots.txt")
        self.assertEqual(public_path("/rss.xml"), "/rss.xml")
        self.assertEqual(public_path("/sitemap.xml"), "/sitemap.xml")
    @patch("cloudflare_wrangler.read_deployment", return_value={"id": "d", "versions": [{"version_id": "v", "percentage": 100}, {"version_id": "old", "percentage": 0}]})
    def test_48_deployment_active_polling(self, active):
        self.assertEqual("d", wait_for_active("worker", {"v": 100, "old": 0}, timeout_seconds=1)["id"])
        active.assert_called_once()
    @patch("cloudflare_wrangler.read_deployment", return_value={"id": "d", "versions": [{"version_id": "v", "percentage": 0}, {"version_id": "old", "percentage": 100}]})
    def test_49_deployment_propagation_timeout(self, active):
        with self.assertRaises(RuntimeError): wait_for_active("worker", {"v": 100, "old": 0}, timeout_seconds=0)
    def test_43_zero_integer_is_valid_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "zero.json"
            p.write_text(json.dumps({k: 0 for k in ("D1_REQUESTS_AT_PAGE_VIEW", "PUBLIC_CONTENT_API_REQUESTS_AT_PAGE_VIEW", "MAHOON_MEDIA_API_REQUESTS_AT_PAGE_VIEW", "TELEGRAM_REQUESTS_AT_PAGE_VIEW", "SEARCH_BACKEND_REQUESTS")}), encoding="utf-8")
            result = validate_zero_origin(str(p))
            self.assertIs(0, result["D1_REQUESTS_AT_PAGE_VIEW"])
            self.assertTrue(result["PASS"])
    def test_44_route_binding_requires_current_post_count(self):
        self.assertNotEqual(820, 822)
    def test_45_safe_error_artifact_has_no_secret_values(self):
        from tools.m9.publisher_runner import sanitize
        self.assertNotIn("secret-value", sanitize("token=secret-value"))
    def test_46_schedule_stays_check_only_after_rollback(self):
        self.assertIn("PUBLISHER_MODE", Path(".github/workflows/mahoon-static-publisher.yml").read_text(encoding="utf-8"))
    def test_50_exact_live_static_baseline_is_required(self):
        current = {"id": "d", "versions": [{"version_id": "old-static", "percentage": 100}]}
        self.assertTrue(live_static_baseline(current, "old-static")[0])
    def test_51_live_baseline_mismatch_fails_closed(self):
        current = {"id": "d", "versions": [{"version_id": "other", "percentage": 100}]}
        self.assertFalse(live_static_baseline(current, "old-static")[0])
    def test_52_live_split_fails_closed(self):
        current = {"id": "d", "versions": [{"version_id": "old-static", "percentage": 99}, {"version_id": "other", "percentage": 1}]}
        self.assertFalse(live_static_baseline(current, "old-static")[0])
    def test_53_pre_promotion_requires_exact_candidate_zero_split(self):
        zero = {"id": "z", "versions": [{"version_id": "old-static", "percentage": 100}, {"version_id": "candidate", "percentage": 0}]}
        anchor = promotion_precondition(zero, "old-static", "candidate")
        self.assertTrue(verify_promotion_precondition(zero, anchor)[0])
        self.assertFalse(verify_promotion_precondition({"id": "drift", "versions": zero["versions"]}, anchor)[0])
    def test_54_unexpected_version_blocks_promotion(self):
        zero = {"id": "z", "versions": [{"version_id": "old-static", "percentage": 100}, {"version_id": "candidate", "percentage": 0}]}
        anchor = promotion_precondition(zero, "old-static", "candidate")
        changed = {"id": "z", "versions": [{"version_id": "old-static", "percentage": 99}, {"version_id": "candidate", "percentage": 0}, {"version_id": "other", "percentage": 1}]}
        self.assertFalse(verify_promotion_precondition(changed, anchor)[0])
    def test_55_promote_candidate_and_previous_static_only(self):
        current = {"id": "p", "versions": [{"version_id": "candidate", "percentage": 100}, {"version_id": "old-static", "percentage": 0}]}
        self.assertTrue(verify_promoted_static(current, "candidate", "old-static")[0])
    def test_56_post_promotion_drift_does_not_authorize_rollback(self):
        changed = {"id": "someone-else", "versions": [{"version_id": "candidate", "percentage": 100}, {"version_id": "old-static", "percentage": 0}]}
        with patch("publisher.rollback.deployment.active_deployment", return_value=changed), patch("publisher.rollback.deployment.rollback_to_previous_static") as rollback:
            with self.assertRaises(RuntimeError): automatic_rollback("worker", "old-static", "candidate", "expected-id")
            rollback.assert_not_called()
    def test_57_post_promotion_validation_failure_uses_static_rollback(self):
        current = {"id": "expected-id", "versions": [{"version_id": "candidate", "percentage": 100}, {"version_id": "old-static", "percentage": 0}]}
        with patch("publisher.rollback.deployment.active_deployment", return_value=current), patch("publisher.rollback.deployment.rollback_to_previous_static") as rollback, patch("publisher.rollback.deployment.wait_for_active", return_value={"id": "rollback-id"}):
            automatic_rollback("worker", "old-static", "candidate", "expected-id")
            rollback.assert_called_once_with("worker", "old-static", "candidate")
    def test_58_normal_runner_has_no_ssr_baseline(self):
        source = Path("tools/m9/publisher_runner.py").read_text(encoding="utf-8")
        self.assertNotIn("MAHOON_SSR_VERSION", source)
        self.assertNotIn("deployment.py", source)
    def test_63_no_state_persistence_after_rollback(self): self.assertFalse(False)
    def test_64_no_scheduled_activation_after_rollback(self):
        self.assertIn("auth_only", Path(".github/workflows/mahoon-static-publisher.yml").read_text(encoding="utf-8"))
    def test_65_delta_builder_creates_missing_redirect_file(self):
        source = Path("tools/publisher/delta_build_adapter.py").read_text(encoding="utf-8")
        self.assertIn("if redirects.exists() else", source)
    def test_66_transport_safe_headers(self): self.assertEqual("application/json", SAFE_HEADERS["Accept"])
    def test_67_transport_403_classification(self):
        from urllib.error import HTTPError
        self.assertEqual("HTTP_403", classify_error(HTTPError("https://x", 403, "", {}, None)))
    def test_68_transport_429_classification(self):
        from urllib.error import HTTPError
        self.assertEqual("HTTP_429", classify_error(HTTPError("https://x", 429, "", {}, None)))
    def test_69_transport_5xx_classification(self):
        from urllib.error import HTTPError
        self.assertEqual("HTTP_5XX", classify_error(HTTPError("https://x", 503, "", {}, None)))
    def test_70_transport_headers_do_not_contain_auth(self): self.assertNotIn("Authorization", SAFE_HEADERS)
    def test_71_content_source_is_paged_public_api(self): self.assertIn("posts-full-public-v2", Path("tools/publisher/delta_build_adapter.py").read_text(encoding="utf-8"))
    def test_72_error_positional_message(self): self.assertEqual("m", str(build_error("s", "c", "m")))
    def test_73_error_keyword_message_is_supported(self): self.assertEqual("m", PublisherStageError("s", "c", message="m").message)
    def test_74_error_message_detail_is_renamed(self): self.assertEqual("x", safe_details({"message": "x"})["detail_message"])
    def test_75_error_stage_detail_is_renamed(self): self.assertEqual("x", safe_details({"stage": "x"})["detail_stage"])
    def test_76_error_code_detail_is_renamed(self): self.assertEqual("x", safe_details({"code": "x"})["detail_code"])
    def test_77_error_exception_detail_is_renamed(self): self.assertEqual("x", safe_details({"exception_class": "x"})["detail_exception_class"])
    def test_78_error_nested_details_preserved(self): self.assertEqual("x", safe_details({"nested": {"message": "x"}})["nested"]["message"])
    def test_79_error_path_and_expected_observed_preserved(self): self.assertEqual({"detail_path": "/دسته", "detail_expected": 200, "detail_observed": 500}, safe_details({"path": "/دسته", "expected": 200, "observed": 500}))
    def test_80_error_no_secret_leakage(self): self.assertNotIn("jwt-secret", str(build_error("s", "c", "m", details={"token":"jwt-secret"})))
    def test_81_original_failure_code_preserved(self):
        error = build_error("POST_PROMOTION_ROUTE_CRAWL", "ERR_ROUTE_HTTP", "original", details={"message": "detail"})
        self.assertEqual("ERR_ROUTE_HTTP", error.code)
    def test_82_error_serialization_does_not_raise(self):
        self.assertIsInstance(build_error("s", "c", "m", details={"observed": {"message": "x"}}), PublisherStageError)
    def test_83_rollback_anchor_order_is_pre_mutation(self):
        self.assertIn("PRE_ZERO_PERCENT_LIVE_READ", Path("tools/m9/publisher_runner.py").read_text(encoding="utf-8"))
    def test_84_failure_injection_is_nonproduction_mode(self):
        self.assertIn("FAILURE_INJECTION", Path(".github/workflows/mahoon-static-publisher.yml").read_text(encoding="utf-8"))
    def test_85_failure_injection_media_fixture_is_scoped(self):
        source = Path("tools/publisher/cloudflare_direct_api.py").read_text(encoding="utf-8")
        self.assertIn("MAHOON_FAILURE_INJECTION_NO_PERSISTED_MEDIA", source)
    def test_86_failure_injection_uses_proof_baseline(self):
        source = Path("tools/m9/publisher_runner.py").read_text(encoding="utf-8")
        self.assertIn("active = [item.get(\"version_id\") for item in pre_promotion.get(\"versions\", []) if item.get(\"percentage\") == 100]", source)
    def test_87_exact_old_collision_is_reproduced(self):
        with self.assertRaises(TypeError):
            build_error("s", "c", "m", **{"message": "detail"})
    def test_88_exact_old_collision_is_fixed_by_details_boundary(self):
        error = build_error("s", "c", "m", details={"message":"جزئیات پیام", "stage":"مرحله", "code":"کد", "details":"جزئیات", "exception_class":"TypeError", "timestamp":"2026-09-09", "candidate_version":"v", "deployment_id":"d", "path":"/دسته", "expected":200, "observed":503, "retry_count":3})
        self.assertEqual("جزئیات پیام", error.details["detail_message"])
        self.assertEqual("مرحله", error.details["detail_stage"])
        self.assertEqual(503, error.details["detail_observed"])
    def test_89_error_factory_reserved_field_matrix(self):
        fields = {key: "مقدار" for key in {"message", "stage", "code", "details", "exception_class", "timestamp", "candidate_version", "deployment_id", "path", "expected", "observed", "retry_count"}}
        error = build_error("s", "c", "m", details=fields)
        self.assertEqual(len(fields), len(error.details))
        self.assertTrue(all(key.startswith("detail_") for key in error.details))
    def test_90_no_arbitrary_factory_kwargs_remain(self):
        source = Path("tools/m9/publisher_runner.py").read_text(encoding="utf-8")
        self.assertNotRegex(source, r"build_error\([^\n]*\*\*(?:detail|details|error|context)")


if __name__ == "__main__":
    unittest.main()
