"""Small, fail-closed Wrangler-only deployment control adapter."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

WRANGLER = os.environ.get("MAHOON_WRANGLER", "npx wrangler") .split()
ACCOUNT = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")


class WranglerError(RuntimeError):
    pass


def _run(args: list[str], timeout: int = 120) -> str:
    proc = subprocess.run(WRANGLER + args, text=True, capture_output=True,
                          timeout=timeout, env=os.environ.copy(), check=False)
    if proc.returncode:
        raise WranglerError((proc.stderr or proc.stdout or "wrangler failed")[-800:])
    return proc.stdout


def _json(args: list[str], timeout: int = 120):
    raw = _run(args, timeout)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WranglerError("malformed Wrangler JSON") from exc


def whoami() -> dict:
    raw = _run(["whoami"])
    match = re.search(r"Account ID\s*[│|:]\s*([0-9a-f]{32})", raw, re.I)
    if not match:
        raise WranglerError("Wrangler account ID missing")
    if ACCOUNT and match.group(1).lower() != ACCOUNT.lower():
        raise WranglerError("Wrangler account mismatch")
    return {"authenticated": True, "account_id": match.group(1)}


def list_versions(worker_name: str) -> list[dict]:
    value = _json(["versions", "list", "--name", worker_name, "--json"])
    if not isinstance(value, list):
        raise WranglerError("versions JSON shape invalid")
    return value


def read_deployment(worker_name: str) -> dict:
    value = _json(["deployments", "list", "--name", worker_name, "--json"])
    if not isinstance(value, list) or not value or not isinstance(value[0], dict):
        raise WranglerError("deployments JSON shape invalid")
    if not isinstance(value[0].get("versions"), list):
        raise WranglerError("deployment versions missing")
    return value[0]


def upload_version(worker_name: str, sealed_artifact_root: str | Path,
                   config_path: str | Path, message: str, tag: str | None = None) -> str:
    root = Path(sealed_artifact_root).resolve()
    seal = root.parent / "artifact-seal.json"
    if not root.is_dir() or not seal.is_file():
        raise WranglerError("sealed artifact root required")
    if "m9-v2-candidate" in str(root).lower():
        raise WranglerError("mutable candidate root refused")
    args = ["versions", "upload", "--config", str(Path(config_path).resolve()),
            "--name", worker_name, "--message", message]
    if tag:
        args += ["--tag", tag]
    before = {item.get("id") for item in list_versions(worker_name)}
    _run(args, timeout=900)
    for item in list_versions(worker_name):
        if item.get("id") not in before and item.get("annotations", {}).get("workers/message") == message:
            return item["id"]
    raise WranglerError("uploaded version ID not found")


def deploy_pair(worker_name: str, primary_version_id: str, primary_percentage: int,
                secondary_version_id: str | None = None, secondary_percentage: int = 0) -> dict:
    specs = [f"{primary_version_id}@{int(primary_percentage)}"]
    if secondary_version_id:
        specs.append(f"{secondary_version_id}@{int(secondary_percentage)}")
    _run(["versions", "deploy", *specs, "--name", worker_name, "--yes"], timeout=180)
    return read_deployment(worker_name)


def verify_deployment(worker_name: str, expected: dict[str, int]) -> dict:
    observed = {item.get("version_id"): item.get("percentage")
                for item in read_deployment(worker_name).get("versions", [])}
    if observed != expected:
        raise WranglerError(f"deployment readback mismatch expected={expected} observed={observed}")
    return observed


def wait_for_active(worker_name: str, expected: dict[str, int] | int, ssr_percent: int | None = None,
                    timeout_seconds: int = 180) -> dict:
    if isinstance(expected, int):
        # Legacy runner shape: (version_id, static_percent, ssr_percent).
        version_id = worker_name
        worker_name = os.environ.get("MAHOON_WORKER", "mahoon-art-magazine")
        expected = {version_id: expected}
        if ssr_percent:
            expected[os.environ.get("MAHOON_SSR_VERSION", "")] = ssr_percent
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            return verify_deployment(worker_name, expected)
        except WranglerError:
            time.sleep(3)
    raise WranglerError("deployment convergence timeout")


def rollback_to_previous_static(worker_name: str, previous_version_id: str,
                                failed_version_id: str) -> dict:
    return deploy_pair(worker_name, previous_version_id, 100, failed_version_id, 0)


# Compatibility names used by the existing runner; all normal calls remain Wrangler-only.
def active_deployment(worker_name: str | None = None) -> dict:
    return read_deployment(worker_name or os.environ.get("MAHOON_WORKER", "mahoon-art-magazine"))


def deployment(version_id: str, ssr_version: str, static_percent: int, ssr_percent: int):
    worker = os.environ.get("MAHOON_WORKER", "mahoon-art-magazine")
    secondary = ssr_version if ssr_percent else None
    return deploy_pair(worker, version_id, static_percent, secondary, ssr_percent)
