"""Derive a route manifest from the locked snapshot without losing old routes."""
from __future__ import annotations

import json
from pathlib import Path


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


def build_candidate_route_manifest(posts: list[dict], accepted_path: Path, output_path: Path) -> dict:
    accepted = json.loads(accepted_path.read_text(encoding="utf-8"))
    old_routes = {str(route) for route in accepted.get("routes", [])}
    current_routes = snapshot_routes(posts)
    candidate_routes = sorted(old_routes | current_routes)
    old_only = sorted(old_routes - current_routes)
    new_routes = sorted(current_routes - old_routes)
    payload = {
        "contract": "CURRENT_CANDIDATE_SEALED_ROUTE_MANIFEST_V1",
        "route_count": len(candidate_routes),
        "routes": candidate_routes,
        "baseline_route_count": len(old_routes),
        "snapshot_derived_route_count": len(current_routes),
        "old_accepted_manifest_role": "NO_ROUTE_LOSS_BASELINE",
        "old_routes_missing_from_candidate": sorted(old_routes - set(candidate_routes)),
        "new_current_post_routes_included": sorted(current_routes & set(candidate_routes)),
        "new_snapshot_routes_missing_from_candidate": sorted(current_routes - set(candidate_routes)),
        "old_only_routes": old_only,
        "new_snapshot_routes": new_routes,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload
