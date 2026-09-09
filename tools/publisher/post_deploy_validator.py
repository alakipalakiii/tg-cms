from __future__ import annotations

import re
import urllib.request
from pathlib import Path
import json
import concurrent.futures


def _request(base: str, path: str, override_version: str | None = None):
    headers = {"User-Agent": "MAHOON-M9-PUBLISHER-VALIDATOR/1.0"}
    if override_version:
        headers["Cloudflare-Workers-Version-Overrides"] = f'mahoon-art-magazine="{override_version}"'
    return urllib.request.Request(base.rstrip("/") + path, headers=headers)


def capture_zero_origin(base: str, paths: list[str], override_version: str | None = None) -> dict:
    """Use real public HTML responses to prove no reader-time origin endpoints are embedded."""
    markers = {
        "PUBLIC_CONTENT_API_REQUESTS_AT_PAGE_VIEW": ("api.mahoonartmagazine.ir", "posts-full-public-v1"),
        "MAHOON_MEDIA_API_REQUESTS_AT_PAGE_VIEW": ("/media-api/", "/media?"),
        "TELEGRAM_REQUESTS_AT_PAGE_VIEW": ("api.telegram.org", "telegram.org/bot"),
        "SEARCH_BACKEND_REQUESTS": ("search-backend", "algolia", "elasticsearch"),
        "D1_REQUESTS_AT_PAGE_VIEW": ("d1_request", "D1_REQUEST"),
    }
    counts = {key: 0 for key in markers}
    inspected = 0
    def inspect(path):
        request = _request(base, path, override_version)
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                body = response.read().decode("utf-8", "ignore").lower()
                return {key: sum(body.count(value.lower()) for value in values) for key, values in markers.items()}, True
        except Exception:
            return {key: 0 for key in markers}, False
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(inspect, paths))
    for result, ok in results:
        inspected += int(ok)
        for key in markers:
            counts[key] += result[key]
        if not ok:
            counts["PUBLIC_CONTENT_API_REQUESTS_AT_PAGE_VIEW"] += 1
    counts["inspected_routes"] = inspected
    counts["PASS"] = inspected == len(paths) and all(counts[key] == 0 for key in markers)
    return counts


def validate_public(base: str, paths: list[str], override_version: str | None = None) -> dict:
    def check(path):
        request = _request(base, path, override_version)
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                body = response.read().decode("utf-8", "ignore")
                if response.status != 200 or (path.startswith("/post/") and not re.search(r"<link[^>]+canonical", body, re.I)):
                    return path, {"path": path, "status": response.status, "reason": "HTTP_OR_CANONICAL"}
        except Exception as exc:
            return path, {"path": path, "status": None, "reason": "REQUEST_EXCEPTION", "exception_class": type(exc).__name__, "message": str(exc)[:200]}
        return path, None
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(check, paths))
    failure_details = [detail for _, detail in results if detail]
    failures = [path for path, detail in results if detail]
    return {"checked": len(paths), "failures": failures, "failure_details": failure_details, "PASS": not failures}


def validate_zero_origin(evidence_path: str | None = None) -> dict:
    """Require explicit production evidence; absence is never interpreted as zero."""
    path = Path(evidence_path) if evidence_path else None
    if not path or not path.exists():
        return {"D1_REQUESTS_AT_PAGE_VIEW": None, "PUBLIC_CONTENT_API_REQUESTS_AT_PAGE_VIEW": None,
                "MAHOON_MEDIA_API_REQUESTS_AT_PAGE_VIEW": None, "TELEGRAM_REQUESTS_AT_PAGE_VIEW": None,
                "SEARCH_BACKEND_REQUESTS": None, "PASS": False, "reason": "ZERO_ORIGIN_EVIDENCE_MISSING"}
    data = json.loads(path.read_text(encoding="utf-8"))
    keys = ("D1_REQUESTS_AT_PAGE_VIEW", "PUBLIC_CONTENT_API_REQUESTS_AT_PAGE_VIEW",
            "MAHOON_MEDIA_API_REQUESTS_AT_PAGE_VIEW", "TELEGRAM_REQUESTS_AT_PAGE_VIEW",
            "SEARCH_BACKEND_REQUESTS")
    result = {key: data.get(key) for key in keys}
    result["PASS"] = all(result[key] == 0 for key in keys)
    return result
