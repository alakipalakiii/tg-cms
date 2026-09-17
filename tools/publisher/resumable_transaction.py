"""Immutable, content-minimized evidence contracts for staged publishing."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .content_taxonomy import CATEGORY_DEFINITIONS, canonical_category
from .media_bootstrap import source_identifiers
from .promotion_gates import _expected_posts

TRANSACTION_RE = re.compile(r"^revision-(\d+)-run-(\d+)-attempt-(\d+)$")
REQUIRED_BUNDLE_FILES = {
    "transaction.json", "candidate-route-manifest.json", "remote-expectations.json",
    "semantic-media-manifest.json", "immutable-media-index.json", "artifact-seal.json",
    "local-evidence.json",
}


def canonical_hash(value: Any) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def transaction_id(revision: int, run_id: str, run_attempt: str) -> str:
    if revision < 1 or not run_id.isdigit() or not run_attempt.isdigit():
        raise ValueError("transaction identity inputs are invalid")
    return f"revision-{revision}-run-{run_id}-attempt-{run_attempt}"


def remote_expectations(posts: list[dict], routes: dict, media: dict) -> dict:
    """Keep only measured identifiers/order/taxonomy; never export post prose."""
    if not posts or not isinstance(routes.get("routes"), list):
        raise ValueError("snapshot posts or candidate routes are missing")
    source_posts = []
    by_id: dict[int, dict] = {}
    for post in posts:
        post_id = int(post["id"])
        slug = str(post.get("slug") or "").strip()
        if not slug or post_id in by_id:
            raise ValueError("snapshot post identity is invalid or duplicated")
        item = {"id": post_id, "slug": slug,
                "created_at": str(post.get("created_at") or ""),
                "category": canonical_category(post),
                "media_type": str(post.get("media_type") or "").lower()}
        source_posts.append(item)
        by_id[post_id] = item
    logical_posts = _expected_posts({"payload": {"posts": posts}})
    logical_ids = [int(post["id"]) for post in logical_posts]
    category_ids = {
        label: [int(item["id"]) for item in logical_posts if canonical_category(item) == label]
        for label, _variants in CATEGORY_DEFINITIONS
    }
    media_sources = {identity for post in posts for identity, _kind in source_identifiers(post)}
    newest_first = sorted(source_posts, key=lambda item: (item["created_at"], item["id"]), reverse=True)
    oldest = min(source_posts, key=lambda item: (item["created_at"], item["id"]))
    newest = newest_first[0]
    category_route = next((route for route in routes["routes"]
                           if route.startswith("/category/") and "/page/" not in route), "")
    audio = next((item for item in newest_first
                  if any(word in item["media_type"] for word in ("audio", "voice", "music"))
                  or item["category"] == "صوتی"), None)
    visual_routes = [
        {"name": "home-desktop", "route": "/"},
        {"name": "archive", "route": "/posts"},
        {"name": "category", "route": category_route},
        {"name": "old-post", "route": f"/post/{oldest['slug']}"},
        {"name": "new-post", "route": f"/post/{newest['slug']}"},
    ]
    if audio:
        visual_routes.append({"name": "audio-post", "route": f"/post/{audio['slug']}"})
    visual_routes.append({"name": "admin-shell", "route": "/admin", "admin": True})
    route_set = set(routes["routes"])
    visual_routes = [item for item in visual_routes if item["route"] in route_set]
    if not {"home-desktop", "archive", "category", "old-post", "new-post", "admin-shell"}.issubset(
        {item["name"] for item in visual_routes}
    ):
        raise ValueError("required representative visual routes are missing")
    return {
        "contract": "MAHOON_REMOTE_EXPECTATIONS_V1",
        "source_post_count": len(source_posts),
        "posts": source_posts,
        "listing_ids": logical_ids,
        "category_ids": category_ids,
        "media_source_count": len(media_sources),
        "visual_routes": visual_routes,
    }


def create_proof_bundle(destination: Path, *, transaction: dict, routes: dict,
                        media_manifest: dict, media_index: dict, seal: dict,
                        local_evidence: dict, posts: list[dict]) -> dict:
    destination.mkdir(parents=True, exist_ok=False)
    if not TRANSACTION_RE.fullmatch(str(transaction.get("transaction_id", ""))):
        raise ValueError("invalid publish transaction id")
    if seal.get("content_fingerprint") != transaction.get("content_fingerprint"):
        raise ValueError("artifact seal does not match content fingerprint")
    if not isinstance(routes.get("routes"), list) or routes.get("route_count") != len(routes["routes"]):
        raise ValueError("candidate route manifest cardinality is invalid")
    if not isinstance(media_manifest.get("records"), list) or not isinstance(media_index.get("entries"), list):
        raise ValueError("media evidence is malformed")
    route_sha = canonical_hash(routes)
    media_sha = canonical_hash(media_manifest)
    index_sha = canonical_hash(media_index)
    if seal.get("route_hash") != route_sha:
        raise ValueError("artifact seal does not match candidate route manifest")
    if seal.get("artifact_sha256") != canonical_hash({key: value for key, value in seal.items()
                                                       if key != "artifact_sha256"}):
        raise ValueError("artifact seal digest is invalid")
    transaction = {
        **transaction,
        "contract": "MAHOON_PUBLISH_TRANSACTION_V1",
        "route_manifest_sha256": route_sha,
        "semantic_media_manifest_sha256": media_sha,
        "immutable_media_index_sha256": index_sha,
        "remote_expectations_sha256": canonical_hash(remote_expectations(posts, routes, media_manifest)),
        "route_count": routes["route_count"],
        "media_record_count": len(media_manifest["records"]),
        "immutable_media_index_entry_count": len(media_index["entries"]),
    }
    values = {
        "transaction.json": transaction,
        "candidate-route-manifest.json": routes,
        "remote-expectations.json": remote_expectations(posts, routes, media_manifest),
        "semantic-media-manifest.json": media_manifest,
        "immutable-media-index.json": media_index,
        "artifact-seal.json": seal,
        "local-evidence.json": local_evidence,
    }
    for name, value in values.items():
        (destination / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    files = {name: hashlib.sha256((destination / name).read_bytes()).hexdigest()
             for name in sorted(REQUIRED_BUNDLE_FILES)}
    bundle_sha = canonical_hash(files)
    (destination / "bundle-index.json").write_text(json.dumps({
        "contract": "MAHOON_IMMUTABLE_PUBLISH_PROOF_BUNDLE_V1",
        "transaction_id": transaction["transaction_id"],
        "files": files,
        "bundle_sha256": bundle_sha,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"transaction_id": transaction["transaction_id"], "bundle_sha256": bundle_sha,
            "route_manifest_sha256": route_sha, "media_manifest_sha256": media_sha,
            "bundle_path": str(destination)}


def verify_proof_bundle(directory: Path, expected_transaction_id: str | None = None,
                        expected_source_sha: str | None = None) -> tuple[dict, str]:
    index = json.loads((directory / "bundle-index.json").read_text(encoding="utf-8"))
    if index.get("contract") != "MAHOON_IMMUTABLE_PUBLISH_PROOF_BUNDLE_V1":
        raise ValueError("proof bundle contract is invalid")
    files = index.get("files")
    if not isinstance(files, dict) or set(files) != REQUIRED_BUNDLE_FILES:
        raise ValueError("proof bundle file inventory is invalid")
    actual_files = {path.name for path in directory.iterdir() if path.is_file()} - {"bundle-index.json"}
    if actual_files != REQUIRED_BUNDLE_FILES:
        raise ValueError("proof bundle contains missing or unapproved files")
    for name, digest in files.items():
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"proof bundle file hash mismatch: {name}")
    bundle_sha = canonical_hash(files)
    if index.get("bundle_sha256") != bundle_sha:
        raise ValueError("proof bundle digest mismatch")
    transaction = json.loads((directory / "transaction.json").read_text(encoding="utf-8"))
    if index.get("transaction_id") != transaction.get("transaction_id"):
        raise ValueError("proof bundle transaction identity mismatch")
    if expected_transaction_id and transaction.get("transaction_id") != expected_transaction_id:
        raise ValueError("unexpected transaction id")
    if expected_source_sha and transaction.get("source_sha") != expected_source_sha:
        raise ValueError("proof bundle source SHA mismatch")
    routes = json.loads((directory / "candidate-route-manifest.json").read_text(encoding="utf-8"))
    expectations = json.loads((directory / "remote-expectations.json").read_text(encoding="utf-8"))
    media = json.loads((directory / "semantic-media-manifest.json").read_text(encoding="utf-8"))
    index_data = json.loads((directory / "immutable-media-index.json").read_text(encoding="utf-8"))
    seal = json.loads((directory / "artifact-seal.json").read_text(encoding="utf-8"))
    local = json.loads((directory / "local-evidence.json").read_text(encoding="utf-8"))
    tx_split = transaction.get("candidate_split", {})
    baseline = transaction.get("baseline_static_version")
    candidate = transaction.get("candidate_static_version")
    if (transaction.get("contract") != "MAHOON_PUBLISH_TRANSACTION_V1"
            or transaction.get("revision_requests") != 1
            or transaction.get("full_v2_exports") != 1
            or transaction.get("snapshot_api_starts") != 0
            or transaction.get("single_snapshot_reuse") != "YES"
            or not transaction.get("source_revision")
            or not transaction.get("source_sha")
            or transaction.get("route_count") != len(routes.get("routes", []))
            or tx_split.get(baseline) != 100 or tx_split.get(candidate) != 0
            or sum(tx_split.values()) != 100):
        raise ValueError("proof bundle transaction metadata or candidate split is invalid")
    if not all((
        (local.get("transaction_start_static_baseline") or {}).get("PASS") is True,
        (local.get("filesystem_gate") or {}).get("PASS") is True,
        (local.get("measured_local_gates") or {}).get("measured") is True,
        (local.get("measured_local_gates") or {}).get("PASS") is True,
        (local.get("pre_upload_live_baseline") or {}).get("PASS") is True,
        (local.get("pre_zero_percent_live_read") or {}).get("PASS") is True,
        bool(local.get("rollback_anchor")),
    )):
        raise ValueError("proof bundle is missing passing local gates or safety anchors")
    if canonical_hash(routes) != transaction.get("route_manifest_sha256"):
        raise ValueError("proof bundle route manifest hash mismatch")
    if canonical_hash(expectations) != transaction.get("remote_expectations_sha256"):
        raise ValueError("proof bundle remote expectations hash mismatch")
    if canonical_hash(media) != transaction.get("semantic_media_manifest_sha256"):
        raise ValueError("proof bundle semantic media hash mismatch")
    if canonical_hash(index_data) != transaction.get("immutable_media_index_sha256"):
        raise ValueError("proof bundle immutable media index hash mismatch")
    if seal.get("content_fingerprint") != transaction.get("content_fingerprint"):
        raise ValueError("proof bundle artifact seal content fingerprint mismatch")
    if seal.get("route_hash") != canonical_hash(routes):
        raise ValueError("proof bundle artifact seal route hash mismatch")
    if seal.get("artifact_sha256") != canonical_hash({key: value for key, value in seal.items()
                                                       if key != "artifact_sha256"}):
        raise ValueError("proof bundle artifact seal digest mismatch")
    return transaction, bundle_sha


def verify_remote_result(result: dict, transaction: dict, bundle_sha: str) -> None:
    if (result.get("contract") != "MAHOON_REMOTE_PROOF_RESULT_V1"
            or result.get("REMOTE_PROOF_PASS") is not True
            or result.get("transaction_id") != transaction.get("transaction_id")
            or result.get("candidate_version") != transaction.get("candidate_static_version")
            or result.get("bundle_sha256") != bundle_sha):
        raise ValueError("successful matching remote-proof artifact is required")


def split_is_baseline_zero(observed: dict, transaction: dict) -> bool:
    versions = observed.get("versions", [])
    state = {item.get("version_id"): item.get("percentage") for item in versions}
    baseline = transaction.get("baseline_static_version")
    candidate = transaction.get("candidate_static_version")
    preserved = transaction.get("preexisting_zero_versions", [])
    return bool(baseline and candidate and baseline != candidate
                and state.get(baseline) == 100 and state.get(candidate) == 0
                and all(state.get(version) == 0 for version in preserved)
                and sum(state.values()) == 100
                and all(version in {baseline, candidate, *preserved} or percentage == 0
                        for version, percentage in state.items()))


def verify_production_result(result: dict, transaction: dict, bundle_sha: str) -> None:
    if (result.get("contract") != "MAHOON_PRODUCTION_RESULT_V1"
            or result.get("PASS") is not True
            or result.get("transaction_id") != transaction.get("transaction_id")
            or result.get("candidate_version") != transaction.get("candidate_static_version")
            or result.get("bundle_sha256") != bundle_sha):
        raise ValueError("successful matching production result is required")
