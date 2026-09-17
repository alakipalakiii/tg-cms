from __future__ import annotations

import json
import os
import re
from urllib.parse import quote, urljoin
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
    canonical = {}
    canonical_mismatches = []
    empty_html = []
    posts = [route for route in expected if route.startswith("/post/")]
    jsonld_missing = 0
    remote_media = 0
    workers_dev = 0
    public_api = 0
    partial_fallback_pages = 0
    media_urls = []
    missing_css_assets = []
    missing_js_assets = []
    checked_css_assets = set()
    checked_js_assets = set()
    broken_internal = set()
    strict_candidate = manifest_payload and manifest_payload.get("contract") == "CURRENT_CANDIDATE_SEALED_ROUTE_MANIFEST_V1"
    for route in expected:
        rel = unquote(route.lstrip("/"))
        candidate = out / ("index.html" if not rel else rel)
        if route.endswith("/") or candidate.is_dir():
            candidate = out / rel / "index.html"
        if not candidate.exists():
            missing.append(route)
            continue
        text = candidate.read_text(encoding="utf-8", errors="ignore")
        try:
            from .promotion_gates import _facts, _url_evidence
        except ImportError:
            from promotion_gates import _facts, _url_evidence
        page_facts = _facts(text, "references")
        url_flags = _url_evidence(text, page_facts)
        for reference in page_facts.references:
            resolved = urlsplit(urljoin("https://mahoonartmagazine.ir" + route, reference))
            if resolved.scheme not in {"http", "https"} or resolved.netloc.lower() != "mahoonartmagazine.ir":
                continue
            linked_path = unquote(resolved.path or "/")
            if linked_path.endswith("/") or not Path(linked_path).suffix:
                target_file = out / linked_path.lstrip("/") / "index.html"
            else:
                target_file = out / linked_path.lstrip("/")
            if not target_file.is_file():
                broken_internal.add((route, reference))
        if not text.strip():
            empty_html.append(route)
            continue
        if route in posts and "application/ld+json" not in text:
            jsonld_missing += 1
        remote_media += int(url_flags["remote_media"])
        workers_dev += int(url_flags["workers_dev"])
        public_api += int(not route.startswith("/admin") and url_flags["public_api"])
        if route.startswith("/post/") and re.search(r"<title[^>]*>[^<]*(?:404|not found|یافت نشد)", text, re.I):
            partial_fallback_pages += 1
        media_urls.extend(re.findall(r"(?<![A-Za-z0-9._-])(/media/[A-Za-z0-9._/-]+)", text, re.I))
        css_urls = re.findall(r'<link[^>]+href=["\']([^"\']+\.css(?:\?[^"\']*)?)["\']', text, re.I)
        js_urls = re.findall(r'<script[^>]+src=["\']([^"\']+\.js(?:\?[^"\']*)?)["\']', text, re.I)
        for asset_url in css_urls:
            parsed = urlsplit(asset_url)
            if not parsed.scheme and not parsed.netloc and not asset_url.startswith(("data:", "#")):
                asset_path = unquote(parsed.path).lstrip("/")
                if asset_path in checked_css_assets:
                    continue
                checked_css_assets.add(asset_path)
                if not (out / asset_path).is_file():
                    missing_css_assets.append(asset_url)
        for asset_url in js_urls:
            parsed = urlsplit(asset_url)
            if not parsed.scheme and not parsed.netloc and not asset_url.startswith(("data:", "#")):
                asset_path = unquote(parsed.path).lstrip("/")
                if asset_path in checked_js_assets:
                    continue
                checked_js_assets.add(asset_path)
                if not (out / asset_path).is_file():
                    missing_js_assets.append(asset_url)
        match = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)', text, re.I)
        if match:
            canonical[route] = match.group(1)
        expected_canonical = "https://mahoonartmagazine.ir" + quote(
            route.rstrip("/") or "/",
            safe="/%:@!$&'()*+,;=-._~",
        )
        if strict_candidate and match and match.group(1) != expected_canonical:
            canonical_mismatches.append(route)
    canonical_for_duplicate = canonical if strict_candidate else {route: value for route, value in canonical.items() if not route.startswith("/post/")}
    duplicate = len(canonical_for_duplicate) - len(set(canonical_for_duplicate.values()))
    static_media_missing = []
    if strict_candidate:
        for media_url in sorted(set(media_urls)):
            if not (out / media_url.lstrip("/")).is_file():
                static_media_missing.append(media_url)
    result = {"expected_html_routes": len(expected), "present_html_routes": len(expected) - len(missing),
              "expected_post_routes": len(posts), "present_post_routes": len(posts) - sum(route in missing for route in posts),
              "missing_html": len(missing), "missing_routes": missing[:20], "empty_html": len(empty_html), "broken_internal_links": len(broken_internal),
              "canonical_mismatches": len(canonical_mismatches), "duplicate_canonicals": duplicate, "post_jsonld_missing": jsonld_missing,
              "route_validation_source": route_source,
              "local_full_route_proof_mode": "STATIC_ARTIFACT_FILESYSTEM" if strict_candidate else "BASELINE_FIXTURE_FILESYSTEM",
              "local_preview_full_crawl_required": False,
              "remote_reader_media_dependencies": remote_media, "public_content_api_dependencies": public_api,
              "static_media_missing": len(static_media_missing), "missing_css_assets": len(set(missing_css_assets)), "missing_js_assets": len(set(missing_js_assets)),
              "partial_fallback_pages": partial_fallback_pages, "workers_dev_canonical_leaks": workers_dev,
              "PASS": not missing and not empty_html and (not broken_internal or not strict_candidate) and duplicate == 0 and len(canonical_mismatches) == 0 and jsonld_missing == 0 and remote_media == 0 and (public_api == 0 if strict_candidate else True) and len(static_media_missing) == 0 and not missing_css_assets and not missing_js_assets and partial_fallback_pages == 0 and workers_dev == 0}
    evidence_path = os.environ.get("MAHOON_CANDIDATE_GATE_OUTPUT")
    if evidence_path:
        output = Path(evidence_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
