from __future__ import annotations

import re
import urllib.request
from pathlib import Path
import json


def capture_zero_origin(base: str, paths: list[str]) -> dict:
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
    for path in paths:
        request = urllib.request.Request(base.rstrip("/") + path, headers={"User-Agent": "MAHOON-M9-PUBLISHER-ZERO-ORIGIN/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                body = response.read().decode("utf-8", "ignore").lower()
                inspected += 1
                for key, values in markers.items():
                    counts[key] += sum(body.count(value.lower()) for value in values)
        except Exception:
            counts["PUBLIC_CONTENT_API_REQUESTS_AT_PAGE_VIEW"] += 1
    counts["inspected_routes"] = inspected
    counts["PASS"] = inspected == len(paths) and all(counts[key] == 0 for key in markers)
    return counts


def validate_public(base: str, paths: list[str]) -> dict:
    failures = []
    for path in paths:
        request = urllib.request.Request(base.rstrip("/") + path, headers={"User-Agent": "MAHOON-M9-PUBLISHER-POSTDEPLOY/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                body = response.read().decode("utf-8", "ignore")
                if response.status != 200 or (path.startswith("/post/") and not re.search(r"<link[^>]+canonical", body, re.I)):
                    failures.append(path)
        except Exception:
            failures.append(path)
    return {"checked": len(paths), "failures": failures, "PASS": not failures}


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
