from __future__ import annotations

import unittest
import fnmatch
import json
from email.message import Message
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from tools.publisher.remote_proof_harness import (
    cache_busted_url, category_page_matches,
    classify_link_target, link_contract_fails, request_with_version_pinning,
)


class _Response:
    def __init__(self, status: int, headers: dict[str, str] | None = None, body: bytes = b""):
        self.status = status
        self.headers = Message()
        for key, value in (headers or {}).items():
            self.headers[key] = value
        self.body = body

    def getcode(self):
        return self.status

    def read(self):
        return self.body

    def close(self):
        pass


class _Opener:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request)
        return next(self.responses)


class RemoteProofHarnessTests(unittest.TestCase):
    def test_version_override_is_reapplied_after_same_origin_redirect(self):
        version = "candidate-v2"
        opener = _Opener([
            _Response(307, {"Location": "/post/32", "X-Mahoon-Worker-Version": version}),
            _Response(200, {"Content-Type": "text/html", "X-Mahoon-Worker-Version": version}, b"<html></html>"),
        ])
        result = request_with_version_pinning(
            "https://mahoonartmagazine.ir/post/slug", worker="mahoon-art-magazine",
            version=version, opener=opener,
        )
        expected_header = 'mahoon-art-magazine="candidate-v2"'
        self.assertEqual(1, result["redirect_hop_count"])
        self.assertTrue(result["override_preserved_on_every_hop"])
        self.assertEqual([expected_header, expected_header], [
            request.get_header("Cloudflare-workers-version-overrides") for request in opener.requests
        ])
        self.assertEqual(version, result["actual_version"])
        self.assertEqual("PROVEN", result["version_attribution_status"])

    def test_candidate_and_baseline_attribution_must_match_each_requested_version(self):
        for requested, actual, expected in (
            ("candidate-v2", "candidate-v2", "PROVEN"),
            ("baseline-v1", "baseline-v1", "PROVEN"),
            ("candidate-v2", "baseline-v1", "NOT_PROVEN"),
            ("candidate-v2", None, "NOT_PROVEN"),
        ):
            headers = {"Content-Type": "text/html"}
            if actual:
                headers["X-Mahoon-Worker-Version"] = actual
            result = request_with_version_pinning(
                "https://mahoonartmagazine.ir/", worker="mahoon-art-magazine",
                version=requested, opener=_Opener([_Response(200, headers, b"ok")]),
            )
            self.assertEqual(expected, result["version_attribution_status"])

    def test_cache_busted_request_uses_unique_query_without_changing_path(self):
        url = "https://mahoonartmagazine.ir/post/slug?view=full#content"
        busted = cache_busted_url(url, "candidate-v2", "nonce-123")
        parsed = urlsplit(busted)
        self.assertEqual("/post/slug", parsed.path)
        self.assertEqual("content", parsed.fragment)
        self.assertEqual("full", parse_qs(parsed.query)["view"][0])
        self.assertEqual("candidate-v2-nonce-123", parse_qs(parsed.query)["__mahoon_proof"][0])
        result = request_with_version_pinning(
            url, worker="mahoon-art-magazine", version="candidate-v2",
            opener=_Opener([_Response(200, {"X-Mahoon-Worker-Version": "candidate-v2"})]),
            cache_bust_nonce="nonce-123",
        )
        self.assertEqual(busted, result["requested_url"])
        self.assertTrue(result["cache_busted"])

    def test_empty_category_with_required_base_route_and_zero_cards_passes(self):
        self.assertTrue(category_page_matches(True, [], []))
        self.assertFalse(category_page_matches(False, [], []))
        self.assertFalse(category_page_matches(True, [], [], 404))
        self.assertFalse(category_page_matches(True, [7], []))

    def test_tag_and_media_targets_are_not_mislabeled_as_missing_page_routes(self):
        manifest = {"/", "/posts"}
        tag_kind, tag_path = classify_link_target(
            "https://mahoonartmagazine.ir/tag/arya", "https://mahoonartmagazine.ir/", manifest
        )
        media_kind, media_path = classify_link_target(
            "/media/ab/hash.jpg", "https://mahoonartmagazine.ir/", manifest
        )
        self.assertEqual(("TAG_ROUTE", "/tag/arya"), (tag_kind, tag_path))
        self.assertEqual(("STATIC_MEDIA", "/media/ab/hash.jpg"), (media_kind, media_path))
        self.assertFalse(link_contract_fails(tag_kind, 200, "text/html"))
        self.assertFalse(link_contract_fails(media_kind, 200, "image/jpeg"))
        self.assertTrue(link_contract_fails(tag_kind, 404, "text/html"))

    def test_real_broken_page_link_still_fails_and_external_other_is_not_critical(self):
        kind, _ = classify_link_target(
            "/post/not-in-manifest", "https://mahoonartmagazine.ir/", {"/", "/posts"}
        )
        self.assertEqual("PAGE_ROUTE", kind)
        self.assertTrue(link_contract_fails(kind, 404, "text/html"))
        external_kind, _ = classify_link_target(
            "https://example.org/unrelated", "https://mahoonartmagazine.ir/", {"/"}
        )
        self.assertEqual("EXTERNAL_OTHER", external_kind)
        self.assertFalse(link_contract_fails(external_kind, None))

    def test_next_candidate_version_metadata_worker_first_covers_accepted_routes(self):
        root = Path(__file__).resolve().parents[2]
        config = json.loads((root / "website/dreary-disk/wrangler.jsonc").read_text(encoding="utf-8"))
        self.assertEqual("CF_VERSION_METADATA", config["version_metadata"]["binding"])
        self.assertEqual("./src/worker.js", config["main"])
        patterns = config["assets"]["run_worker_first"]
        for route in ("/about", "/about/", "/contact", "/contact/"):
            self.assertIn(route, patterns, f"Worker-first attribution is missing {route}")
        routes_path = root / "publisher-state/current-accepted-route-manifest.json"
        routes = json.loads(routes_path.read_text(encoding="utf-8"))["routes"]
        uncovered = [route for route in routes if not any(fnmatch.fnmatchcase(route, pattern) for pattern in patterns)]
        self.assertEqual([], uncovered[:20], f"worker-first attribution misses {len(uncovered)} accepted routes")


if __name__ == "__main__":
    unittest.main()
