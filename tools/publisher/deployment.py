from __future__ import annotations

import http.client
import json
import os
import time

ACCOUNT = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
WORKER = os.environ.get("MAHOON_WORKER", "mahoon-art-magazine")
TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN", "")


def api(method: str, path: str, payload: dict | None = None):
    conn = http.client.HTTPSConnection("api.cloudflare.com", timeout=120)
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Accept": "application/json"}
    if body:
        headers["Content-Type"] = "application/json"
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    conn.request(method, path, body, headers)
    response = conn.getresponse()
    raw = response.read()
    status = response.status
    conn.close()
    data = json.loads(raw.decode("utf-8")) if raw else {}
    if not 200 <= status < 300 or not data.get("success", True):
        raise RuntimeError(f"Cloudflare API failed HTTP {status}")
    return data


def deployment(version_id: str, ssr_version: str, static_percent: int, ssr_percent: int):
    return api("POST", f"/client/v4/accounts/{ACCOUNT}/workers/scripts/{WORKER}/deployments",
               {"strategy": "percentage", "versions": [{"version_id": ssr_version, "percentage": ssr_percent}, {"version_id": version_id, "percentage": static_percent}]})


def active_deployment() -> dict:
    """Capture the current deployment; promotion must rollback this exact object."""
    data = api("GET", f"/client/v4/accounts/{ACCOUNT}/workers/scripts/{WORKER}/deployments")
    result = data.get("result", [])
    deployments = result.get("deployments", []) if isinstance(result, dict) else result
    if not deployments:
        raise RuntimeError("ACTIVE_DEPLOYMENT_MISSING")
    return deployments[0]


def rollback(previous_deployment: dict):
    versions = previous_deployment.get("versions", [])
    return api("POST", f"/client/v4/accounts/{ACCOUNT}/workers/scripts/{WORKER}/deployments",
               {"strategy": "percentage", "versions": versions})


def wait_for_active(version_id: str, static_percent: int, ssr_percent: int,
                    timeout_seconds: int = 180, interval_seconds: int = 3) -> dict:
    deadline = time.monotonic() + timeout_seconds
    expected = {version_id: static_percent}
    expected_ssr = os.environ.get("MAHOON_SSR_VERSION", "b660c7ff-9042-4b4e-ab14-63211aa9c1f1")
    while time.monotonic() < deadline:
        current = active_deployment()
        observed = {item.get("version_id"): item.get("percentage") for item in current.get("versions", [])}
        if observed.get(version_id) == static_percent and observed.get(expected_ssr) == ssr_percent:
            return current
        time.sleep(interval_seconds)
    raise RuntimeError(f"ERR_DEPLOYMENT_PROPAGATION_TIMEOUT expected={expected} expected_ssr={ssr_percent}")
