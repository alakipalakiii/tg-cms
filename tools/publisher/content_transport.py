"""Bounded, observable read-only transport for the public content API."""
from __future__ import annotations

import hashlib
import json
import socket
import time
import urllib.error
import urllib.request

RETRY_DELAYS = (2, 5, 10, 20, 40)
SAFE_HEADERS = {"Accept": "application/json", "User-Agent": "MAHOON-Static-Publisher/1.0"}


def classify_error(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 403: return "HTTP_403"
        if exc.code == 429: return "HTTP_429"
        if 500 <= exc.code <= 599: return "HTTP_5XX"
        return f"HTTP_{exc.code}"
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, socket.timeout): return "CONNECT_TIMEOUT"
        if isinstance(reason, socket.gaierror): return "DNS_FAILURE"
        if isinstance(reason, TimeoutError): return "CONNECT_TIMEOUT"
        if isinstance(reason, OSError) and "timed out" in str(reason).lower(): return "READ_TIMEOUT"
        if "ssl" in str(reason).lower(): return "TLS_FAILURE"
        return "TRANSPORT_FAILED_BEFORE_HTTP"
    if isinstance(exc, json.JSONDecodeError): return "INVALID_JSON"
    return "CONTRACT_FAILURE"


def _safe_error(exc: Exception) -> str:
    return str(exc).replace("CLOUDFLARE_API_TOKEN", "[REDACTED_SECRET]")[:300]


def fetch_json(url: str, timeout: int = 60, opener=urllib.request.urlopen) -> tuple[dict, dict]:
    attempts = []
    for index, delay in enumerate(RETRY_DELAYS, start=1):
        started = time.monotonic()
        request = urllib.request.Request(url, headers=SAFE_HEADERS)
        try:
            with opener(request, timeout=timeout) as response:
                body = response.read()
                meta = {"attempt": index, "status": response.status, "content_type": response.headers.get("Content-Type"), "content_length": response.headers.get("Content-Length"), "server": response.headers.get("Server"), "cf_ray": response.headers.get("CF-Ray"), "retry_after": response.headers.get("Retry-After"), "location": response.headers.get("Location"), "elapsed_ms": round((time.monotonic() - started) * 1000)}
                payload = json.loads(body.decode("utf-8"))
                meta.update({"sha256": hashlib.sha256(body).hexdigest(), "response_bytes": len(body), "attempts": attempts + [meta]})
                return payload, meta
        except Exception as exc:
            kind = classify_error(exc)
            record = {"attempt": index, "failure_class": kind, "exception_class": type(exc).__name__, "sanitized_error": _safe_error(exc), "elapsed_ms": round((time.monotonic() - started) * 1000)}
            attempts.append(record)
            retryable = kind in {"DNS_FAILURE", "CONNECT_TIMEOUT", "READ_TIMEOUT", "TLS_FAILURE", "HTTP_429", "HTTP_5XX", "TRANSPORT_FAILED_BEFORE_HTTP"}
            if not retryable or index == len(RETRY_DELAYS):
                raise RuntimeError(json.dumps({"failure_class": kind, "attempts": attempts}, ensure_ascii=False)) from exc
            time.sleep(delay)
