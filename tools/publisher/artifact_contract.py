"""Strict, credential-free validation for MAHOON publisher V1 artifacts."""
from __future__ import annotations

import copy
import base64
import hashlib
import json
import re
import uuid
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, Mapping


SCHEMA_VERSION = "1.0"
ARTIFACT_TYPES = frozenset({
    "revision_resolution",
    "admission_receipt",
    "build_bundle",
    "mutation_intent",
    "mutation_result",
    "recovered_mutation_result",
    "pre_promotion_proof_evidence",
    "proof_evidence",
    "recovery_decision",
    "final_persistence_payload",
})
OPERATION_NAMES = ("upload_version", "deploy_zero_percent", "promote", "rollback")
RESULT_STATES = frozenset({"APPLIED", "NOT_APPLIED", "UNKNOWN"})
RECOVERY_DECISIONS = frozenset({
    "RECONCILED_APPLIED", "RECONCILED_NOT_APPLIED", "BLOCKED_UNKNOWN",
})
ADMISSION_DECISIONS = frozenset({"ADMITTED", "COALESCED", "DEFERRED", "SUPERSEDED"})
REVISION_DECISIONS = frozenset({"UNCHANGED", "CHANGED"})
ENDPOINT_IDS = frozenset({"mahoon-content-revision-v1"})
STATE_FILE_PATHS = frozenset({
    "publisher-state/production-content-fingerprint.json",
    "publisher-state/production-media-manifest.json",
    "publisher-state/immutable-media-index.json",
    "publisher-state/published-route-manifest.json",
    "publisher-state/current-accepted-route-manifest.json",
    "publisher-state/published-static-state.json",
})
PRIOR_IMMUTABLE_MEDIA_INDEX_PATH = "publisher-state/immutable-media-index.json"

LOCAL_GATES = (
    "content_parity", "listing_uniqueness", "category_parity",
    "latest_parity", "seo", "media",
)
REMOTE_GATES = (
    "full_route_crawl", "content_parity", "listing_uniqueness",
    "category_parity", "latest_parity", "seo", "media", "visual",
    "zero_origin_runtime",
)
PRODUCTION_GATES = (
    "route_parity", "page_attribution", "content_parity",
    "listing_uniqueness", "category_parity", "latest_parity", "media",
    "visual", "seo", "zero_origin", "admin_panel",
)

_ENVELOPE_FIELDS = frozenset({
    "artifact_type", "schema_version", "artifact_id", "created_at",
    "producer", "transaction", "payload", "artifact_sha256",
})
_PRODUCER_FIELDS = frozenset({"workflow_run_id", "run_attempt", "job", "source_sha"})
_TRANSACTION_FIELDS = frozenset({"worker", "content_revision", "logical_transaction_id"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_OPAQUE_ID_RE = re.compile(r"^[^\s\x00-\x1f\x7f]+$")
_SECRET_KEY_RE = re.compile(r"(?:token|secret|password|authorization|credential|api[_-]?key)", re.I)


class ArtifactContractError(ValueError):
    """Artifact is malformed, unsupported, or fails an integrity check."""


def _exact_fields(value: object, expected: frozenset[str] | set[str], label: str) -> dict:
    if not isinstance(value, dict):
        raise ArtifactContractError(f"{label} must be an object")
    actual = set(value)
    expected_set = set(expected)
    missing = expected_set - actual
    unknown = actual - expected_set
    if missing:
        raise ArtifactContractError(f"{label} missing required fields: {sorted(missing)}")
    if unknown:
        raise ArtifactContractError(f"{label} contains unsupported fields: {sorted(unknown)}")
    return value


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _positive_int(value: object, label: str) -> int:
    if not _is_int(value) or value < 1:
        raise ArtifactContractError(f"{label} must be a positive integer")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if not _is_int(value) or value < 0:
        raise ArtifactContractError(f"{label} must be a non-negative integer")
    return value


def _nonempty_string(value: object, label: str, *, opaque: bool = False) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ArtifactContractError(f"{label} must be a nonempty trimmed string")
    if opaque and not _OPAQUE_ID_RE.fullmatch(value):
        raise ArtifactContractError(f"{label} must be an opaque identifier without whitespace/control characters")
    return value


def _sha256(value: object, label: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ArtifactContractError(f"{label} must be a lowercase SHA-256 digest")
    return value


def sha256_bytes(value: bytes) -> str:
    """Hash exact raw bytes; artifact envelopes still use canonical_json_bytes()."""
    if not isinstance(value, bytes):
        raise ArtifactContractError("raw digest input must be bytes")
    return hashlib.sha256(value).hexdigest()


def _reject_floats(value: object) -> None:
    if isinstance(value, float):
        raise ArtifactContractError("floating-point values are not allowed")
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ArtifactContractError("object keys must be strings")
        for key, child in value.items():
            if _SECRET_KEY_RE.search(key):
                raise ArtifactContractError("secret-like fields are forbidden")
            _reject_floats(child)
    elif isinstance(value, list):
        for child in value:
            _reject_floats(child)
    elif value is not None and not isinstance(value, (str, int, bool)):
        raise ArtifactContractError("value is not JSON-compatible")


def canonical_json_bytes(value: Any) -> bytes:
    """Encode JSON deterministically; reject floats and non-JSON values."""
    _reject_floats(value)
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ArtifactContractError("value cannot be canonically encoded") from exc


def logical_transaction_id(worker: str, content_revision: int) -> str:
    _nonempty_string(worker, "worker")
    _positive_int(content_revision, "content_revision")
    return hashlib.sha256(f"{worker}\0{content_revision}".encode("utf-8")).hexdigest()


def operation_id_for(logical_id: str, operation_name: str) -> str:
    _sha256(logical_id, "logical_transaction_id")
    if operation_name not in OPERATION_NAMES:
        raise ArtifactContractError("unsupported operation_name")
    return hashlib.sha256(f"{logical_id}\0{operation_name}".encode("utf-8")).hexdigest()


def artifact_digest(artifact: Mapping[str, Any]) -> str:
    body = copy.deepcopy(dict(artifact))
    body.pop("artifact_sha256", None)
    return hashlib.sha256(canonical_json_bytes(body)).hexdigest()


def seal_artifact(artifact: Mapping[str, Any]) -> dict:
    sealed = copy.deepcopy(dict(artifact))
    sealed.pop("artifact_sha256", None)
    sealed["artifact_sha256"] = artifact_digest(sealed)
    return sealed


def _validate_timestamp(value: object, label: str = "created_at") -> None:
    if not isinstance(value, str) or not value:
        raise ArtifactContractError(f"{label} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ArtifactContractError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ArtifactContractError(f"{label} must include a timezone")


def _validate_uuid(value: object, label: str) -> None:
    if not isinstance(value, str):
        raise ArtifactContractError(f"{label} must be a UUID")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ArtifactContractError(f"{label} must be a UUID") from exc
    if str(parsed) != value:
        raise ArtifactContractError(f"{label} must be a canonical lowercase UUID")


def _validate_relative_path(value: object, label: str, *, allowlist: frozenset[str] | None = None) -> str:
    path = _nonempty_string(value, label)
    if "\\" in path or path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        raise ArtifactContractError(f"{label} must be a normalized relative path")
    pure = PurePosixPath(path)
    if any(part in {"", ".", ".."} for part in pure.parts) or str(pure) != path:
        raise ArtifactContractError(f"{label} must be a normalized relative path")
    if allowlist is not None and path not in allowlist:
        raise ArtifactContractError(f"{label} is outside the approved allowlist")
    return path


def _validate_file_entries(value: object, label: str, *, state_files: bool = False) -> list[dict]:
    if not isinstance(value, list):
        raise ArtifactContractError(f"{label} must be a list")
    result = []
    last = None
    seen = set()
    for index, item in enumerate(value):
        entry = _exact_fields(item, {"path", "size_bytes", "sha256"}, f"{label}[{index}]")
        path = _validate_relative_path(
            entry["path"], f"{label}[{index}].path", allowlist=STATE_FILE_PATHS if state_files else None,
        )
        _nonnegative_int(entry["size_bytes"], f"{label}[{index}].size_bytes")
        _sha256(entry["sha256"], f"{label}[{index}].sha256")
        if path in seen:
            raise ArtifactContractError(f"{label} contains duplicate paths")
        if last is not None and path <= last:
            raise ArtifactContractError(f"{label} must be sorted by normalized path")
        seen.add(path)
        last = path
        result.append(entry)
    return result


def _validate_gate_map(value: object, names: tuple[str, ...], label: str) -> dict:
    result = _exact_fields(value, set(names), label)
    if any(type(result[name]) is not bool for name in names):
        raise ArtifactContractError(f"{label} values must be booleans")
    return result


def _validate_gate_stage(value: object, stage: str) -> dict:
    if stage == "local":
        result = _exact_fields(value, {"evidence_sha256", "gates", "PASS"}, "gate_results.local")
        _sha256(result["evidence_sha256"], "gate_results.local.evidence_sha256")
        gates = _validate_gate_map(result["gates"], LOCAL_GATES, "gate_results.local.gates")
    elif stage == "remote":
        result = _exact_fields(value, {"crawler_evidence_sha256", "browser_evidence_sha256", "gates", "PASS"}, "gate_results.remote")
        _sha256(result["crawler_evidence_sha256"], "gate_results.remote.crawler_evidence_sha256")
        _sha256(result["browser_evidence_sha256"], "gate_results.remote.browser_evidence_sha256")
        gates = _validate_gate_map(result["gates"], REMOTE_GATES, "gate_results.remote.gates")
    else:
        result = _exact_fields(value, {"crawler_evidence_sha256", "browser_evidence_sha256", "route_state_evidence_sha256", "gates", "PASS"}, "gate_results.production")
        _sha256(result["crawler_evidence_sha256"], "gate_results.production.crawler_evidence_sha256")
        _sha256(result["browser_evidence_sha256"], "gate_results.production.browser_evidence_sha256")
        _sha256(result["route_state_evidence_sha256"], "gate_results.production.route_state_evidence_sha256")
        gates = _validate_gate_map(result["gates"], PRODUCTION_GATES, "gate_results.production.gates")
    if type(result["PASS"]) is not bool or result["PASS"] != all(gates.values()):
        raise ArtifactContractError(f"gate_results.{stage}.PASS must equal the conjunction of all gates")
    return result


def _validate_operation_results(value: object, label: str) -> dict:
    result = _exact_fields(value, set(OPERATION_NAMES), label)
    for name in OPERATION_NAMES:
        _sha256(result[name], f"{label}.{name}", nullable=True)
    return result


def _validate_desired_state(operation: str, value: object, worker: str, build_digest: str) -> dict:
    if operation == "upload_version":
        result = _exact_fields(value, {"worker", "build_bundle_sha256"}, "desired_state")
        if result["worker"] != worker:
            raise ArtifactContractError("desired_state.worker must match transaction worker")
        if _sha256(result["build_bundle_sha256"], "desired_state.build_bundle_sha256") != build_digest:
            raise ArtifactContractError("desired_state build digest mismatch")
        return result
    if operation in {"deploy_zero_percent", "promote"}:
        result = _exact_fields(value, {
            "worker", "candidate_version_id", "baseline_version_id",
            "expected_current_deployment_id", "candidate_percentage", "baseline_percentage",
        }, "desired_state")
        if result["worker"] != worker:
            raise ArtifactContractError("desired_state.worker must match transaction worker")
        candidate = _nonempty_string(result["candidate_version_id"], "candidate_version_id", opaque=True)
        baseline = _nonempty_string(result["baseline_version_id"], "baseline_version_id", opaque=True)
        _nonempty_string(result["expected_current_deployment_id"], "expected_current_deployment_id", opaque=True)
        if candidate == baseline:
            raise ArtifactContractError("candidate and baseline version IDs must differ")
        expected = (0, 100) if operation == "deploy_zero_percent" else (100, 0)
        if (result["candidate_percentage"], result["baseline_percentage"]) != expected:
            raise ArtifactContractError("desired_state traffic split is invalid")
        return result
    result = _exact_fields(value, {
        "worker", "baseline_version_id", "failed_candidate_version_id",
        "expected_current_deployment_id", "baseline_percentage", "candidate_percentage",
    }, "desired_state")
    if result["worker"] != worker:
        raise ArtifactContractError("desired_state.worker must match transaction worker")
    baseline = _nonempty_string(result["baseline_version_id"], "baseline_version_id", opaque=True)
    failed = _nonempty_string(result["failed_candidate_version_id"], "failed_candidate_version_id", opaque=True)
    _nonempty_string(result["expected_current_deployment_id"], "expected_current_deployment_id", opaque=True)
    if baseline == failed:
        raise ArtifactContractError("baseline and failed candidate IDs must differ")
    if (result["baseline_percentage"], result["candidate_percentage"]) != (100, 0):
        raise ArtifactContractError("rollback desired_state traffic split is invalid")
    return result


def _validate_readback(value: object, worker: str, operation_name: str | None = None) -> dict:
    result = _exact_fields(value, {"resource_type", "worker", "resource_id"}, "readback_reference")
    if result["worker"] != worker:
        raise ArtifactContractError("readback worker mismatch")
    if result["resource_type"] not in {"version", "deployment"}:
        raise ArtifactContractError("readback resource_type is invalid")
    _nonempty_string(result["resource_id"], "readback_reference.resource_id", opaque=True)
    if operation_name:
        expected = "version" if operation_name == "upload_version" else "deployment"
        if result["resource_type"] != expected:
            raise ArtifactContractError("readback resource_type does not match operation")
    return result


def _validate_candidate_identity(value: object, worker: str) -> dict:
    result = _exact_fields(value, {
        "worker", "candidate_version_id", "baseline_version_id",
        "zero_percent_deployment_id", "content_fingerprint",
    }, "candidate_identity")
    if result["worker"] != worker:
        raise ArtifactContractError("candidate_identity.worker mismatch")
    candidate = _nonempty_string(result["candidate_version_id"], "candidate_version_id", opaque=True)
    baseline = _nonempty_string(result["baseline_version_id"], "baseline_version_id", opaque=True)
    _nonempty_string(result["zero_percent_deployment_id"], "zero_percent_deployment_id", opaque=True)
    _sha256(result["content_fingerprint"], "candidate_identity.content_fingerprint")
    if candidate == baseline:
        raise ArtifactContractError("candidate and baseline version IDs must differ")
    return result


def _validate_production_validation(value: object, candidate_identity: Mapping[str, Any]) -> dict:
    result = _exact_fields(value, {"identity_confirmation", "gates", "PASS"}, "production_validation")
    identity = _exact_fields(result["identity_confirmation"], {
        "candidate_version_id", "baseline_version_id", "promotion_deployment_id",
        "candidate_percentage", "baseline_percentage", "PASS",
    }, "production_validation.identity_confirmation")
    if identity["candidate_version_id"] != candidate_identity["candidate_version_id"] or identity["baseline_version_id"] != candidate_identity["baseline_version_id"]:
        raise ArtifactContractError("production identity does not match candidate_identity")
    _nonempty_string(identity["promotion_deployment_id"], "promotion_deployment_id", opaque=True)
    if (identity["candidate_percentage"], identity["baseline_percentage"]) != (100, 0):
        raise ArtifactContractError("production traffic split is invalid")
    if type(identity["PASS"]) is not bool:
        raise ArtifactContractError("production identity PASS must be boolean")
    gates = _validate_gate_map(result["gates"], PRODUCTION_GATES, "production_validation.gates")
    expected = identity["PASS"] and all(gates.values())
    if type(result["PASS"]) is not bool or result["PASS"] != expected:
        raise ArtifactContractError("production_validation.PASS must equal identity and gate conjunction")
    return result


def _validate_zero_origin(value: object) -> dict:
    result = _exact_fields(value, {"public_pages_checked", "requests", "PASS"}, "zero_origin_validation")
    _positive_int(result["public_pages_checked"], "zero_origin_validation.public_pages_checked")
    requests = _exact_fields(result["requests"], {
        "content_api", "media_api", "workers_dev_content", "telegram", "search_backend",
    }, "zero_origin_validation.requests")
    if any(not _is_int(v) or v != 0 for v in requests.values()):
        raise ArtifactContractError("zero-origin request counters must all be zero")
    if result["PASS"] is not True:
        raise ArtifactContractError("zero_origin_validation.PASS must be true")
    return result


def _referenced_artifact(references: Mapping[str, Any] | None, digest: str, kind: str, label: str) -> dict:
    if references is None or digest not in references:
        raise ArtifactContractError(f"{label} referenced artifact is unavailable")
    artifact = validate_artifact(references[digest], referenced_artifacts=references)
    if artifact["artifact_sha256"] != digest or artifact["artifact_type"] != kind:
        raise ArtifactContractError(f"{label} artifact identity or type mismatch")
    return artifact


def _validate_pre_promotion_lineage(
    proof: Mapping[str, Any], references: Mapping[str, Any] | None,
) -> None:
    payload = proof["payload"]
    transaction = proof["transaction"]
    source_sha = proof["producer"]["source_sha"]
    bundle = _referenced_artifact(
        references, payload["build_bundle_artifact_sha256"], "build_bundle", "build bundle",
    )
    if references is None or payload["deploy_zero_percent_result_artifact_sha256"] not in references:
        raise ArtifactContractError("zero-percent deployment result artifact is unavailable")
    deployment = validate_artifact(
        references[payload["deploy_zero_percent_result_artifact_sha256"]],
        expected_transaction=transaction, expected_source_sha=source_sha,
        referenced_artifacts=references,
    )
    if deployment["artifact_type"] not in {"mutation_result", "recovered_mutation_result"}:
        raise ArtifactContractError("zero-percent deployment result type is invalid")
    intent_digest = deployment["payload"]["intent_artifact_sha256"]
    deployment_intent = _referenced_artifact(
        references, intent_digest, "mutation_intent", "zero-percent deployment intent",
    )
    for artifact in (bundle, deployment, deployment_intent):
        if artifact["transaction"] != transaction or artifact["producer"]["source_sha"] != source_sha:
            raise ArtifactContractError("pre-promotion proof transaction/source lineage mismatch")
    if bundle["artifact_sha256"] != payload["build_bundle_artifact_sha256"]:
        raise ArtifactContractError("pre-promotion proof build bundle mismatch")
    candidate = payload["candidate_identity"]
    if bundle["payload"]["content_fingerprint"] != candidate["content_fingerprint"]:
        raise ArtifactContractError("pre-promotion proof content fingerprint mismatch")
    from publisher.effective_mutation_result import validate_effective_applied_result
    try:
        effective_deployment = validate_effective_applied_result(
            deployment, deployment_intent, referenced_artifacts=references,
        )
    except ValueError as exc:
        raise ArtifactContractError("pre-promotion deployment result is not effectively APPLIED") from exc
    desired = deployment_intent["payload"]["desired_state"]
    readback = effective_deployment["payload"]["readback_reference"]
    if (deployment_intent["payload"]["operation_name"] != "deploy_zero_percent"
            or effective_deployment["payload"]["operation_id"] != operation_id_for(
                transaction["logical_transaction_id"], "deploy_zero_percent")
            or effective_deployment["payload"]["result_state"] != "APPLIED"
            or effective_deployment["payload"]["build_bundle_sha256"] != bundle["artifact_sha256"]
            or deployment_intent["payload"]["build_bundle_sha256"] != bundle["artifact_sha256"]
            or desired["candidate_version_id"] != candidate["candidate_version_id"]
            or desired["baseline_version_id"] != candidate["baseline_version_id"]
            or desired["candidate_percentage"] != 0 or desired["baseline_percentage"] != 100
            or readback["resource_id"] != candidate["zero_percent_deployment_id"]):
        raise ArtifactContractError("pre-promotion proof deployment lineage is not APPLIED/matching")


def _validate_promote_authority(
    intent: Mapping[str, Any], references: Mapping[str, Any] | None,
) -> None:
    payload = intent["payload"]
    proof = _referenced_artifact(
        references, payload["prerequisite_artifact_sha256"],
        "pre_promotion_proof_evidence", "promote authority",
    )
    _validate_pre_promotion_lineage(proof, references)
    pp = proof["payload"]
    desired = payload["desired_state"]
    if (proof["transaction"] != intent["transaction"]
            or proof["producer"]["source_sha"] != intent["producer"]["source_sha"]
            or pp["PASS"] is not True
            or pp["build_bundle_artifact_sha256"] != payload["build_bundle_sha256"]
            or pp["candidate_identity"]["candidate_version_id"] != desired["candidate_version_id"]
            or pp["candidate_identity"]["baseline_version_id"] != desired["baseline_version_id"]
            or pp["candidate_identity"]["zero_percent_deployment_id"]
                != desired["expected_current_deployment_id"]):
        raise ArtifactContractError("promote intent lacks matching passing pre-promotion proof")


def _validate_prior_index_binding(value: object) -> dict:
    result = _exact_fields(value, {
        "repository", "ref", "commit_sha", "relative_path", "exists",
        "content_sha256", "byte_length", "transport_base64",
    }, "payload.prior_immutable_media_index")
    repository = _nonempty_string(result["repository"], "prior index repository")
    if (repository.count("/") != 1 or any(ch.isspace() for ch in repository)
            or any(ord(ch) < 32 for ch in repository)):
        raise ArtifactContractError("prior index repository identity is invalid")
    if result["ref"] != "refs/heads/main":
        raise ArtifactContractError("prior index ref is not the accepted state ref")
    if not isinstance(result["commit_sha"], str) or not _COMMIT_SHA_RE.fullmatch(result["commit_sha"]):
        raise ArtifactContractError("prior index commit SHA is invalid")
    if result["relative_path"] != PRIOR_IMMUTABLE_MEDIA_INDEX_PATH:
        raise ArtifactContractError("prior index path is not the accepted exact path")
    if type(result["exists"]) is not bool:
        raise ArtifactContractError("prior index exists flag must be boolean")
    digest = _sha256(result["content_sha256"], "prior index content_sha256")
    length = _nonnegative_int(result["byte_length"], "prior index byte_length")
    encoded = result["transport_base64"]
    if not isinstance(encoded, str):
        raise ArtifactContractError("prior index transport must be base64 text")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise ArtifactContractError("prior index transport is invalid base64") from exc
    if base64.b64encode(raw).decode("ascii") != encoded:
        raise ArtifactContractError("prior index transport is not canonical base64")
    if len(raw) != length or sha256_bytes(raw) != digest:
        raise ArtifactContractError("prior index transport digest or length mismatch")
    if result["exists"] and not raw:
        raise ArtifactContractError("present prior index cannot be empty")
    if not result["exists"] and raw:
        raise ArtifactContractError("absent prior index must have empty transport")
    if raw:
        try:
            json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ArtifactContractError("prior index snapshot is not valid UTF-8 JSON") from exc
    return result


def validate_prior_index_transport(artifact: object, raw: bytes, *,
                                   expected_transaction: Mapping[str, Any] | None = None,
                                   expected_source_sha: str | None = None) -> dict:
    """Validate transport bytes only against the sealed build-bundle authority."""
    bundle = validate_artifact(
        artifact, expected_transaction=expected_transaction,
        expected_source_sha=expected_source_sha,
    )
    binding = bundle["payload"].get("prior_immutable_media_index")
    if binding is None:
        raise ArtifactContractError("build bundle lacks prior index authority binding")
    if not isinstance(raw, bytes):
        raise ArtifactContractError("prior index transport input must be bytes")
    if len(raw) != binding["byte_length"] or sha256_bytes(raw) != binding["content_sha256"]:
        raise ArtifactContractError("prior index transport does not match sealed authority")
    return binding


def _validate_payload(artifact_type: str, payload: object, transaction: Mapping[str, Any]) -> dict:
    worker = transaction["worker"]
    tx_id = transaction["logical_transaction_id"]
    if artifact_type == "revision_resolution":
        result = _exact_fields(payload, {"revision", "published_revision", "changed_at", "endpoint_id", "request_count", "decision"}, "payload")
        revision = _positive_int(result["revision"], "payload.revision")
        if revision != transaction["content_revision"]:
            raise ArtifactContractError("resolved revision must match envelope content_revision")
        if result["published_revision"] is not None:
            _nonnegative_int(result["published_revision"], "payload.published_revision")
        _validate_timestamp(result["changed_at"], "payload.changed_at")
        if result["endpoint_id"] not in ENDPOINT_IDS:
            raise ArtifactContractError("endpoint_id is outside the approved allowlist")
        if result["request_count"] != 1 or not _is_int(result["request_count"]):
            raise ArtifactContractError("request_count must equal 1")
        if result["decision"] not in REVISION_DECISIONS:
            raise ArtifactContractError("revision decision is invalid")
        return result

    if artifact_type == "admission_receipt":
        result = _exact_fields(payload, {"decision", "journal_generation", "journal_sha256", "revision_resolution_sha256", "pending_revision", "active_transaction_id"}, "payload")
        if result["decision"] not in ADMISSION_DECISIONS:
            raise ArtifactContractError("admission decision is invalid")
        _nonnegative_int(result["journal_generation"], "journal_generation")
        _sha256(result["journal_sha256"], "journal_sha256")
        _sha256(result["revision_resolution_sha256"], "revision_resolution_sha256")
        if result["pending_revision"] is not None:
            _positive_int(result["pending_revision"], "pending_revision")
        if result["active_transaction_id"] is not None:
            _sha256(result["active_transaction_id"], "active_transaction_id")
        return result

    if artifact_type == "build_bundle":
        required = {"admission_receipt_sha256", "files", "content_fingerprint", "snapshot_sha256", "route_manifest_sha256", "media_manifest_sha256", "local_gate_evidence_sha256"}
        if isinstance(payload, dict) and "prior_immutable_media_index" in payload:
            required.add("prior_immutable_media_index")
        result = _exact_fields(payload, required, "payload")
        for key in ("admission_receipt_sha256", "content_fingerprint", "snapshot_sha256", "route_manifest_sha256", "media_manifest_sha256", "local_gate_evidence_sha256"):
            _sha256(result[key], key)
        _validate_file_entries(result["files"], "payload.files")
        if "prior_immutable_media_index" in result:
            _validate_prior_index_binding(result["prior_immutable_media_index"])
        return result

    if artifact_type == "mutation_intent":
        result = _exact_fields(payload, {"operation_id", "operation_name", "attempt_id", "intent_state", "build_bundle_sha256", "prerequisite_artifact_sha256", "journal_generation", "desired_state"}, "payload")
        operation = result["operation_name"]
        if operation not in OPERATION_NAMES:
            raise ArtifactContractError("unsupported operation_name")
        if result["operation_id"] != operation_id_for(tx_id, operation):
            raise ArtifactContractError("operation_id does not match transaction and operation")
        _validate_uuid(result["attempt_id"], "attempt_id")
        if result["intent_state"] != "RECORDED":
            raise ArtifactContractError("intent_state must be RECORDED")
        build_digest = _sha256(result["build_bundle_sha256"], "build_bundle_sha256")
        _sha256(result["prerequisite_artifact_sha256"], "prerequisite_artifact_sha256")
        _nonnegative_int(result["journal_generation"], "journal_generation")
        _validate_desired_state(operation, result["desired_state"], worker, build_digest)
        return result

    if artifact_type == "mutation_result":
        result = _exact_fields(payload, {"operation_id", "attempt_id", "result_state", "evidence_sha256", "intent_artifact_sha256", "build_bundle_sha256", "readback_reference"}, "payload")
        _sha256(result["operation_id"], "operation_id")
        _validate_uuid(result["attempt_id"], "attempt_id")
        state = result["result_state"]
        if state not in RESULT_STATES:
            raise ArtifactContractError("unsupported result_state")
        _sha256(result["evidence_sha256"], "evidence_sha256", nullable=(state == "UNKNOWN"))
        if state != "UNKNOWN" and result["evidence_sha256"] is None:
            raise ArtifactContractError("conclusive result requires evidence_sha256")
        _sha256(result["intent_artifact_sha256"], "intent_artifact_sha256")
        _sha256(result["build_bundle_sha256"], "build_bundle_sha256")
        readback_reference = result["readback_reference"]
        if readback_reference is None:
            if state != "UNKNOWN":
                raise ArtifactContractError("conclusive result requires readback_reference")
        else:
            _validate_readback(readback_reference, worker)
        return result

    if artifact_type == "recovered_mutation_result":
        result = _exact_fields(payload, {
            "operation_id", "operation_name", "attempt_id", "result_state",
            "intent_artifact_sha256", "original_result_artifact_sha256",
            "recovery_decision_artifact_sha256", "recovery_evidence_sha256",
            "recovery_decision_evidence_sha256", "recovery_readback_observed_at",
            "evidence_sha256", "build_bundle_sha256",
            "readback_reference", "journal_generation", "journal_sha256",
            "journal_remote_head", "journal_result_digest",
        }, "payload")
        operation = result["operation_name"]
        if operation not in OPERATION_NAMES:
            raise ArtifactContractError("unsupported recovered operation_name")
        if result["operation_id"] != operation_id_for(tx_id, operation):
            raise ArtifactContractError("recovered operation_id does not match transaction")
        _validate_uuid(result["attempt_id"], "attempt_id")
        if result["result_state"] != "APPLIED":
            raise ArtifactContractError("recovered mutation result must be APPLIED")
        for field in (
            "intent_artifact_sha256", "original_result_artifact_sha256",
            "recovery_decision_artifact_sha256", "recovery_evidence_sha256",
            "recovery_decision_evidence_sha256", "evidence_sha256",
            "build_bundle_sha256", "journal_sha256",
            "journal_result_digest",
        ):
            _sha256(result[field], field)
        _validate_timestamp(result["recovery_readback_observed_at"],
                            "recovery_readback_observed_at")
        _validate_readback(result["readback_reference"], worker, operation)
        _nonnegative_int(result["journal_generation"], "journal_generation")
        if not isinstance(result["journal_remote_head"], str) or not _COMMIT_SHA_RE.fullmatch(result["journal_remote_head"]):
            raise ArtifactContractError("journal_remote_head must be a lowercase 40-character Git SHA")
        return result

    if artifact_type == "proof_evidence":
        result = _exact_fields(payload, {"build_bundle_sha256", "operation_result_sha256s", "gate_results", "candidate_identity", "production_validation", "zero_origin_validation", "proof_state"}, "payload")
        _sha256(result["build_bundle_sha256"], "build_bundle_sha256")
        _validate_operation_results(result["operation_result_sha256s"], "operation_result_sha256s")
        gates = _exact_fields(result["gate_results"], {"local", "remote", "production"}, "gate_results")
        for stage in ("local", "remote", "production"):
            _validate_gate_stage(gates[stage], stage)
        candidate = _validate_candidate_identity(result["candidate_identity"], worker)
        production = _validate_production_validation(result["production_validation"], candidate)
        _validate_zero_origin(result["zero_origin_validation"])
        if result["proof_state"] not in {"PASS", "FAIL"}:
            raise ArtifactContractError("proof_state is invalid")
        all_gates = all(gates[stage]["PASS"] for stage in ("local", "remote", "production")) and production["PASS"]
        if result["proof_state"] == "PASS" and not all_gates:
            raise ArtifactContractError("PASS proof requires every required gate to pass")
        return result

    if artifact_type == "pre_promotion_proof_evidence":
        result = _exact_fields(payload, {
            "build_bundle_artifact_sha256", "deploy_zero_percent_result_artifact_sha256",
            "candidate_identity", "remote", "zero_origin_validation", "PASS",
        }, "payload")
        _sha256(result["build_bundle_artifact_sha256"], "build_bundle_artifact_sha256")
        _sha256(result["deploy_zero_percent_result_artifact_sha256"], "deploy_zero_percent_result_artifact_sha256")
        candidate = _validate_candidate_identity(result["candidate_identity"], worker)
        remote = _validate_gate_stage(result["remote"], "remote")
        _validate_zero_origin(result["zero_origin_validation"])
        if type(result["PASS"]) is not bool or result["PASS"] != remote["PASS"]:
            raise ArtifactContractError("pre-promotion proof PASS must match remote gates and zero-origin PASS")
        return result

    if artifact_type == "recovery_decision":
        result = _exact_fields(payload, {"operation_id", "attempt_id", "decision", "evidence_sha256", "intent_artifact_sha256", "result_artifact_sha256", "journal_generation", "resume_allowed"}, "payload")
        _sha256(result["operation_id"], "operation_id")
        _validate_uuid(result["attempt_id"], "attempt_id")
        if result["decision"] not in RECOVERY_DECISIONS:
            raise ArtifactContractError("unsupported recovery decision")
        _sha256(result["evidence_sha256"], "evidence_sha256")
        _sha256(result["intent_artifact_sha256"], "intent_artifact_sha256")
        _sha256(result["result_artifact_sha256"], "result_artifact_sha256")
        _nonnegative_int(result["journal_generation"], "journal_generation")
        if type(result["resume_allowed"]) is not bool:
            raise ArtifactContractError("resume_allowed must be boolean")
        if result["decision"] == "BLOCKED_UNKNOWN" and result["resume_allowed"]:
            raise ArtifactContractError("BLOCKED_UNKNOWN cannot allow resume")
        if result["decision"] == "RECONCILED_APPLIED" and result["resume_allowed"]:
            raise ArtifactContractError("RECONCILED_APPLIED cannot replay mutation")
        return result

    result = _exact_fields(payload, {"build_bundle_sha256", "proof_evidence_sha256", "operation_result_sha256s", "state_files", "state_commit_sha", "journal_generation"}, "payload")
    _sha256(result["build_bundle_sha256"], "build_bundle_sha256")
    _sha256(result["proof_evidence_sha256"], "proof_evidence_sha256")
    _validate_operation_results(result["operation_result_sha256s"], "operation_result_sha256s")
    _validate_file_entries(result["state_files"], "state_files", state_files=True)
    if not isinstance(result["state_commit_sha"], str) or not _COMMIT_SHA_RE.fullmatch(result["state_commit_sha"]):
        raise ArtifactContractError("state_commit_sha must be a lowercase 40-character Git commit SHA")
    _nonnegative_int(result["journal_generation"], "journal_generation")
    return result


def validate_artifact(
    artifact: object,
    *,
    expected_transaction: Mapping[str, Any] | None = None,
    expected_source_sha: str | None = None,
    expected_parents: Mapping[str, str] | None = None,
    expected_journal_generation: int | None = None,
    trusted_producer: Mapping[str, Any] | None = None,
    referenced_artifacts: Mapping[str, Any] | None = None,
) -> dict:
    """Validate envelope, strict payload, identity, lineage inputs, and digest."""
    value = _exact_fields(artifact, _ENVELOPE_FIELDS, "artifact")
    artifact_type = value["artifact_type"]
    if artifact_type not in ARTIFACT_TYPES:
        raise ArtifactContractError("unsupported artifact_type")
    if value["schema_version"] != SCHEMA_VERSION:
        raise ArtifactContractError("unsupported schema_version")
    _validate_uuid(value["artifact_id"], "artifact_id")
    _validate_timestamp(value["created_at"])

    producer = _exact_fields(value["producer"], _PRODUCER_FIELDS, "producer")
    _nonempty_string(producer["workflow_run_id"], "producer.workflow_run_id")
    _positive_int(producer["run_attempt"], "producer.run_attempt")
    _nonempty_string(producer["job"], "producer.job")
    if not isinstance(producer["source_sha"], str) or not _SOURCE_SHA_RE.fullmatch(producer["source_sha"]):
        raise ArtifactContractError("producer identity is invalid")
    if expected_source_sha is not None and producer["source_sha"] != expected_source_sha:
        raise ArtifactContractError("source SHA does not match expected source")
    if trusted_producer is not None:
        trusted = dict(trusted_producer)
        for key in ("workflow_run_id", "run_attempt", "job", "source_sha"):
            if key in trusted and producer[key] != trusted[key]:
                raise ArtifactContractError("producer metadata is not trusted")

    transaction = _exact_fields(value["transaction"], _TRANSACTION_FIELDS, "transaction")
    worker = _nonempty_string(transaction["worker"], "transaction.worker")
    revision = _positive_int(transaction["content_revision"], "transaction.content_revision")
    _sha256(transaction["logical_transaction_id"], "logical_transaction_id")
    if transaction["logical_transaction_id"] != logical_transaction_id(worker, revision):
        raise ArtifactContractError("logical transaction ID does not match worker and revision")
    if expected_transaction is not None and dict(expected_transaction) != transaction:
        raise ArtifactContractError("transaction does not match expected identity")

    payload = _validate_payload(artifact_type, value["payload"], transaction)
    if expected_journal_generation is not None and "journal_generation" in payload:
        if payload["journal_generation"] != expected_journal_generation:
            raise ArtifactContractError("journal generation mismatch")
    if expected_parents:
        for field, digest in expected_parents.items():
            if field not in payload or payload[field] != digest:
                raise ArtifactContractError(f"parent lineage mismatch for {field}")

    _reject_floats(value)
    digest = _sha256(value["artifact_sha256"], "artifact_sha256")
    if digest != artifact_digest(value):
        raise ArtifactContractError("artifact digest mismatch")
    if artifact_type == "pre_promotion_proof_evidence":
        _validate_pre_promotion_lineage(value, referenced_artifacts)
    elif (artifact_type == "mutation_intent"
          and value["payload"]["operation_name"] == "promote"):
        _validate_promote_authority(value, referenced_artifacts)
    return value


def validate_intent_result_pair(
    intent: Mapping[str, Any], result: Mapping[str, Any], *,
    referenced_artifacts: Mapping[str, Any] | None = None,
) -> None:
    """Validate exact transaction/build/operation/attempt lineage for a mutation pair."""
    intent_v = validate_artifact(intent, referenced_artifacts=referenced_artifacts)
    result_v = validate_artifact(result, expected_transaction=intent_v["transaction"], expected_source_sha=intent_v["producer"]["source_sha"])
    if intent_v["artifact_type"] != "mutation_intent" or result_v["artifact_type"] != "mutation_result":
        raise ArtifactContractError("intent/result artifact types are required")
    ip = intent_v["payload"]
    rp = result_v["payload"]
    if rp["operation_id"] != ip["operation_id"] or rp["attempt_id"] != ip["attempt_id"]:
        raise ArtifactContractError("operation or attempt lineage mismatch")
    if rp["intent_artifact_sha256"] != intent_v["artifact_sha256"]:
        raise ArtifactContractError("intent artifact lineage mismatch")
    if rp["build_bundle_sha256"] != ip["build_bundle_sha256"]:
        raise ArtifactContractError("build bundle lineage mismatch")
    if rp["readback_reference"] is None:
        if rp["result_state"] != "UNKNOWN":
            raise ArtifactContractError("conclusive result requires readback_reference")
    else:
        _validate_readback(rp["readback_reference"], intent_v["transaction"]["worker"], ip["operation_name"])
