"""Fresh read-only Cloudflare evidence for UNKNOWN publisher operations."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol

from publisher import artifact_contract as contracts
from publisher import effective_mutation_result as effective_result
from publisher import proof_recovery_runner as recovery


EVIDENCE_TYPE = "MAHOON_FRESH_RECOVERY_READBACK_V1"
MAX_AGE_SECONDS = 300
_FIELDS = {
    "evidence_type", "observed_at", "transaction", "source_sha", "operation_name",
    "operation_id", "attempt_id", "intent_artifact_sha256", "result_artifact_sha256",
    "build_bundle_sha256", "desired_state", "desired_state_sha256",
    "candidate_version_id", "baseline_version_id", "expected_current_deployment_id",
    "readback", "readback_sha256", "evidence_sha256",
}


class RecoveryReadbackRejected(ValueError):
    """Fresh recovery evidence is missing, stale, or has mismatched lineage."""


class ReadOnlyCloudflareBackend(Protocol):
    def list_versions(self, worker: str) -> list[dict]: ...
    def read_deployment(self, worker: str) -> dict: ...


class WranglerReadOnlyBackend:
    """Calls only Wrangler version-list and deployment-list read operations."""

    def list_versions(self, worker: str) -> list[dict]:
        from publisher.cloudflare_wrangler import list_versions
        return list_versions(worker)

    def read_deployment(self, worker: str) -> dict:
        from publisher.cloudflare_wrangler import read_deployment
        return read_deployment(worker)


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise RecoveryReadbackRejected(f"{label} is invalid")
    return value


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise RecoveryReadbackRejected("observed_at is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RecoveryReadbackRejected("observed_at is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RecoveryReadbackRejected("observed_at must include a timezone")
    return parsed.astimezone(timezone.utc)


def _desired_state(intent: Mapping[str, Any]) -> dict:
    value = intent["payload"]["desired_state"]
    return dict(value)


def _validate_inputs(intent: object, result: object,
                     references: Mapping[str, Any] | None) -> tuple[dict, dict, dict]:
    intent_v = contracts.validate_artifact(intent, referenced_artifacts=references)
    if intent_v["artifact_type"] != "mutation_intent":
        raise RecoveryReadbackRejected("sealed mutation intent required")
    result_v = contracts.validate_artifact(
        result, expected_transaction=intent_v["transaction"],
        expected_source_sha=intent_v["producer"]["source_sha"],
        referenced_artifacts=references,
    )
    if result_v["artifact_type"] != "mutation_result":
        raise RecoveryReadbackRejected("sealed mutation result required")
    contracts.validate_intent_result_pair(intent_v, result_v, referenced_artifacts=references)
    if result_v["payload"]["result_state"] != "UNKNOWN":
        raise RecoveryReadbackRejected("fresh recovery readback requires UNKNOWN result")

    payload = intent_v["payload"]
    refs = references or {}
    bundle = refs.get(payload["build_bundle_sha256"])
    prerequisite = refs.get(payload["prerequisite_artifact_sha256"])
    if bundle is None or prerequisite is None:
        raise RecoveryReadbackRejected("sealed build and prerequisite context are required")
    bundle_v = contracts.validate_artifact(
        bundle, expected_transaction=intent_v["transaction"],
        expected_source_sha=intent_v["producer"]["source_sha"],
        referenced_artifacts=refs,
    )
    if bundle_v["artifact_type"] != "build_bundle" or bundle_v["artifact_sha256"] != payload["build_bundle_sha256"]:
        raise RecoveryReadbackRejected("sealed build bundle lineage mismatch")
    prerequisite_v = contracts.validate_artifact(
        prerequisite, expected_transaction=intent_v["transaction"],
        expected_source_sha=intent_v["producer"]["source_sha"],
        referenced_artifacts=refs,
    )
    if prerequisite_v["artifact_sha256"] != payload["prerequisite_artifact_sha256"]:
        raise RecoveryReadbackRejected("operation prerequisite lineage mismatch")

    operation = payload["operation_name"]
    desired = payload["desired_state"]
    if operation == "upload_version":
        if (prerequisite_v["artifact_type"] != "admission_receipt"
                or prerequisite_v["payload"]["decision"] != "ADMITTED"
                or bundle_v["payload"]["admission_receipt_sha256"] != prerequisite_v["artifact_sha256"]):
            raise RecoveryReadbackRejected("upload recovery lacks matching admission/build context")
    elif operation == "deploy_zero_percent":
        if prerequisite_v["artifact_type"] not in {"mutation_result", "recovered_mutation_result"}:
            raise RecoveryReadbackRejected("zero-percent recovery lacks applied upload prerequisite")
        prior_intent = next((item for item in refs.values()
                             if isinstance(item, Mapping)
                             and item.get("artifact_type") == "mutation_intent"
                             and item.get("payload", {}).get("operation_name") == "upload_version"
                             and item.get("artifact_sha256") == prerequisite_v["payload"]["intent_artifact_sha256"]), None)
        if prior_intent is None:
            raise RecoveryReadbackRejected("upload intent prerequisite is missing")
        applied = effective_result.validate_effective_applied_result(
            prerequisite_v, prior_intent, referenced_artifacts=refs,
        )
        if (applied["payload"]["readback_reference"]["resource_id"]
                != desired["candidate_version_id"]):
            raise RecoveryReadbackRejected("zero-percent candidate differs from applied upload")
    elif operation == "promote":
        if (prerequisite_v["artifact_type"] != "pre_promotion_proof_evidence"
                or prerequisite_v["payload"]["PASS"] is not True
                or prerequisite_v["payload"]["build_bundle_artifact_sha256"] != bundle_v["artifact_sha256"]):
            raise RecoveryReadbackRejected("promotion recovery lacks passing pre-promotion proof")
    elif operation == "rollback":
        if prerequisite_v["artifact_type"] != "proof_evidence":
            raise RecoveryReadbackRejected("rollback recovery lacks production proof")
        promote_result = next((item for item in refs.values() if isinstance(item, Mapping)
                               and item.get("artifact_type") in {"mutation_result", "recovered_mutation_result"}
                               and item.get("artifact_sha256") ==
                                   prerequisite_v["payload"]["operation_result_sha256s"]["promote"]), None)
        promote_intent = next((item for item in refs.values() if isinstance(item, Mapping)
                               and item.get("artifact_type") == "mutation_intent"
                               and promote_result is not None
                               and item.get("artifact_sha256") == promote_result.get("payload", {}).get(
                                   "intent_artifact_sha256")), None)
        if promote_intent is None or promote_result is None:
            raise RecoveryReadbackRejected("rollback promotion lineage is missing")
        recovery.authorize_rollback(
            prerequisite_v, promote_intent, promote_result, intent_v,
            referenced_artifacts=refs,
        )
    else:
        raise RecoveryReadbackRejected("unsupported recovery operation")
    return intent_v, result_v, bundle_v


def _deployment_readback(intent: Mapping[str, Any], backend: ReadOnlyCloudflareBackend) -> dict:
    tx, payload = intent["transaction"], intent["payload"]
    operation, desired = payload["operation_name"], payload["desired_state"]
    deployment = backend.read_deployment(tx["worker"])
    deployment_id = deployment.get("id")
    if not isinstance(deployment_id, str) or not deployment_id.strip():
        raise RecoveryReadbackRejected("fresh deployment readback has no deployment identity")
    versions = deployment.get("versions")
    if not isinstance(versions, list):
        raise RecoveryReadbackRejected("fresh deployment readback has no versions")
    actual: dict[str, int] = {}
    for item in versions:
        if (not isinstance(item, Mapping) or not isinstance(item.get("version_id"), str)
                or not item["version_id"] or isinstance(item.get("percentage"), bool)
                or not isinstance(item.get("percentage"), int)
                or not 0 <= item["percentage"] <= 100
                or item["version_id"] in actual):
            raise RecoveryReadbackRejected("fresh deployment readback is malformed")
        actual[item["version_id"]] = item["percentage"]

    if operation == "deploy_zero_percent":
        target = {desired["baseline_version_id"]: 100, desired["candidate_version_id"]: 0}
        starting = {desired["baseline_version_id"]: 100}
    elif operation == "promote":
        target = {desired["candidate_version_id"]: 100, desired["baseline_version_id"]: 0}
        starting = {desired["baseline_version_id"]: 100, desired["candidate_version_id"]: 0}
    else:
        target = {desired["baseline_version_id"]: 100, desired["failed_candidate_version_id"]: 0}
        starting = {desired["failed_candidate_version_id"]: 100}
    return {
        "desired_state_matches": actual == target,
        "precondition_matches": deployment_id == desired["expected_current_deployment_id"] and actual == starting,
        "current_deployment_id": deployment_id,
        "resource_type": "deployment",
        "resource_id": deployment_id,
    }


def _upload_readback(intent: Mapping[str, Any], backend: ReadOnlyCloudflareBackend) -> dict:
    tx, payload = intent["transaction"], intent["payload"]
    versions = backend.list_versions(tx["worker"])
    if not isinstance(versions, list):
        raise RecoveryReadbackRejected("fresh version readback is malformed")
    marker = f"MAHOON-A3:{payload['operation_id']}:{payload['attempt_id']}"
    matches = []
    for item in versions:
        if not isinstance(item, Mapping):
            raise RecoveryReadbackRejected("fresh version entry is malformed")
        annotations = item.get("annotations")
        if annotations is not None and not isinstance(annotations, Mapping):
            raise RecoveryReadbackRejected("fresh version annotations are malformed")
        if isinstance(annotations, Mapping) and annotations.get("workers/message") == marker:
            version_id = item.get("id")
            if not isinstance(version_id, str) or not version_id.strip():
                raise RecoveryReadbackRejected("matching upload version has no identity")
            matches.append(version_id)
    if len(matches) > 1:
        raise RecoveryReadbackRejected("multiple versions match the exact upload attempt")
    resource_id = matches[0] if matches else None
    return {
        "desired_state_matches": bool(matches),
        "precondition_matches": None,
        "current_deployment_id": None,
        "resource_type": "version" if resource_id is not None else None,
        "resource_id": resource_id,
    }


def collect_fresh_readback(intent: object, result: object, *,
                           references: Mapping[str, Any], backend: ReadOnlyCloudflareBackend,
                           clock=None) -> dict:
    """Perform one fresh read-only query and return lineage-bound raw evidence."""
    intent_v, result_v, _bundle = _validate_inputs(intent, result, references)
    payload = intent_v["payload"]
    observed = (_upload_readback(intent_v, backend) if payload["operation_name"] == "upload_version"
                else _deployment_readback(intent_v, backend))
    observed = recovery._checked_readback(observed, payload["operation_name"])
    now = clock or (lambda: datetime.now(timezone.utc).isoformat())
    desired = _desired_state(intent_v)
    envelope = {
        "evidence_type": EVIDENCE_TYPE,
        "observed_at": now(),
        "transaction": dict(intent_v["transaction"]),
        "source_sha": intent_v["producer"]["source_sha"],
        "operation_name": payload["operation_name"],
        "operation_id": payload["operation_id"],
        "attempt_id": payload["attempt_id"],
        "intent_artifact_sha256": intent_v["artifact_sha256"],
        "result_artifact_sha256": result_v["artifact_sha256"],
        "build_bundle_sha256": payload["build_bundle_sha256"],
        "desired_state": desired,
        "desired_state_sha256": hashlib.sha256(contracts.canonical_json_bytes(desired)).hexdigest(),
        "candidate_version_id": desired.get("candidate_version_id", desired.get("failed_candidate_version_id")),
        "baseline_version_id": desired.get("baseline_version_id"),
        "expected_current_deployment_id": desired.get("expected_current_deployment_id"),
        "readback": observed,
        "readback_sha256": hashlib.sha256(contracts.canonical_json_bytes(observed)).hexdigest(),
    }
    envelope["evidence_sha256"] = hashlib.sha256(contracts.canonical_json_bytes(envelope)).hexdigest()
    return validate_fresh_readback(
        envelope, intent_v, result_v, references=references,
        now=_timestamp(envelope["observed_at"]),
    )


def validate_fresh_readback(value: object, intent: object, result: object, *,
                            references: Mapping[str, Any], now: datetime | None = None) -> dict:
    if not isinstance(value, Mapping) or set(value) != _FIELDS:
        raise RecoveryReadbackRejected("fresh recovery readback schema invalid")
    intent_v, result_v, _bundle = _validate_inputs(intent, result, references)
    if value["evidence_type"] != EVIDENCE_TYPE:
        raise RecoveryReadbackRejected("fresh recovery evidence type invalid")
    tx, payload = intent_v["transaction"], intent_v["payload"]
    expected_desired = dict(payload["desired_state"])
    expected_candidate = expected_desired.get("candidate_version_id", expected_desired.get("failed_candidate_version_id"))
    bindings = {
        "transaction": tx,
        "source_sha": intent_v["producer"]["source_sha"],
        "operation_name": payload["operation_name"],
        "operation_id": payload["operation_id"],
        "attempt_id": payload["attempt_id"],
        "intent_artifact_sha256": intent_v["artifact_sha256"],
        "result_artifact_sha256": result_v["artifact_sha256"],
        "build_bundle_sha256": payload["build_bundle_sha256"],
        "desired_state": expected_desired,
        "candidate_version_id": expected_candidate,
        "baseline_version_id": expected_desired.get("baseline_version_id"),
        "expected_current_deployment_id": expected_desired.get("expected_current_deployment_id"),
    }
    if any(value.get(key) != expected for key, expected in bindings.items()):
        raise RecoveryReadbackRejected("fresh recovery evidence lineage mismatch")
    observed_at = _timestamp(value["observed_at"])
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise RecoveryReadbackRejected("validation time must include timezone")
    age = (instant.astimezone(timezone.utc) - observed_at).total_seconds()
    if age < 0 or age > MAX_AGE_SECONDS:
        raise RecoveryReadbackRejected("fresh recovery evidence is future-dated or stale")
    desired_sha = hashlib.sha256(contracts.canonical_json_bytes(expected_desired)).hexdigest()
    if _sha(value["desired_state_sha256"], "desired_state_sha256") != desired_sha:
        raise RecoveryReadbackRejected("desired state digest mismatch")
    readback = recovery._checked_readback(value["readback"], payload["operation_name"])
    readback_sha = hashlib.sha256(contracts.canonical_json_bytes(readback)).hexdigest()
    if _sha(value["readback_sha256"], "readback_sha256") != readback_sha:
        raise RecoveryReadbackRejected("readback evidence digest mismatch")
    expected_evidence = dict(value)
    supplied_evidence_sha = _sha(expected_evidence.pop("evidence_sha256"), "evidence_sha256")
    actual_evidence_sha = hashlib.sha256(contracts.canonical_json_bytes(expected_evidence)).hexdigest()
    if supplied_evidence_sha != actual_evidence_sha:
        raise RecoveryReadbackRejected("fresh recovery evidence digest mismatch")
    return {**dict(value), "readback": readback}


def write_evidence(path: str | Path, value: object, *, intent: object,
                   result: object, references: Mapping[str, Any],
                   now: datetime | None = None) -> dict:
    checked = validate_fresh_readback(value, intent, result, references=references, now=now)
    target = Path(path)
    raw = contracts.canonical_json_bytes(checked) + b"\n"
    with target.open("xb") as stream:
        stream.write(raw)
        stream.flush()
    return checked


def read_evidence(path: str | Path, *, intent: object, result: object,
                  references: Mapping[str, Any], now: datetime | None = None) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RecoveryReadbackRejected("fresh recovery evidence is unreadable") from exc
    return validate_fresh_readback(value, intent, result, references=references, now=now)
