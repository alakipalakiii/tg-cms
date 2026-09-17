import json
import os
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

from static_build_adapter import build, validate
from state import persist_after_public_pass
from tools.publisher.astro_static_materializer import _artifact_path


class PublisherAdapterTests(unittest.TestCase):
    def filesystem_gate(self, body: str, routes: list[str] | None = None):
        with tempfile.TemporaryDirectory(prefix="mahoon-filesystem-gate-") as directory:
            root = Path(directory)
            manifest = root / "routes.json"
            route = "/post/1"
            manifest.write_text(json.dumps({"routes": routes or [route]}), encoding="utf-8")
            target = root / "post" / "1" / "index.html"
            target.parent.mkdir(parents=True)
            target.write_text(body, encoding="utf-8")
            previous = os.environ.get("MAHOON_ROUTE_MANIFEST")
            os.environ["MAHOON_ROUTE_MANIFEST"] = str(manifest)
            try:
                return validate(root)
            finally:
                if previous is None:
                    os.environ.pop("MAHOON_ROUTE_MANIFEST", None)
                else:
                    os.environ["MAHOON_ROUTE_MANIFEST"] = previous

    def test_filesystem_gate_catches_missing_html(self):
        result = self.filesystem_gate('<link rel="canonical" href="https://mahoonartmagazine.ir/post/1"><script type="application/ld+json">{}</script>', ["/post/1", "/post/missing"])
        self.assertFalse(result["PASS"])
        self.assertEqual(result["missing_html"], 1)

    def test_filesystem_gate_catches_missing_jsonld(self):
        result = self.filesystem_gate('<link rel="canonical" href="https://mahoonartmagazine.ir/post/1">')
        self.assertFalse(result["PASS"])
        self.assertEqual(result["post_jsonld_missing"], 1)

    def test_filesystem_gate_catches_api_media_dependency(self):
        result = self.filesystem_gate('<link rel="canonical" href="https://mahoonartmagazine.ir/post/1"><script type="application/ld+json">{"image":"https://api.mahoonartmagazine.ir/media/x"}</script>')
        self.assertFalse(result["PASS"])
        self.assertGreater(result["remote_reader_media_dependencies"], 0)

    def test_filesystem_gate_catches_workers_dev_canonical_leak(self):
        result = self.filesystem_gate('<link rel="canonical" href="https://example.workers.dev/post/1"><script type="application/ld+json">{}</script>')
        self.assertFalse(result["PASS"])
        self.assertEqual(result["workers_dev_canonical_leaks"], 1)

    def test_strict_filesystem_gate_catches_missing_media_and_duplicate_canonical(self):
        with tempfile.TemporaryDirectory(prefix="mahoon-strict-gate-") as directory:
            root = Path(directory)
            manifest = root / "routes.json"
            routes = ["/post/1", "/post/2"]
            manifest.write_text(json.dumps({
                "contract": "CURRENT_CANDIDATE_SEALED_ROUTE_MANIFEST_V1",
                "routes": routes,
            }), encoding="utf-8")
            body = '<link rel="canonical" href="https://mahoonartmagazine.ir/post/1"><a href="/post/missing">broken</a><script type="application/ld+json">{"image":"/media/missing.jpg"}</script>'
            for route in routes:
                target = root / route.lstrip("/") / "index.html"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(body, encoding="utf-8")
            previous = os.environ.get("MAHOON_ROUTE_MANIFEST")
            os.environ["MAHOON_ROUTE_MANIFEST"] = str(manifest)
            try:
                result = validate(root)
            finally:
                if previous is None:
                    os.environ.pop("MAHOON_ROUTE_MANIFEST", None)
                else:
                    os.environ["MAHOON_ROUTE_MANIFEST"] = previous
            self.assertFalse(result["PASS"])
            self.assertEqual(result["duplicate_canonicals"], 1)
            self.assertEqual(result["static_media_missing"], 1)
            self.assertGreater(result["broken_internal_links"], 0)

    def test_encoded_tag_route_maps_to_unicode_static_file_and_internal_category(self):
        with tempfile.TemporaryDirectory(prefix="mahoon-encoded-route-") as directory:
            root = Path(directory)
            tag_route = "/tag/" + quote("کتاب_گویا", safe="-_.!~*'()")
            category_route = "/category/نقاشی"
            manifest = root / "routes.json"
            manifest.write_text(json.dumps({
                "contract": "CURRENT_CANDIDATE_SEALED_ROUTE_MANIFEST_V1",
                "routes": [tag_route, category_route],
            }), encoding="utf-8")
            tag_file = _artifact_path(root, tag_route)
            category_file = _artifact_path(root, category_route)
            canonical_safe = "/%:@!$&'()*+,;=-._~"
            tag_file.parent.mkdir(parents=True)
            category_file.parent.mkdir(parents=True)
            tag_file.write_text(
                f'<link rel="canonical" href="https://mahoonartmagazine.ir{quote(tag_route, safe=canonical_safe)}"><a href="{category_route}">category</a>',
                encoding="utf-8",
            )
            category_file.write_text(
                f'<link rel="canonical" href="https://mahoonartmagazine.ir{quote(category_route, safe=canonical_safe)}">',
                encoding="utf-8",
            )
            previous = os.environ.get("MAHOON_ROUTE_MANIFEST")
            os.environ["MAHOON_ROUTE_MANIFEST"] = str(manifest)
            try:
                result = validate(root)
            finally:
                if previous is None:
                    os.environ.pop("MAHOON_ROUTE_MANIFEST", None)
                else:
                    os.environ["MAHOON_ROUTE_MANIFEST"] = previous
            self.assertTrue(result["PASS"], json.dumps(result, ensure_ascii=True))
            self.assertEqual(result["present_html_routes"], 2)
            self.assertEqual(result["broken_internal_links"], 0)

    def test_approved_text_contract_is_self_contained(self):
        base = Path("publisher-base")
        self.assertTrue((base / "_headers").exists())
        self.assertTrue((base / "_redirects").exists())
        self.assertTrue((base / "search" / "search-index.json").exists())
        self.assertFalse(any(p.suffix.lower() in {".mp3", ".mp4", ".jpg", ".png", ".webp"} for p in base.rglob("*")))

    def test_metadata_manifest_has_immutable_media_proof(self):
        data = json.loads(Path("publisher-state/production-media-manifest.json").read_text(encoding="utf-8"))
        media = {k: v for k, v in data.items() if k.startswith("/media/")}
        # The accepted P0-closed media manifest contains six additional immutable
        # entries compared with the older 489-entry fixture.
        self.assertEqual(len(media), 495)
        self.assertTrue(all(len(v["mahoon_sha256"]) == 64 and len(v["cloudflare_hash"]) == 32 for v in media.values()))

    def test_local_build_route_and_unicode_gate(self):
        with tempfile.TemporaryDirectory(prefix="mahoon-adapter-") as directory:
            out = Path(directory) / "build"
            build(out)
            result = validate(out)
            self.assertTrue(result["PASS"])
            self.assertEqual(result["missing_html"], 0)
            self.assertEqual(result["post_jsonld_missing"], 0)

    def test_state_persistence_requires_public_pass(self):
        with self.assertRaises(RuntimeError):
            persist_after_public_pass(Path("publisher-test-state"), {"x.json": {"x": 1}}, False)


if __name__ == "__main__":
    unittest.main()
