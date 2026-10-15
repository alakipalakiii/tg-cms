from __future__ import annotations

import json
import hashlib
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from publisher import astro_static_materializer as materializer


class AstroStaticMaterializerTests(unittest.TestCase):
    def test_repeated_media_uses_the_verified_immutable_digest_without_rereading_blob(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            out = root / 'site'; out.mkdir()
            data = b'fixture' * 10000
            digest = hashlib.sha256(data).hexdigest()
            public = '/media/' + digest + '.jpg'
            blob = root / (digest + '.jpg'); blob.write_bytes(data)
            manifest_path = root / 'manifest.json'
            manifest_path.write_text(json.dumps({'records': [{'source_identifier': 'fixture', 'sha256': digest,
                'immutable_path': public, 'fallback': False, 'detected_mime': 'image/jpeg',
                'expected_media_type': 'photo', 'post_ids': [1]}]}), encoding='utf-8')
            index = root / 'index.json'; index.write_text('{"entries":[]}', encoding='utf-8')
            resolver = materializer.PublishedMediaResolver()
            resolver.manifest, resolver.index_path, resolver.store = manifest_path, index, root
            cache, manifest, reads = {}, {}, []
            original = Path.read_bytes
            def read(path):
                if path == blob: reads.append(path)
                return original(path)
            html = '<img src="https://api.mahoonartmagazine.ir/media/fixture">'
            with patch.object(Path, 'read_bytes', read):
                for _ in range(10):
                    self.assertEqual('<img src="' + public + '">', materializer._materialize_media(
                        html, out, manifest, cache, threading.Lock(), resolver))
            self.assertEqual(len(reads), 1)
            self.assertEqual(manifest[public]['mahoon_sha256'], digest)
            self.assertEqual(manifest[public]['cloudflare_hash'], digest[:32])
            self.assertEqual(manifest[public]['size'], len(data))
            self.assertEqual((out / public.lstrip('/')).read_bytes(), data)

    def test_static_archive_preserves_public_config_and_replaces_api_runtime(self):
        html = ('<script id="archiveConfig" type="application/json">'
                '{"apiBase":"https://api.mahoonartmagazine.ir","mode":"category","category":"book",'
                '"pageSize":20,"initialNextOffset":40,"initialHasMore":true}</script>'
                '<script>fetch("https://api.mahoonartmagazine.ir/public/posts-v1")</script>')
        result = materializer._strip_runtime_api_scripts(html, "/category/book/page/2")
        self.assertIn('"initialNextOffset": 40', result)
        self.assertIn('"category": "book"', result)
        self.assertIn('src="/mahoon-static-archive.js"', result)
        self.assertNotIn("apiBase", result)
        self.assertNotIn("api.mahoonartmagazine.ir", result)
        self.assertEqual(html, materializer._strip_runtime_api_scripts(html, "/admin"))

    def test_static_home_search_gets_client_without_api_runtime(self):
        html = '<body><input id="mSearch"><script>fetch("https://api.mahoonartmagazine.ir")</script></body>'
        result = materializer._strip_runtime_api_scripts(html, "/")
        self.assertIn('src="/mahoon-static-archive.js"', result)
        self.assertNotIn("api.mahoonartmagazine.ir", result)

    def test_static_category_reuses_exact_tags_including_audio_books(self):
        config = json.dumps({"apiBase": "https://api.mahoonartmagazine.ir", "mode": "category", "category": "صوتی"})
        html = '<script id="archiveConfig" type="application/json">' + config + '</script>'
        result = materializer._strip_runtime_api_scripts(html, "/category/audio")
        public = json.loads(result.split(">", 1)[1].split("</script>", 1)[0])
        self.assertIn("کتاب گویا", public["category_tags"])
        self.assertIn("کتابگویا", public["category_tags"])
        self.assertIn("صوتی", public["category_tags"])

    def test_full_materializer_uses_direct_dispatch_not_preview_fetch(self):
        source = __import__("inspect").getsource(materializer.build)
        self.assertIn("_DirectWorkerRenderer", source)
        self.assertNotIn("_fetch_preview_html", source)
        self.assertIn('media_manifest.update(json.loads(resolver.manifest.read_text', source)

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
                publisher_base = root / "publisher-base"
                publisher_base.mkdir()
                (publisher_base / "_redirects").write_text("", encoding="utf-8")
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
                })
                with patch.object(materializer, "BASE", publisher_base):
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
