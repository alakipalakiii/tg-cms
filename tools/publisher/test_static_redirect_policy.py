from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote

from static_redirect_policy import (
    generate_candidate_redirects,
    validate_candidate_redirects,
)


ROOT = Path(__file__).resolve().parents[2]
HISTORICAL_REDIRECTS = ROOT / "publisher-base" / "_redirects"


class StaticRedirectPolicyTests(unittest.TestCase):
    def _raw_rule_for_id(self, post_id: int) -> tuple[str, str]:
        for line in HISTORICAL_REDIRECTS.read_text(encoding="utf-8").splitlines():
            fields = line.split()
            if len(fields) == 3 and fields[1] == f"/post/{post_id}/" and fields[2] == "200":
                return fields[0], fields[1]
        self.fail(f"No historical slug proxy for post {post_id}")

    def _rule_for_id(self, post_id: int) -> tuple[str, str]:
        source, destination = self._raw_rule_for_id(post_id)
        return unquote(source), destination

    def _history_fixture(self, root: Path, post_ids: tuple[int, ...]) -> Path:
        path = root / "historical-redirects"
        lines = [
            f"{source} {destination} 200"
            for post_id in post_ids
            for source, destination in [self._raw_rule_for_id(post_id)]
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    @staticmethod
    def _write_html(root: Path, route: str, canonical: str) -> bytes:
        path = root / route.lstrip("/") / "index.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        content = f'<link rel="canonical" href="{canonical}">'.encode("utf-8")
        path.write_bytes(content)
        return content

    def test_id_32_materialized_slug_proxy_is_removed_and_canonicals_stay_distinct(self):
        slug, numeric = self._rule_for_id(32)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            slug_canonical = f"https://mahoonartmagazine.ir{slug}"
            numeric_canonical = "https://mahoonartmagazine.ir/post/32"
            slug_html = self._write_html(root, slug, slug_canonical)
            numeric_html = self._write_html(root, "/post/32", numeric_canonical)
            candidate = root / "_redirects"
            historical = self._history_fixture(root, (32,))
            proof = generate_candidate_redirects(
                historical, candidate, [slug, "/post/32"], root
            )
            self.assertNotIn(f"{slug} {numeric} 200", candidate.read_text(encoding="utf-8"))
            self.assertEqual(1, proof["shadowing_proxy_rules_removed"])
            self.assertEqual(0, proof["candidate_shadowing_redirect_rules"])
            self.assertEqual(slug_html, (root / slug.lstrip("/") / "index.html").read_bytes())
            self.assertEqual(numeric_html, (root / "post" / "32" / "index.html").read_bytes())
            self.assertIn(slug_canonical.encode(), slug_html)
            self.assertIn(numeric_canonical.encode(), numeric_html)

    def test_early_middle_and_id_888_proxies_are_filtered(self):
        samples = [self._rule_for_id(post_id) for post_id in (32, 460, 888)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            historical = self._history_fixture(root, (32, 460, 888))
            routes: list[str] = []
            for slug, destination in samples:
                self._write_html(root, slug, f"https://mahoonartmagazine.ir{slug}")
                routes.extend((slug, destination))
            proof = generate_candidate_redirects(
                historical, root / "_redirects", routes, root
            )
            self.assertEqual(3, proof["shadowing_proxy_rules_removed"])
            self.assertEqual(0, proof["shadowing_proxy_rules_remaining"])
            self.assertEqual(0, proof["candidate_shadowing_redirect_rules"])

    def test_current_820_legacy_proxies_are_all_removed_from_the_candidate(self):
        sources: list[str] = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for line in HISTORICAL_REDIRECTS.read_text(encoding="utf-8").splitlines():
                fields = line.split()
                if len(fields) != 3 or fields[2] != "200":
                    continue
                source = unquote(fields[0])
                sources.append(source)
                path = root / source.lstrip("/") / "index.html"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("<html></html>", encoding="utf-8")
            proof = generate_candidate_redirects(
                HISTORICAL_REDIRECTS, root / "_redirects", sources, root
            )
            self.assertEqual(820, proof["historical_redirect_rules_total"])
            self.assertEqual(820, proof["legacy_post_proxy_rules"])
            self.assertEqual(820, proof["shadowing_proxy_rules_removed"])
            self.assertEqual(0, proof["shadowing_proxy_rules_remaining"])

    def test_local_routing_gate_rejects_status_200_shadow_even_with_healthy_html(self):
        slug, numeric = self._rule_for_id(32)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_html(root, slug, f"https://mahoonartmagazine.ir{slug}")
            candidate = root / "_redirects"
            candidate.write_text(f"{slug} {numeric} 200\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "CANDIDATE_REDIRECT_SHADOWS_MATERIALIZED_ROUTE"):
                validate_candidate_redirects(candidate, [slug], root)

    def test_allowlisted_non_shadowing_compatibility_rule_is_retained_and_classified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            historical = root / "historical"
            candidate = root / "_redirects"
            historical.write_text("/legacy-about /about/ 301\n", encoding="utf-8")
            policy = {
                "/legacy-about": {
                    "destination": "/about/",
                    "status": 301,
                    "reason": "Preserve the documented legacy about URL.",
                    "required": True,
                }
            }
            proof = generate_candidate_redirects(
                historical, candidate, ["/about"], root, policy
            )
            self.assertEqual(1, proof["compatibility_rules_classified"])
            self.assertIn("/legacy-about /about/ 301", candidate.read_text(encoding="utf-8"))
            self.assertIn(
                "# Compatibility: Preserve the documented legacy about URL.",
                candidate.read_text(encoding="utf-8"),
            )

    def test_wildcard_mixing_current_and_noncurrent_routes_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            historical = root / "historical"
            historical.write_text("/legacy/* /new/:splat 200\n", encoding="utf-8")
            self._write_html(root, "/legacy/present", "https://mahoonartmagazine.ir/legacy/present")
            with self.assertRaisesRegex(
                ValueError, "REDIRECT_PATTERN_MIXES_MATERIALIZED_AND_COMPATIBILITY_ROUTES"
            ):
                generate_candidate_redirects(
                    historical,
                    root / "_redirects",
                    ["/legacy/present", "/legacy/not-materialized"],
                    root,
                )

    def test_unclassified_non_shadowing_rule_fails_instead_of_silent_deletion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            historical = root / "historical"
            candidate = root / "_redirects"
            historical.write_text("/legacy-about /about/ 301\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "NON_SHADOWING_REDIRECT_REQUIRES_COMPATIBILITY_REASON"):
                generate_candidate_redirects(historical, candidate, ["/about"], root)
            self.assertFalse(candidate.exists())

    def test_generated_redirect_output_is_deterministic(self):
        slug, _numeric = self._rule_for_id(32)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            historical = self._history_fixture(root, (32,))
            self._write_html(root, slug, f"https://mahoonartmagazine.ir{slug}")
            first = root / "first" / "_redirects"
            second = root / "second" / "_redirects"
            generate_candidate_redirects(historical, first, [slug], root)
            generate_candidate_redirects(historical, second, [slug], root)
            self.assertEqual(first.read_bytes(), second.read_bytes())


if __name__ == "__main__":
    unittest.main()
