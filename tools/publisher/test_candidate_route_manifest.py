from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from candidate_route_manifest import build_candidate_route_manifest


class CandidateRouteManifestTests(unittest.TestCase):
    def test_preserves_old_routes_and_adds_numeric_and_slug_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            accepted = root / "accepted.json"
            output = root / "candidate.json"
            accepted.write_text(json.dumps({"routes": ["/", "/post/1", "/post/old-slug"]}), encoding="utf-8")
            result = build_candidate_route_manifest([
                {"id": 1, "slug": "new-slug"}, {"id": 2, "slug": "two-slug"}
            ], accepted, output)
            self.assertEqual(result["old_routes_missing_from_candidate"], [])
            self.assertEqual(result["new_snapshot_routes"], ["/post/2", "/post/new-slug", "/post/two-slug"])
            self.assertEqual(result["route_count"], 13)
            self.assertEqual(result["snapshot_post_route_count"], 4)
            self.assertEqual(result["snapshot_derived_route_count"], 4)
            self.assertEqual(result["required_control_routes"], ["/admin", "/admin/analytics"])
            self.assertEqual(result["snapshot_tag_route_count"], 0)
            self.assertIn("/category/نقاشی", result["routes"])

    def test_candidate_never_silently_shrinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            accepted = root / "accepted.json"
            output = root / "candidate.json"
            accepted.write_text(json.dumps({"routes": ["/post/1", "/post/legacy"]}), encoding="utf-8")
            result = build_candidate_route_manifest([{ "id": 2, "slug": "two" }], accepted, output)
            self.assertEqual(result["old_routes_missing_from_candidate"], [])
            self.assertIn("/post/legacy", result["old_only_routes"])
            self.assertEqual(result["control_route_count"], 2)
            self.assertEqual(result["route_count"], 11)

    def test_snapshot_tags_become_encoded_routes_and_all_taxonomy_routes_are_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            accepted = root / "accepted.json"
            output = root / "candidate.json"
            accepted.write_text(json.dumps({"routes": ["/"]}), encoding="utf-8")
            result = build_candidate_route_manifest([
                {"id": 1, "slug": "one", "text": "#کتاب_گویا #John_Lennon"},
                {"id": 2, "slug": "two", "text": "#کتاب_گویا #هنر"},
            ], accepted, output)
            self.assertEqual(result["snapshot_tag_route_count"], 3)
            self.assertEqual(result["new_snapshot_tag_routes_missing_from_candidate"], [])
            self.assertIn("/tag/%DA%A9%D8%AA%D8%A7%D8%A8_%DA%AF%D9%88%DB%8C%D8%A7", result["routes"])
            self.assertIn("/tag/John_Lennon", result["routes"])
            self.assertIn("/category/نقاشی", result["routes"])


if __name__ == "__main__":
    unittest.main()
