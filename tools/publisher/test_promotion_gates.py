import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.publisher.promotion_gates import (
    category_parity, content_parity, latest_parity, listing_uniqueness,
    media_gate, seo_gate, _read_page,
)
from tools.publisher.candidate_override_crawl import _measure, _url_evidence


def _fixture(with_media=False):
    root = Path(tempfile.mkdtemp())
    posts = [
        {"id": 2, "slug": "new-post", "created_at": "2026-09-02T00:00:00Z", "text": "Newest #متن"},
        {"id": 1, "slug": "old-post", "created_at": "2026-09-01T00:00:00Z", "text": "Older #کتاب"},
    ]
    routes = ["/", "/posts", "/category/کتاب", "/category/شعر و متن", "/post/2", "/post/new-post", "/post/1", "/post/old-post", "/robots.txt", "/sitemap.xml"]
    media_records = []
    media_url = None
    if with_media:
        data = b"\xff\xd8\xfffixture-image"
        digest = hashlib.sha256(data).hexdigest()
        media_path = f"/media/{digest[:2]}/{digest}.jpg"
        media_url = media_path
        (root / media_path.lstrip("/")).parent.mkdir(parents=True)
        (root / media_path.lstrip("/")).write_bytes(data)
        posts[0]["media_file_id"] = "fixture-photo"
        media_records = [{"source_identifier": "fixture-photo", "immutable_path": media_path, "sha256": digest, "mime": "image/jpeg"}]
    snapshot = {"contract": "POSTS_FULL_PUBLIC_SNAPSHOT_V2", "payload": {"posts": posts}}
    expected = [
        {"id": 2, "slug": "new-post", "title": "Newest", "category": "شعر و متن", "url": "https://mahoonartmagazine.ir/post/new-post"},
        {"id": 1, "slug": "old-post", "title": "Older", "category": "کتاب", "url": "https://mahoonartmagazine.ir/post/old-post"},
    ]
    root.joinpath("search").mkdir()
    (root / "search/search-index.json").write_text(json.dumps({"contract": "STATIC_SEARCH_CONTRACT_V2", "records": expected}), encoding="utf-8")

    def page(route, cards=(), title="Fixture", jsonld=False, media_url=None, latest_rows=()):
        canonical = "https://mahoonartmagazine.ir" + ("/" if not route.strip("/") else "/" + route.strip("/"))
        links = "".join(f'<article class="mahoon-archive-card"><a href="/post/{slug}">{slug}</a></article>' for slug in cards)
        latest = "".join(f'<a class="m-list-row" href="/post/{slug}">{slug}</a>' for slug in latest_rows)
        image = f'<img src="{media_url}" />' if media_url else ""
        schema = '<script type="application/ld+json">{}</script>' if jsonld else ""
        return f'<html><head><title>{title}</title><meta name="description" content="Fixture summary"><meta property="og:title" content="Fixture"><link rel="canonical" href="{canonical}">{schema}</head><body><header>Site</header><main><h1>{title}</h1>{image}{latest}{links}</main></body></html>'

    def write_route(route, text):
        path = root / route.strip("/") / "index.html" if route.strip("/") else root / "index.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    write_route("/", page("/", ("old-post", "new-post"), "Home", latest_rows=("new-post", "old-post")))
    write_route("/posts", page("/posts", ("new-post", "old-post"), "Posts"))
    write_route("/category/کتاب", page("/category/کتاب", ("old-post",), "Books"))
    write_route("/category/شعر و متن", page("/category/شعر و متن", ("new-post",), "Text"))
    for post in posts:
        for route in (f"/post/{post['id']}", f"/post/{post['slug']}"):
            write_route(route, page(route, (), post["text"], True, media_url if with_media and post["id"] == 2 else None))
    (root / "robots.txt").write_text("User-agent: *\nAllow: /\nSitemap: https://mahoonartmagazine.ir/sitemap.xml\n", encoding="utf-8")
    (root / "sitemap.xml").write_text("<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">" + "".join(
        f"<url><loc>https://mahoonartmagazine.ir/post/{post['slug']}</loc></url>" for post in posts
    ) + "</urlset>", encoding="utf-8")
    manifest = {"contract": "CURRENT_CANDIDATE_SEALED_ROUTE_MANIFEST_V1", "routes": routes}
    media = {"contract": "CURRENT_MEDIA_RESOLUTION_V1", "records": media_records,
             "stats": {"unresolved": 0}}
    return root, snapshot, manifest, media


class PromotionGateTests(unittest.TestCase):
    def test_url_leak_gates_classify_hosts_not_prose(self):
        from tools.publisher.promotion_gates import _facts, _url_evidence as classify_urls
        prose = _url_evidence("<p>Preview the artwork at any time.</p>", _facts("<p>Preview the artwork at any time.</p>"))
        self.assertFalse(prose["preview_url"])
        leaked = _url_evidence(
            '<link rel="canonical" href="https://preview-demo.mahoon.workers.dev/post/x">',
            _facts('<link rel="canonical" href="https://preview-demo.mahoon.workers.dev/post/x">'),
        )
        self.assertTrue(leaked["workers_dev"])
        self.assertTrue(leaked["preview_url"])
        self.assertEqual(leaked, classify_urls(
            '<link rel="canonical" href="https://preview-demo.mahoon.workers.dev/post/x">',
            _facts('<link rel="canonical" href="https://preview-demo.mahoon.workers.dev/post/x">'),
        ))

    def test_content_parity_passes_and_missing_canonical_route_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, snapshot, manifest, _ = _fixture()
            try:
                self.assertTrue(content_parity(snapshot, root, manifest)["PASS"])
                broken = dict(manifest, routes=[route for route in manifest["routes"] if route != "/post/new-post"])
                self.assertFalse(content_parity(snapshot, root, broken)["PASS"])
            finally:
                import shutil
                shutil.rmtree(root)

    def test_listing_uniqueness_passes_and_duplicate_card_fails(self):
        root, snapshot, manifest, _ = _fixture()
        try:
            self.assertTrue(listing_uniqueness(snapshot, root, manifest)["PASS"])
            path = root / "posts/index.html"
            path.write_text(path.read_text(encoding="utf-8").replace("</main>", '<article class="mahoon-archive-card"><a href="/post/new-post">duplicate</a></article></main>'), encoding="utf-8")
            _read_page.cache_clear()
            from tools.publisher.promotion_gates import _facts
            _facts.cache_clear()
            self.assertFalse(listing_uniqueness(snapshot, root, manifest)["PASS"])
        finally:
            import shutil
            shutil.rmtree(root)

    def test_home_editorial_rail_order_is_not_used_as_global_latest_order(self):
        root, snapshot, manifest, _ = _fixture()
        try:
            self.assertTrue(listing_uniqueness(snapshot, root, manifest)["PASS"])
            self.assertTrue(latest_parity(snapshot, root, manifest)["PASS"])
        finally:
            import shutil
            shutil.rmtree(root)

    def test_category_parity_passes_and_wrong_category_fails(self):
        root, snapshot, manifest, _ = _fixture()
        try:
            self.assertTrue(category_parity(snapshot, root, manifest)["PASS"])
            path = root / "category/کتاب/index.html"
            path.write_text(path.read_text(encoding="utf-8").replace("old-post", "new-post"), encoding="utf-8")
            _read_page.cache_clear()
            from tools.publisher.promotion_gates import _facts
            _facts.cache_clear()
            self.assertFalse(category_parity(snapshot, root, manifest)["PASS"])
        finally:
            import shutil
            shutil.rmtree(root)

    def test_latest_parity_passes_and_reordered_home_fails(self):
        root, snapshot, manifest, _ = _fixture()
        try:
            self.assertTrue(latest_parity(snapshot, root, manifest)["PASS"])
            path = root / "index.html"
            text = path.read_text(encoding="utf-8")
            start = text.index('<a class="m-list-row"')
            second = text.index('<a class="m-list-row"', start + 1)
            blocks = [text[start:text.index("</a>", start) + 4], text[second:text.index("</a>", second) + 4]]
            text = text.replace("".join(blocks), "".join(reversed(blocks)))
            path.write_text(text, encoding="utf-8")
            _read_page.cache_clear()
            from tools.publisher.promotion_gates import _facts
            _facts.cache_clear()
            self.assertFalse(latest_parity(snapshot, root, manifest)["PASS"])
        finally:
            import shutil
            shutil.rmtree(root)

    def test_seo_passes_and_missing_post_jsonld_fails(self):
        root, snapshot, manifest, _ = _fixture()
        try:
            self.assertTrue(seo_gate(snapshot, root, manifest)["PASS"])
            path = root / "post/new-post/index.html"
            path.write_text(path.read_text(encoding="utf-8").replace('<script type="application/ld+json">{}</script>', ""), encoding="utf-8")
            _read_page.cache_clear()
            from tools.publisher.promotion_gates import _facts
            _facts.cache_clear()
            self.assertFalse(seo_gate(snapshot, root, manifest)["PASS"])
        finally:
            import shutil
            shutil.rmtree(root)

    def test_media_passes_and_corrupt_signature_fails(self):
        root, snapshot, manifest, media = _fixture(with_media=True)
        try:
            self.assertTrue(media_gate(snapshot, root, manifest, media)["PASS"])
            target = next((root / "media").rglob("*.jpg"))
            target.write_bytes(b"not-an-image")
            from tools.publisher.promotion_gates import _facts
            _facts.cache_clear()
            self.assertFalse(media_gate(snapshot, root, manifest, media)["PASS"])
        finally:
            import shutil
            shutil.rmtree(root)

    def test_remote_candidate_gate_metrics_pass_and_fail_on_broken_listing(self):
        root, snapshot, manifest, media = _fixture()
        try:
            from tools.publisher.promotion_gates import _facts, _route_file
            routes = manifest["routes"]
            remote_routes = {}
            for route in routes:
                target = _route_file(root, route)
                if target.suffix in {".txt", ".xml"}:
                    remote_routes[route] = {"status": "PASS", "http_status": 200, "is_html": False}
                else:
                    facts = _facts(target.read_text(encoding="utf-8"))
                    remote_routes[route] = {
                        "status": "PASS", "http_status": 200, "is_html": True,
                        "canonical": facts.canonicals[0] if facts.canonicals else "",
                        "title": bool(facts.titles), "h1": bool(facts.h1s), "meta": bool(facts.descriptions),
                        "og": bool(facts.descriptions), "jsonld": facts.jsonld, "robots_noindex": False,
                        "card_routes": facts.cards, "anchor_links": facts.anchors,
                        "latest_rows": facts.latest_rows,
                        "workers_dev": False, "preview_url": False, "remote_media": False,
                    }
            remote_routes["/robots.txt"]["robots_sitemap"] = True
            remote_routes["/sitemap.xml"]["sitemap_posts"] = ["/post/new-post", "/post/old-post"]
            search = json.loads((root / "search/search-index.json").read_text(encoding="utf-8"))
            search["http_status"] = 200
            healthy = _measure(routes, {"routes": remote_routes}, snapshot, search, media)
            self.assertTrue(healthy["PASS"], json.dumps(healthy, ensure_ascii=True))
            broken = {"routes": {key: dict(value) for key, value in remote_routes.items()}}
            broken["routes"]["/posts"]["card_routes"].append("/post/new-post")
            unhealthy = _measure(routes, broken, snapshot, search, media)
            self.assertFalse(unhealthy["gates"]["remote_listing_uniqueness"]["PASS"])
        finally:
            import shutil
            shutil.rmtree(root)

    def test_real_browser_visual_and_zero_origin_fixtures_pass_and_fail(self):
        result = subprocess.run(["node", "tools/publisher/prepromotion_browser_gate.mjs", "--self-test"],
                                capture_output=True, text=True, check=False, timeout=120)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        proof = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertTrue(proof["visual_healthy_fixture"])
        self.assertTrue(proof["visual_broken_fixture"])
        self.assertTrue(proof["zero_origin_healthy_fixture"])
        self.assertTrue(proof["zero_origin_broken_fixture"])


if __name__ == "__main__":
    unittest.main()
