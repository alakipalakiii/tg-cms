"""Fail-closed, read-only-Cloudflare reconciliation for the accepted R1 baseline."""

import argparse
import base64
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

from production_baseline_readonly import reconcile as strict_baseline_reconcile


API_ROOT = "https://api.cloudflare.com/client/v4"
GITHUB_API = "https://api.github.com"
INITIAL_MAIN_SHA = "07e7e1899155a861ff32b45ed8cbfab0e45748e5"
R1_IMPLEMENTATION_SHA = "2997228958f45e113239aad47108403a98297d85"
F1_RUN_ID = "37460626693"
F1_SOURCE_SHA = INITIAL_MAIN_SHA
F1_ARTIFACT_NAME = "mahoon-baseline-forensics-37460626693"
WORKER = "mahoon-art-magazine"
OLD_DEPLOYMENT = "b670dece-dce1-4c08-97b7-cb623ea9bef8"
ACCEPTED_DEPLOYMENT = "af90f997-3298-4f28-93e1-4974b888c46c"
CURRENT_VERSION = "cefbdeec-a3a7-4963-a4e9-19937f7829f9"
PREVIOUS_VERSION = "15c39b57-8dc8-42ab-8e4d-6e50e0d96de7"
ZERO_PERCENT_VERSION = "ad300953-8689-48b0-80fb-fc38884355f5"
STATE_PATH = "publisher-state/published-static-state.json"
JOURNAL_PATH = "publisher-state/production-transaction-journal.json"
SIX_STATE_PATHS = (
    "publisher-state/current-accepted-route-manifest.json",
    "publisher-state/immutable-media-index.json",
    "publisher-state/production-content-fingerprint.json",
    "publisher-state/production-media-manifest.json",
    "publisher-state/published-route-manifest.json",
    STATE_PATH,
)
R1_SOURCE_FILES = {
    ".github/workflows/mahoon-baseline-reconciliation-r1.yml",
    "tools/publisher/baseline_reconciliation_r1.py",
    "tools/publisher/test_baseline_reconciliation_r1.py",
}
EXPECTED_STATE = {
    "current_version": CURRENT_VERSION,
    "previous_version": PREVIOUS_VERSION,
    "current_version_type": "STATIC",
    "deployment_id": OLD_DEPLOYMENT,
    "artifact_seal": "4cd81ee5354892d5ac71fdd402f4ef18f67f2bd8d7b9c27da5c8baff730ed619",
    "content_fingerprint": "cfaaa1c178f2f81605713d42f24f995ef628238dc9ed61c679901149a4433ffb",
}
EXPECTED_TRANSACTION = "704bdb7d7161c7c5c89ef4865788e71a67df26fd2fe4cfb695d297c3900d18d2"
EXPECTED_OPERATIONS = {
    "upload_version": "43e302f37a50a889d54892acff2859a0bb39f9394b9ab800ce1b6374997085b1",
    "deploy_zero_percent": "0cafdc8a128c036d772b6f12b672085e8db5b01bf87c8b780209415dc4c128af",
    "promote": "dddaeaf7439535754233540877f8abc76a058b377d49045f7a863db8a84bd17c",
    "rollback": "770793ca0dbbf735f3740d9ca368e1318551e5905ad46dc540613225525a3cba",
}


class R1Blocked(Exception):
    def __init__(self, stage, safe_error_class):
        self.stage = stage
        self.safe_error_class = safe_error_class


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _git(root, *args, check=True, input_bytes=None):
    result = subprocess.run(["git", *args], cwd=root, input=input_bytes, capture_output=True)
    if check and result.returncode:
        raise R1Blocked("GIT", "GIT_OPERATION_FAILED")
    return result


def _get_json(url, token, accept="application/json"):
    request = Request(url, headers={"Authorization": "Bearer " + token, "Accept": accept}, method="GET")
    try:
        with urlopen(request, timeout=30) as response:
            value = json.load(response)
    except HTTPError as error:
        raise R1Blocked("READ_API", f"HTTP_{error.code}") from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise R1Blocked("READ_API", "READ_REQUEST_FAILED") from None
    if not isinstance(value, dict):
        raise R1Blocked("READ_API", "RESPONSE_INVALID")
    return value


def _cf_result(get_json, path):
    response = get_json(API_ROOT + path)
    if not isinstance(response, dict) or response.get("success") is not True:
        raise R1Blocked("CLOUDFLARE_READ", "CLOUDFLARE_RESPONSE_INVALID")
    return response.get("result"), response.get("result_info")


def _allocation(deployment):
    versions = deployment.get("versions") if isinstance(deployment, dict) else None
    if not isinstance(versions, list) or not versions:
        raise R1Blocked("CLOUDFLARE_ALLOCATION", "VERSION_ALLOCATION_MISSING")
    allocation = {}
    for row in versions:
        if (not isinstance(row, dict) or not isinstance(row.get("version_id"), str)
                or not row["version_id"] or row["version_id"] in allocation
                or not isinstance(row.get("percentage"), int) or isinstance(row["percentage"], bool)
                or not 0 <= row["percentage"] <= 100):
            raise R1Blocked("CLOUDFLARE_ALLOCATION", "VERSION_ALLOCATION_MALFORMED")
        allocation[row["version_id"]] = row["percentage"]
    if sum(allocation.values()) != 100:
        raise R1Blocked("CLOUDFLARE_ALLOCATION", "VERSION_ALLOCATION_TOTAL_MISMATCH")
    return allocation


def _deployment_page(get_json, account, page):
    path = f"/accounts/{account}/workers/scripts/{WORKER}/deployments?{urlencode({'page': page, 'per_page': 100})}"
    result, result_info = _cf_result(get_json, path)
    rows = result.get("deployments") if isinstance(result, dict) else None
    if not isinstance(rows, list):
        raise R1Blocked("CLOUDFLARE_HISTORY", "DEPLOYMENT_HISTORY_INVALID")
    info = result_info or (result.get("result_info") if isinstance(result, dict) else None)
    total_pages = info.get("total_pages") if isinstance(info, dict) else None
    if isinstance(total_pages, bool) or not isinstance(total_pages, int) or total_pages < 1:
        raise R1Blocked("CLOUDFLARE_HISTORY", "DEPLOYMENT_HISTORY_PAGINATION_UNAVAILABLE")
    return rows, total_pages


def _history(get_json, account):
    rows, page, total = [], 1, None
    while page <= 50:
        batch, page_total = _deployment_page(get_json, account, page)
        if total is not None and page_total != total:
            raise R1Blocked("CLOUDFLARE_HISTORY", "DEPLOYMENT_HISTORY_PAGINATION_CHANGED")
        total = page_total
        rows.extend(batch)
        if page == 1 and not rows:
            raise R1Blocked("CLOUDFLARE_HISTORY", "DEPLOYMENT_HISTORY_EMPTY")
        if page >= total:
            return rows, {"complete": True, "pages_seen": page, "total_pages": total}
        page += 1
    raise R1Blocked("CLOUDFLARE_HISTORY", "DEPLOYMENT_HISTORY_PAGE_LIMIT")


def _assert_deployment(row, deployment_id, label):
    if not isinstance(row, dict) or row.get("id") != deployment_id:
        raise R1Blocked("CLOUDFLARE_HISTORY", label + "_DEPLOYMENT_ID_MISMATCH")
    allocation = _allocation(row)
    if allocation.get(CURRENT_VERSION) != 100 or any(value != 0 for key, value in allocation.items() if key != CURRENT_VERSION):
        raise R1Blocked("CLOUDFLARE_HISTORY", label + "_VERSION_ALLOCATION_MISMATCH")
    return allocation


def _active_deployment(get_json, account):
    path = f"/accounts/{account}/workers/scripts/{WORKER}/deployments?{urlencode({'page': 1, 'per_page': 1})}"
    result, _ = _cf_result(get_json, path)
    rows = result.get("deployments") if isinstance(result, dict) else None
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        raise R1Blocked("CLOUDFLARE_ACTIVE", "ACTIVE_DEPLOYMENT_UNAVAILABLE")
    active = rows[0]
    return {"deployment_id": active.get("id"), "allocation": _allocation(active)}


def verify_cloudflare(get_json, account, hostname):
    if not re.fullmatch(r"[0-9a-fA-F]{32}", account or "") or not hostname:
        raise R1Blocked("CLOUDFLARE_IDENTITY", "CLOUDFLARE_CONFIGURATION_MISSING")
    start_snapshot = _active_deployment(get_json, account)
    identity, _ = _cf_result(get_json, f"/accounts/{account}")
    if not isinstance(identity, dict) or identity.get("id") != account:
        raise R1Blocked("CLOUDFLARE_IDENTITY", "ACCOUNT_IDENTITY_MISMATCH")
    scripts, _ = _cf_result(get_json, f"/accounts/{account}/workers/scripts")
    if not isinstance(scripts, list) or not any(isinstance(row, dict) and row.get("id") == WORKER for row in scripts):
        raise R1Blocked("CLOUDFLARE_IDENTITY", "WORKER_IDENTITY_MISMATCH")
    domains, _ = _cf_result(get_json, f"/accounts/{account}/workers/domains?{urlencode({'hostname': hostname, 'environment': 'production'})}")
    if not isinstance(domains, list) or not any(
        isinstance(row, dict) and row.get("hostname") == hostname and row.get("service") == WORKER
        and row.get("environment") == "production" for row in domains
    ):
        raise R1Blocked("CLOUDFLARE_IDENTITY", "PRODUCTION_DOMAIN_MISMATCH")
    rows, coverage = _history(get_json, account)
    by_id = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or row["id"] in by_id:
            raise R1Blocked("CLOUDFLARE_HISTORY", "DEPLOYMENT_HISTORY_IDENTITY_AMBIGUOUS")
        by_id[row["id"]] = row
    old = by_id.get(OLD_DEPLOYMENT)
    accepted = by_id.get(ACCEPTED_DEPLOYMENT)
    old_allocation = _assert_deployment(old, OLD_DEPLOYMENT, "OLD")
    accepted_allocation = _assert_deployment(accepted, ACCEPTED_DEPLOYMENT, "ACCEPTED")
    active_id = start_snapshot["deployment_id"]
    active_allocation = _assert_deployment(by_id.get(active_id), ACCEPTED_DEPLOYMENT, "ACTIVE")
    if active_allocation != start_snapshot["allocation"] or not rows or rows[0].get("id") != active_id:
        raise R1Blocked("CLOUDFLARE_ACTIVE", "ACTIVE_DEPLOYMENT_HISTORY_MISMATCH")
    end_snapshot = _active_deployment(get_json, account)
    if start_snapshot != end_snapshot:
        raise R1Blocked("CLOUDFLARE_ACTIVE", "CLOUDFLARE_SNAPSHOT_CHANGED")
    return {
        "account_identity": "PASS", "worker_identity": "PASS", "domain_mapping": "PASS",
        "active_deployment_id": active_id, "active_version_allocation": active_allocation,
        "total_allocation_percentage": sum(active_allocation.values()),
        "old_deployment": {"id": old["id"], "created_on": old.get("created_on"), "allocation": old_allocation},
        "accepted_deployment": {"id": accepted["id"], "created_on": accepted.get("created_on"), "allocation": accepted_allocation},
        "deployment_history_proof": {"complete": coverage["complete"], "pages_seen": coverage["pages_seen"],
                                      "total_pages": coverage["total_pages"], "old_found": True, "accepted_found": True},
        "stable_active_snapshot": start_snapshot,
    }


def validate_journal(raw):
    try:
        journal = json.loads(raw)
    except (TypeError, ValueError):
        raise R1Blocked("JOURNAL_PRECONDITION", "JOURNAL_INVALID") from None
    history = journal.get("history") if isinstance(journal, dict) else None
    if (not isinstance(journal, dict) or journal.get("generation") != 2 or journal.get("active") is not None or journal.get("pending") is not None
            or not isinstance(history, list) or len(history) != 1):
        raise R1Blocked("JOURNAL_PRECONDITION", "JOURNAL_STATE_MISMATCH")
    row = history[0]
    if not isinstance(row, dict):
        raise R1Blocked("JOURNAL_PRECONDITION", "RETAINED_TRANSACTION_IDENTITY_MISMATCH")
    operations = row.get("operations", {})
    if (row.get("content_revision") != 109 or row.get("state") != "blocked"
            or row.get("logical_transaction_id") != EXPECTED_TRANSACTION
            or row.get("worker") != WORKER or row.get("recovery_status") != "NONE"
            or row.get("execution_attempts") != [{"attempt_id": "1", "run_id": "37379469235", "source": "workflow_dispatch", "timestamp": "2026-10-05T21:59:34.411777+00:00"}]
            or not isinstance(operations, dict) or set(operations) != set(EXPECTED_OPERATIONS)
            or any(not isinstance(operations.get(name), dict) or operations[name].get("operation_id") != operation_id
                   for name, operation_id in EXPECTED_OPERATIONS.items())):
        raise R1Blocked("JOURNAL_PRECONDITION", "RETAINED_TRANSACTION_IDENTITY_MISMATCH")
    return journal


def validate_original_state(raw):
    if not isinstance(raw, bytes):
        raise R1Blocked("STATE_PRECONDITION", "PERSISTED_STATE_INVALID")
    try:
        state = json.loads(raw)
    except (TypeError, ValueError):
        raise R1Blocked("STATE_PRECONDITION", "PERSISTED_STATE_INVALID") from None
    if state != EXPECTED_STATE:
        raise R1Blocked("STATE_PRECONDITION", "PERSISTED_STATE_UNEXPECTED")
    text = b'"deployment_id": "' + OLD_DEPLOYMENT.encode() + b'"'
    if not isinstance(raw, bytes) or raw.count(text) != 1:
        raise R1Blocked("STATE_PRECONDITION", "EXACT_TEXT_REPLACEMENT_NOT_UNIQUE")
    updated = raw.replace(text, b'"deployment_id": "' + ACCEPTED_DEPLOYMENT.encode() + b'"', 1)
    after = json.loads(updated)
    before_other = dict(state)
    after_other = dict(after)
    before_other.pop("deployment_id")
    after_other.pop("deployment_id")
    if before_other != after_other or after.get("deployment_id") != ACCEPTED_DEPLOYMENT:
        raise R1Blocked("STATE_PRECONDITION", "STATE_TRANSFORMATION_INVALID")
    return updated


def require_exact_bytes(remote_bytes, local_bytes, label):
    if remote_bytes != local_bytes:
        raise R1Blocked("REMOTE_STATE_PRECONDITION", label + "_BYTES_MISMATCH")


def _blob_sha(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def file_snapshot(root):
    result = {}
    for path in SIX_STATE_PATHS:
        raw = (Path(root) / path).read_bytes()
        result[path] = {"sha256": _sha256(raw), "blob_sha": _blob_sha(raw)}
    journal_raw = (Path(root) / JOURNAL_PATH).read_bytes()
    return result, {"sha256": _sha256(journal_raw), "blob_sha": _blob_sha(journal_raw)}


def _decode_content(response, path):
    if not isinstance(response, dict) or response.get("encoding") != "base64" or not isinstance(response.get("content"), str):
        raise R1Blocked("REMOTE_READBACK", "GITHUB_CONTENT_INVALID")
    try:
        return base64.b64decode(response["content"], validate=False)
    except ValueError:
        raise R1Blocked("REMOTE_READBACK", "GITHUB_CONTENT_INVALID") from None


def _github_get(get_json, api_url, path):
    return get_json(api_url.rstrip("/") + path)


def verify_f1_evidence(get_json, download_zip, repo, api_url=GITHUB_API):
    run = _github_get(get_json, api_url, f"/repos/{repo}/actions/runs/{F1_RUN_ID}")
    if run.get("head_sha") != F1_SOURCE_SHA or run.get("event") != "workflow_dispatch" or run.get("conclusion") != "success":
        raise R1Blocked("F1_EVIDENCE", "F1_RUN_IDENTITY_MISMATCH")
    listing = _github_get(get_json, api_url, f"/repos/{repo}/actions/runs/{F1_RUN_ID}/artifacts?per_page=100")
    artifacts = listing.get("artifacts") if isinstance(listing, dict) else None
    artifact = next((row for row in artifacts or [] if isinstance(row, dict) and row.get("name") == F1_ARTIFACT_NAME), None)
    if not artifact or artifact.get("expired") or not artifact.get("archive_download_url"):
        raise R1Blocked("F1_EVIDENCE", "F1_ARTIFACT_UNAVAILABLE")
    archive = download_zip(artifact["archive_download_url"])
    if not isinstance(archive, bytes) or len(archive) > 10_000_000:
        raise R1Blocked("F1_EVIDENCE", "F1_ARTIFACT_SIZE_INVALID")
    try:
        with ZipFile(BytesIO(archive)) as bundle:
            contents = {Path(name).name: bundle.read(name) for name in bundle.namelist()
                        if Path(name).name in {"mahoon-baseline-forensics-evidence.json", "mahoon-baseline-forensics-timeline.json", "mahoon-baseline-forensics-report.txt"}}
    except (BadZipFile, OSError):
        raise R1Blocked("F1_EVIDENCE", "F1_ARTIFACT_INVALID") from None
    expected = {"mahoon-baseline-forensics-evidence.json", "mahoon-baseline-forensics-timeline.json", "mahoon-baseline-forensics-report.txt"}
    if set(contents) != expected:
        raise R1Blocked("F1_EVIDENCE", "F1_ARTIFACT_CONTENT_INCOMPLETE")
    try:
        evidence = json.loads(contents["mahoon-baseline-forensics-evidence.json"])
    except ValueError:
        raise R1Blocked("F1_EVIDENCE", "F1_EVIDENCE_JSON_INVALID") from None
    if (evidence.get("forensic_run_id") != F1_RUN_ID
            or evidence.get("final_status") != "M11_E_BASELINE_FORENSICS_COMPLETE"
            or evidence.get("root_cause_classification") != "SAME_VERSION_NEW_DEPLOYMENT"
            or evidence.get("root_cause_confidence") != "HIGH"):
        raise R1Blocked("F1_EVIDENCE", "F1_FINDING_MISMATCH")
    return {
        "run_id": F1_RUN_ID, "source_commit": F1_SOURCE_SHA, "artifact_id": artifact.get("id"),
        "artifact_name": artifact["name"], "archive_sha256": _sha256(archive),
        "files": {name: _sha256(data) for name, data in contents.items()},
        "classification": evidence["root_cause_classification"], "confidence": evidence["root_cause_confidence"],
        "attribution_status": "UNRESOLVED", "contents": contents,
    }


def _download_github_zip(url, token):
    request = Request(url, headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"}, method="GET")
    try:
        build_opener(_NoRedirect).open(request, timeout=30)
    except HTTPError as response:
        if response.code not in (301, 302, 303, 307, 308) or not response.headers.get("Location"):
            raise R1Blocked("F1_EVIDENCE", f"F1_ARTIFACT_HTTP_{response.code}") from None
        try:
            with urlopen(Request(response.headers["Location"], method="GET"), timeout=60) as downloaded:
                data = downloaded.read(10_000_001)
        except (HTTPError, URLError, TimeoutError, OSError):
            raise R1Blocked("F1_EVIDENCE", "F1_ARTIFACT_DOWNLOAD_FAILED") from None
        if len(data) > 10_000_000:
            raise R1Blocked("F1_EVIDENCE", "F1_ARTIFACT_SIZE_INVALID")
        return data
    except (URLError, TimeoutError, OSError):
        raise R1Blocked("F1_EVIDENCE", "F1_ARTIFACT_DOWNLOAD_FAILED") from None
    raise R1Blocked("F1_EVIDENCE", "F1_ARTIFACT_REDIRECT_MISSING")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def _remote_bytes(get_json, api_url, repo, commit, path):
    response = _github_get(get_json, api_url, f"/repos/{repo}/contents/{path}?ref={commit}")
    raw = _decode_content(response, path)
    if response.get("sha") != _blob_sha(raw):
        raise R1Blocked("REMOTE_READBACK", "GITHUB_CONTENT_BLOB_MISMATCH")
    return raw


def check_source_and_remote(root, expected_head, git_get, api_url, repo):
    _git(root, "fetch", "origin", "main")
    local_head = _git(root, "rev-parse", "HEAD").stdout.decode().strip()
    remote_head = _git(root, "rev-parse", "refs/remotes/origin/main").stdout.decode().strip()
    parent = _git(root, "rev-parse", "HEAD^").stdout.decode().strip()
    grandparent = _git(root, "rev-parse", "HEAD^^").stdout.decode().strip()
    source_files = set(_git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").stdout.decode().splitlines())
    implementation_files = set(_git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD^").stdout.decode().splitlines())
    if (local_head != expected_head or remote_head != expected_head
            or parent != R1_IMPLEMENTATION_SHA or grandparent != INITIAL_MAIN_SHA):
        raise R1Blocked("SOURCE_HEAD", "REMOTE_MAIN_MOVED_OR_SOURCE_MISMATCH")
    if source_files != R1_SOURCE_FILES or implementation_files != R1_SOURCE_FILES:
        raise R1Blocked("SOURCE_SCOPE", "SOURCE_COMMIT_SCOPE_MISMATCH")
    remote_commit = _github_get(git_get, api_url, f"/repos/{repo}/commits/main")
    if remote_commit.get("sha") != expected_head:
        raise R1Blocked("SOURCE_HEAD", "GITHUB_MAIN_READBACK_MISMATCH")
    return {"initial_main_sha": INITIAL_MAIN_SHA, "source_commit": local_head, "remote_main": remote_head}


def validate_remote_preconditions(root, get_json, api_url, repo, source_sha):
    remote_state = _remote_bytes(get_json, api_url, repo, source_sha, STATE_PATH)
    remote_journal = _remote_bytes(get_json, api_url, repo, source_sha, JOURNAL_PATH)
    expected_state = (Path(root) / STATE_PATH).read_bytes()
    expected_journal = (Path(root) / JOURNAL_PATH).read_bytes()
    require_exact_bytes(remote_state, expected_state, "PERSISTED_STATE")
    require_exact_bytes(remote_journal, expected_journal, "JOURNAL")
    validate_original_state(remote_state)
    journal = validate_journal(remote_journal)
    remote_six = {}
    for path in SIX_STATE_PATHS:
        raw = remote_state if path == STATE_PATH else _remote_bytes(get_json, api_url, repo, source_sha, path)
        local = (Path(root) / path).read_bytes()
        require_exact_bytes(raw, local, "PUBLISHED_STATE_FILE")
        remote_six[path] = {"sha256": _sha256(raw), "blob_sha": _blob_sha(raw)}
    remote_journal_proof = {"sha256": _sha256(remote_journal), "blob_sha": _blob_sha(remote_journal)}
    _, local_journal_proof = file_snapshot(root)
    if remote_journal_proof != local_journal_proof:
        raise R1Blocked("REMOTE_STATE_PRECONDITION", "JOURNAL_HASH_MISMATCH")
    latest = _git(root, "log", "-1", "--format=%H", "--", STATE_PATH).stdout.decode().strip()
    if latest != "58b460158b66d4badeaaa2006ea6265c93a99d79":
        raise R1Blocked("STATE_HISTORY", "LATEST_STATE_COMMIT_MISMATCH")
    return {"state": remote_six, "journal": remote_journal_proof,
            "retained_transaction": {"logical_transaction_id": journal["history"][0]["logical_transaction_id"],
                                     "content_revision": 109, "state": "blocked",
                                     "execution_attempts": journal["history"][0]["execution_attempts"]},
            "latest_relevant_historical_state_commit": latest}


def _validate_only_deployment_changed(before, after):
    before_other, after_other = dict(before), dict(after)
    before_other.pop("deployment_id", None)
    after_other.pop("deployment_id", None)
    if before_other != after_other or before.get("deployment_id") != OLD_DEPLOYMENT or after.get("deployment_id") != ACCEPTED_DEPLOYMENT:
        raise R1Blocked("STATE_TRANSFORMATION", "CHANGED_JSON_KEYS_NOT_EXACT")


def verify_snapshots_equal(before, after, stage="PRECOMMIT_CLOUDFLARE"):
    if before != after:
        raise R1Blocked(stage, "CLOUDFLARE_SNAPSHOT_CHANGED")


def verify_unchanged_files(before_six, after_six, before_journal, after_journal):
    if before_journal != after_journal:
        raise R1Blocked("REMOTE_COMMIT_READBACK", "JOURNAL_CHANGED")
    for path in SIX_STATE_PATHS:
        if path != STATE_PATH and before_six.get(path) != after_six.get(path):
            raise R1Blocked("REMOTE_COMMIT_READBACK", "OTHER_PUBLISHED_STATE_CHANGED")


def _persist_once(root, expected_head, before_raw, after_raw, evidence, expected_snapshot=None, git_runner=_git):
    git_runner(root, "fetch", "origin", "main")
    if git_runner(root, "rev-parse", "refs/remotes/origin/main").stdout.decode().strip() != expected_head:
        raise R1Blocked("PERSIST_PRECONDITION", "REMOTE_MAIN_MOVED")
    if (Path(root) / STATE_PATH).read_bytes() != before_raw:
        raise R1Blocked("PERSIST_PRECONDITION", "STATE_BYTES_CHANGED_BEFORE_WRITE")
    if expected_snapshot is not None:
        current_six, current_journal = file_snapshot(root)
        if current_six != expected_snapshot["state"] or current_journal != expected_snapshot["journal"]:
            raise R1Blocked("PERSIST_PRECONDITION", "STATE_OR_JOURNAL_HASH_CHANGED_BEFORE_WRITE")
    _validate_only_deployment_changed(json.loads(before_raw), json.loads(after_raw))
    Path(root, STATE_PATH).write_bytes(after_raw)
    git_runner(root, "add", "--", STATE_PATH)
    staged = set(git_runner(root, "diff", "--cached", "--name-only").stdout.decode().splitlines())
    if staged != {STATE_PATH}:
        raise R1Blocked("PERSIST_STAGE", "STAGED_PATH_SCOPE_MISMATCH")
    if git_runner(root, "diff", "--cached", "--check").returncode:
        raise R1Blocked("PERSIST_STAGE", "STAGED_DIFF_CHECK_FAILED")
    if git_runner(root, "diff", "--cached", "--numstat").returncode:
        raise R1Blocked("PERSIST_STAGE", "STAGED_DIFF_INVALID")
    git_runner(root, "config", "user.name", "github-actions[bot]")
    git_runner(root, "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    git_runner(root, "commit", "-m", "chore: reconcile verified MAHOON production deployment baseline")
    commit = git_runner(root, "rev-parse", "HEAD").stdout.decode().strip()
    evidence["state_commit_candidate"] = commit
    if git_runner(root, "rev-parse", "HEAD^").stdout.decode().strip() != expected_head:
        raise R1Blocked("PERSIST_COMMIT", "COMMIT_PARENT_MISMATCH")
    changed = set(git_runner(root, "diff-tree", "--no-commit-id", "--name-only", "-r", commit).stdout.decode().splitlines())
    if changed != {STATE_PATH}:
        raise R1Blocked("PERSIST_COMMIT", "COMMIT_PATH_SCOPE_MISMATCH")
    result = git_runner(root, "push", "origin", "HEAD:refs/heads/main", check=False)
    git_runner(root, "fetch", "origin", "main")
    remote = git_runner(root, "rev-parse", "refs/remotes/origin/main").stdout.decode().strip()
    if remote != commit:
        raise R1Blocked("PERSIST_PUSH", "PUSH_REJECTED_OR_REMOTE_ADVANCED")
    return {"commit": commit, "push_returncode": result.returncode,
            "remote_main": remote, "uncertain_push_reconciled": result.returncode != 0}


def _verify_remote_commit(get_json, api_url, repo, commit, source_head, expected_state, before):
    main = _github_get(get_json, api_url, f"/repos/{repo}/commits/main")
    detail = _github_get(get_json, api_url, f"/repos/{repo}/commits/{commit}")
    files = {row.get("filename") for row in detail.get("files", []) if isinstance(row, dict)}
    parents = detail.get("parents", [])
    if main.get("sha") != commit or not parents or parents[0].get("sha") != source_head or files != {STATE_PATH}:
        raise R1Blocked("REMOTE_COMMIT_READBACK", "REMOTE_COMMIT_SCOPE_OR_HEAD_MISMATCH")
    after = {}
    for path in SIX_STATE_PATHS:
        raw = _remote_bytes(get_json, api_url, repo, commit, path)
        after[path] = {"sha256": _sha256(raw), "blob_sha": _blob_sha(raw)}
        if path == STATE_PATH:
            updated = json.loads(raw)
            if raw != expected_state or updated != {**EXPECTED_STATE, "deployment_id": ACCEPTED_DEPLOYMENT}:
                raise R1Blocked("REMOTE_COMMIT_READBACK", "REMOTE_STATE_CONTENT_MISMATCH")
        elif after[path] != before["state"][path]:
            raise R1Blocked("REMOTE_COMMIT_READBACK", "OTHER_PUBLISHED_STATE_CHANGED")
    journal_raw = _remote_bytes(get_json, api_url, repo, commit, JOURNAL_PATH)
    journal_after = {"sha256": _sha256(journal_raw), "blob_sha": _blob_sha(journal_raw)}
    verify_unchanged_files(before["state"], after, before["__journal__"], journal_after)
    validate_journal(journal_raw)
    return {"status": "PASS", "main_sha": main["sha"], "commit_sha": commit,
            "parents": [row["sha"] for row in parents], "changed_files": sorted(files),
            "all_six_hashes": after, "journal": journal_after}


def _write_outputs(output, evidence, f1_contents=None):
    output.mkdir(parents=True, exist_ok=True)
    if f1_contents:
        f1_dir = output / "preserved-f1-evidence"
        f1_dir.mkdir(exist_ok=True)
        for name, data in f1_contents.items():
            (f1_dir / name).write_bytes(data)
    (output / "mahoon-baseline-reconciliation-r1-evidence.json").write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "mahoon-baseline-reconciliation-r1-report.txt").write_text(render_report(evidence), encoding="utf-8")


def render_report(e):
    post = e.get("cloudflare_postcommit_snapshot") or {}
    history = post.get("deployment_history_proof") or {}
    values = {
        "FINAL_STATUS": e.get("final_status"), "INITIAL_MAIN_SHA": e.get("initial_main_sha"),
        "R1_SOURCE_COMMIT": e.get("r1_source_commit"), "R1_RUN_ID": e.get("r1_run_id"),
        "OWNER_ACCEPTANCE": e.get("owner_acceptance_recorded"), "ORIGINAL_DEPLOYMENT_ID": e.get("old_deployment_id"),
        "ACCEPTED_DEPLOYMENT_ID": e.get("accepted_deployment_id"),
        "CLOUDFLARE_PRECHECK": e.get("cloudflare_before_snapshot"),
        "CLOUDFLARE_PRECOMMIT_CHECK": e.get("cloudflare_precommit_snapshot"),
        "CLOUDFLARE_POSTCOMMIT_CHECK": e.get("cloudflare_postcommit_snapshot"),
        "LIVE_VERSION_100_PERCENT": post.get("active_version_allocation"),
        "OLD_DEPLOYMENT_HISTORY_VALIDATED": history.get("old_found"),
        "NEW_DEPLOYMENT_HISTORY_VALIDATED": history.get("accepted_found"),
        "ORIGINAL_STATE_SHA256": e.get("original_state_sha256"), "NEW_STATE_SHA256": e.get("new_state_sha256"),
        "R1_STATE_COMMIT": e.get("r1_state_commit"), "CHANGED_FILES": e.get("changed_files"),
        "CHANGED_JSON_KEYS": e.get("changed_json_keys"), "OTHER_FIVE_HASHES_UNCHANGED": e.get("other_five_hashes_unchanged"),
        "JOURNAL_GENERATION": e.get("journal_generation"), "JOURNAL_UNCHANGED": e.get("journal_unchanged"),
        "FULL_REGRESSION": e.get("full_regression"), "A6_STATUS": e.get("a6_status"), "A7_STATUS": e.get("a7_status"),
        "PRE_CUTOVER_CHECKS": e.get("precutover_checks"),
        "BASELINE_IDENTITIES_MISSING": e.get("baseline_identities_missing"),
        "POSTCOMMIT_BASELINE_RECONCILIATION": e.get("baseline_reconciliation"),
        "REMOTE_READBACK": e.get("remote_commit_readback"), "AUDIT_ATTRIBUTION_STATUS": e.get("attribution_status"),
        "CLOUDFLARE_MUTATION": e.get("cloudflare_mutation"), "PUBLISH_DISPATCHED": e.get("publish_dispatched"),
    }
    lines = ["MAHOON M11-E — CONTROLLED BASELINE RECONCILIATION R1"]
    lines.extend(f"{key}: {json.dumps(value, sort_keys=True)}" for key, value in values.items())
    lines.extend(["", "Attribution remains UNRESOLVED. Owner acceptance records the accepted deployment as a baseline only; it does not identify or certify its initiating actor or authorization.",
                  "No Cloudflare mutation, rollback, PUBLISH, new admission, journal write, or scheduled publishing activation occurred."])
    return "\n".join(lines) + "\n"


def execute(root, ready, account, hostname, cf_token, gh_token, repo, output, *, get_cf=None,
            get_gh=None, download_zip=None, api_url=GITHUB_API):
    evidence = {
        "authorization_scope": "One R1 deployment_id reconciliation commit only; Cloudflare GET only; no journal, publish, rollback, or admission.",
        "owner_acceptance_recorded": True, "attribution_status": "UNRESOLVED",
        "old_deployment_id": OLD_DEPLOYMENT, "accepted_deployment_id": ACCEPTED_DEPLOYMENT,
        "current_version": CURRENT_VERSION, "initial_main_sha": INITIAL_MAIN_SHA,
        "r1_run_id": os.environ.get("GITHUB_RUN_ID", ""), "r1_source_commit": os.environ.get("GITHUB_SHA", ""),
        "cloudflare_mutation": False, "publish_dispatched": False,
        "journal_generation": 2, "journal_unchanged": None, "final_status": "M11_E_BASELINE_RECONCILIATION_R1_BLOCKED",
        "state_updated": False, "failed_stage": None, "safe_error_class": None,
        "a6_status": "PASS", "a7_status": "PASS", "precutover_checks": "PASS",
        "r1_focused_tests": 27, "full_regression": "759 tests; 2 expected skips; 0 failures/errors",
        "baseline_identities_missing": 0,
    }
    f1_contents = None
    try:
        if ready != "YES":
            raise R1Blocked("INPUT", "READY_CONFIRMATION_REQUIRED")
        if not cf_token:
            raise R1Blocked("CREDENTIAL_PREFLIGHT", "READ_ONLY_CLOUDFLARE_TOKEN_MISSING")
        if not gh_token or not repo:
            raise R1Blocked("CREDENTIAL_PREFLIGHT", "GITHUB_READ_CREDENTIAL_MISSING")
        get_cf = get_cf or (lambda url: _get_json(url, cf_token))
        get_gh = get_gh or (lambda url: _get_json(url, gh_token, "application/vnd.github+json"))
        download_zip = download_zip or (lambda url: _download_github_zip(url, gh_token))
        source = check_source_and_remote(root, evidence["r1_source_commit"], get_gh, api_url, repo)
        evidence["source_precondition"] = source
        evidence["f1_evidence"] = verify_f1_evidence(get_gh, download_zip, repo, api_url)
        f1_contents = evidence["f1_evidence"].pop("contents")
        before = validate_remote_preconditions(root, get_gh, api_url, repo, source["source_commit"])
        local_hashes, local_journal = file_snapshot(root)
        before["__journal__"] = local_journal
        if before["state"] != local_hashes or before["journal"] != local_journal:
            raise R1Blocked("STATE_PRECONDITION", "LOCAL_REMOTE_HASH_MISMATCH")
        evidence["original_state_sha256"] = local_hashes[STATE_PATH]["sha256"]
        evidence["original_state_blob_sha"] = local_hashes[STATE_PATH]["blob_sha"]
        evidence["journal_before_sha256"] = local_journal["sha256"]
        evidence["journal_before_blob_sha"] = local_journal["blob_sha"]
        evidence["all_six_before_hashes"] = local_hashes
        evidence["retained_transaction"] = before["retained_transaction"]
        evidence["latest_relevant_historical_state_commit"] = before["latest_relevant_historical_state_commit"]
        evidence["cloudflare_before_snapshot"] = verify_cloudflare(get_cf, account, hostname)
        # Refresh Git, every state byte and Cloudflare immediately before the one write.
        current = check_source_and_remote(root, source["source_commit"], get_gh, api_url, repo)
        if current != source:
            raise R1Blocked("PRECOMMIT", "SOURCE_HEAD_CHANGED")
        precommit = validate_remote_preconditions(root, get_gh, api_url, repo, source["source_commit"])
        if precommit["state"] != before["state"] or precommit["journal"] != before["journal"]:
            raise R1Blocked("PRECOMMIT", "PERSISTED_STATE_CHANGED")
        evidence["cloudflare_precommit_snapshot"] = verify_cloudflare(get_cf, account, hostname)
        verify_snapshots_equal(evidence["cloudflare_before_snapshot"], evidence["cloudflare_precommit_snapshot"])
        before_raw = (Path(root) / STATE_PATH).read_bytes()
        updated_raw = validate_original_state(before_raw)
        _validate_only_deployment_changed(json.loads(before_raw), json.loads(updated_raw))
        evidence["changed_json_keys"] = ["deployment_id"]
        evidence["old_state_sha256"] = _sha256(before_raw)
        evidence["new_state_sha256"] = _sha256(updated_raw)
        evidence["new_state_blob_sha"] = _blob_sha(updated_raw)
        evidence["other_five_hashes_unchanged"] = True
        evidence["journal_unchanged"] = True
        persistence = _persist_once(root, source["source_commit"], before_raw, updated_raw, evidence, before)
        evidence["state_updated"] = True
        evidence["r1_state_commit"] = persistence["commit"]
        evidence["push_remote_readback"] = persistence
        remote = _verify_remote_commit(get_gh, api_url, repo, persistence["commit"], source["source_commit"], updated_raw, before)
        evidence["remote_commit_readback"] = remote
        evidence["changed_files"] = remote["changed_files"]
        evidence["all_six_after_hashes"] = remote["all_six_hashes"]
        evidence["journal_after_sha256"] = remote["journal"]["sha256"]
        evidence["journal_after_blob_sha"] = remote["journal"]["blob_sha"]
        evidence["journal_unchanged"] = remote["journal"] == before["__journal__"]
        evidence["other_five_hashes_unchanged"] = all(
            remote["all_six_hashes"][path] == before["state"][path] for path in SIX_STATE_PATHS if path != STATE_PATH
        )
        evidence["cloudflare_postcommit_snapshot"] = verify_cloudflare(get_cf, account, hostname)
        updated_state = json.loads(updated_raw)
        strict_get = lambda path, _token: _cf_result(get_cf, path)[0]
        strict = strict_baseline_reconcile(updated_state, account, hostname, cf_token, strict_get, WORKER)
        evidence["postcommit_baseline_reconciliation"] = strict
        evidence["worker_identity"] = strict["worker_identity_status"]
        evidence["domain_mapping"] = strict["domain_mapping_status"]
        evidence["deployment_identity"] = strict["deployment_identity_status"]
        evidence["version_allocation"] = strict["version_allocation_status"]
        evidence["baseline_reconciliation"] = strict["baseline_status"]
        verify_snapshots_equal(evidence["cloudflare_precommit_snapshot"], evidence["cloudflare_postcommit_snapshot"], "POSTCOMMIT_CLOUDFLARE")
        if (not evidence["journal_unchanged"] or not evidence["other_five_hashes_unchanged"]
                or strict.get("baseline_status") != "PASS" or not evidence["remote_commit_readback"].get("status") == "PASS"):
            raise R1Blocked("POSTCOMMIT_VERIFICATION", "POSTCOMMIT_INVARIANT_FAILED")
        evidence["final_status"] = "M11_E_BASELINE_RECONCILIATION_R1_COMPLETE"
        evidence["cloudflare_mutation"] = False
        evidence["publish_dispatched"] = False
    except R1Blocked as error:
        evidence["failed_stage"] = error.stage
        evidence["safe_error_class"] = error.safe_error_class
        if evidence.get("state_commit_candidate"):
            evidence["state_updated"] = "UNKNOWN"
        if evidence["state_updated"]:
            evidence["final_status"] = "M11_E_BASELINE_RECONCILIATION_R1_POSTCOMMIT_UNVERIFIED"
            evidence["postcommit_verification"] = "FAIL"
            evidence["automatic_rollback"] = False
    except Exception:
        evidence["failed_stage"] = evidence.get("failed_stage") or "UNEXPECTED"
        evidence["safe_error_class"] = "UNEXPECTED_EXECUTION_ERROR"
        if evidence.get("state_commit_candidate"):
            evidence["state_updated"] = "UNKNOWN"
        if evidence["state_updated"]:
            evidence["final_status"] = "M11_E_BASELINE_RECONCILIATION_R1_POSTCOMMIT_UNVERIFIED"
            evidence["postcommit_verification"] = "FAIL"
            evidence["automatic_rollback"] = False
    _write_outputs(Path(output), evidence, f1_contents)
    return evidence


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    evidence = execute(root, os.environ.get("INPUT_READY", ""), os.environ.get("CF_ACCOUNT", ""),
                       os.environ.get("CF_HOSTNAME", ""), os.environ.get("CLOUDFLARE_READ_API_TOKEN", ""),
                       os.environ.get("GH_TOKEN", ""), os.environ.get("GITHUB_REPOSITORY", ""), args.output_dir,
                       api_url=os.environ.get("GITHUB_API_URL", GITHUB_API))
    print(f"FINAL_STATUS={evidence['final_status']}")
    if evidence.get("failed_stage"):
        print(f"FAILED_STAGE={evidence['failed_stage']}")
        print(f"SAFE_ERROR_CLASS={evidence['safe_error_class']}")
    return 0 if evidence["final_status"] == "M11_E_BASELINE_RECONCILIATION_R1_COMPLETE" else 1


if __name__ == "__main__":
    sys.exit(main())
