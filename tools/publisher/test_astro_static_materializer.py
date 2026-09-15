from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from publisher import astro_static_materializer as materializer


class AstroStaticMaterializerTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "Cloudflare preview fixture runs in the Linux CI runtime")
    def test_materializes_a_fixture_snapshot_without_snapshot_api(self) -> None:
        locked = materializer.PROJECT / "src" / "generated" / "locked-published-content.json"
        original = locked.read_bytes()
        previous = os.environ.copy()
        try:
            with tempfile.TemporaryDirectory(prefix="mahoon-direct-snapshot-") as directory:
                root = Path(directory)
                snapshot = root / "snapshot.json"
                routes = root / "routes.json"
                output = root / "site"
                astro_output = root / "astro"
                snapshot.write_text(json.dumps({
                    "contract": "POSTS_FULL_PUBLIC_SNAPSHOT_V2",
                    "snapshot_total_count": 1,
                    "payload": {"posts": [{
                        "id": 1,
                        "slug": "fixture-post",
                        "text": "مطلب آزمایشی #شعر",
                        "created_at": "2026-09-15 00:00:00",
                        "media_type": None,
                    }]},
                }, ensure_ascii=False), encoding="utf-8")
                routes.write_text(json.dumps({"routes": [
                    "/", "/posts", "/category/شعر و متن", "/post/fixture-post", "/rss.xml", "/sitemap.xml",
                ]}, ensure_ascii=False), encoding="utf-8")
                os.environ.update({
                    "MAHOON_PUBLISHED_CONTENT_SNAPSHOT": str(snapshot),
                    "MAHOON_ROUTE_MANIFEST": str(routes),
                    "MAHOON_ASTRO_OUT_DIR": str(astro_output),
                })
                result = materializer.build(output)
                self.assertEqual(result["snapshot_api_starts"], 0)
                self.assertEqual(result["snapshot_binding"], "DIRECT_LOCKED_SNAPSHOT")
                self.assertTrue((output / "index.html").is_file())
                self.assertTrue((output / "post" / "fixture-post" / "index.html").is_file())
        finally:
            locked.write_bytes(original)
            os.environ.clear()
            os.environ.update(previous)


if __name__ == "__main__":
    unittest.main()
