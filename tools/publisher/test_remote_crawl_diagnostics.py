import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.publisher import candidate_override_crawl as crawl


class RemoteCrawlDiagnosticsTests(unittest.TestCase):
    def test_post_route_identity_resolves_numeric_and_encoded_slug_ids(self):
        by_slug = {"معنا زندگی": 32, "meaning-of-life": 1840}
        by_id = {"32": 32, "1840": 1840}

        self.assertEqual(("NUMERIC_POST", 32), crawl._post_route_identity("/post/32", by_slug, by_id))
        self.assertEqual(
            ("SLUG_POST", 1840),
            crawl._post_route_identity("/post/meaning-of-life", by_slug, by_id),
        )
        self.assertEqual(
            ("SLUG_POST", 32),
            crawl._post_route_identity("/post/%D9%85%D8%B9%D9%86%D8%A7%20%D8%B2%D9%86%D8%AF%DA%AF%DB%8C",
                                       by_slug, by_id),
        )
        self.assertEqual(("OTHER", None), crawl._post_route_identity("/category/books", by_slug, by_id))

    def test_failed_id_ranges_are_sorted_unique_and_exact(self):
        self.assertEqual(
            [{"start": 32, "end": 34, "count": 3}, {"start": 39, "end": 39, "count": 1},
             {"start": 41, "end": 42, "count": 2}],
            crawl._integer_ranges([42, 34, 32, 33, 39, 41, 39]),
        )
        self.assertEqual([], crawl._integer_ranges([]))

    def test_canonical_sample_binds_to_seal_and_local_filesystem_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            local_path = root / "local-evidence.json"
            seal_path = root / "artifact-seal.json"
            local_path.write_text(json.dumps({
                "filesystem_gate": {
                    "PASS": True, "expected_html_routes": 1, "present_html_routes": 1,
                    "missing_html": 0, "canonical_mismatches": 0,
                },
                "measured_local_gates": {
                    "measured": True, "PASS": True, "gates": {"seo": {"PASS": True}},
                },
            }), encoding="utf-8")
            seal_path.write_text(json.dumps({
                "contract": "MAHOON_STATIC_ARTIFACT_SEAL_V1",
                "artifact_sha256": "seal-id", "artifact_tree_sha256": "tree-id",
            }), encoding="utf-8")
            with patch.object(crawl, "LOCAL_EVIDENCE_PATH", local_path), \
                 patch.object(crawl, "ARTIFACT_SEAL_PATH", seal_path), \
                 patch.object(crawl, "VERSION", "candidate-version"), \
                 patch.object(crawl, "BASE", "https://mahoonartmagazine.ir"):
                sample = crawl._canonical_failure_sample(
                    "/post/meaning-of-life",
                    {
                        "canonical": "https://mahoonartmagazine.ir/post/32",
                        "http_status": 200,
                        "final_url": "https://mahoonartmagazine.ir/post/meaning-of-life",
                        "actual_version": "candidate-version",
                        "cf_cache_status": "DYNAMIC",
                        "body_sha256": "body-hash",
                        "redirect_chain": [],
                    },
                    {"meaning-of-life": 32}, {"32": 32}, ["/post/meaning-of-life"],
                )

        self.assertEqual("SLUG_POST", sample["route_type"])
        self.assertEqual(32, sample["logical_post_id"])
        self.assertEqual("https://mahoonartmagazine.ir/post/meaning-of-life", sample["expected_canonical"])
        self.assertEqual("https://mahoonartmagazine.ir/post/32", sample["actual_canonical"])
        self.assertTrue(sample["sealed_static_route_exists"])
        self.assertEqual(sample["expected_canonical"], sample["sealed_static_canonical"])
        self.assertEqual("seal-id", sample["sealed_static_artifact_sha256"])
        self.assertFalse(sample["sealed_static_html_retained_for_byte_comparison"])

    def test_attribution_samples_classify_worker_first_and_direct_assets(self):
        patterns = ("/post/*", "/robots.txt")
        page = crawl._attribution_failure_sample(
            "/post/meaning-of-life",
            {"http_status": 200, "actual_version": "wrong", "content_type": "text/html",
             "is_html": True, "redirect_chain": [], "cf_cache_status": "DYNAMIC"},
            {"meaning-of-life": 32}, {"32": 32}, patterns,
        )
        asset = crawl._attribution_failure_sample(
            "/_astro/site.css",
            {"http_status": 200, "actual_version": None, "content_type": "text/css",
             "is_html": False, "redirect_chain": [], "cf_cache_status": "HIT"},
            {}, {}, patterns,
        )

        self.assertEqual("SLUG_POST", page["route_type"])
        self.assertEqual(32, page["logical_post_id"])
        self.assertEqual("HTML_PAGE", page["route_class"])
        self.assertTrue(page["attribution_required"])
        self.assertEqual("STATIC_ASSET", asset["route_class"])
        self.assertFalse(asset["worker_first_route"])
        self.assertFalse(asset["attribution_required"])
        self.assertEqual("HIT", asset["cf_cache_status"])

    def test_sample_selection_is_deterministic_and_bounded(self):
        records = [{"id": value} for value in range(100)]
        selected = crawl._evenly_spaced(records, 20)
        self.assertEqual(20, len(selected))
        self.assertEqual(0, selected[0]["id"])
        self.assertEqual(99, selected[-1]["id"])
        self.assertEqual(selected, crawl._evenly_spaced(records, 20))


if __name__ == "__main__":
    unittest.main()
