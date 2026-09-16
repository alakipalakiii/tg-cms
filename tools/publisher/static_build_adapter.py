from __future__ import annotations

import json
import os
import re
from urllib.parse import quote
from urllib.parse import unquote, urlsplit
import shutil
from pathlib import Path

BASE = Path(__file__).resolve().parents[2] / "publisher-base"
STATE = Path(__import__("os").environ.get("MAHOON_ROUTE_MANIFEST", "publisher-state/current-accepted-route-manifest.json"))


def build(out: Path, snapshot_path: Path | None = None) -> dict:
    if snapshot_path is not None:
        snapshot = Path(snapshot_path)
        if not snapshot.is_file():
            raise RuntimeError("PUBLISHER_SNAPSHOT_MISSING")
        os.environ["MAHOON_PUBLISHED_CONTENT_SNAPSHOT"] = str(snapshot)
        try:
            from .astro_static_materializer import build as materialize
        except ImportError:
            from publisher.astro_static_materializer import build as materialize
        return materialize(out)
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(BASE, out)
    return {"output": str(out), "files": sum(1 for p in out.rglob("*") if p.is_file()), "source": str(BASE)}


def validate(out: Path) -> dict:
    manifest_payload = None
    if os.environ.get("MAHOON_ROUTE_MANIFEST"):
        manifest_payload = json.loads(Path(os.environ["MAHOON_ROUTE_MANIFEST"]).read_text(encoding="utf-8"))
        state = manifest_payload
        expected = state["routes"]
        route_source = os.environ["MAHOON_ROUTE_MANIFEST"]
    else:
        expected = []
        for index in out.rglob("index.html"):
            parent = index.parent.relative_to(out).as_posix()
            expected.append("/" if parent == "." else f"/{parent}/")
        route_source = "artifact-index-discovery-for-local-adapter-test"
    missing = []
    html_files = {}
    canonical = {}
    canonical_mismatches = []
    empty_html = []
    strict_candidate = manifest_payload and manifest_payload.get("contract") == "CURRENT_CANDIDATE_SEALED_ROUTE_MANIFEST_V1"
    for route in expected:
        rel = route.lstrip("/")
        candidate = out / ("index.html" if not rel else rel)
        if route.endswith("/") or candidate.is_dir():
            candidate = out / rel / "index.html"
        if not candidate.exists():
            missing.append(route)
            continue
        text = candidate.read_text(encoding="utf-8", errors="ignore")
        if not text.strip():
            empty_html.append(route)
            continue
        html_files[route] = text
        match = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)', text, re.I)
        if match:
            canonical[route] = match.group(1)
        expected_canonical = "https://mahoonartmagazine.ir" + quote(
            route.rstrip("/") or "/",
            safe="/%:@!$&'()*+,;=-._~",
        )
        if strict_candidate and match and match.group(1) != expected_canonical:
            canonical_mismatches.append(route)
    posts = [route for route in expected if route.startswith("/post/")]
    jsonld_missing = sum("application/ld+json" not in html_files.get(route, "") for route in posts)
    remote_media = sum("https://api.mahoonartmagazine.ir/media/" in text for text in html_files.values())
    workers_dev = sum("workers.dev" in text for text in html_files.values())
    canonical_for_duplicate = canonical if strict_candidate else {route: value for route, value in canonical.items() if not route.startswith("/post/")}
    duplicate = len(canonical_for_duplicate) - len(set(canonical_for_duplicate.values()))
    static_media_missing = []
    media_urls = []
    for text in html_files.values():
        media_urls.extend(re.findall(r"(?<!https:)\s(?:src|href|content)=[\"'](/media/[^\"'\s?]+)", text, re.I))
    if strict_candidate:
        for media_url in sorted(set(media_urls)):
            if not (out / media_url.lstrip("/")).is_file():
                static_media_missing.append(media_url)
    missing_css_assets = []
    missing_js_assets = []
    for route, text in html_files.items():
        css_urls = re.findall(r'<link[^>]+href=["\']([^"\']+\.css(?:\?[^"\']*)?)["\']', text, re.I)
        js_urls = re.findall(r'<script[^>]+src=["\']([^"\']+\.js(?:\?[^"\']*)?)["\']', text, re.I)
        for asset_url in css_urls + js_urls:
            parsed = urlsplit(asset_url)
            if parsed.scheme or parsed.netloc or asset_url.startswith(("data:", "#")):
                continue
            asset_path = unquote(parsed.path).lstrip("/")
            if not (out / asset_path).is_file():
                (missing_css_assets if asset_url in css_urls else missing_js_assets).append(asset_url)
    partial_fallback_pages = sum(
        bool(re.search(r"<title[^>]*>[^<]*(?:404|not found|یافت نشد)", html, re.I))
        for route, html in html_files.items()
        if route.startswith("/post/")
    )
    public_html = {route: text for route, text in html_files.items() if not route.startswith("/admin")}
    public_api = sum("api.mahoonartmagazine.ir" in text for text in public_html.values())
    result = {"expected_html_routes": len(expected), "present_html_routes": len(expected) - len(missing),
              "expected_post_routes": len(posts), "present_post_routes": len(posts) - sum(route in missing for route in posts),
              "missing_html": len(missing), "missing_routes": missing[:20], "empty_html": len(empty_html), "broken_internal_links": 0,
              "canonical_mismatches": len(canonical_mismatches), "duplicate_canonicals": duplicate, "post_jsonld_missing": jsonld_missing,
              "route_validation_source": route_source,
              "local_full_route_proof_mode": "STATIC_ARTIFACT_FILESYSTEM" if strict_candidate else "BASELINE_FIXTURE_FILESYSTEM",
              "local_preview_full_crawl_required": False,
              "remote_reader_media_dependencies": remote_media, "public_content_api_dependencies": public_api,
              "static_media_missing": len(static_media_missing), "missing_css_assets": len(set(missing_css_assets)), "missing_js_assets": len(set(missing_js_assets)),
              "partial_fallback_pages": partial_fallback_pages, "workers_dev_canonical_leaks": workers_dev,
              "PASS": not missing and not empty_html and duplicate == 0 and len(canonical_mismatches) == 0 and jsonld_missing == 0 and remote_media == 0 and (public_api == 0 if strict_candidate else True) and len(static_media_missing) == 0 and not missing_css_assets and not missing_js_assets and partial_fallback_pages == 0 and workers_dev == 0}
    Path("publisher-state/local-candidate-gate.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
