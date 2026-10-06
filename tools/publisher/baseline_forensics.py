"""GET-only forensic collection for the MAHOON production baseline mismatch."""

import argparse
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
from zipfile import BadZipFile, ZipFile


API_ROOT = "https://api.cloudflare.com/client/v4"
PERSISTED_DEPLOYMENT = "b670dece-dce1-4c08-97b7-cb623ea9bef8"
PRIOR_OBSERVED_DEPLOYMENT = "af90f997-3298-4f28-93e1-4974b888c46c"
PRIOR_OBSERVED_LATEST_VERSION = "ad300953-8689-48b0-80fb-fc38884355f5"
PERSISTED_VERSION = "cefbdeec-a3a7-4963-a4e9-19937f7829f9"
WORKER = "mahoon-art-magazine"
DEPLOYMENT_PAGES = 20
VERSION_PAGES = 20
AUDIT_PAGES = 10


class ForensicError(Exception):
    def __init__(self, safe_class, http_status=None):
        self.safe_class = safe_class
        self.http_status = http_status


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _utc(timestamp):
    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except (AttributeError, ValueError):
        return timestamp


def _get_json(url, token, headers=None):
    request_headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
    request_headers.update(headers or {})
    request = Request(url, headers=request_headers, method="GET")
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as error:
        raise ForensicError("HTTP_READ_FAILED", error.code) from None
    except json.JSONDecodeError:
        raise ForensicError("RESPONSE_INVALID") from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise ForensicError("HTTP_READ_FAILED") from None


def _envelope(envelope):
    if not isinstance(envelope, dict) or envelope.get("success") is not True:
        raise ForensicError("RESPONSE_INVALID")
    return envelope.get("result"), envelope.get("result_info")


def _pagination(result_info):
    if not isinstance(result_info, dict):
        return None
    total = result_info.get("total_pages")
    page = result_info.get("page")
    if isinstance(total, bool) or not isinstance(total, int) or total < 1:
        return None
    if page is not None and (isinstance(page, bool) or not isinstance(page, int) or page < 1):
        return None
    return total


def _paged_get(get_json, path, collection_key, cap):
    rows, pages_seen, total_pages, error = [], 0, None, None
    for page in range(1, cap + 1):
        url = API_ROOT + path + ("&" if "?" in path else "?") + urlencode({"page": page, "per_page": 100})
        try:
            envelope = get_json(url)
            result, result_info = _envelope(envelope)
            items = result if collection_key is None and isinstance(result, list) else result.get(collection_key) if isinstance(result, dict) else None
            if collection_key == "items" and isinstance(result, list):
                items = result
            if not isinstance(items, list):
                raise ForensicError("RESPONSE_INVALID")
            rows.extend(items)
            pages_seen = page
            total_pages = _pagination(result_info or (result.get("result_info") if isinstance(result, dict) else None))
            if total_pages is None:
                error = "PAGINATION_METADATA_UNAVAILABLE"
                break
            if page >= total_pages:
                break
        except ForensicError as exception:
            error = exception.safe_class
            break
    complete = total_pages is not None and pages_seen == total_pages and total_pages <= cap
    if total_pages is not None and total_pages > cap:
        error = "PAGE_LIMIT_REACHED"
    return {"items": rows, "pages_seen": pages_seen, "total_pages": total_pages,
            "complete": complete, "safe_error_class": error}


def _active_snapshot(get_json, account):
    path = f"/accounts/{account}/workers/scripts/{WORKER}/deployments?per_page=1&page=1"
    try:
        result, _ = _envelope(get_json(API_ROOT + path))
    except ForensicError as error:
        return None, error.safe_class
    rows = result.get("deployments") if isinstance(result, dict) else None
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        return None, "ACTIVE_DEPLOYMENT_UNAVAILABLE"
    return rows[0], None


def _strict_allocation(deployment):
    versions = deployment.get("versions") if isinstance(deployment, dict) else None
    if not isinstance(versions, list) or not versions:
        raise ValueError("VERSIONS_MISSING")
    allocation = {}
    for item in versions:
        if (not isinstance(item, dict) or not isinstance(item.get("version_id"), str)
                or not item["version_id"] or item["version_id"] in allocation
                or not isinstance(item.get("percentage"), int) or isinstance(item["percentage"], bool)
                or not 0 <= item["percentage"] <= 100):
            raise ValueError("VERSIONS_MALFORMED")
        allocation[item["version_id"]] = item["percentage"]
    return allocation, sum(allocation.values())


def _deployment_record(row):
    if not isinstance(row, dict):
        return {"malformed": True}
    record = {key: row[key] for key in ("id", "created_on", "modified_on", "source", "strategy") if key in row}
    annotations = row.get("annotations")
    if isinstance(annotations, dict):
        record["annotations"] = {key: annotations[key] for key in ("workers/message", "workers/triggered_by") if key in annotations}
        if isinstance(record["annotations"].get("workers/message"), str):
            message = record["annotations"]["workers/message"]
            message = re.sub(r"(?i)(bearer\s+)[^\s,;]+", r"\1[REDACTED]", message)
            message = re.sub(r"(?i)(token|secret|password)\s*[:=]\s*[^\s,;]+", r"\1=[REDACTED]", message)
            record["annotations"]["workers/message"] = message[:1000]
    if "author_email" in row:
        record["author_email"] = "[REDACTED]"
    try:
        allocation, total = _strict_allocation(row)
        record["versions"] = [{"version_id": key, "percentage": value} for key, value in allocation.items()]
        record["total_allocation_percentage"] = total
    except ValueError as error:
        record["versions"] = None
        record["allocation_error"] = str(error)
    return record


def _match(rows, deployment_id, complete):
    for row in rows:
        if isinstance(row, dict) and row.get("id") == deployment_id:
            return {"status": "FOUND", "deployment": _deployment_record(row)}
    return {"status": "NOT_FOUND_IN_COMPLETE_HISTORY" if complete else "NOT_FOUND_IN_RETRIEVED_WINDOW",
            "deployment": None}


def _artifact_references(archive_bytes, artifact_name, run_id):
    allowed = {"deployment_id", "observed_deployment_id", "current_deployment_id", "version_id",
               "current_version", "previous_version", "active_version_id", "candidate_version_id",
               "rollback_version_id"}
    uuid = re.compile(r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
    found = []

    def walk(value, prefix=""):
        if isinstance(value, dict):
            for key, child in value.items():
                name = str(key).lower()
                location = f"{prefix}.{key}" if prefix else str(key)
                if name in allowed and isinstance(child, str) and uuid.fullmatch(child):
                    found.append({"path": location, "key": name, "value": child})
                else:
                    walk(child, location)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{prefix}[{index}]")

    try:
        with ZipFile(BytesIO(archive_bytes)) as bundle:
            total = 0
            for member in bundle.infolist():
                if not member.filename.lower().endswith(".json") or member.file_size > 2_000_000:
                    continue
                total += member.file_size
                if total > 10_000_000:
                    break
                try:
                    walk(json.loads(bundle.read(member)))
                except (ValueError, BadZipFile):
                    continue
    except BadZipFile:
        return []
    return [{"artifact_name": artifact_name, "run_id": run_id, **reference} for reference in found]


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def _download_artifact_refs(download_url, token, name, run_id):
    request = Request(download_url, headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"}, method="GET")
    try:
        build_opener(_NoRedirect).open(request, timeout=30)
    except HTTPError as redirect:
        if redirect.code not in (301, 302, 303, 307, 308):
            raise ForensicError("ARTIFACT_READ_FAILED", redirect.code) from None
        location = redirect.headers.get("Location")
        if not location:
            raise ForensicError("ARTIFACT_REDIRECT_INVALID") from None
        # Signed artifact URL is requested without the GitHub token.
        try:
            with urlopen(Request(location, method="GET"), timeout=60) as response:
                body = response.read(10_000_001)
        except (HTTPError, URLError, TimeoutError, OSError):
            raise ForensicError("ARTIFACT_READ_FAILED") from None
        if len(body) > 10_000_000:
            raise ForensicError("ARTIFACT_SIZE_LIMIT")
        return _artifact_references(body, name, run_id)
    except (URLError, TimeoutError, OSError):
        raise ForensicError("ARTIFACT_READ_FAILED") from None
    raise ForensicError("ARTIFACT_REDIRECT_MISSING")


def _compact_version(row):
    if not isinstance(row, dict):
        return {"malformed": True}
    item = {key: row[key] for key in ("id", "number") if key in row}
    metadata = row.get("metadata")
    if isinstance(metadata, dict):
        allowed = ("author_id", "created_on", "modified_on", "source", "hasPreview")
        item["metadata"] = {key: metadata[key] for key in allowed if key in metadata}
        if "author_email" in metadata:
            item["metadata"]["author_email"] = "[REDACTED]"
    return item


def _compact_audit(row, relevant_ids, worker):
    if not isinstance(row, dict):
        return None
    resource = row.get("resource") if isinstance(row.get("resource"), dict) else {}
    action = row.get("action") if isinstance(row.get("action"), dict) else {}
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    # Match only explicit identifiers or the exact Worker name; never retain free-form values.
    searchable = json.dumps([resource.get("id"), resource.get("type"), metadata], sort_keys=True, default=str)
    if not any(identifier and identifier in searchable for identifier in relevant_ids) and worker not in searchable:
        return None
    actor = row.get("actor") if isinstance(row.get("actor"), dict) else {}
    safe_metadata = {key: metadata[key] for key in ("name", "type", "deployment_id", "version_id", "script_name", "worker_name") if key in metadata}
    return {key: row[key] for key in ("id", "when", "interface") if key in row} | {
        "action": {key: action[key] for key in ("type", "result") if key in action},
        "resource": {key: resource[key] for key in ("id", "type") if key in resource},
        "actor": {key: actor[key] for key in ("id", "type") if key in actor},
        "metadata": safe_metadata,
        "actor_email": "[REDACTED]" if actor.get("email") else None,
        "actor_ip": "[REDACTED]" if actor.get("ip") else None,
    }


def classify(active_id, allocation, persisted_deployment, persisted_version, snapshot_changed,
             audit_events, git_history, audit_status):
    if snapshot_changed:
        return "REMOTE_SNAPSHOT_CHANGED_DURING_FORENSICS", "HIGH"
    if not isinstance(allocation, dict):
        return "HISTORICAL_EVIDENCE_INCOMPLETE", "LOW"
    total = sum(allocation.values())
    if total != 100:
        return "TRAFFIC_ALLOCATION_DRIFT", "HIGH"
    current_pct = allocation.get(persisted_version)
    if current_pct == 100 and active_id != persisted_deployment:
        return "SAME_VERSION_NEW_DEPLOYMENT", "HIGH"
    if current_pct is not None and current_pct != 100:
        return "TRAFFIC_ALLOCATION_DRIFT", "HIGH"
    if current_pct is None:
        commits = [item.get("commit_timestamp_utc") for item in git_history if item.get("deployment_id") == persisted_deployment]
        persisted_at = min(commits) if commits else None
        attributed = any(
            event.get("action", {}).get("result") is True
            and (event.get("resource", {}).get("id") == active_id
                 or event.get("metadata", {}).get("deployment_id") == active_id
                 or event.get("metadata", {}).get("version_id") in allocation)
            and persisted_at and event.get("when") and _utc(event["when"]) > persisted_at
            for event in audit_events
        )
        if attributed:
            return "PERSISTED_STATE_STALE", "MEDIUM"
        if len(allocation) == 1 and total == 100:
            return "DIFFERENT_ACTIVE_VERSION", "HIGH"
        return "UNATTRIBUTED_REMOTE_CHANGE", "MEDIUM" if audit_status == "AVAILABLE" else "LOW"
    return "BASELINE_MATCH", "HIGH"


def git_state_history(repo_root, state_path="publisher-state/published-static-state.json"):
    command = ["git", "log", "--all", "--format=%H%x09%P%x09%cI", "--", state_path]
    output = subprocess.check_output(command, cwd=repo_root, text=True, encoding="utf-8")
    history = []
    for line in output.splitlines():
        commit, parents, timestamp = line.split("\t", 2)
        try:
            raw = subprocess.check_output(["git", "show", f"{commit}:{state_path}"], cwd=repo_root)
            state = json.loads(raw)
        except (subprocess.CalledProcessError, ValueError):
            history.append({"commit_sha": commit, "parent_sha": parents.split()[0] if parents else None,
                        "commit_timestamp_utc": _utc(timestamp), "file_read_status": "UNAVAILABLE"})
            continue
        history.append({"commit_sha": commit, "parent_sha": parents.split()[0] if parents else None,
                        "commit_timestamp_utc": _utc(timestamp), "file_sha256": hashlib.sha256(raw).hexdigest(),
                        **{key: state.get(key) for key in ("deployment_id", "current_version", "previous_version",
                                                          "current_version_type", "artifact_seal", "content_fingerprint")}})
    return history


def git_history_findings(repo_root, history, persisted_deployment, observed_deployment, active_versions,
                         state_path="publisher-state/published-static-state.json"):
    chronological = list(reversed(history))
    introduced = None
    previous = None
    for item in chronological:
        if item.get("deployment_id") == persisted_deployment and (previous is None or previous.get("deployment_id") != persisted_deployment):
            parent_state = next((row for row in history if row.get("commit_sha") == item.get("parent_sha")), None)
            if parent_state is None and item.get("parent_sha"):
                try:
                    raw = subprocess.check_output(["git", "show", f"{item['parent_sha']}:{state_path}"], cwd=repo_root)
                    value = json.loads(raw)
                    parent_state = {"commit_sha": item["parent_sha"], "file_sha256": hashlib.sha256(raw).hexdigest(),
                                    **{key: value.get(key) for key in ("deployment_id", "current_version", "previous_version", "current_version_type", "artifact_seal", "content_fingerprint")}}
                except (subprocess.CalledProcessError, ValueError):
                    parent_state = {"commit_sha": item["parent_sha"], "status": "STATE_FILE_UNAVAILABLE"}
            introduced = {"commit_sha": item.get("commit_sha"), "parent_sha": item.get("parent_sha"),
                          "commit_timestamp_utc": item.get("commit_timestamp_utc"),
                          "file_sha256": item.get("file_sha256"), "parent_state": parent_state}
            break
        previous = item
    return {"first_commit_introducing_persisted_deployment": introduced,
            "observed_deployment_ever_persisted": any(item.get("deployment_id") == observed_deployment for item in history),
            "active_version_ever_persisted": {version: any(item.get("current_version") == version for item in history) for version in active_versions}}


def _github_json(url, token):
    return _get_json(url, token, {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})


def collect_github_history(repo, token, api_url="https://api.github.com", max_runs=40):
    if not token or not repo:
        return {"status": "UNAVAILABLE", "safe_error_class": "GITHUB_READ_CREDENTIAL_MISSING", "runs": [], "artifacts": []}
    try:
        envelope = _github_json(f"{api_url}/repos/{repo}/actions/runs?per_page={max_runs}", token)
        run_rows = envelope.get("workflow_runs") if isinstance(envelope, dict) else None
        if not isinstance(run_rows, list):
            raise ForensicError("RESPONSE_INVALID")
        runs, artifacts = [], []
        artifact_downloads = 0
        for row in run_rows[:max_runs]:
            if not isinstance(row, dict):
                continue
            run = {key: row[key] for key in ("id", "head_sha", "event", "status", "conclusion", "created_at", "updated_at", "html_url", "name", "path") if key in row}
            runs.append(run)
            try:
                data = _github_json(f"{api_url}/repos/{repo}/actions/runs/{row['id']}/artifacts?per_page=100", token)
                for artifact in (data.get("artifacts", []) if isinstance(data, dict) else []):
                    if isinstance(artifact, dict) and any(term in artifact.get("name", "").lower() for term in ("proof", "baseline", "result")):
                        summary = {key: artifact[key] for key in ("id", "name", "size_in_bytes", "created_at", "expired") if key in artifact} | {"run_id": row["id"]}
                        if (artifact_downloads < 12 and not artifact.get("expired")
                                and artifact.get("size_in_bytes", 0) <= 10_000_000 and artifact.get("archive_download_url")):
                            try:
                                summary["references"] = _download_artifact_refs(artifact["archive_download_url"], token, artifact.get("name", ""), row["id"])
                            except ForensicError as error:
                                summary["reference_read_error"] = error.safe_class
                            artifact_downloads += 1
                        artifacts.append(summary)
            except (ForensicError, KeyError):
                artifacts.append({"run_id": row.get("id"), "status": "UNAVAILABLE"})
        return {"status": "AVAILABLE", "safe_error_class": None, "runs": runs, "artifacts": artifacts}
    except ForensicError as error:
        return {"status": "UNAVAILABLE", "safe_error_class": error.safe_class, "runs": [], "artifacts": []}


def _cloudflare_evidence(get_json, account, hostname, now):
    evidence = {"account_identity_status": "NOT_CHECKED", "worker_identity_status": "NOT_CHECKED",
                "domain_mapping_status": "NOT_CHECKED", "active_deployment_status": "NOT_CHECKED",
                "deployment_history": {"items": [], "complete": False, "pages_seen": 0, "total_pages": None},
                "worker_version_history": {"items": [], "complete": False, "pages_seen": 0, "total_pages": None},
                "audit_evidence_status": "UNAVAILABLE", "audit_evidence": [], "limitations": []}
    if not re.fullmatch(r"[0-9a-fA-F]{32}", account or "") or not hostname:
        evidence["limitations"].append("MISSING_CONFIGURATION")
        return evidence
    try:
        account_result, _ = _envelope(get_json(f"{API_ROOT}/accounts/{account}"))
        if isinstance(account_result, dict) and account_result.get("id") == account:
            evidence["account_identity_status"] = "PASS"
        else:
            evidence["account_identity_status"] = "UNVERIFIED"
            evidence["limitations"].append("ACCOUNT_IDENTITY_RESPONSE_INVALID")
    except ForensicError as error:
        evidence["account_identity_status"] = "UNAVAILABLE"
        evidence["limitations"].append(f"ACCOUNT_IDENTITY_{error.safe_class}")
    worker_url = f"{API_ROOT}/accounts/{account}/workers/scripts"
    domain_url = f"{API_ROOT}/accounts/{account}/workers/domains?{urlencode({'hostname': hostname, 'environment': 'production'})}"
    try:
        result, _ = _envelope(get_json(worker_url))
        evidence["worker_identity_status"] = "PASS" if isinstance(result, list) and any(isinstance(row, dict) and row.get("id") == WORKER for row in result) else "FAIL"
    except ForensicError as error:
        evidence["worker_identity_status"] = "UNAVAILABLE"
        evidence["limitations"].append(f"WORKER_{error.safe_class}")
    try:
        result, _ = _envelope(get_json(domain_url))
        evidence["domain_mapping_status"] = "PASS" if isinstance(result, list) and any(
            isinstance(row, dict) and row.get("hostname") == hostname and row.get("service") == WORKER and row.get("environment") == "production" for row in result
        ) else "FAIL"
    except ForensicError as error:
        evidence["domain_mapping_status"] = "UNAVAILABLE"
        evidence["limitations"].append(f"DOMAIN_{error.safe_class}")
    deployment_path = f"/accounts/{account}/workers/scripts/{WORKER}/deployments"
    deployment_pages = _paged_get(get_json, deployment_path, "deployments", DEPLOYMENT_PAGES)
    evidence["deployment_history"] = {**deployment_pages, "items": [_deployment_record(row) for row in deployment_pages["items"]]}
    if deployment_pages["safe_error_class"]:
        evidence["limitations"].append("DEPLOYMENT_HISTORY_" + deployment_pages["safe_error_class"])
    rows = deployment_pages["items"]
    active = rows[0] if rows and isinstance(rows[0], dict) else None
    if active:
        try:
            allocation, total = _strict_allocation(active)
            evidence["active_deployment"] = _deployment_record(active)
            evidence["active_allocations"] = allocation
            evidence["active_total_allocation_percentage"] = total
            evidence["active_deployment_status"] = "PASS"
        except ValueError as error:
            evidence["active_deployment"] = _deployment_record(active)
            evidence["active_allocations"] = None
            evidence["active_deployment_status"] = "MALFORMED"
            evidence["limitations"].append("ACTIVE_ALLOCATION_" + str(error))
    else:
        evidence["active_deployment"] = None
        evidence["active_allocations"] = None
        evidence["active_deployment_status"] = "UNAVAILABLE"
    evidence["persisted_deployment_history_match"] = _match(rows, PERSISTED_DEPLOYMENT, deployment_pages["complete"])
    evidence["observed_deployment_history_match"] = _match(rows, PRIOR_OBSERVED_DEPLOYMENT, deployment_pages["complete"])

    version_path = f"/accounts/{account}/workers/scripts/{WORKER}/versions"
    version_pages = _paged_get(get_json, version_path, "items", VERSION_PAGES)
    evidence["worker_version_history"] = {**version_pages, "items": [_compact_version(row) for row in version_pages["items"]]}
    if version_pages["safe_error_class"]:
        evidence["limitations"].append("WORKER_VERSIONS_" + version_pages["safe_error_class"])
    associations = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("id"), str):
            try:
                allocation, _ = _strict_allocation(row)
            except ValueError:
                continue
            for version_id, percentage in allocation.items():
                associations.setdefault(version_id, []).append({"deployment_id": row["id"], "percentage": percentage})
    for item in evidence["worker_version_history"]["items"]:
        item["deployment_associations"] = associations.get(item.get("id"), [])

    audit_query = urlencode({"since": "2026-09-28T00:00:00Z", "before": now})
    try:
        audit_pages = _paged_get(get_json, f"/accounts/{account}/audit_logs?{audit_query}", None, AUDIT_PAGES)
        if audit_pages["safe_error_class"] not in (None, "PAGINATION_METADATA_UNAVAILABLE", "PAGE_LIMIT_REACHED"):
            raise ForensicError(audit_pages["safe_error_class"])
        ids = (PERSISTED_DEPLOYMENT, PRIOR_OBSERVED_DEPLOYMENT, PERSISTED_VERSION, PRIOR_OBSERVED_LATEST_VERSION)
        evidence["audit_evidence"] = [entry for row in audit_pages["items"] if (entry := _compact_audit(row, ids, WORKER))]
        evidence["audit_evidence_status"] = "AVAILABLE" if audit_pages["complete"] else "AVAILABLE_WINDOW_ONLY"
        if evidence["audit_evidence_status"] == "AVAILABLE_WINDOW_ONLY":
            evidence["limitations"].append("AUDIT_HISTORY_WINDOW_INCOMPLETE")
    except ForensicError as error:
        evidence["audit_evidence_status"] = "UNAVAILABLE"
        evidence["audit_error_class"] = error.safe_class
        evidence["limitations"].append("AUDIT_EVIDENCE_UNAVAILABLE")
    return evidence


def build_timeline(git_history, github_history, cloudflare, started, finished):
    events = [{"timestamp_utc": started, "event": "forensics_started", "source": "forensic_workflow"}]
    for item in git_history:
        if item.get("deployment_id"):
            events.append({"timestamp_utc": item["commit_timestamp_utc"], "event": "persisted_state_commit",
                           "source": "git", "commit_sha": item["commit_sha"],
                           "deployment_id": item["deployment_id"], "version_id": item.get("current_version")})
    for run in github_history.get("runs", []):
        if run.get("created_at"):
            events.append({"timestamp_utc": _utc(run["created_at"]), "event": run.get("name", "workflow_run"),
                           "source": "github_actions", **{key: run.get(key) for key in ("id", "head_sha", "event", "conclusion")}})
    for artifact in github_history.get("artifacts", []):
        if artifact.get("created_at"):
            events.append({"timestamp_utc": _utc(artifact["created_at"]), "event": "github_artifact_published",
                           "source": "github_actions_artifacts", "run_id": artifact.get("run_id"),
                           "artifact_name": artifact.get("name"), "references": artifact.get("references", [])})
    for item in cloudflare.get("deployment_history", {}).get("items", []):
        if isinstance(item, dict) and item.get("created_on"):
            events.append({"timestamp_utc": _utc(item["created_on"]), "event": "worker_deployment_record",
                           "source": "cloudflare_deployments", "deployment_id": item.get("id"),
                           "versions": item.get("versions"), "metadata": item.get("annotations", {})})
    for row in cloudflare.get("audit_evidence", []):
        if row.get("when"):
            events.append({"timestamp_utc": row["when"], "event": "cloudflare_audit_event", "source": "cloudflare_audit",
                           **{key: row.get(key) for key in ("id", "action", "resource", "actor")}})
    events.append({"timestamp_utc": finished, "event": "forensics_finished", "source": "forensic_workflow"})
    return sorted(events, key=lambda event: event.get("timestamp_utc") or "")


def run_forensics(repo_root, account, hostname, token, gh_token, repo, get_json=None, gh_history=None):
    started = utc_now()
    repo_root = Path(repo_root)
    state_path = repo_root / "publisher-state/published-static-state.json"
    journal_path = repo_root / "publisher-state/production-transaction-journal.json"
    state_raw = state_path.read_bytes()
    state = json.loads(state_raw)
    journal_before = hashlib.sha256(journal_path.read_bytes()).hexdigest()
    def client(url):
        if get_json is not None:
            return get_json(url)
        if not token:
            raise ForensicError("READ_ONLY_TOKEN_MISSING")
        return _get_json(url, token)
    cloudflare = _cloudflare_evidence(client, account, hostname, started)
    history = git_state_history(repo_root)
    github = gh_history or collect_github_history(repo, gh_token, os.environ.get("GITHUB_API_URL", "https://api.github.com"))
    end_active, end_error = _active_snapshot(client, account)
    try:
        end_allocation, _ = _strict_allocation(end_active) if end_active else (None, None)
    except ValueError:
        end_allocation = None
    start_active = cloudflare.get("active_deployment")
    start_id = start_active.get("id") if isinstance(start_active, dict) else None
    start_allocation = cloudflare.get("active_allocations")
    end_id = end_active.get("id") if isinstance(end_active, dict) else None
    changed = start_id != end_id or start_allocation != end_allocation
    if end_error:
        cloudflare["limitations"].append("END_SNAPSHOT_" + end_error)
        changed = True
    cloudflare["active_snapshot_start"] = {"deployment_id": start_id, "allocations": start_allocation}
    cloudflare["active_snapshot_end"] = {"deployment_id": end_id, "allocations": end_allocation}
    allocation = start_allocation
    audit_events = cloudflare.get("audit_evidence", [])
    classification, confidence = classify(start_id, allocation, state.get("deployment_id"),
                                          state.get("current_version"), changed, audit_events,
                                          history, cloudflare.get("audit_evidence_status"))
    git_findings = git_history_findings(repo_root, history, state.get("deployment_id"), start_id,
                                        list(allocation or {}))
    journal_after = hashlib.sha256(journal_path.read_bytes()).hexdigest()
    state_after = hashlib.sha256(state_path.read_bytes()).hexdigest()
    finished = utc_now()
    timeline = build_timeline(history, github, cloudflare, started, finished)
    required = (cloudflare.get("account_identity_status") == "PASS"
                and cloudflare.get("worker_identity_status") == "PASS"
                and cloudflare.get("domain_mapping_status") == "PASS"
                and cloudflare.get("active_deployment_status") == "PASS"
                and cloudflare.get("deployment_history", {}).get("complete") is True
                and not changed and journal_before == journal_after and hashlib.sha256(state_raw).hexdigest() == state_after)
    evidence = {
        "source_commit": os.environ.get("GITHUB_SHA", ""), "forensic_run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "inspection_started_utc": started, "inspection_finished_utc": finished,
        "account_id": account, "worker": WORKER, "hostname": hostname,
        "persisted_deployment_id": state.get("deployment_id"), "persisted_current_version": state.get("current_version"),
        "observed_active_deployment_id": start_id, "observed_active_allocations": allocation,
        "active_version_ids": list(allocation) if isinstance(allocation, dict) else None,
        "percentage_per_version": allocation,
        "total_allocation_percentage": sum(allocation.values()) if isinstance(allocation, dict) else None,
        "active_deployment_status": cloudflare.get("active_deployment_status"),
        "worker_identity_status": cloudflare.get("worker_identity_status"),
        "domain_mapping_status": cloudflare.get("domain_mapping_status"),
        "account_identity_status": cloudflare.get("account_identity_status"),
        "persisted_deployment_history_match": cloudflare.get("persisted_deployment_history_match"),
        "observed_deployment_history_match": cloudflare.get("observed_deployment_history_match"),
        "deployment_history": cloudflare.get("deployment_history"), "worker_version_history": cloudflare.get("worker_version_history"),
        "active_snapshot_start": cloudflare.get("active_snapshot_start"), "active_snapshot_end": cloudflare.get("active_snapshot_end"),
        "audit_evidence_status": cloudflare.get("audit_evidence_status"), "audit_evidence": audit_events,
        "git_state_history": history, "github_actions_history": github,
        "git_history_findings": git_findings,
        "timeline": timeline, "root_cause_classification": classification, "root_cause_confidence": confidence,
        "supporting_evidence": [], "unresolved_questions": cloudflare.get("limitations", []) + [
            "Whether the Cloudflare change was authorized is unresolved unless a successful matching audit event is present.",
            "Whether the observed deployment was the intended release remains unresolved without matching release evidence.",
        ],
        "journal_unchanged": journal_before == journal_after,
        "persisted_state_unchanged": hashlib.sha256(state_raw).hexdigest() == state_after,
        "production_state_unchanged": not changed,
        "cloudflare_mutation_started": False, "publish_dispatched": False,
        "final_status": "M11_E_BASELINE_FORENSICS_COMPLETE" if required else "M11_E_BASELINE_FORENSICS_INCOMPLETE",
    }
    evidence["supporting_evidence"] = [
        f"persisted deployment {state.get('deployment_id')} at version {state.get('current_version')}",
        f"observed active deployment {start_id} allocation {allocation}",
        f"Cloudflare deployment history complete={cloudflare.get('deployment_history', {}).get('complete')}",
        f"audit evidence status={cloudflare.get('audit_evidence_status')}",
    ]
    report = render_report(evidence)
    return evidence, timeline, report


def render_report(evidence):
    allocation = evidence.get("observed_active_allocations")
    lines = [
        "MAHOON M11-E — PRODUCTION BASELINE FORENSICS F1",
        f"FINAL_STATUS: {evidence['final_status']}",
        "BASELINE_RECONCILIATION: STILL_BLOCKED",
        "PUBLISH_DISPATCHED: NO",
        "PRODUCTION_MUTATION_STARTED: NO",
        f"source_commit: {evidence.get('source_commit')}",
        f"forensic_run_id: {evidence.get('forensic_run_id')}",
        f"inspection_started_utc: {evidence.get('inspection_started_utc')}",
        f"inspection_finished_utc: {evidence.get('inspection_finished_utc')}",
        f"persisted_deployment_id: {evidence.get('persisted_deployment_id')}",
        f"observed_active_deployment_id: {evidence.get('observed_active_deployment_id')}",
        f"persisted_current_version: {evidence.get('persisted_current_version')}",
        f"observed_active_allocations: {json.dumps(allocation, sort_keys=True)}",
        f"root_cause_classification: {evidence.get('root_cause_classification')}",
        f"root_cause_confidence: {evidence.get('root_cause_confidence')}",
        f"persisted_deployment_history_match: {json.dumps(evidence.get('persisted_deployment_history_match'), sort_keys=True)}",
        f"observed_deployment_history_match: {json.dumps(evidence.get('observed_deployment_history_match'), sort_keys=True)}",
        f"audit_evidence_status: {evidence.get('audit_evidence_status')}",
        f"first_commit_introducing_persisted_deployment: {json.dumps(evidence.get('git_history_findings', {}).get('first_commit_introducing_persisted_deployment'), sort_keys=True)}",
        f"observed_deployment_ever_persisted: {evidence.get('git_history_findings', {}).get('observed_deployment_ever_persisted')}",
        f"active_version_ever_persisted: {json.dumps(evidence.get('git_history_findings', {}).get('active_version_ever_persisted'), sort_keys=True)}",
        f"journal_unchanged: {evidence.get('journal_unchanged')}",
        f"production_state_unchanged: {evidence.get('production_state_unchanged')}",
        "",
        "Chronological timeline (UTC):",
    ]
    for event in evidence.get("timeline", []):
        lines.append(f"{event.get('timestamp_utc', 'timestamp unavailable')} | {event.get('source')} | {event.get('event')} | {json.dumps(event, sort_keys=True)}")
    lines.extend(["", "Confirmed facts are tied to the evidence artifact sources listed above. Missing audit access is not evidence that no operator changed production.",
                  "Recommendations only (not authorized in F1):",
                  "- State reconciliation after independent proof: risk of accepting an unattributed deployment or overwriting provenance.",
                  "- Rollback after separate approval: risk of changing live traffic and user-visible behavior.",
                  "- Fresh publish after a separately approved baseline decision: risk of creating a new production deployment; existing safety gates must remain in force.",
                  "No remediation or production action occurred in F1."])
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    evidence, timeline, report = run_forensics(
        Path(__file__).resolve().parents[2], os.environ.get("CF_ACCOUNT", ""),
        os.environ.get("CF_HOSTNAME", ""), os.environ.get("CLOUDFLARE_API_TOKEN", ""),
        os.environ.get("GH_TOKEN", ""), os.environ.get("GITHUB_REPOSITORY", ""),
    )
    (output / "mahoon-baseline-forensics-evidence.json").write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "mahoon-baseline-forensics-timeline.json").write_text(json.dumps(timeline, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "mahoon-baseline-forensics-report.txt").write_text(report, encoding="utf-8")
    print(f"FINAL_STATUS={evidence['final_status']}")
    return 0 if evidence["final_status"] == "M11_E_BASELINE_FORENSICS_COMPLETE" else 1


if __name__ == "__main__":
    sys.exit(main())
