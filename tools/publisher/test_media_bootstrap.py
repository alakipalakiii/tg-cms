from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import media_bootstrap


JPEG = b"\xff\xd8\xff\xe0" + b"fixture-media"


def post(post_id: int, media: str = "media-1") -> dict:
    return {"id": post_id, "media_file_id": media, "media_type": "photo"}


class MediaBootstrapTests(unittest.TestCase):
    def run_bootstrap(self, posts: list[dict], index: dict, fetch):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index_path = root / "index.json"
            index_path.write_text(json.dumps(index), encoding="utf-8")
            with patch.object(media_bootstrap, "_fetch", side_effect=fetch):
                result = media_bootstrap.bootstrap(posts, index_path=index_path, store=root / "store", output_manifest=root / "manifest.json", output_index=root / "next-index.json")
            return result, json.loads((root / "manifest.json").read_text(encoding="utf-8")), json.loads((root / "next-index.json").read_text(encoding="utf-8"))

    def test_clean_runner_bootstraps_existing_media_from_static(self):
        digest = hashlib.sha256(JPEG).hexdigest()
        index = {"contract": "IMMUTABLE_MEDIA_INDEX_V1", "entries": [{"source_identifier": "media-1", "immutable_path": f"/media/{digest[:2]}/{digest}.jpg", "sha256": digest, "mime": "image/jpeg", "media_type": "photo", "fallback": False}]}
        calls = []
        def fetch(url): calls.append(url); return JPEG, "image/jpeg"
        result, manifest, _next = self.run_bootstrap([post(1)], index, fetch)
        self.assertEqual(result["published"], 1)
        self.assertEqual(result["new"], 0)
        self.assertTrue(calls[0].startswith("https://mahoonartmagazine.ir/media/"))
        self.assertEqual(manifest["records"][0]["sha256"], digest)

    def test_hash_mismatch_fails_closed(self):
        index = {"entries": [{"source_identifier": "media-1", "immutable_path": "/media/aa/bad.jpg", "sha256": "a" * 64, "mime": "image/jpeg"}]}
        with self.assertRaisesRegex(media_bootstrap.MediaBootstrapError, "SHA256_MISMATCH"):
            self.run_bootstrap([post(1)], index, lambda _url: (JPEG, "image/jpeg"))

    def test_html_masquerading_as_image_fails_closed(self):
        with self.assertRaisesRegex(media_bootstrap.MediaBootstrapError, "INVALID_SIGNATURE"):
            self.run_bootstrap([post(1)], {"entries": []}, lambda _url: (b"<html>error</html>", "text/html"))

    def test_new_shared_media_is_acquired_once(self):
        calls = []
        def fetch(url): calls.append(url); return JPEG, "image/jpeg"
        result, manifest, next_index = self.run_bootstrap([post(1), post(2)], {"entries": []}, fetch)
        self.assertEqual(result["required_distinct"], 1)
        self.assertEqual(result["new"], 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(manifest["records"][0]["post_ids"], [1, 2])
        self.assertEqual(len(next_index["entries"]), 1)

    def test_permanent_new_source_unavailability_uses_fallback(self):
        from urllib.error import HTTPError
        def fetch(url): raise HTTPError(url, 404, "missing", {}, None)
        result, manifest, _next = self.run_bootstrap([post(1)], {"entries": []}, fetch)
        self.assertEqual(result["fallback"], 1)
        self.assertTrue(manifest["records"][0]["fallback"])

    def test_machine_local_runner_evidence_is_not_required(self):
        digest = hashlib.sha256(JPEG).hexdigest()
        index = {"entries": [{"source_identifier": "media-1", "immutable_path": f"/media/{digest[:2]}/{digest}.jpg", "sha256": digest, "mime": "image/jpeg"}]}
        result, _manifest, _next = self.run_bootstrap([post(1)], index, lambda _url: (JPEG, "image/jpeg"))
        self.assertEqual(result["unresolved"], 0)


if __name__ == "__main__":
    unittest.main()
