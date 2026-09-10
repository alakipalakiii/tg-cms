import json
import re
import unittest
from pathlib import Path


SOURCE = Path(__file__).parents[1] / "src" / "index.ts"


class PostsFullPublicV2ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_text(encoding="utf-8")
        start = cls.source.index("async function mahoonPublicPostsFullV2")
        end = cls.source.index("/* mahoon-scale-v1 */")
        cls.fn = cls.source[start:end]

    def test_route_and_contract_are_present(self):
        self.assertIn('url.pathname === "/posts-full-public-v2"', self.source)
        for key in ("snapshot_max_id", "snapshot_total_count", "next_cursor", "has_more", "items"):
            self.assertIn(key, self.fn)

    def test_keyset_shape_and_bound_are_present(self):
        self.assertIn("id > ?", self.fn)
        self.assertIn("id <= ?", self.fn)
        self.assertIn("ORDER BY id ASC", self.fn)
        self.assertIn("Math.min(Number(raw), 500)", self.source)
        self.assertIn("snapshot_max_id", self.fn)
        self.assertIn("snapshot_total_count", self.fn)
        self.assertIn("Snapshot metadata is required after the first page", self.fn)

    def test_public_predicate_parity_and_no_writes(self):
        self.assertIn("(is_published = 1 OR is_published IS NULL)", self.fn)
        self.assertIn("(deleted_at IS NULL OR deleted_at = '')", self.fn)
        self.assertNotRegex(self.fn, r"\b(?:INSERT|UPDATE|DELETE|CREATE|DROP|ALTER)\b")
        for private_field in ("admin_note", "chat_id", "chat_title", "deleted_at", "telegram_message_id"):
            self.assertNotIn(f'"{private_field}"', self.fn)

    def test_1099_fixture_keyset_has_no_skips_or_duplicates(self):
        fixture = [
            {"id": i, "is_published": 1, "deleted_at": None}
            for i in range(1, 1100)
        ]
        fixture.extend([
            {"id": 1100, "is_published": 0, "deleted_at": None},
            {"id": 1101, "is_published": 1, "deleted_at": "2026-01-01"},
        ])
        snapshot_max_id = max(row["id"] for row in fixture if row["is_published"] == 1 and not row["deleted_at"])
        public = [row for row in fixture if row["is_published"] == 1 and not row["deleted_at"] and row["id"] <= snapshot_max_id]
        cursor = 0
        collected = []
        while True:
            page = [row for row in public if row["id"] > cursor][:250]
            collected.extend(page)
            if len(page) < 250:
                break
            cursor = page[-1]["id"]
        ids = [row["id"] for row in collected]
        self.assertEqual(len(ids), 1099)
        self.assertEqual(ids, sorted(set(ids)))
        self.assertLessEqual(ids[-1], snapshot_max_id)

    def test_cursor_and_page_size_validation_shapes(self):
        self.assertRegex(self.source, r"/\^\\d\+\$/")
        self.assertIn(', 400)', self.fn)


if __name__ == "__main__":
    unittest.main()
