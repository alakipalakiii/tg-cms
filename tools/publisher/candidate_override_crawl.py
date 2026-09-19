"""Measured full-route and snapshot-parity crawl for a sealed Static candidate."""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlsplit

try:
    from .content_taxonomy import CATEGORY_DEFINITIONS, canonical_category
    from .promotion_gates import _expected_posts, _id_for_href, _posts, _url_evidence
    from .remote_proof_harness import (
        category_page_matches, classify_link_target,
        is_worker_first_route, link_contract_fails, request_with_version_pinning,
    )
except ImportError:
    from content_taxonomy import CATEGORY_DEFINITIONS, canonical_category
    from promotion_gates import _expected_posts, _id_for_href, _posts, _url_evidence
    from remote_proof_harness import (
        category_page_matches, classify_link_target,
        is_worker_first_route, link_contract_fails, request_with_version_pinning,
    )

SOURCE = Path(os.environ.get("MAHOON_ASSETS_DIRECTORY", "publisher-base"))
ROOT = Path(os.environ.get("MAHOON_CRAWL_OUTPUT", "publisher-state/override-crawl"))
OUT = ROOT / "production-override-crawl"
STATE_PATH = OUT / "production-override-crawl-state.json"
BASE = os.environ.get("MAHOON_CRAWL_BASE", os.environ.get("MAHOON_PRODUCTION_ORIGIN", "https://mahoonartmagazine.ir")).rstrip("/")
WORKER = os.environ.get("MAHOON_OVERRIDE_WORKER", "mahoon-art-magazine")
VERSION = os.environ.get("MAHOON_CANDIDATE_VERSION", "")
ROUTES_PATH = Path(os.environ.get("MAHOON_ROUTE_MANIFEST", "publisher-state/current-accepted-route-manifest.json"))
SNAPSHOT_PATH = Path(os.environ.get("MAHOON_PUBLISHED_CONTENT_SNAPSHOT", "runner-evidence/current-v2-snapshot.json"))
EXPECTATIONS_PATH = Path(os.environ["MAHOON_REMOTE_EXPECTATIONS"]) if os.environ.get("MAHOON_REMOTE_EXPECTATIONS") else None
MEDIA_PATH = Path(os.environ.get("MAHOON_MEDIA_MANIFEST", "publisher-state/production-media-manifest.json"))
UA = "MAHOON-M10-Measured-Static-Candidate-Crawl/1.0"
PAGE_SIZE = 20


def _send_version_override() -> bool:
    return bool(VERSION) and os.environ.get("MAHOON_DISABLE_VERSION_OVERRIDE") != "1"


def _version_attribution_required() -> bool:
    return bool(VERSION)


def _requires_version_attribution(path: str) -> bool:
    return bool(VERSION) and is_worker_first_route(path)


def _url(path: str) -> str:
    return BASE + quote("/" + path.lstrip("/"), safe="/%:@!$&'()*+,;=-._~")


def _is_html_route(path: str) -> bool:
    return Path(urlsplit(path).path).suffix.lower() not in {".txt", ".xml", ".json", ".ico", ".svg", ".png", ".jpg", ".mp3", ".mp4", ".webp"}


def routes() -> list[str]:
    manifest = json.loads(ROUTES_PATH.read_text(encoding="utf-8"))
    values = manifest.get("routes") if isinstance(manifest, dict) else None
    if not isinstance(values, list) or not values or not all(isinstance(route, str) for route in values):
        raise ValueError("candidate route manifest is empty or invalid")
    return sorted(set(values))


def _crawl_headers() -> dict[str, str]:
    return {"User-Agent": UA, "Accept": "text/html,application/json,application/xml,text/plain,*/*"}


def _pinned_request(url: str, method: str = "GET") -> dict:
    path = urlsplit(url).path
    worker_first = is_worker_first_route(path)
    send_override = _send_version_override() and worker_first
    return request_with_version_pinning(
        url, worker=WORKER, version=VERSION, method=method, headers=_crawl_headers(),
        send_version_override=send_override,
        require_actual_version=bool(VERSION) and worker_first,
        cache_bust_nonce=uuid.uuid4().hex if send_override else None,
    )


def fetch_url(url: str) -> dict:
    last = None
    for attempt, delay in enumerate((0, 2, 5, 10), 1):
        if delay:
            time.sleep(delay)
        try:
            proof = _pinned_request(url)
            if proof["status"] >= 500 or proof["status"] == 408:
                last = {"status": "RETRY_PENDING", "http_status": proof["status"], "attempts": attempt,
                        "error_class": "TRANSIENT_HTTP_ERROR", "redirect_loop": False}
                continue
            body = proof["body"]
            content_type = proof["content_type"]
            text = body.decode("utf-8", "replace") if content_type.startswith(("text/", "application/json", "application/xml")) else ""
            facts = None
            if content_type == "text/html":
                try:
                    from .promotion_gates import _facts
                except ImportError:
                    from promotion_gates import _facts
                facts = _facts(text)
            url_evidence = _url_evidence(text, facts) if facts else {
                "workers_dev": False, "preview_url": False, "remote_media": False
            }
            attribution_required = proof.get(
                "actual_version_required",
                _requires_version_attribution(urlsplit(url).path),
            )
            attribution_ok = proof["version_attribution_status"] == "PROVEN" if attribution_required else True
            return {
                "status": "PASS" if proof["status"] == 200 and attribution_ok else "FAIL",
                "http_status": proof["status"], "final_url": proof["final_url"],
                "content_type": content_type, "bytes": len(body), "attempts": attempt,
                "is_html": content_type == "text/html",
                "canonical": facts.canonicals[0] if facts and facts.canonicals else "",
                "title": bool(facts and facts.titles and facts.titles[0].strip()),
                "h1": bool(facts and facts.h1s and facts.h1s[0].strip()),
                "meta": bool(facts and facts.descriptions and facts.descriptions[0].strip()),
                "og": bool(re.search(r'<meta[^>]+(?:property|name)=["\']og:', text, re.I)),
                "jsonld": bool(facts and facts.jsonld),
                "robots_noindex": bool(facts and any("noindex" in value for value in facts.robots)),
                **url_evidence,
                "card_routes": facts.cards if facts else [],
                "latest_rows": facts.latest_rows if facts else [],
                "anchor_links": facts.anchors if facts else [],
                "requested_version": VERSION or None,
                "actual_version": proof["actual_version"],
                "version_attribution_status": proof["version_attribution_status"],
                "override_preserved_on_every_hop": proof["override_preserved_on_every_hop"],
                "override_header_sent": proof.get("override_header_sent", False),
                "redirect_hop_count": proof["redirect_hop_count"],
                "redirect_chain": proof["redirect_chain"],
                "cache_busted": proof["cache_busted"],
                "cf_cache_status": proof["headers"].get("CF-Cache-Status"),
                "body_sha256": hashlib.sha256(body).hexdigest(),
                **({} if attribution_ok else {"error_class": "VERSION_ATTRIBUTION_MISSING_OR_MISMATCH"}),
            }
        except Exception as exc:
            last = {"status": "RETRY_PENDING", "http_status": None, "attempts": attempt,
                    "error_class": type(exc).__name__, "error": str(exc)[:300], "redirect_loop": False}
    return last or {"status": "FAIL", "http_status": None, "attempts": 4, "error_class": "UNKNOWN", "redirect_loop": False}


def fetch(path: str) -> dict:
    return fetch_url(_url(path))


def _save(state: dict) -> None:
    tmp = STATE_PATH.with_suffix(".json.part")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def _route_id_map(posts: list[dict]) -> tuple[dict[str, int], dict[str, int]]:
    by_slug = {str(post.get("slug")): int(post["id"]) for post in posts if post.get("slug") and str(post.get("id", "")).isdigit()}
    by_id = {str(post["id"]): int(post["id"]) for post in posts if str(post.get("id", "")).isdigit()}
    return by_slug, by_id


def _page_routes(all_routes: set[str], prefix: str, pages: int) -> list[tuple[int, str]]:
    base = prefix.rstrip("/")
    result = []
    route = base if base in all_routes else base + "/" if base + "/" in all_routes else None
    if route:
        result.append((1, route))
    for value in all_routes:
        match = re.fullmatch(re.escape(base) + r"/page/(\d+)/?", value)
        if match and 2 <= int(match.group(1)) <= pages:
            result.append((int(match.group(1)), value))
    return sorted(result)


def _ids(hrefs: list[str], by_slug: dict[str, int], by_id: dict[str, int]) -> list[int]:
    return [value for href in hrefs if (value := _id_for_href(href, by_slug, by_id)) is not None]


def _head_media(path: str) -> dict:
    try:
        proof = request_with_version_pinning(
            _url(path), worker=WORKER,
            version=VERSION,
            send_version_override=False, require_actual_version=False,
            headers=_crawl_headers(), method="HEAD", timeout=30,
        )
        return {"status": proof["status"], "content_type": proof["content_type"]}
    except Exception as exc:
        return {"status": None, "error_class": type(exc).__name__}


def _measure_link_targets(route_list: list[str], state: dict) -> dict[str, dict]:
    route_set = set(route_list)
    targets: dict[str, str] = {}
    for source_route, value in state.get("routes", {}).items():
        for href in value.get("anchor_links", []):
            kind, path = classify_link_target(urljoin(BASE + source_route, href), BASE, route_set)
            if kind != "EXTERNAL_OTHER":
                targets[path] = kind

    checks: dict[str, dict] = {}
    pending: list[tuple[str, str]] = []
    for path, kind in targets.items():
        if path in route_set:
            route = state.get("routes", {}).get(path, {})
            checks[path] = {"status": route.get("http_status"), "content_type": route.get("content_type"), "source": "manifest"}
        else:
            pending.append((path, kind))

    def check_target(item: tuple[str, str]) -> tuple[str, dict]:
        path, kind = item
        if kind in {"STATIC_MEDIA", "STATIC_ASSET"}:
            return path, {**_head_media(path), "source": "http_head"}
        route = fetch_url(_url(path))
        status = route.get("http_status")
        if _requires_version_attribution(path) and route.get("version_attribution_status") != "PROVEN":
            status = None
        return path, {
            "status": status, "content_type": route.get("content_type"),
            "version_attribution_status": route.get("version_attribution_status"), "source": "pinned_http_get",
        }

    if pending:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            checks.update(executor.map(check_target, pending))
    return checks


def _measure(route_list: list[str], state: dict, snapshot: dict, search_result: dict,
             media_manifest: dict) -> dict:
    minimized = snapshot.get("contract") == "MAHOON_REMOTE_EXPECTATIONS_V1"
    if minimized:
        posts = snapshot.get("posts", [])
        expected_ids = [int(value) for value in snapshot.get("listing_ids", [])]
        expected_categories = snapshot.get("category_ids", {})
    else:
        posts = _posts(snapshot)
        logical = _expected_posts(snapshot)
        expected_ids = [int(post["id"]) for post in logical]
        expected_categories = {
            label: [int(post["id"]) for post in logical if canonical_category(post) == label]
            for label, _variants in CATEGORY_DEFINITIONS
        }
    by_slug, by_id = _route_id_map(posts)
    route_set = set(route_list)
    post_source_routes = {f"/post/{post['id']}" for post in posts if str(post.get("id", "")).isdigit()}
    post_source_routes.update(f"/post/{post['slug']}" for post in posts if post.get("slug"))
    observed_post_routes = {route for route in route_set if route.startswith("/post/")}
    missing_source_routes = post_source_routes - observed_post_routes
    unexpected_routes = observed_post_routes - post_source_routes
    route_status_failures = [path for path in route_list if state["routes"].get(path, {}).get("http_status") != 200]
    html_routes = [path for path in route_list if _is_html_route(path)]
    html = {path: state["routes"].get(path, {}) for path in html_routes}
    html_failures = [path for path in html_routes if html[path].get("http_status") != 200 or html[path].get("is_html") is not True]
    post_route_failures = [path for path in post_source_routes if state["routes"].get(path, {}).get("http_status") != 200]
    canonical_by_route = {path: value.get("canonical") for path, value in html.items() if value.get("canonical")}
    duplicate_canonicals = len(canonical_by_route) - len(set(canonical_by_route.values()))
    workers_dev = sum(int(bool(value.get("workers_dev"))) for value in html.values())
    preview_leaks = sum(int(bool(value.get("preview_url"))) for value in html.values())
    reader_media = sum(int(bool(value.get("remote_media"))) for value in html.values())
    post_seo_failures = 0
    canonical_failures = 0
    for post in posts:
        route = f"/post/{post.get('slug')}"
        value = html.get(route, {})
        canonical_failures += int(value.get("canonical") != _url(route))
        post_seo_failures += sum(not value.get(key) for key in ("title", "h1", "meta", "og", "jsonld"))
        post_seo_failures += int(bool(value.get("robots_noindex")))
    post_jsonld_missing = sum(
        not html.get(f"/post/{post.get('slug')}", {}).get("jsonld")
        for post in posts if post.get("slug")
    )
    link_checks = state.get("link_checks", {})
    link_kind_counts: dict[str, int] = {}
    broken_link_targets: list[dict] = []
    false_positive_link_targets: set[str] = set()
    for route, value in html.items():
        for href in value.get("anchor_links", []):
            kind, path = classify_link_target(urljoin(BASE + route, href), BASE, route_set)
            link_kind_counts[kind] = link_kind_counts.get(kind, 0) + 1
            if kind == "EXTERNAL_OTHER":
                continue
            check = link_checks.get(path)
            if check is None and path in route_set:
                route_check = state.get("routes", {}).get(path, {})
                check = {"status": route_check.get("http_status"), "content_type": route_check.get("content_type")}
            if check is None:
                broken_link_targets.append({"path": path, "kind": kind, "reason": "UNVERIFIED_TARGET"})
                continue
            if path not in route_set and check.get("status") == 200:
                false_positive_link_targets.add(path)
            if link_contract_fails(kind, check.get("status"), check.get("content_type", "")):
                broken_link_targets.append({"path": path, "kind": kind, "status": check.get("status"), "content_type": check.get("content_type")})
    # A repeated href to the same failed destination is one broken destination, not an inflated count.
    broken_link_targets = list({item["path"]: item for item in broken_link_targets}.values())
    broken_links = len(broken_link_targets)
    redirect_loops = sum(int(bool(value.get("redirect_loop"))) for value in state["routes"].values())
    search_ok = search_result.get("http_status") == 200 and isinstance(search_result.get("records"), list)
    search_records = search_result.get("records", []) if search_ok else []
    search_ids = [int(item["id"]) for item in search_records if str(item.get("id", "")).isdigit()]
    search_duplicate = len(search_ids) - len(set(search_ids))
    search_parity_failures = int(search_ids != expected_ids)
    missing_canonical_count = len(missing_source_routes)
    card_ids_by_route = {path: _ids(value.get("card_routes", []), by_slug, by_id) for path, value in html.items()}
    duplicate_card_ids = sum(len(ids) - len(set(ids)) for ids in card_ids_by_route.values())
    overlap = 0
    coverage_failures = 0
    page_count = (len(expected_ids) + PAGE_SIZE - 1) // PAGE_SIZE
    archive_pages = _page_routes(route_set, "/posts", page_count)
    archive_ids = []
    seen: set[int] = set()
    for page_number, route in archive_pages:
        ids = card_ids_by_route.get(route, [])
        overlap += len(seen.intersection(ids))
        seen.update(ids)
        archive_ids.extend(ids)
        if ids != expected_ids[(page_number - 1) * PAGE_SIZE:page_number * PAGE_SIZE]:
            coverage_failures += 1
    coverage_failures += int(len(archive_pages) != page_count)
    home_rows = html.get("/", {}).get("latest_rows", [])
    home_ids = _ids(home_rows, by_slug, by_id)
    home_latest_pass = bool(home_ids) and home_ids == expected_ids[:len(home_ids)]
    latest_pass = home_latest_pass and archive_ids == expected_ids
    category_wrong = category_missing = category_extra = category_multi = category_overlap = 0
    category_memberships: dict[int, int] = {}
    category_sequences: dict[str, list[int]] = {}
    for label, _variants in CATEGORY_DEFINITIONS:
        expected = [int(value) for value in expected_categories.get(label, [])]
        required_pages = max(1, (len(expected) + PAGE_SIZE - 1) // PAGE_SIZE)
        pages = _page_routes(route_set, "/category/" + label, required_pages)
        sequence = []
        page_seen: set[int] = set()
        for page_number, route in pages:
            ids = card_ids_by_route.get(route, [])
            category_overlap += len(page_seen.intersection(ids))
            page_seen.update(ids)
            sequence.extend(ids)
            expected_page_ids = expected[(page_number - 1) * PAGE_SIZE:page_number * PAGE_SIZE]
            if not category_page_matches(
                route in route_set, expected_page_ids, ids,
                state.get("routes", {}).get(route, {}).get("http_status"),
            ):
                category_wrong += 1
        if len(pages) != required_pages:
            category_missing += 1
        category_missing += len(set(expected) - set(sequence))
        category_extra += len(set(sequence) - set(expected))
        category_sequences[label] = sequence
        for post_id in sequence:
            category_memberships[post_id] = category_memberships.get(post_id, 0) + 1
    category_multi = sum(count > 1 for count in category_memberships.values())
    category_overlap += len([post_id for post_id, count in category_memberships.items() if count > 1])
    all_listing_ids = {post_id for ids in card_ids_by_route.values() for post_id in ids}
    orphan_posts = len(set(expected_ids) - (all_listing_ids | set(search_ids)))
    robots = state["routes"].get("/robots.txt", {}).get("robots_sitemap", False)
    sitemap_urls = state["routes"].get("/sitemap.xml", {}).get("sitemap_posts", [])
    sitemap_paths = set(sitemap_urls)
    missing_sitemap_posts = sum(f"/post/{post.get('slug')}" not in sitemap_paths for post in posts if post.get("slug"))
    media_records = media_manifest.get("records", []) if isinstance(media_manifest, dict) else []
    media_paths = sorted({str(item.get("immutable_path")) for item in media_records if isinstance(item, dict) and item.get("immutable_path") and not item.get("fallback")})
    media_responses: dict[str, dict] = {}
    if media_paths:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            media_responses = dict(zip(media_paths, executor.map(_head_media, media_paths)))
    media_http_failures = sum(result.get("status") != 200 for result in media_responses.values())
    media_unresolved = media_manifest.get("stats", {}).get("unresolved") if isinstance(media_manifest, dict) else None
    if not isinstance(media_unresolved, int):
        media_unresolved = None
    attribution_required = bool(VERSION)
    version_attribution_failures = sum(
        value.get("version_attribution_status") != "PROVEN" or value.get("actual_version") != VERSION
        for path, value in state["routes"].items() if _requires_version_attribution(path)
    ) if attribution_required else 0
    override_header_sent = any(bool(value.get("override_header_sent")) for value in state["routes"].values())
    all_status = len(route_status_failures) == 0 and version_attribution_failures == 0
    route_parity = all_status and not missing_source_routes and not unexpected_routes and not html_failures and not post_route_failures
    content_pass = route_parity and canonical_failures == 0 and search_parity_failures == 0 and search_duplicate == 0
    listing_pass = not any((duplicate_card_ids, search_duplicate, overlap, category_overlap, orphan_posts, coverage_failures))
    category_pass = not any((category_wrong, category_missing, category_extra, category_multi, category_overlap))
    seo_pass = not any((post_seo_failures, duplicate_canonicals, canonical_failures, workers_dev, missing_sitemap_posts)) and robots
    media_pass = media_unresolved == 0 and media_http_failures == 0 and not reader_media
    return {
        "measured": True,
        "html_routes": len(html_routes), "html_final_200": len(html_routes) - len(html_failures),
        "all_manifest_routes": len(route_list), "manifest_routes_final_200": len(route_list) - len(route_status_failures),
        "expected_route_count": len(route_list), "present_route_count": len(route_list) - len(route_status_failures),
        "missing_routes": [path for path in route_list if state["routes"].get(path, {}).get("http_status") != 200],
        "post_routes": len(post_source_routes), "post_final_200": len(post_source_routes) - len(post_route_failures),
        "broken_critical_links": broken_links, "orphan_posts": orphan_posts,
        "broken_critical_link_samples": broken_link_targets[:25],
        "link_target_class_counts": link_kind_counts,
        "broken_link_false_positive_targets": len(false_positive_link_targets),
        "unverified_link_targets": sum(item.get("reason") == "UNVERIFIED_TARGET" for item in broken_link_targets),
        "version_attribution_failures": version_attribution_failures,
        "remote_crawler_version_pinning": {
            "required_version": VERSION or None,
            "attribution_required": "YES" if attribution_required else "NO",
            "override_sent": "YES" if override_header_sent else "NO",
            "override_expected": "YES" if _send_version_override() else "NO",
            "PASS": not attribution_required or version_attribution_failures == 0,
        },
        "duplicate_canonicals": duplicate_canonicals, "duplicate_listing_ids": duplicate_card_ids,
        "pagination_overlap": overlap + category_overlap, "listing_page_parity_failures": coverage_failures,
        "category_wrong_membership": category_wrong, "category_missing_membership": category_missing,
        "category_extra_membership": category_extra, "category_multi_membership": category_multi,
        "latest_home_pass": home_latest_pass, "latest_archive_pass": archive_ids == expected_ids,
        "redirect_loops": redirect_loops, "remote_reader_media_dependencies": reader_media,
        "workers_dev_leaks": workers_dev, "preview_url_leaks": preview_leaks,
        "post_seo_failures": post_seo_failures, "canonical_failures": canonical_failures,
        "post_jsonld_missing": post_jsonld_missing,
        "search_index_ids": len(search_ids), "search_index_duplicate_ids": search_duplicate,
        "search_index_parity_failures": search_parity_failures,
        "robots_sitemap_directive": bool(robots), "missing_sitemap_posts": missing_sitemap_posts,
        "required_remote_media_objects": len(media_paths), "remote_media_http_failures": media_http_failures,
        "media_manifest_unresolved": media_unresolved,
        "expected_media_source_count": snapshot.get("media_source_count") if minimized else None,
        "gates": {
            "remote_route_parity": {"measured": True, "PASS": route_parity},
            "remote_content_parity": {"measured": True, "PASS": content_pass},
            "remote_listing_uniqueness": {"measured": True, "PASS": listing_pass},
            "remote_category_parity": {"measured": True, "PASS": category_pass},
            "remote_latest_parity": {"measured": True, "PASS": latest_pass},
            "remote_seo": {"measured": True, "PASS": seo_pass},
            "remote_media": {"measured": media_unresolved is not None, "PASS": media_pass},
            "remote_broken_critical_links": {"measured": True, "PASS": broken_links == 0},
        },
        "PASS": all_status and all(gate["measured"] and gate["PASS"] for gate in {
            "route": {"measured": True, "PASS": route_parity},
            "content": {"measured": True, "PASS": content_pass},
            "listing": {"measured": True, "PASS": listing_pass},
            "category": {"measured": True, "PASS": category_pass},
            "latest": {"measured": True, "PASS": latest_pass},
            "seo": {"measured": True, "PASS": seo_pass},
            "media": {"measured": media_unresolved is not None, "PASS": media_pass},
            "links": {"measured": True, "PASS": broken_links == 0},
        }.values()),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    expected = routes()
    snapshot = json.loads((EXPECTATIONS_PATH or SNAPSHOT_PATH).read_text(encoding="utf-8-sig"))
    if EXPECTATIONS_PATH and snapshot.get("contract") != "MAHOON_REMOTE_EXPECTATIONS_V1":
        raise ValueError("remote proof expectations contract is invalid")
    media_manifest = json.loads(MEDIA_PATH.read_text(encoding="utf-8")) if MEDIA_PATH.is_file() else {}
    route_hash = hashlib.sha256(json.dumps(expected, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    state = {"base": BASE, "override_worker": WORKER,
             "override_version": VERSION if _send_version_override() else "PRODUCTION",
             "version_attribution_protocol": "CF_VERSION_METADATA_V1",
             "route_hash": route_hash, "routes": {path: {"status": "PENDING"} for path in expected}}
    if STATE_PATH.exists():
        old = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if (old.get("base") == state["base"] and old.get("override_worker") == WORKER
                and old.get("override_version") == state["override_version"]
                and old.get("version_attribution_protocol") == state["version_attribution_protocol"]
                and old.get("route_hash") == route_hash):
            for path in expected:
                prior = old.get("routes", {}).get(path, {})
                attribution_checkpoint_valid = (
                    prior.get("version_attribution_status") == "PROVEN"
                    and prior.get("actual_version") == VERSION
                    if _requires_version_attribution(path)
                    else prior.get("version_attribution_status") in {"NOT_REQUIRED", "PROVEN"}
                )
                if (prior.get("status") == "PASS" and prior.get("http_status") == 200
                        and attribution_checkpoint_valid):
                    state["routes"][path] = prior
    pending = [path for path in expected if state["routes"][path].get("status") != "PASS"]
    _save(state)
    print(json.dumps({"expected_routes": len(expected), "checkpoint_pass": len(expected) - len(pending), "pending": len(pending), "route_hash": route_hash}, ensure_ascii=False), flush=True)
    workers = max(1, min(12, int(os.environ.get("MAHOON_REMOTE_CRAWL_WORKERS", "8"))))
    systemic_failure = False
    for start in range(0, len(pending), 80):
        batch = pending[start:start + 80]
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            results = list(executor.map(fetch, batch))
        for path, result in zip(batch, results):
            state["routes"][path] = result
        _save(state)
        failures = [item for item in results if item.get("status") != "PASS"]
        # Stop spending time on thousands of requests when a whole batch shows
        # the same systemic outage; retain an explicit failure record per route.
        if len(failures) >= max(10, int(len(batch) * 0.8)):
            classes = {item.get("error_class", item.get("http_status")) for item in failures}
            systemic_failure = len(classes) == 1
            if systemic_failure:
                for remaining in pending[start + len(batch):]:
                    state["routes"][remaining] = {
                        "status": "FAIL", "http_status": None,
                        "error_class": "SYSTEMIC_FAILURE_NOT_ATTEMPTED",
                    }
                _save(state)
        summary = {"batch_start": start, "batch_size": len(batch),
                   "pass_total": sum(item.get("status") == "PASS" for item in state["routes"].values()),
                   "fail_total": sum(item.get("status") == "FAIL" for item in state["routes"].values()),
                   "retry_pending": sum(item.get("status") == "RETRY_PENDING" for item in state["routes"].values()),
                   "systemic_failure": systemic_failure, "bounded_workers": workers}
        (OUT / f"batch-{start // 50 + 1:03d}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False), flush=True)
        if systemic_failure:
            break
    search_result = fetch("/search/search-index.json")
    if search_result.get("http_status") == 200:
        try:
            search_body = _pinned_request(_url("/search/search-index.json"))
            if _requires_version_attribution("/search/search-index.json") and search_body["version_attribution_status"] != "PROVEN":
                raise ValueError("search index response version attribution is not proven")
            search_result["records"] = json.loads(search_body["body"].decode("utf-8")).get("records", [])
        except Exception as exc:
            search_result["records"] = []
            search_result["search_parse_error"] = type(exc).__name__
    sitemap = state["routes"].get("/sitemap.xml", {})
    robots = state["routes"].get("/robots.txt", {})
    # Re-read only small text resources to measure their actual returned contents.
    for path, target in (("/sitemap.xml", sitemap), ("/robots.txt", robots)):
        try:
            proof = _pinned_request(_url(path))
            if _requires_version_attribution(path) and proof["version_attribution_status"] != "PROVEN":
                raise ValueError("control resource response version attribution is not proven")
            body = proof["body"].decode("utf-8", "replace")
            if path.endswith("robots.txt"):
                target["robots_sitemap"] = bool(re.search(r"(?im)^\s*Sitemap:\s*" + re.escape(BASE + "/sitemap.xml") + r"\s*$", body))
            else:
                target["sitemap_posts"] = [unquote(urlsplit(value).path).rstrip("/") for value in re.findall(r"<loc>\s*([^<]+)\s*</loc>", body, re.I) if "/post/" in value]
        except Exception:
            target["robots_sitemap"] = False
            target["sitemap_posts"] = []
    state["link_checks"] = _measure_link_targets(expected, state)
    result = _measure(expected, state, snapshot, search_result, media_manifest)
    state["supplemental_search"] = {key: value for key, value in search_result.items() if key != "records"}
    _save(state)
    result["html_routes"] = sum(1 for path in expected if _is_html_route(path))
    result["html_final_200"] = sum(1 for path in expected if _is_html_route(path) and state["routes"][path].get("http_status") == 200 and state["routes"][path].get("is_html"))
    summary_path = OUT / "production-override-crawl-summary.json"
    summary_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
