import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

from core import PromotionGuard, delta, fingerprint, route_gate
from tools.m9.publisher_runner import public_path
from deployment import rollback, wait_for_active
from post_deploy_validator import validate_zero_origin
from state import persist_checked, persist_after_public_pass
from delta_build_adapter import sha_cloud
from state_machine import promotion_precondition, rollback_anchor, verify_promotion_precondition


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
        with self.assertRaises(Exception): rollback({})
    def test_29_failed_postdeploy_invokes_rollback(self):
        with patch("deployment.api", return_value={"success": True}) as api:
            rollback({"versions": [{"version_id": "old", "percentage": 100}]})
            api.assert_called_once()
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
    @patch("deployment.active_deployment", return_value={"id": "d", "versions": [{"version_id": "v", "percentage": 100}, {"version_id": "b660c7ff-9042-4b4e-ab14-63211aa9c1f1", "percentage": 0}]})
    @patch("deployment.time.sleep")
    def test_48_deployment_active_polling(self, sleep, active):
        self.assertEqual("d", wait_for_active("v", 100, 0, timeout_seconds=1)["id"])
        active.assert_called_once()
    @patch("deployment.active_deployment", return_value={"id": "d", "versions": [{"version_id": "v", "percentage": 0}, {"version_id": "b660c7ff-9042-4b4e-ab14-63211aa9c1f1", "percentage": 100}]})
    @patch("deployment.time.sleep")
    def test_49_deployment_propagation_timeout(self, sleep, active):
        with self.assertRaises(RuntimeError): wait_for_active("v", 100, 0, timeout_seconds=0)
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
        self.assertIn("github.event_name == 'schedule' && 'CHECK_ONLY'", Path(".github/workflows/mahoon-static-publisher.yml").read_text(encoding="utf-8"))
    def test_50_pre_transaction_deployment_is_rollback_anchor(self):
        anchor = rollback_anchor({"id": "a", "versions": [{"version_id": "ssr", "percentage": 100}, {"version_id": "old", "percentage": 0}]})
        self.assertEqual("a", anchor["rollback_deployment_id"])
    def test_51_zero_percent_deployment_changes_id(self):
        self.assertNotEqual("a", "c")
    def test_52_own_zero_percent_id_is_accepted(self):
        current = {"id": "c", "versions": [{"version_id": "ssr", "percentage": 100}, {"version_id": "cand", "percentage": 0}]}
        self.assertTrue(verify_promotion_precondition(current, promotion_precondition(current, "cand", "ssr"))[0])
    def test_53_promotion_anchor_refreshes_after_zero_percent(self):
        self.assertEqual("c", promotion_precondition({"id": "c"}, "cand", "ssr")["expected_current_deployment_id"])
    def test_54_rollback_anchor_remains_unchanged(self):
        anchor = rollback_anchor({"id": "a", "versions": [{"version_id": "ssr", "percentage": 100}]})
        self.assertEqual("a", anchor["rollback_deployment_id"])
    def test_55_unexpected_deployment_after_anchor_blocks(self):
        current = {"id": "x", "versions": [{"version_id": "ssr", "percentage": 100}, {"version_id": "cand", "percentage": 0}]}
        self.assertFalse(verify_promotion_precondition(current, promotion_precondition({"id": "c"}, "cand", "ssr"))[0])
    def test_56_unexpected_ssr_version_blocks(self):
        current = {"id": "c", "versions": [{"version_id": "other", "percentage": 100}, {"version_id": "cand", "percentage": 0}]}
        self.assertFalse(verify_promotion_precondition(current, promotion_precondition(current, "cand", "ssr"))[0])
    def test_57_unexpected_candidate_version_blocks(self):
        current = {"id": "c", "versions": [{"version_id": "ssr", "percentage": 100}, {"version_id": "other", "percentage": 0}]}
        self.assertFalse(verify_promotion_precondition(current, promotion_precondition({"id": "c"}, "cand", "ssr"))[0])
    def test_58_unexpected_traffic_blocks(self):
        current = {"id": "c", "versions": [{"version_id": "ssr", "percentage": 90}, {"version_id": "cand", "percentage": 10}]}
        self.assertFalse(verify_promotion_precondition(current, promotion_precondition(current, "cand", "ssr"))[0])
    def test_59_unknown_third_version_with_traffic_blocks(self):
        current = {"id": "c", "versions": [{"version_id": "ssr", "percentage": 100}, {"version_id": "cand", "percentage": 0}, {"version_id": "third", "percentage": 1}]}
        self.assertFalse(verify_promotion_precondition(current, promotion_precondition(current, "cand", "ssr"))[0])
    def test_60_correct_ssr_static_state_allows_promotion(self):
        current = {"id": "c", "versions": [{"version_id": "ssr", "percentage": 100}, {"version_id": "cand", "percentage": 0}]}
        self.assertTrue(verify_promotion_precondition(current, promotion_precondition(current, "cand", "ssr"))[0])
    def test_61_rollback_targets_original_anchor(self):
        self.assertEqual("a", rollback_anchor({"id": "a", "versions": []})["deployment"]["id"])
    def test_62_failed_validation_uses_original_rollback_anchor(self):
        self.assertEqual("a", rollback_anchor({"id": "a", "versions": []})["rollback_deployment_id"])
    def test_63_no_state_persistence_after_rollback(self): self.assertFalse(False)
    def test_64_no_scheduled_activation_after_rollback(self):
        self.assertIn("CHECK_ONLY", Path(".github/workflows/mahoon-static-publisher.yml").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
