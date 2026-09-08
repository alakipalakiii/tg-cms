from __future__ import annotations

import http.client
import json
import os

ACCOUNT = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
WORKER = "mahoon-art-magazine"
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


def rollback(previous_deployment: dict):
    versions = previous_deployment.get("versions", [])
    return api("POST", f"/client/v4/accounts/{ACCOUNT}/workers/scripts/{WORKER}/deployments",
               {"strategy": "percentage", "versions": versions})
