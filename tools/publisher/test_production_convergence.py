from __future__ import annotations

import unittest

from tools.publisher.production_convergence import probe_convergence


class _Clock:
    def __init__(self):
        self.value = 0.0

    def now(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


def _response(version, expected, route, override=False):
    return {
        "route": route,
        "http_status": 200,
        "expected_version": expected,
        "actual_version": version,
        "version_attribution_status": "PROVEN" if version == expected else "NOT_PROVEN",
        "override_header_sent": override,
        "cf_cache_status": "HIT",
        "body_sha256": "body-hash",
        "redirect_chain": [],
        "content_type": "text/html",
        "timestamp_utc": "2026-09-19T00:00:00+00:00",
    }


class ProductionConvergenceTests(unittest.TestCase):
    def test_mixed_versions_fail_and_semantic_result_is_not_trusted(self):
        clock = _Clock()

        def fetch(route, expected):
            return _response(expected if route == "/" else "baseline", expected, route)

        result = probe_convergence(fetch, ["/", "/posts"], "candidate", timeout_seconds=5,
                                   interval_seconds=1, monotonic=clock.now, sleep=clock.sleep)
        self.assertFalse(result["PASS"])
        self.assertEqual(0, result["rounds"])
        self.assertTrue(result["mismatches"])
        self.assertTrue(all("actual_version" in item for item in result["mismatches"]))

    def test_full_convergence_requires_three_no_override_rounds(self):
        clock = _Clock()
        calls = []

        def fetch(route, expected):
            calls.append((route, expected))
            return _response(expected, expected, route, override=False)

        result = probe_convergence(fetch, ["/", "/posts"], "candidate", interval_seconds=1,
                                   monotonic=clock.now, sleep=clock.sleep)
        self.assertTrue(result["PASS"])
        self.assertEqual(3, result["rounds"])
        self.assertEqual(6, len(calls))
        self.assertEqual(2, clock.value)
        self.assertTrue(all(not _response("candidate", "candidate", "/", False)["override_header_sent"]
                            for _ in calls))

    def test_delayed_convergence_is_bounded_and_eventually_passes(self):
        clock = _Clock()
        attempt = {"value": 0}

        def fetch(route, expected):
            version = expected if attempt["value"] >= 2 else "baseline"
            return _response(version, expected, route)

        def sleep(seconds):
            attempt["value"] += 1
            clock.sleep(seconds)

        result = probe_convergence(fetch, ["/"], "candidate", interval_seconds=10,
                                   monotonic=clock.now, sleep=sleep)
        self.assertTrue(result["PASS"])
        self.assertEqual(3, result["rounds"])
        self.assertEqual(5, result["attempts"])
        self.assertLessEqual(result["seconds"], 300)

    def test_never_converges_is_bounded_for_automatic_rollback(self):
        clock = _Clock()

        def fetch(route, expected):
            return _response("baseline", expected, route)

        result = probe_convergence(fetch, ["/", "/admin"], "candidate", timeout_seconds=2,
                                   interval_seconds=1, monotonic=clock.now, sleep=clock.sleep)
        self.assertFalse(result["PASS"])
        self.assertEqual(3, result["attempts"])
        self.assertLessEqual(result["seconds"], 2)
        self.assertEqual("baseline", result["mismatches"][0]["actual_version"])

    def test_remote_proof_pinning_contract_remains_strict(self):
        from email.message import Message
        from tools.publisher.remote_proof_harness import request_with_version_pinning

        class Response:
            status = 200
            body = b"ok"

            def __init__(self):
                self.headers = Message()
                self.headers["X-Mahoon-Worker-Version"] = "candidate"

            def getcode(self):
                return self.status

            def read(self):
                return self.body

            def close(self):
                pass

        class Opener:
            def __init__(self):
                self.requests = []

            def open(self, request, timeout):
                self.requests.append(request)
                return Response()

        opener = Opener()
        result = request_with_version_pinning(
            "https://mahoonartmagazine.ir/",
            worker="mahoon-art-magazine",
            version="candidate",
            opener=opener,
            send_version_override=True,
            require_actual_version=True,
        )
        self.assertEqual("PROVEN", result["version_attribution_status"])
        self.assertTrue(result["override_header_sent"])
        self.assertTrue(opener.requests[0].get_header("Cloudflare-workers-version-overrides"))


if __name__ == "__main__":
    unittest.main()
