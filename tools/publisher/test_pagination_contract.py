from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from candidate_route_manifest import build_candidate_route_manifest
from pagination_contract import PAGE_SIZE, page_count


def _posts(count: int, *, category: str | None = None) -> list[dict]:
    return [
        {
            "id": index + 1,
            "slug": f"post-{index + 1}",
            "created_at": f"2026-09-{(index // 28) + 1:02d}T{(index % 28):02d}:00:00Z",
            "text": f"unique-{index + 1}" + (f" #{category}" if category else ""),
            "media_unique_id": f"media-{index + 1}",
        }
        for index in range(count)
    ]


def _manifest(posts: list[dict]) -> dict:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        accepted = root / "accepted.json"
        output = root / "candidate.json"
        accepted.write_text(json.dumps({"routes": []}), encoding="utf-8")
        return build_candidate_route_manifest(posts, accepted, output)


class PaginationContractTests(unittest.TestCase):
    def test_global_boundaries(self):
        for count, expected_last in ((20, 1), (21, 2), (40, 2), (41, 3)):
            routes = _manifest(_posts(count))["routes"]
            self.assertEqual(page_count(count), expected_last)
            self.assertIn("/posts", routes)
            for number in range(2, expected_last + 1):
                self.assertIn(f"/posts/page/{number}", routes)
            self.assertNotIn(f"/posts/page/{expected_last + 1}", routes)

    def test_category_boundaries(self):
        for count, expected_last in ((20, 1), (21, 2), (40, 2), (41, 3)):
            routes = _manifest(_posts(count, category="نقاشی"))["routes"]
            self.assertIn("/category/نقاشی", routes)
            for number in range(2, expected_last + 1):
                self.assertIn(f"/category/نقاشی/page/{number}", routes)
            self.assertNotIn(f"/category/نقاشی/page/{expected_last + 1}", routes)

    def test_duplicate_source_rows_do_not_inflate_page_count(self):
        posts = _posts(20)
        posts.append({
            **posts[0],
            "id": 999,
            "slug": "duplicate-source-row",
            "created_at": "2026-09-01T00:05:00Z",
        })
        routes = _manifest(posts)["routes"]
        self.assertNotIn("/posts/page/2", routes)

    def test_astro_archive_page_size_remains_twenty(self):
        source = Path("website/dreary-disk/src/pages/posts.astro").read_text(encoding="utf-8")
        self.assertIn("const PAGE_SIZE = 20;", source)
        self.assertEqual(PAGE_SIZE, 20)


if __name__ == "__main__":
    unittest.main()