"""Read-only GitHub-runner transport matrix for the configured public API."""
from __future__ import annotations

import hashlib
import json
import socket
import subprocess
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
from pathlib import Path

from content_transport import SAFE_HEADERS, classify_error, fetch_json
from delta_build_adapter import API


def response_record(label, status=None, headers=None, body=b"", elapsed_ms=None, error=None):
    headers = headers or {}
    record = {"transport": label, "DNS_RESULT": "NOT_RUN", "RESOLVED_IP_FAMILY": "UNKNOWN", "HTTP_STATUS": status, "CONTENT_TYPE": headers.get("Content-Type"), "CONTENT_LENGTH": headers.get("Content-Length"), "SERVER": headers.get("Server"), "CF_RAY": headers.get("CF-Ray"), "RETRY_AFTER": headers.get("Retry-After"), "LOCATION": headers.get("Location"), "ELAPSED_MS": elapsed_ms}
    if body:
        try: payload = json.loads(body.decode("utf-8"))
        except Exception: payload = None
        record.update({"SHA256": hashlib.sha256(body).hexdigest(), "STRUCTURAL_KEYS": sorted(payload.keys()) if isinstance(payload, dict) else [], "POST_COUNT": len(payload.get("posts", [])) if isinstance(payload, dict) and isinstance(payload.get("posts"), list) else None})
    if error:
        record.update({"EXCEPTION_CLASS": type(error).__name__, "SANITIZED_ERROR": str(error)[:300], "FAILURE_CLASS": classify_error(error)})
    return record


def urllib_probe(label, headers=None, family=socket.AF_UNSPEC):
    started = time.monotonic()
    try:
        request = urllib.request.Request(API, headers=headers or {})
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
            record = response_record(label, response.status, dict(response.headers), body, round((time.monotonic() - started) * 1000))
    except Exception as exc:
        record = response_record(label, error=exc, elapsed_ms=round((time.monotonic() - started) * 1000))
    return record


def main():
    parsed = urlparse(API)
    host = parsed.hostname
    dns = []
    try:
        dns = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except Exception as exc:
        dns_error = {"EXCEPTION_CLASS": type(exc).__name__, "SANITIZED_ERROR": str(exc)[:300], "FAILURE_CLASS": classify_error(urllib.error.URLError(exc))}
    matrix = {"CONTENT_SOURCE_URL": API, "CONTENT_SOURCE_HOST": host, "CONTENT_SOURCE_PATH": parsed.path, "CONTENT_SOURCE_QUERY": parsed.query, "DNS": {"DNS_RESULT": "PASS" if dns else "FAIL", "RESOLVED_IP_FAMILY": sorted({"IPv4" if item[0] == socket.AF_INET else "IPv6" for item in dns}) if dns else [], "details": dns_error if not dns else None}, "PROBES": []}
    matrix["PROBES"].append(urllib_probe("urllib_current_adapter", {"Accept": "application/json", "User-Agent": "MAHOON-M9-PUBLISHER/1.0"}))
    matrix["PROBES"].append(urllib_probe("urllib_explicit_safe_headers", SAFE_HEADERS))
    for flag, label in (("-4", "curl_ipv4"), ("-6", "curl_ipv6")):
        if flag == "-6" and not any(item[0] == socket.AF_INET6 for item in dns):
            matrix["PROBES"].append({"transport": label, "FAILURE_CLASS": "IPV6_UNAVAILABLE"})
            continue
        started = time.monotonic()
        try:
            result = subprocess.run(["curl", flag, "-sS", "-L", "--max-time", "30", "-D", "-", API], capture_output=True, timeout=35, check=False)
            raw = result.stdout
            head, _, body = raw.partition(b"\r\n\r\n")
            status = int(next((line.split()[1] for line in head.splitlines() if line.startswith(b"HTTP/")), b"0")) if head else None
            headers = {line.split(b":", 1)[0].decode(errors="ignore"): line.split(b":", 1)[1].strip().decode(errors="ignore") for line in head.splitlines()[1:] if b":" in line}
            matrix["PROBES"].append(response_record(label, status, headers, body, round((time.monotonic() - started) * 1000), RuntimeError(result.stderr.decode(errors="ignore")[:300]) if result.returncode else None))
        except Exception as exc:
            matrix["PROBES"].append(response_record(label, error=exc, elapsed_ms=round((time.monotonic() - started) * 1000)))
    try:
        payload, transport = fetch_json(API)
        matrix["BOUNDED_RETRY_ADAPTER"] = {"PASS": True, "transport": transport, "POST_COUNT": len(payload.get("posts", [])) if isinstance(payload, dict) else None}
    except Exception as exc:
        matrix["BOUNDED_RETRY_ADAPTER"] = {"PASS": False, "error": str(exc)[:500]}
    Path("runner-evidence").mkdir(parents=True, exist_ok=True)
    Path("runner-evidence/github-content-api-transport-matrix.json").write_text(json.dumps(matrix, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"CONTENT_SOURCE_URL": API, "PROBES": len(matrix["PROBES"]), "BOUNDED_RETRY_PASS": matrix["BOUNDED_RETRY_ADAPTER"].get("PASS")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
