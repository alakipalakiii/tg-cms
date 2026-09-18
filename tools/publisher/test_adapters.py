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

    def assert_current_media_manifest(self, data: dict, index: dict):
        self.assertEqual(data.get("contract"), "CURRENT_MEDIA_RESOLUTION_V1")
        records = data.get("records")
        stats = data.get("stats")
        self.assertIsInstance(records, list)
        self.assertIsInstance(stats, dict)

        for key in ("required_distinct", "published", "new", "fallback", "unresolved"):
            self.assertIs(type(stats.get(key)), int, key)
            self.assertGreaterEqual(stats[key], 0, key)
        self.assertEqual(stats["required_distinct"], len(records))
        self.assertGreater(stats["required_distinct"], 0)
        self.assertEqual(stats["unresolved"], 0)
        self.assertEqual(stats["published"] + stats["new"] + stats["fallback"], stats["required_distinct"])

        source_ids = []
        fallback_count = 0
        immutable_count = 0
        for record in records:
            self.assertIsInstance(record, dict)
            source_id = record.get("source_identifier")
            self.assertIsInstance(source_id, str)
            self.assertTrue(source_id.strip())
            source_ids.append(source_id)
            self.assertIsInstance(record.get("post_ids"), list)
            self.assertTrue(all(type(post_id) is int and post_id > 0 for post_id in record["post_ids"]))
            self.assertIs(type(record.get("fallback")), bool)
            if record["fallback"]:
                fallback_count += 1
                self.assertIsInstance(record.get("fallback_reason"), str)
                self.assertTrue(record["fallback_reason"].strip())
                continue

            immutable_count += 1
            immutable_path = record.get("immutable_path")
            sha256 = record.get("sha256")
            mime = record.get("mime")
            self.assertIsInstance(immutable_path, str)
            self.assertTrue(immutable_path.startswith("/media/"))
            self.assertIsInstance(sha256, str)
            self.assertRegex(sha256, r"\A[0-9a-f]{64}\Z")
            path = Path(immutable_path)
            self.assertEqual(path.stem, sha256)
            self.assertEqual(path.parts[-2], sha256[:2])
            self.assertIsInstance(mime, str)
            self.assertTrue(mime.strip())
            if "detected_mime" in record:
                self.assertEqual(record["detected_mime"], mime)

        self.assertEqual(len(source_ids), len(set(source_ids)))
        self.assertEqual(fallback_count, stats["fallback"])
        self.assertEqual(immutable_count, stats["published"] + stats["new"])

        self.assertEqual(index.get("contract"), "IMMUTABLE_MEDIA_INDEX_V1")
        entries = index.get("entries")
        self.assertIsInstance(entries, list)
        entries_by_source = {}
        for entry in entries:
            self.assertIsInstance(entry, dict)
            source_id = entry.get("source_identifier")
            if source_id:
                self.assertNotIn(source_id, entries_by_source)
                entries_by_source[source_id] = entry
        for record in records:
            if record["fallback"]:
                continue
            indexed = entries_by_source.get(record["source_identifier"])
            self.assertIsNotNone(indexed, record["source_identifier"])
            for key in ("immutable_path", "sha256", "mime"):
                self.assertEqual(indexed.get(key), record.get(key), record["source_identifier"])

    @staticmethod
    def current_media_fixture():
        sha256 = "a" * 64
        immutable_path = f"/media/{sha256[:2]}/{sha256}.jpg"
        immutable = {
            "source_identifier": "fixture-photo-1",
            "post_ids": [101],
            "immutable_path": immutable_path,
            "sha256": sha256,
            "mime": "image/jpeg",
            "detected_mime": "image/jpeg",
            "media_type": "photo",
            "fallback": False,
        }
        same_content = {**immutable, "source_identifier": "fixture-photo-2", "post_ids": [102]}
        fallback = {
            "source_identifier": "fixture-fallback",
            "post_ids": [103],
            "fallback": True,
            "fallback_reason": "SOURCE_HTTP_404",
        }
        records = [immutable, same_content, fallback]
        manifest = {
            "contract": "CURRENT_MEDIA_RESOLUTION_V1",
            "records": records,
            "stats": {
                "required_distinct": len(records),
                "published": 1,
                "new": 1,
                "fallback": 1,
                "unresolved": 0,
            },
        }
        index = {
            "contract": "IMMUTABLE_MEDIA_INDEX_V1",
            "entries": [
                {key: item[key] for key in ("source_identifier", "immutable_path", "sha256", "mime")}
                for item in records[:2]
            ],
        }
        return manifest, index

    def test_metadata_manifest_has_immutable_media_proof(self):
        data = json.loads(Path("publisher-state/production-media-manifest.json").read_text(encoding="utf-8"))
        index = json.loads(Path("publisher-state/immutable-media-index.json").read_text(encoding="utf-8"))
        self.assert_current_media_manifest(data, index)

    def test_current_media_resolution_v1_synthetic_fixture(self):
        manifest, index = self.current_media_fixture()
        self.assert_current_media_manifest(manifest, index)
        self.assertEqual(manifest["stats"]["required_distinct"], len(manifest["records"]))
        self.assertNotIn("immutable_path", manifest["records"][-1])
        self.assertNotIn("sha256", manifest["records"][-1])

    def test_current_media_resolution_v1_rejects_contract_violations(self):
        cases = (
            ("manifest-index mismatch", self._mutate_media_index_mismatch),
            ("invalid SHA-256", self._mutate_media_invalid_sha),
            ("wrong immutable path shard", self._mutate_media_wrong_shard),
            ("unresolved media", self._mutate_media_unresolved),
            ("duplicate source identifier", self._mutate_media_duplicate_source),
            ("incorrect accounting", self._mutate_media_incorrect_accounting),
        )
        for label, mutate in cases:
            with self.subTest(label=label):
                manifest, index = self.current_media_fixture()
                mutate(manifest, index)
                with self.assertRaises(AssertionError):
                    self.assert_current_media_manifest(manifest, index)

    @staticmethod
    def _mutate_media_index_mismatch(manifest: dict, index: dict):
        index["entries"][0]["mime"] = "image/png"

    @staticmethod
    def _mutate_media_invalid_sha(manifest: dict, index: dict):
        manifest["records"][0]["sha256"] = "g" * 64

    @staticmethod
    def _mutate_media_wrong_shard(manifest: dict, index: dict):
        immutable_path = manifest["records"][0]["immutable_path"]
        wrong_path = "/media/bb/" + immutable_path.rsplit("/", 1)[-1]
        manifest["records"][0]["immutable_path"] = wrong_path
        index["entries"][0]["immutable_path"] = wrong_path

    @staticmethod
    def _mutate_media_unresolved(manifest: dict, index: dict):
        manifest["stats"]["unresolved"] = 1

    @staticmethod
    def _mutate_media_duplicate_source(manifest: dict, index: dict):
        manifest["records"].append(dict(manifest["records"][-1]))
        manifest["stats"]["required_distinct"] = len(manifest["records"])
        manifest["stats"]["fallback"] += 1

    @staticmethod
    def _mutate_media_incorrect_accounting(manifest: dict, index: dict):
        manifest["stats"]["new"] -= 1

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
