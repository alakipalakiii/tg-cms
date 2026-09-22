"""Derive a route manifest from the locked snapshot without losing old routes."""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote

try:
    from .content_taxonomy import CATEGORY_DEFINITIONS, canonical_category
    from .pagination_contract import PAGE_SIZE, page_count
    from .public_listing_dedupe import dedupe_public_listing_posts
except ImportError:
    from content_taxonomy import CATEGORY_DEFINITIONS, canonical_category
    from pagination_contract import PAGE_SIZE, page_count
    from public_listing_dedupe import dedupe_public_listing_posts

REQUIRED_CONTROL_ROUTES = {"/admin", "/admin/analytics"}
REQUIRED_CATEGORY_ROUTES = {f"/category/{label}" for label, _variants in CATEGORY_DEFINITIONS}
TAG_LINK_SAFE = "-_.!~*'()"


def snapshot_routes(posts: list[dict]) -> set[str]:
    routes: set[str] = set()
    for post in posts:
        post_id = str(post.get("id") or "").strip()
        slug = str(post.get("slug") or "").strip()
        if post_id.isdigit():
            routes.add(f"/post/{post_id}")
        if slug:
            routes.add(f"/post/{slug}")
    return routes


def snapshot_tag_routes(posts: list[dict]) -> set[str]:
    tags = {
        match.group(2)
        for post in posts
        for match in re.finditer(r"(^|\s)#([^\s#]+)", str(post.get("text") or ""), re.UNICODE | re.MULTILINE)
        if match.group(2)
    }
    return {"/tag/" + quote(tag, safe=TAG_LINK_SAFE) for tag in tags}


def snapshot_pagination_routes(posts: list[dict]) -> set[str]:
    logical_posts = dedupe_public_listing_posts(posts)
    routes = {"/posts"}
    for number in range(2, page_count(len(logical_posts)) + 1):
        routes.add(f"/posts/page/{number}")
    for label, _variants in CATEGORY_DEFINITIONS:
        routes.add(f"/category/{label}")
        members = [post for post in logical_posts if canonical_category(post) == label]
        for number in range(2, page_count(len(members)) + 1):
            routes.add(f"/category/{label}/page/{number}")
    return routes


def build_candidate_route_manifest(posts: list[dict], accepted_path: Path, output_path: Path) -> dict:
    accepted = json.loads(accepted_path.read_text(encoding="utf-8"))
    old_routes = {str(route) for route in accepted.get("routes", [])}
    current_routes = snapshot_routes(posts)
    current_tag_routes = snapshot_tag_routes(posts)
    current_pagination_routes = snapshot_pagination_routes(posts)
    snapshot_derived_routes = current_routes | current_tag_routes | current_pagination_routes
    required_routes = REQUIRED_CATEGORY_ROUTES | REQUIRED_CONTROL_ROUTES
    candidate_routes = sorted(old_routes | snapshot_derived_routes | required_routes)
    old_only = sorted(old_routes - snapshot_derived_routes - required_routes)
    new_routes = sorted(current_routes - old_routes)
    payload = {
        "contract": "CURRENT_CANDIDATE_SEALED_ROUTE_MANIFEST_V1",
        "route_count": len(candidate_routes),
        "routes": candidate_routes,
        "baseline_route_count": len(old_routes),
        "snapshot_derived_route_count": len(snapshot_derived_routes),
        "snapshot_post_route_count": len(current_routes),
        "snapshot_tag_route_count": len(current_tag_routes),
        "snapshot_pagination_route_count": len(current_pagination_routes),
        "required_category_routes": sorted(REQUIRED_CATEGORY_ROUTES),
        "required_control_routes": sorted(REQUIRED_CONTROL_ROUTES),
        "control_route_count": len(REQUIRED_CONTROL_ROUTES),
        "old_accepted_manifest_role": "NO_ROUTE_LOSS_BASELINE",
        "old_routes_missing_from_candidate": sorted(old_routes - set(candidate_routes)),
        "new_current_post_routes_included": sorted(current_routes & set(candidate_routes)),
        "new_snapshot_routes_missing_from_candidate": sorted(current_routes - set(candidate_routes)),
        "new_snapshot_tag_routes": sorted(current_tag_routes - old_routes),
        "new_snapshot_tag_routes_missing_from_candidate": sorted(current_tag_routes - set(candidate_routes)),
        "new_snapshot_pagination_routes": sorted(current_pagination_routes - old_routes),
        "new_snapshot_pagination_routes_missing_from_candidate": sorted(current_pagination_routes - set(candidate_routes)),
        "old_only_routes": old_only,
        "new_snapshot_routes": new_routes,
        "new_control_routes": sorted(REQUIRED_CONTROL_ROUTES - old_routes),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload
