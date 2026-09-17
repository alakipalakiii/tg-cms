"""Small, fail-closed Wrangler-only deployment control adapter."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import datetime
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
    if not isinstance(value, list) or not value or any(not isinstance(item, dict) for item in value):
        raise WranglerError("deployments JSON shape invalid")
    try:
        latest = max(value, key=lambda item: datetime.fromisoformat(
            str(item["created_on"]).replace("Z", "+00:00")
        ))
    except (KeyError, TypeError, ValueError) as exc:
        raise WranglerError("deployment creation time missing or invalid") from exc
    if not isinstance(latest.get("versions"), list):
        raise WranglerError("deployment versions missing")
    return latest


def upload_version(worker_name: str, sealed_artifact_root: str | Path,
                   config_path: str | Path, message: str, tag: str | None = None) -> str:
    root = Path(sealed_artifact_root).resolve()
    seal = root.parent / "artifact-seal.json"
    if not root.is_dir() or not seal.is_file():
        raise WranglerError("sealed artifact root required")
    try:
        from .seal_artifact import verify_seal
        if not verify_seal(root, json.loads(seal.read_text(encoding="utf-8"))):
            raise WranglerError("sealed artifact changed after sealing")
    except (OSError, json.JSONDecodeError) as exc:
        raise WranglerError("artifact seal is unreadable") from exc
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
    primary_percentage = int(primary_percentage)
    secondary_percentage = int(secondary_percentage)
    if not primary_version_id or not 0 <= primary_percentage <= 100:
        raise WranglerError("invalid primary static deployment target")
    specs = [f"{primary_version_id}@{int(primary_percentage)}"]
    if secondary_version_id:
        if secondary_version_id == primary_version_id or not 0 <= secondary_percentage <= 100:
            raise WranglerError("invalid secondary static deployment target")
        if primary_percentage + secondary_percentage != 100:
            raise WranglerError("static traffic split must total 100 percent")
        specs.append(f"{secondary_version_id}@{int(secondary_percentage)}")
    elif primary_percentage != 100:
        raise WranglerError("single-version deployment must receive 100 percent")
    _run(["versions", "deploy", *specs, "--name", worker_name, "--yes"], timeout=180)
    return read_deployment(worker_name)


def verify_deployment(worker_name: str, expected: dict[str, int]) -> dict:
    deployment = read_deployment(worker_name)
    versions = deployment.get("versions", [])
    if any(not item.get("version_id") or not isinstance(item.get("percentage"), int) for item in versions):
        raise WranglerError("deployment readback is malformed")
    observed = {item["version_id"]: item["percentage"] for item in versions}
    if len(observed) != len(versions) or sum(observed.values()) != 100:
        raise WranglerError("deployment readback has duplicate versions or invalid traffic total")
    if observed != expected:
        raise WranglerError(f"deployment readback mismatch expected={expected} observed={observed}")
    return deployment


def wait_for_active(worker_name: str, expected: dict[str, int], timeout_seconds: int = 180) -> dict:
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
