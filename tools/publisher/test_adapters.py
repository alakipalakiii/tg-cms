import json
import unittest
from pathlib import Path

from static_build_adapter import build, validate
from state import persist_after_public_pass


class PublisherAdapterTests(unittest.TestCase):
    def test_approved_text_contract_is_self_contained(self):
        base = Path("publisher-base")
        self.assertTrue((base / "_headers").exists())
        self.assertTrue((base / "_redirects").exists())
        self.assertTrue((base / "search" / "search-index.json").exists())
        self.assertFalse(any(p.suffix.lower() in {".mp3", ".mp4", ".jpg", ".png", ".webp"} for p in base.rglob("*")))

    def test_metadata_manifest_has_immutable_media_proof(self):
        data = json.loads(Path("publisher-state/production-media-manifest.json").read_text(encoding="utf-8"))
        media = {k: v for k, v in data.items() if k.startswith("/media/")}
        self.assertEqual(len(media), 489)
        self.assertTrue(all(len(v["mahoon_sha256"]) == 64 and len(v["cloudflare_hash"]) == 32 for v in media.values()))

    def test_local_build_route_and_unicode_gate(self):
        out = Path("publisher-test-adapter-build")
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
