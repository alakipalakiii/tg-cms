"""Read-only Cloudflare production baseline gate for a fresh publisher run."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


WORKER_NAME = "mahoon-art-magazine"
API_ROOT = "https://api.cloudflare.com/client/v4"


class BaselineBlocked(Exception):
    def __init__(self, error_class):
        self.error_class = error_class


def _request(path, token):
    request = Request(API_ROOT + path, headers={"Authorization": "Bearer " + token}, method="GET")
    try:
        with urlopen(request, timeout=30) as response:
            value = json.load(response)
    except json.JSONDecodeError:
        raise BaselineBlocked("CLOUDFLARE_RESPONSE_INVALID") from None
    except (HTTPError, URLError, TimeoutError, OSError):
        raise BaselineBlocked("CLOUDFLARE_READ_FAILED") from None
    if not isinstance(value, dict) or value.get("success") is not True:
        raise BaselineBlocked("CLOUDFLARE_RESPONSE_INVALID")
    return value.get("result")


def reconcile(state, account_id, hostname, token, getter, worker_name=WORKER_NAME):
    evidence = {
        "account_id": account_id or "",
        "worker_name": worker_name,
        "hostname": hostname or "",
        "persisted_deployment_id": None,
        "observed_deployment_id": None,
        "persisted_current_version": None,
        "observed_version_allocation": None,
        "worker_identity_status": "NOT_CHECKED",
        "domain_mapping_status": "NOT_CHECKED",
        "deployment_identity_status": "NOT_CHECKED",
        "version_allocation_status": "NOT_CHECKED",
        "baseline_status": "BLOCKED",
        "safe_error_class": None,
        "publish_authorized": False,
    }
    try:
        worker = worker_name
        if not account_id or not re.fullmatch(r"[0-9a-fA-F]{32}", account_id):
            raise BaselineBlocked("MISSING_CONFIGURATION")
        if not worker_name or not hostname or "/" in hostname or "?" in hostname:
            raise BaselineBlocked("MISSING_CONFIGURATION")
        if not token:
            raise BaselineBlocked("READ_ONLY_TOKEN_MISSING")
        if (not isinstance(state, dict) or state.get("current_version_type") != "STATIC"
                or not isinstance(state.get("current_version"), str) or not state["current_version"]
                or not isinstance(state.get("deployment_id"), str) or not state["deployment_id"]):
            raise BaselineBlocked("PERSISTED_STATE_INVALID")
        evidence["persisted_deployment_id"] = state["deployment_id"]
        evidence["persisted_current_version"] = state["current_version"]

        def safe_get(path):
            try:
                return getter(path, token)
            except BaselineBlocked:
                raise
            except Exception:
                raise BaselineBlocked("CLOUDFLARE_READ_FAILED") from None

        def snapshot():
            scripts = safe_get(f"/accounts/{account_id}/workers/scripts")
            if not isinstance(scripts, list) or not any(
                isinstance(row, dict) and row.get("id") == worker for row in scripts
            ):
                raise BaselineBlocked("PRODUCTION_BASELINE_DRIFT")
            evidence["worker_identity_status"] = "PASS"
            domains = safe_get(
                f"/accounts/{account_id}/workers/domains?{urlencode({'hostname': hostname, 'environment': 'production'})}"
            )
            if not isinstance(domains, list) or not any(
                isinstance(row, dict) and row.get("hostname") == hostname
                and row.get("service") == worker and row.get("environment") == "production"
                for row in domains
            ):
                raise BaselineBlocked("PRODUCTION_BASELINE_DRIFT")
            evidence["domain_mapping_status"] = "PASS"
            deployments = safe_get(
                f"/accounts/{account_id}/workers/scripts/{worker}/deployments?per_page=1"
            )
            rows = deployments.get("deployments") if isinstance(deployments, dict) else None
            if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
                raise BaselineBlocked("PRODUCTION_BASELINE_DRIFT")
            return scripts, domains, rows[0]

        first = snapshot()
        live = first[2]
        evidence["observed_deployment_id"] = live.get("id")
        if live.get("id") != state["deployment_id"]:
            raise BaselineBlocked("PRODUCTION_BASELINE_DRIFT")
        evidence["deployment_identity_status"] = "PASS"
        versions = live.get("versions")
        if not isinstance(versions, list) or not versions:
            raise BaselineBlocked("PRODUCTION_BASELINE_DRIFT")
        allocation = {}
        for item in versions:
            if (not isinstance(item, dict) or not isinstance(item.get("version_id"), str)
                    or not item["version_id"] or item["version_id"] in allocation
                    or not isinstance(item.get("percentage"), int)
                    or isinstance(item["percentage"], bool) or not 0 <= item["percentage"] <= 100):
                raise BaselineBlocked("PRODUCTION_BASELINE_DRIFT")
            allocation[item["version_id"]] = item["percentage"]
        evidence["observed_version_allocation"] = allocation
        if allocation.get(state["current_version"]) != 100 or sum(allocation.values()) != 100:
            raise BaselineBlocked("PRODUCTION_BASELINE_DRIFT")
        evidence["version_allocation_status"] = "PASS"
        if first != snapshot():
            raise BaselineBlocked("PRODUCTION_BASELINE_DRIFT")
        evidence.update(baseline_status="PASS", safe_error_class=None, publish_authorized=True)
    except BaselineBlocked as error:
        evidence["safe_error_class"] = error.error_class
    return evidence


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    evidence = {
        "repository": os.environ.get("GITHUB_REPOSITORY", ""),
        "source_commit": os.environ.get("GITHUB_SHA", ""),
        "inspection_timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = None
    evidence.update(reconcile(
        state, os.environ.get("CF_ACCOUNT", ""), os.environ.get("CF_HOSTNAME", ""),
        os.environ.get("CLOUDFLARE_API_TOKEN", ""), _request, os.environ.get("CF_WORKER", ""),
    ))
    Path(args.output).write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"BASELINE_STATUS={evidence['baseline_status']}")
    if evidence["safe_error_class"]:
        print(f"SAFE_ERROR_CLASS={evidence['safe_error_class']}")
    return 0 if evidence["baseline_status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
