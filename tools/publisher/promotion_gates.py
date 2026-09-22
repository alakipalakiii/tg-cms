"""Measured promotion gates over one locked content snapshot and Static artifact."""
from __future__ import annotations

from html.parser import HTMLParser
import json
import os
from functools import lru_cache
from pathlib import Path
import re
from urllib.parse import quote, unquote, urlsplit
import xml.etree.ElementTree as ET

try:
    from .content_taxonomy import CATEGORY_DEFINITIONS, canonical_category
    from .media_bootstrap import signature_mime, source_identifiers
    from .public_listing_dedupe import dedupe_public_listing_posts
    from .pagination_contract import PAGE_SIZE
except ImportError:
    from content_taxonomy import CATEGORY_DEFINITIONS, canonical_category
    from media_bootstrap import signature_mime, source_identifiers
    from public_listing_dedupe import dedupe_public_listing_posts
    from pagination_contract import PAGE_SIZE

SITE = os.environ.get("MAHOON_SITE_URL", "https://mahoonartmagazine.ir").rstrip("/")

POST_HREF = re.compile(r"^/post/[^?#]+/?$")


class _Facts(HTMLParser):
    def __init__(self, fields: str = "all") -> None:
        super().__init__(convert_charrefs=True)
        self.fields = fields
        self.canonicals: list[str] = []
        self.titles: list[str] = []
        self.h1s: list[str] = []
        self.descriptions: list[str] = []
        self.robots: list[str] = []
        self.stylesheets: list[str] = []
        self.scripts: list[str] = []
        self.references: list[str] = []
        self.anchors: list[str] = []
        self.cards: list[str] = []
        self.latest_rows: list[str] = []
        self.related: list[str] = []
        self._card_stack: list[dict] = []
        self._capture = ""
        self._text: list[str] = []
        self.jsonld = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self.fields == "canonical":
            if tag == "link" and "canonical" in (a.get("rel") or "").lower().split():
                self.canonicals.append(a.get("href", ""))
            return
        classes = set((a.get("class") or "").split())
        if self.fields == "related":
            href = a.get("href", "")
            if tag == "a" and "client-related-item" in classes and POST_HREF.match(href):
                self.related.append(href)
            return
        if self.fields == "references":
            if tag == "link" and "stylesheet" in (a.get("rel") or "").lower().split():
                self.stylesheets.append(a.get("href", ""))
            elif tag == "script" and a.get("src"):
                self.scripts.append(a["src"])
            if tag == "a" and a.get("href"):
                self.references.append(a["href"])
            if a.get("src"):
                self.references.append(a["src"])
            return
        if self.fields == "cards":
            if tag in {"article", "div"} and classes.intersection({"m-card", "mahoon-archive-card"}):
                href = a.get("data-post-href", "")
                self._card_stack.append({"tag": tag, "hrefs": [href] if href else []})
            elif tag == "a" and POST_HREF.match(a.get("href", "")):
                for card in self._card_stack:
                    card["hrefs"].append(a["href"])
            return
        if self.fields == "seo":
            if tag == "link" and "canonical" in (a.get("rel") or "").lower().split():
                self.canonicals.append(a.get("href", ""))
            elif tag == "meta":
                name = (a.get("name") or "").lower()
                if name == "description" and a.get("content"):
                    self.descriptions.append(a["content"])
                elif name == "robots" and a.get("content"):
                    self.robots.append(a["content"].lower())
            elif tag == "script" and (a.get("type") or "").lower() == "application/ld+json":
                self.jsonld = True
            if tag in {"title", "h1"}:
                self._capture = tag
                self._text = []
            return
        if tag in {"article", "div"} and classes.intersection({"m-card", "mahoon-archive-card"}):
            href = a.get("data-post-href", "")
            self._card_stack.append({"tag": tag, "hrefs": [href] if href else []})
        if tag == "a":
            href = a.get("href", "")
            if href:
                self.references.append(href)
                self.anchors.append(href)
                if POST_HREF.match(href):
                    if "m-list-row" in classes:
                        self.latest_rows.append(href)
                    for card in self._card_stack:
                        card["hrefs"].append(href)
                    if "client-related-item" in classes:
                        self.related.append(href)
        for key in ("src",):
            if a.get(key):
                self.references.append(a[key])
        if tag == "link" and "stylesheet" in (a.get("rel") or "").lower().split():
            self.stylesheets.append(a.get("href", ""))
        if tag == "script":
            if a.get("src"):
                self.scripts.append(a["src"])
            if (a.get("type") or "").lower() == "application/ld+json":
                self.jsonld = True
        if tag == "link" and "canonical" in (a.get("rel") or "").lower().split():
            self.canonicals.append(a.get("href", ""))
        if tag == "meta":
            name = (a.get("name") or "").lower()
            if name == "description" and a.get("content"):
                self.descriptions.append(a["content"])
            elif name == "robots" and a.get("content"):
                self.robots.append(a["content"].lower())
        if tag in {"title", "h1"}:
            self._capture = tag
            self._text = []

    def handle_endtag(self, tag):
        if self._capture == tag:
            value = " ".join(" ".join(self._text).split())
            (self.titles if tag == "title" else self.h1s).append(value)
            self._capture = ""
        for index in range(len(self._card_stack) - 1, -1, -1):
            if self._card_stack[index]["tag"] == tag:
                frame = self._card_stack.pop(index)
                paths = list(dict.fromkeys(frame["hrefs"]))
                if paths:
                    self.cards.append(paths[0])
                break

    def handle_data(self, data):
        if self._capture:
            self._text.append(data)


@lru_cache(maxsize=4096)
def _facts(text: str, fields: str = "all") -> _Facts:
    parser = _Facts(fields)
    parser.feed(text)
    parser.close()
    return parser


def _url_evidence(text: str, facts: _Facts) -> dict:
    values = list(facts.references) + list(facts.canonicals) + list(facts.stylesheets) + list(facts.scripts)
    values.extend(re.findall(r"https?://[^\s\"'<>`)]+", text, re.I))
    hosts = set()
    remote_media = False
    for value in values:
        parsed = urlsplit(value)
        if parsed.scheme.lower() in {"http", "https"} and parsed.hostname:
            host = parsed.hostname.lower()
            hosts.add(host)
            remote_media |= host == "api.mahoonartmagazine.ir" and parsed.path.startswith("/media/")
    workers_dev = any(host == "workers.dev" or host.endswith(".workers.dev") for host in hosts)
    preview_url = workers_dev or any(
        host == "pages.dev" or host.endswith(".pages.dev") or "preview" in host
        for host in hosts
    )
    return {"workers_dev": workers_dev, "preview_url": preview_url,
            "remote_media": remote_media,
            "public_api": "api.mahoonartmagazine.ir" in hosts}


def _posts(snapshot: dict) -> list[dict]:
    payload = snapshot.get("payload") or {}
    posts = payload.get("posts")
    if not isinstance(posts, list) or any(not isinstance(post, dict) for post in posts):
        raise ValueError("locked snapshot posts are missing")
    return posts


def _route_file(root: Path, route: str) -> Path:
    path = unquote(urlsplit(route).path).strip("/")
    if not path:
        return root / "index.html"
    if Path(path).suffix:
        return root / path
    return root / path / "index.html"


@lru_cache(maxsize=8000)
def _read_page(root: Path, route: str) -> str:
    return _route_file(root, route).read_text(encoding="utf-8")


def _canonical_url(route: str) -> str:
    return SITE + quote("/" + route.strip("/"), safe="/%:@!$&'()*+,;=-._~") if route.strip("/") else SITE + "/"


def _expected_posts(snapshot: dict) -> list[dict]:
    return dedupe_public_listing_posts(_posts(snapshot))


def _id_for_href(href: str, by_slug: dict[str, int], by_id: dict[str, int]) -> int | None:
    path = unquote(urlsplit(href).path).strip("/")
    if not path.startswith("post/"):
        return None
    key = path[5:]
    return by_slug.get(key, by_id.get(key))


def _route_ids(root: Path, route: str, by_slug: dict[str, int], by_id: dict[str, int]) -> tuple[list[int], int]:
    facts = _facts(_read_page(root, route))
    ids = [_id_for_href(href, by_slug, by_id) for href in facts.cards]
    return [item for item in ids if item is not None], sum(item is None for item in ids)


def _routes(manifest: dict) -> list[str]:
    routes = manifest.get("routes")
    if not isinstance(routes, list) or not all(isinstance(route, str) for route in routes):
        raise ValueError("candidate route manifest is invalid")
    return routes


def content_parity(snapshot: dict, root: Path, manifest: dict) -> dict:
    source = _posts(snapshot)
    routes = set(_routes(manifest))
    missing: list[str] = []
    unexpected: list[str] = []
    canonical_failures: list[str] = []
    for post in source:
        slug = str(post.get("slug") or "").strip()
        route = f"/post/{slug}" if slug else ""
        if not route or route not in routes or not _route_file(root, route).is_file():
            missing.append(route or f"post-id:{post.get('id')}")
            continue
        facts = _facts(_read_page(root, route))
        if facts.canonicals != [_canonical_url(route)]:
            canonical_failures.append(route)
    snapshot_routes = {f"/post/{post.get('id')}" for post in source if str(post.get("id", "")).isdigit()}
    snapshot_routes.update(f"/post/{post.get('slug')}" for post in source if post.get("slug"))
    manifest_post_routes = {route for route in routes if route.startswith("/post/")}
    missing.extend(sorted(snapshot_routes - manifest_post_routes))
    unexpected.extend(sorted(manifest_post_routes - snapshot_routes))
    search_path = root / "search" / "search-index.json"
    search = json.loads(search_path.read_text(encoding="utf-8")) if search_path.is_file() else {}
    expected_listing = _expected_posts(snapshot)
    expected_ids = [int(post["id"]) for post in expected_listing]
    observed_ids = [int(record["id"]) for record in search.get("records", []) if str(record.get("id", "")).isdigit()]
    return {"measured": True, "snapshot_post_count": len(source), "canonical_source_ids": len({str(post.get('id')) for post in source}),
            "candidate_canonical_post_routes": len(snapshot_routes & manifest_post_routes),
            "missing_expected_canonical_routes": len(missing), "unexpected_canonical_routes": len(unexpected),
            "canonical_failures": len(canonical_failures), "logical_listing_count": len(expected_ids),
            "search_index_count": len(observed_ids), "search_index_duplicate_ids": len(observed_ids) - len(set(observed_ids)),
            "search_index_missing_ids": len(set(expected_ids) - set(observed_ids)),
            "search_index_unexpected_ids": len(set(observed_ids) - set(expected_ids)),
            "PASS": not missing and not unexpected and not canonical_failures and observed_ids == expected_ids}


def _pages_for_prefix(routes: set[str], prefix: str, page_count: int) -> list[tuple[int, str]]:
    result = []
    base = prefix.rstrip("/")
    if base in routes or base + "/" in routes:
        result.append((1, base if base in routes else base + "/"))
    for route in routes:
        match = re.fullmatch(re.escape(base) + r"/page/(\d+)/?", route)
        if match and 2 <= int(match.group(1)) <= page_count:
            result.append((int(match.group(1)), route))
    return sorted(result)


def listing_uniqueness(snapshot: dict, root: Path, manifest: dict) -> dict:
    source = _expected_posts(snapshot)
    routes = set(_routes(manifest))
    by_slug = {str(post.get("slug")): int(post["id"]) for post in _posts(snapshot) if post.get("slug") and str(post.get("id", "")).isdigit()}
    by_id = {str(post["id"]): int(post["id"]) for post in _posts(snapshot) if str(post.get("id", "")).isdigit()}
    duplicate_pages = 0
    unrecognized = 0
    overlaps = 0
    coverage_missing = 0
    checked_pages = 0
    listing_samples: list[dict] = []
    missing_pagination_routes: list[str] = []
    expected_ids = [int(post["id"]) for post in source]
    page_count = (len(expected_ids) + PAGE_SIZE - 1) // PAGE_SIZE
    groups: list[tuple[str, list[int]]] = []
    for prefix in ("/posts",):
        pages = _pages_for_prefix(routes, prefix, page_count)
        seen: set[int] = set()
        observed: list[int] = []
        if len(pages) != page_count:
            coverage_missing += abs(page_count - len(pages))
            observed_numbers = {number for number, _route in pages}
            missing_pagination_routes.extend(
                f"{prefix}/page/{number}"
                for number in range(2, page_count + 1)
                if number not in observed_numbers
            )
        for page_number, route in pages:
            ids, unknown = _route_ids(root, route, by_slug, by_id)
            checked_pages += 1
            unrecognized += unknown
            duplicate_pages += len(ids) - len(set(ids))
            overlaps += len(seen.intersection(ids))
            seen.update(ids)
            observed.extend(ids)
            expected_chunk = expected_ids[(page_number - 1) * PAGE_SIZE:page_number * PAGE_SIZE]
            if ids != expected_chunk:
                coverage_missing += 1
                if len(listing_samples) < 10:
                    listing_samples.append({
                        "route": route, "page_number": page_number,
                        "expected_ids": expected_chunk, "actual_ids": ids,
                        "missing_ids": sorted(set(expected_chunk) - set(ids)),
                        "extra_ids": sorted(set(ids) - set(expected_chunk)),
                        "expected_page_count": page_count,
                        "observed_page_count": len(pages),
                    })
        groups.append((prefix, observed))
    # Home has editorial category rails in addition to its latest list. The latest
    # ordering is measured separately from its dedicated m-list-row elements.
    if "/" in routes:
        home_ids, unknown = _route_ids(root, "/", by_slug, by_id)
        unrecognized += unknown
        duplicate_pages += len(home_ids) - len(set(home_ids))
    related_duplicates = 0
    for post in _posts(snapshot):
        route = f"/post/{post.get('slug')}"
        if route not in routes or not _route_file(root, route).is_file():
            continue
        facts = _facts(_read_page(root, route))
        related_ids = [_id_for_href(href, by_slug, by_id) for href in facts.related]
        related_ids = [item for item in related_ids if item is not None]
        related_duplicates += len(related_ids) - len(set(related_ids))
        related_duplicates += int(int(post["id"]) in related_ids)
    # Category sequences may overlap only when source taxonomy says that they should;
    # this taxonomy is single-valued, so repeated IDs across categories fail parity.
    category_ids: list[int] = []
    category_overlaps = 0
    for label, _variants in CATEGORY_DEFINITIONS:
        expected_category = [int(post["id"]) for post in source if canonical_category(post) == label]
        prefix = "/category/" + label
        count = (len(expected_category) + PAGE_SIZE - 1) // PAGE_SIZE
        pages = _pages_for_prefix(routes, prefix, count)
        seen: set[int] = set()
        actual: list[int] = []
        if count and len(pages) != count:
            coverage_missing += abs(count - len(pages))
        for page_number, route in pages:
            ids, unknown = _route_ids(root, route, by_slug, by_id)
            unrecognized += unknown
            checked_pages += 1
            duplicate_pages += len(ids) - len(set(ids))
            category_overlaps += len(seen.intersection(ids))
            seen.update(ids)
            actual.extend(ids)
            if ids != expected_category[(page_number - 1) * PAGE_SIZE:page_number * PAGE_SIZE]:
                coverage_missing += 1
        category_ids.extend(actual)
    category_overlaps += len(category_ids) - len(set(category_ids))
    search = json.loads((root / "search" / "search-index.json").read_text(encoding="utf-8"))
    search_ids = [int(item["id"]) for item in search.get("records", []) if str(item.get("id", "")).isdigit()]
    duplicate_search = len(search_ids) - len(set(search_ids))
    return {"measured": True, "listing_pages_checked": checked_pages, "duplicate_logical_ids": duplicate_pages + duplicate_search + related_duplicates,
            "duplicate_canonical_cards": duplicate_pages + duplicate_search + related_duplicates,
            "pagination_overlap": overlaps + category_overlaps, "unrecognized_card_routes": unrecognized,
            "listing_page_parity_failures": coverage_missing,
            "LISTING_PARITY_FAILURE_SAMPLES": listing_samples,
            "CATEGORY_PARITY_FAILURE_SAMPLES": [],
            "MISSING_EXPECTED_PAGINATION_ROUTES": sorted(set(missing_pagination_routes)),
            "PASS": not any((duplicate_pages, duplicate_search, related_duplicates, overlaps,
                              category_overlaps, unrecognized, coverage_missing))}


def category_parity(snapshot: dict, root: Path, manifest: dict) -> dict:
    posts = _expected_posts(snapshot)
    routes = set(_routes(manifest))
    by_slug = {str(post.get("slug")): int(post["id"]) for post in _posts(snapshot) if post.get("slug") and str(post.get("id", "")).isdigit()}
    by_id = {str(post["id"]): int(post["id"]) for post in _posts(snapshot) if str(post.get("id", "")).isdigit()}
    wrong = multi = missing = extra = 0
    membership_count = {}
    category_samples: list[dict] = []
    missing_pagination_routes: list[str] = []
    for label, _variants in CATEGORY_DEFINITIONS:
        expected = [int(post["id"]) for post in posts if canonical_category(post) == label]
        expected_page_count = (len(expected) + PAGE_SIZE - 1) // PAGE_SIZE
        pages = _pages_for_prefix(routes, "/category/" + label, expected_page_count)
        observed: list[int] = []
        if expected and len(pages) != expected_page_count:
            missing += 1
        observed_numbers = {number for number, _route in pages}
        missing_page_routes = [
            f"/category/{label}/page/{number}"
            for number in range(2, expected_page_count + 1)
            if number not in observed_numbers
        ]
        missing_pagination_routes.extend(missing_page_routes)
        for _number, route in pages:
            ids, _ = _route_ids(root, route, by_slug, by_id)
            observed.extend(ids)
        missing_post_ids = sorted(set(expected) - set(observed))
        extra_post_ids = sorted(set(observed) - set(expected))
        missing += len(missing_post_ids)
        extra += len(extra_post_ids)
        wrong += sum(item not in set(expected) for item in observed)
        if (missing_page_routes or missing_post_ids or extra_post_ids) and len(category_samples) < 10:
            category_samples.append({
                "category": label,
                "expected_count": len(expected),
                "expected_page_count": expected_page_count,
                "observed_page_count": len(pages),
                "missing_page_routes": missing_page_routes,
                "missing_post_ids": missing_post_ids,
                "extra_post_ids": extra_post_ids,
            })
        for item in observed:
            membership_count[item] = membership_count.get(item, 0) + 1
    multi = sum(count > 1 for count in membership_count.values())
    expected_multi = sum(sum(canonical_category(post) == label for label, _ in CATEGORY_DEFINITIONS) > 1 for post in posts)
    return {"measured": True, "wrong_category_count": wrong, "multi_category_count": multi,
            "missing_category_membership": missing, "extra_category_membership": extra,
            "LISTING_PARITY_FAILURE_SAMPLES": [],
            "CATEGORY_PARITY_FAILURE_SAMPLES": category_samples,
            "MISSING_EXPECTED_PAGINATION_ROUTES": sorted(set(missing_pagination_routes)),
            "PASS": not any((wrong, multi, missing, extra, expected_multi))}


def latest_parity(snapshot: dict, root: Path, manifest: dict) -> dict:
    expected = [int(post["id"]) for post in _expected_posts(snapshot)]
    routes = set(_routes(manifest))
    by_slug = {str(post.get("slug")): int(post["id"]) for post in _posts(snapshot) if post.get("slug") and str(post.get("id", "")).isdigit()}
    by_id = {str(post["id"]): int(post["id"]) for post in _posts(snapshot) if str(post.get("id", "")).isdigit()}
    home_facts = _facts(_read_page(root, "/")) if "/" in routes else _facts("")
    home = [_id_for_href(href, by_slug, by_id) for href in home_facts.latest_rows]
    home = [item for item in home if item is not None]
    unknown = len(home_facts.latest_rows) - len(home)
    pages = _pages_for_prefix(routes, "/posts", (len(expected) + PAGE_SIZE - 1) // PAGE_SIZE)
    archive = []
    for _number, route in pages:
        ids, unrecognized = _route_ids(root, route, by_slug, by_id)
        unknown += unrecognized
        archive.extend(ids)
    home_ok = bool(home) and home == expected[:len(home)]
    archive_ok = archive == expected
    return {"measured": True, "latest_snapshot_post_id": expected[0] if expected else None,
            "home_first_post_id": home[0] if home else None,
            "home_latest_rows_checked": len(home),
            "home_latest_order_match": home_ok, "archive_latest_order_match": archive_ok,
            "unrecognized_cards": unknown, "PASS": home_ok and archive_ok and unknown == 0}


def seo_gate(snapshot: dict, root: Path, manifest: dict) -> dict:
    posts = _posts(snapshot)
    routes = _routes(manifest)
    post_failures = 0
    canonical_duplicates = 0
    workers_dev = 0
    canonical_seen: dict[str, str] = {}
    for route in routes:
        target = _route_file(root, route)
        if not target.is_file() or target.suffix.lower() != ".html":
            continue
        text = _read_page(root, route)
        facts = _facts(text)
        url_flags = _url_evidence(text, facts)
        workers_dev += int(url_flags["workers_dev"])
        if facts.canonicals:
            canonical = facts.canonicals[0]
            if canonical in canonical_seen and canonical_seen[canonical] != route:
                canonical_duplicates += 1
            canonical_seen[canonical] = route
        if route.startswith("/post/") and any(str(post.get("slug")) == unquote(route.removeprefix("/post/").rstrip("/")) for post in posts):
            post_failures += int(not facts.titles or not facts.titles[0].strip())
            post_failures += int(not facts.descriptions or not facts.descriptions[0].strip())
            post_failures += int(not facts.h1s or not facts.h1s[0].strip())
            post_failures += int(not facts.jsonld)
            post_failures += int(any("noindex" in value for value in facts.robots))
            post_failures += int(facts.canonicals != [_canonical_url(route)])
    robots_path = root / "robots.txt"
    sitemap_path = root / "sitemap.xml"
    robots = robots_path.read_text(encoding="utf-8") if robots_path.is_file() else ""
    robots_ok = bool(re.search(r"(?im)^\s*Sitemap:\s*" + re.escape(SITE + "/sitemap.xml") + r"\s*$", robots))
    sitemap_values: set[str] = set()
    try:
        tree = ET.parse(sitemap_path)
        for node in tree.iter():
            if node.tag.endswith("loc") and node.text:
                parsed = urlsplit(node.text.strip())
                sitemap_values.add((parsed.netloc.lower(), unquote(parsed.path).rstrip("/")))
    except (ET.ParseError, OSError):
        sitemap_values = set()
    missing_sitemap_posts = sum((urlsplit(SITE).netloc.lower(), "/post/" + str(post.get("slug")).strip("/")) not in sitemap_values for post in posts if post.get("slug"))
    return {"measured": True, "post_seo_failures": post_failures,
            "duplicate_canonicals": canonical_duplicates, "workers_dev_leaks": workers_dev,
            "robots_sitemap_directive": robots_ok, "missing_sitemap_posts": missing_sitemap_posts,
            "PASS": not any((post_failures, canonical_duplicates, workers_dev, missing_sitemap_posts)) and robots_ok}


def media_gate(snapshot: dict, root: Path, manifest: dict, media_manifest: dict) -> dict:
    posts = _posts(snapshot)
    routes = _routes(manifest)
    media_paths: set[str] = set()
    unresolved_urls = 0
    for route in routes:
        target = _route_file(root, route)
        if not target.is_file() or target.suffix.lower() != ".html":
            continue
        facts = _facts(_read_page(root, route))
        for value in facts.references:
            parsed = urlsplit(value)
            if parsed.path.startswith("/media/"):
                media_paths.add(unquote(parsed.path))
            elif "api.mahoonartmagazine.ir/media/" in value:
                unresolved_urls += 1

    records = media_manifest.get("records", []) if isinstance(media_manifest, dict) else []
    semantic_records = [
        record for record in records
        if isinstance(record, dict) and record.get("immutable_path") and not record.get("fallback")
    ]
    expected_by_path = {str(record["immutable_path"]): record for record in semantic_records}
    required_paths = sorted(media_paths | set(expected_by_path))
    missing = invalid = hash_mismatch = 0
    inventory = []
    for public_path in required_paths:
        target = root / public_path.lstrip("/")
        expected = expected_by_path.get(public_path, {})
        expected_mime = expected.get("detected_mime") or expected.get("mime")
        expected_sha256 = str(expected.get("sha256") or Path(public_path).stem).lower()
        expected_size = expected.get("size")
        if not target.is_file():
            missing += 1
            inventory.append({"path": public_path, "sha256": expected_sha256, "size": expected_size,
                              "mime": expected_mime, "present_in_sealed_artifact": False})
            continue
        data = target.read_bytes()
        detected = signature_mime(data)
        digest = __import__("hashlib").sha256(data).hexdigest()
        ext = target.suffix.lower()
        expected_ext = {
            "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
            "image/gif": ".gif", "audio/mpeg": ".mp3", "audio/ogg": ".ogg",
            "video/mp4": ".mp4",
        }.get(detected)
        signature_ok = bool(detected) and expected_ext == ext and (not expected_mime or detected == expected_mime)
        hash_ok = digest == target.stem.lower() and (not expected_sha256 or digest == expected_sha256)
        size_ok = expected_size is None or int(expected_size) == len(data)
        invalid += int(not signature_ok or not size_ok)
        hash_mismatch += int(not hash_ok)
        inventory.append({"path": public_path, "sha256": digest, "size": len(data),
                          "mime": detected, "present_in_sealed_artifact": True,
                          "signature_mime_pass": signature_ok, "hash_pass": hash_ok, "size_pass": size_ok})

    resolved_sources = {
        str(record.get("source_identifier")) for record in records
        if isinstance(record, dict) and record.get("source_identifier")
    }
    required_sources = {identity for post in posts for identity, _kind in source_identifiers(post)}
    media_sources = len(required_sources)
    unresolved_count = media_manifest.get("stats", {}).get("unresolved") if isinstance(media_manifest, dict) else None
    missing_sources = len(required_sources - resolved_sources)
    unresolved = int(unresolved_count) if isinstance(unresolved_count, int) else None
    semantic_missing = sorted(set(expected_by_path) - {
        entry["path"] for entry in inventory
        if entry["present_in_sealed_artifact"] and entry.get("hash_pass")
    })
    inventory_pass = not missing and not invalid and not hash_mismatch
    parity_pass = not semantic_missing and len(expected_by_path) <= len(inventory)
    return {
        "measured": True,
        "required_media_references": len(media_paths),
        "snapshot_media_sources": media_sources,
        "missing_media_files": missing,
        "invalid_media_signatures_or_mime": invalid,
        "media_hash_mismatches": hash_mismatch,
        "remote_media_api_references": unresolved_urls,
        "media_source_ids_missing_from_manifest": missing_sources,
        "media_manifest_unresolved": unresolved,
        "SEALED_MEDIA_INVENTORY": {
            "measured": True, "entries": inventory, "missing": missing,
            "invalid": invalid, "PASS": inventory_pass,
        },
        "SEMANTIC_TO_SEALED_MEDIA_PARITY": {
            "measured": True, "semantic_records": len(expected_by_path),
            "sealed_records": len(inventory), "missing": semantic_missing,
            "PASS": parity_pass,
        },
        "PASS": unresolved is not None and inventory_pass and parity_pass
        and not any((unresolved_urls, missing_sources, unresolved)),
    }

def evaluate_local_candidate(snapshot_path: Path, root: Path, route_manifest_path: Path,
                             media_manifest_path: Path) -> dict:
    _read_page.cache_clear()
    _facts.cache_clear()
    try:
        snapshot = json.loads(Path(snapshot_path).read_text(encoding="utf-8-sig"))
        manifest = json.loads(Path(route_manifest_path).read_text(encoding="utf-8"))
        media_manifest = json.loads(Path(media_manifest_path).read_text(encoding="utf-8"))
        root = Path(root)
        gates = {
            "content_parity": content_parity(snapshot, root, manifest),
            "listing_uniqueness": listing_uniqueness(snapshot, root, manifest),
            "category_parity": category_parity(snapshot, root, manifest),
            "latest_parity": latest_parity(snapshot, root, manifest),
            "seo": seo_gate(snapshot, root, manifest),
            "media": media_gate(snapshot, root, manifest, media_manifest),
        }
        return {"measured": True, "gates": gates,
                "PASS": all(result.get("measured") is True and result.get("PASS") is True for result in gates.values())}
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return {"measured": False, "PASS": False, "failure_class": type(exc).__name__,
                "failure": str(exc)[:300]}
    finally:
        _read_page.cache_clear()
        _facts.cache_clear()
