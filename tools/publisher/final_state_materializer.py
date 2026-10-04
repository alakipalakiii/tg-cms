"""Pure materialization of the six publisher-state files from sealed evidence."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Mapping

from publisher import artifact_contract as contracts
from publisher import final_persistence_runner as persistence
from publisher import effective_mutation_result as effective_result
from publisher import media_bootstrap
from publisher import proof_recovery_runner
from publisher import seal_artifact
from publisher.core import fingerprint


class MaterializationRejected(ValueError):
    """A5.7 inputs cannot authorize deterministic final state bytes."""


_OPERATIONS = ("upload_version", "deploy_zero_percent", "promote")


def _json_object(raw: bytes, label: str) -> dict:
    if not isinstance(raw, bytes):
        raise MaterializationRejected(f"{label} must be raw bytes")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise MaterializationRejected(f"{label} is not UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise MaterializationRejected(f"{label} must contain an object")
    contracts.canonical_json_bytes(value)
    return value


def _state_json(value: dict) -> bytes:
    contracts.canonical_json_bytes(value)
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _site_inventory(root: Path) -> list[dict]:
    raw_root = Path(root)
    if raw_root.is_symlink():
        raise MaterializationRejected("sealed site root cannot be a symlink")
    root = raw_root.resolve(strict=True)
    if not root.is_dir():
        raise MaterializationRejected("sealed site root is not a directory")
    result = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise MaterializationRejected("sealed site contains a symlink")
        if path.is_file():
            data = path.read_bytes()
            result.append({
                "path": path.relative_to(root).as_posix(),
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            })
    return result


def _snapshot_posts(raw: bytes, bundle: Mapping) -> tuple[list[dict], int]:
    snapshot = _json_object(raw, "content snapshot")
    if (set(snapshot) != {"contract", "snapshot_total_count", "payload"}
            or snapshot["contract"] != "POSTS_FULL_PUBLIC_SNAPSHOT_V2"
            or not isinstance(snapshot["payload"], dict)
            or set(snapshot["payload"]) != {"posts"}
            or not isinstance(snapshot["payload"]["posts"], list)):
        raise MaterializationRejected("content snapshot contract is invalid")
    posts = snapshot["payload"]["posts"]
    count = snapshot["snapshot_total_count"]
    if isinstance(count, bool) or not isinstance(count, int) or count != len(posts):
        raise MaterializationRejected("content snapshot count is inconsistent")
    exported = {"contract": "PUBLISHED_CONTENT_DELTA_CONTRACT_V2", "count": count,
                "posts": posts}
    if fingerprint(exported) != bundle["payload"]["content_fingerprint"]:
        raise MaterializationRejected("snapshot content fingerprint differs from build bundle")
    return posts, count


def _merge_media_index(prior_raw: bytes, binding: Mapping, posts: list[dict],
                       media: Mapping) -> bytes:
    exists = binding["exists"]
    previous = json.loads(prior_raw.decode("utf-8")) if exists else None
    if previous is not None:
        contracts.canonical_json_bytes(previous)
    known = media_bootstrap.load_index_bytes(prior_raw if exists else None)

    required: dict[str, dict] = {}
    for post in posts:
        post_id = post.get("id") if isinstance(post, dict) else None
        if isinstance(post_id, bool) or not isinstance(post_id, int) or post_id < 1:
            raise MaterializationRejected("snapshot post ID is invalid for media lineage")
        for identity, kind in media_bootstrap.source_identifiers(post):
            item = required.setdefault(identity, {"post_ids": [], "media_type": kind})
            item["post_ids"].append(post_id)

    records = media.get("records")
    if not isinstance(records, list):
        raise MaterializationRejected("current media records are invalid")
    identities = [item.get("source_identifier") if isinstance(item, dict) else None
                  for item in records]
    if identities != sorted(required) or len(set(identities)) != len(identities):
        raise MaterializationRejected("current media manifest does not match snapshot identities")
    for record in records:
        identity = record["source_identifier"]
        if record.get("post_ids") != required[identity]["post_ids"]:
            raise MaterializationRejected("current media post-ID lineage mismatch")
        if record.get("fallback") is True:
            if identity in known or not isinstance(record.get("fallback_reason"), str):
                raise MaterializationRejected("media fallback conflicts with historical index")
            continue
        if record.get("fallback") is not False:
            raise MaterializationRejected("media record fallback state is invalid")
        item = {key: value for key, value in record.items()
                if key not in {"post_ids", "detected_mime"}}
        if (item.get("media_type") != required[identity]["media_type"]
                or not isinstance(item.get("immutable_path"), str)
                or not isinstance(item.get("mime"), str)
                or not isinstance(item.get("sha256"), str)):
            raise MaterializationRejected("successful media record is incomplete")
        # Historical bootstrap preserves prior canonical rows and only adds unseen successes.
        known.setdefault(identity, item)
    return media_bootstrap.serialize_index(known)


def materialize_final_state(*, proof: object, build_bundle: object,
                            operation_intents: Mapping[str, object],
                            operation_results: Mapping[str, object],
                            snapshot_bytes: bytes, media_manifest_bytes: bytes,
                            route_manifest_bytes: bytes, sealed_root: str | Path,
                            artifact_seal: object,
                            referenced_artifacts: Mapping[str, object] | None = None
                            ) -> dict[str, bytes]:
    """Return exactly six deterministic files; performs no persistence or mutations."""
    try:
        proof_v = contracts.validate_artifact(proof)
        bundle_v = contracts.validate_artifact(
            build_bundle, expected_transaction=proof_v["transaction"],
            expected_source_sha=proof_v["producer"]["source_sha"],
        )
        proof_v = proof_recovery_runner.validate_proof(
            proof_v, bundle_v, operation_results, referenced_artifacts=referenced_artifacts,
        )
        if proof_v["payload"]["proof_state"] != "PASS":
            raise MaterializationRejected("proof evidence is not PASS")
        if set(operation_intents) != set(_OPERATIONS):
            raise MaterializationRejected("exactly three operation intents are required")
        if set(operation_results) != set(_OPERATIONS):
            raise MaterializationRejected("exactly three operation results are required")

        tx, source_sha = proof_v["transaction"], proof_v["producer"]["source_sha"]
        bundle_sha = bundle_v["artifact_sha256"]
        refs = referenced_artifacts or {}
        checked_intents = {}
        for operation in _OPERATIONS:
            intent = contracts.validate_artifact(
                operation_intents[operation], expected_transaction=tx,
                expected_source_sha=source_sha, referenced_artifacts=refs,
            )
            result = contracts.validate_artifact(
                operation_results[operation], expected_transaction=tx,
                expected_source_sha=source_sha, referenced_artifacts=refs,
            )
            applied = effective_result.validate_effective_applied_result(
                result, intent, referenced_artifacts=refs,
            )
            ip, rp = intent["payload"], applied["payload"]
            if (ip["operation_name"] != operation or ip["build_bundle_sha256"] != bundle_sha
                    or rp["build_bundle_sha256"] != bundle_sha):
                raise MaterializationRejected(f"{operation} is not bound to this build")
            checked_intents[operation] = intent

        pp, bp = proof_v["payload"], bundle_v["payload"]
        identity = pp["candidate_identity"]
        production_identity = pp["production_validation"]["identity_confirmation"]
        upload = operation_results["upload_version"]["payload"]["readback_reference"]
        zero = operation_results["deploy_zero_percent"]["payload"]["readback_reference"]
        promoted = operation_results["promote"]["payload"]["readback_reference"]
        if (identity["content_fingerprint"] != bp["content_fingerprint"]
                or upload["resource_id"] != identity["candidate_version_id"]
                or zero["resource_id"] != identity["zero_percent_deployment_id"]
                or promoted["resource_id"] != production_identity["promotion_deployment_id"]
                or production_identity["candidate_version_id"] != identity["candidate_version_id"]
                or production_identity["baseline_version_id"] != identity["baseline_version_id"]):
            raise MaterializationRejected("candidate or deployment readback identity mismatch")

        binding = bp.get("prior_immutable_media_index")
        if binding is None:
            raise MaterializationRejected("build bundle lacks prior index authority")
        try:
            prior_raw = base64.b64decode(binding["transport_base64"], validate=True)
        except (ValueError, TypeError) as exc:
            raise MaterializationRejected("prior index transport is invalid") from exc
        contracts.validate_prior_index_transport(
            bundle_v, prior_raw, expected_transaction=tx, expected_source_sha=source_sha,
        )

        routes = _json_object(route_manifest_bytes, "route manifest")
        media = _json_object(media_manifest_bytes, "media manifest")
        if (contracts.sha256_bytes(snapshot_bytes) != bp["snapshot_sha256"]
                or contracts.sha256_bytes(route_manifest_bytes) != bp["route_manifest_sha256"]
                or contracts.sha256_bytes(media_manifest_bytes) != bp["media_manifest_sha256"]):
            raise MaterializationRejected("snapshot or manifest bytes differ from sealed build bundle")
        if media.get("contract") != "CURRENT_MEDIA_RESOLUTION_V1":
            raise MaterializationRejected("current media manifest contract is invalid")
        if not seal_artifact.verify_seal(Path(sealed_root), artifact_seal):
            raise MaterializationRejected("sealed static artifact verification failed")
        if (artifact_seal.get("content_fingerprint") != bp["content_fingerprint"]
                or artifact_seal.get("route_hash") != fingerprint(routes)):
            raise MaterializationRejected("static seal does not match build and route identity")
        inventory = _site_inventory(Path(sealed_root))
        if not inventory or inventory != bp["files"]:
            raise MaterializationRejected("sealed site inventory differs from build bundle")

        posts, count = _snapshot_posts(snapshot_bytes, bundle_v)
        state = contracts.STATE_FILE_PATHS
        result = {
            "publisher-state/production-content-fingerprint.json": _state_json({
                "fingerprint": bp["content_fingerprint"],
                "count": count,
                "published_content_revision": tx["content_revision"],
            }),
            "publisher-state/production-media-manifest.json": media_manifest_bytes,
            "publisher-state/immutable-media-index.json": _merge_media_index(
                prior_raw, binding, posts, media,
            ),
            "publisher-state/published-route-manifest.json": route_manifest_bytes,
            "publisher-state/current-accepted-route-manifest.json": route_manifest_bytes,
            "publisher-state/published-static-state.json": _state_json({
                "current_version": identity["candidate_version_id"],
                "previous_version": identity["baseline_version_id"],
                "current_version_type": "STATIC",
                "deployment_id": production_identity["promotion_deployment_id"],
                "artifact_seal": artifact_seal["artifact_sha256"],
                "content_fingerprint": bp["content_fingerprint"],
            }),
        }
        if set(result) != set(state) or any(not isinstance(data, bytes) for data in result.values()):
            raise MaterializationRejected("materializer did not produce exact-six byte mapping")
        persistence.validate_finalization_inputs(
            proof_v, bundle_v, operation_results, result, 0,
            referenced_artifacts=refs,
        )
        return {path: result[path] for path in sorted(result)}
    except MaterializationRejected:
        raise
    except Exception as exc:
        raise MaterializationRejected("sealed final-state inputs are invalid") from exc
