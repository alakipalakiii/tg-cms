"""Small, testable primitives for version-pinned remote proof requests."""
from __future__ import annotations

import urllib.error
import urllib.request
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

VERSION_OVERRIDE_HEADER = "Cloudflare-Workers-Version-Overrides"
VERSION_RESPONSE_HEADER = "X-Mahoon-Worker-Version"


def is_worker_first_route(path: str) -> bool:
    normalized = urlsplit(path).path.rstrip("/") or "/"
    return (
        normalized == "/"
        or normalized in {"/about", "/contact", "/robots.txt", "/rss.xml", "/sitemap.xml"}
        or normalized.startswith(("/posts", "/post/", "/category/", "/tag/", "/admin", "/search"))
    )


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def cache_busted_url(url: str, version: str, nonce: str) -> str:
    parts = urlsplit(url)
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
             if key != "__mahoon_proof"]
    query.append(("__mahoon_proof", f"{version}-{nonce}"))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def category_page_matches(route_exists: bool, expected_ids: list[int], actual_ids: list[int], http_status: int | None = 200) -> bool:
    """An empty category is valid when its required base page exists and has no cards."""
    return route_exists and http_status == 200 and expected_ids == actual_ids


def classify_link_target(url: str, base_url: str, manifest_routes: set[str]) -> tuple[str, str]:
    target = urlsplit(urljoin(base_url.rstrip("/") + "/", url))
    base = urlsplit(base_url)
    if target.scheme not in {"http", "https"} or (target.scheme, target.netloc.lower()) != (base.scheme, base.netloc.lower()):
        return "EXTERNAL_OTHER", target.path

    from urllib.parse import unquote
    path = unquote(target.path).rstrip("/") or "/"
    if path in {"/robots.txt", "/sitemap.xml", "/rss.xml", "/search", "/search/search-index.json"}:
        return "SPECIAL_CONTROL_ROUTE", path
    if path.startswith("/tag/"):
        return "TAG_ROUTE", path
    if path.startswith("/media/"):
        return "STATIC_MEDIA", path
    if path in {unquote(urlsplit(route).path).rstrip("/") or "/" for route in manifest_routes}:
        return "PAGE_ROUTE", path
    suffix = path.rsplit("/", 1)[-1].lower()
    if "." in suffix:
        if suffix.endswith((".html", ".htm")):
            return "PAGE_ROUTE", path
        return "STATIC_ASSET", path
    return "PAGE_ROUTE", path


def link_contract_fails(kind: str, status: int | None, content_type: str = "") -> bool:
    content_type = (content_type or "").lower()
    if kind == "EXTERNAL_OTHER":
        return False
    if status != 200:
        return True
    if kind in {"PAGE_ROUTE", "TAG_ROUTE"}:
        return not content_type.startswith("text/html")
    if kind == "SPECIAL_CONTROL_ROUTE":
        return not content_type.startswith(("text/", "application/"))
    return False


def request_with_version_pinning(
    url: str,
    *,
    worker: str,
    version: str,
    opener=None,
    timeout: int = 45,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    cache_bust_nonce: str | None = None,
    max_redirects: int = 8,
    send_version_override: bool | None = None,
    require_actual_version: bool | None = None,
) -> dict:
    """Request a URL with independently controlled override and attribution gates."""
    if send_version_override is None:
        send_version_override = bool(version)
    if require_actual_version is None:
        require_actual_version = bool(version)
    request_url = cache_busted_url(url, version, cache_bust_nonce) if cache_bust_nonce else url
    pinned_header = f'{worker}="{version}"'
    current = request_url
    origin = urlsplit(request_url)
    chain: list[dict] = []
    opener = opener or urllib.request.build_opener(_NoRedirect())
    response = None

    for hop in range(max_redirects + 1):
        request_headers = dict(headers or {})
        if send_version_override:
            request_headers[VERSION_OVERRIDE_HEADER] = pinned_header
        request = urllib.request.Request(current, headers=request_headers, method=method)
        try:
            response = opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            response = error

        status = int(getattr(response, "status", None) or response.getcode())
        response_headers = response.headers
        location = response_headers.get("Location")
        actual_version = response_headers.get(VERSION_RESPONSE_HEADER)
        chain.append({
            "hop": hop,
            "requested_url": current,
            "override_header_sent": request.get_header("Cloudflare-workers-version-overrides") if send_version_override else None,
            "status": status,
            "location": location,
            "actual_version": actual_version,
        })

        if not (300 <= status < 400 and location):
            break
        next_url = urljoin(current, location)
        next_origin = urlsplit(next_url)
        if (next_origin.scheme, next_origin.netloc.lower()) != (origin.scheme, origin.netloc.lower()):
            break
        if hop == max_redirects:
            break
        response.close()
        current = next_url

    body = response.read()
    response_headers = response.headers
    actual_version = response_headers.get(VERSION_RESPONSE_HEADER)
    every_hop_pinned = bool(chain) and all(item["override_header_sent"] == pinned_header for item in chain) if send_version_override else True
    attribution_proven = bool(require_actual_version and version) and all(
        item["actual_version"] == version for item in chain
    )
    content_type = response_headers.get_content_type() if hasattr(response_headers, "get_content_type") else response_headers.get("Content-Type", "")
    result = {
        "requested_url": request_url,
        "final_url": current,
        "status": int(getattr(response, "status", None) or response.getcode()),
        "headers": response_headers,
        "body": body,
        "content_type": str(content_type or ""),
        "actual_version": actual_version,
        "version_attribution_status": "PROVEN" if attribution_proven else ("NOT_REQUIRED" if not require_actual_version else "NOT_PROVEN"),
        "redirect_chain": chain,
        "redirect_hop_count": len(chain) - 1,
        "override_preserved_on_every_hop": every_hop_pinned,
        "override_header_sent": bool(send_version_override),
        "actual_version_required": bool(require_actual_version),
        "cache_busted": bool(cache_bust_nonce),
    }
    response.close()
    return result
