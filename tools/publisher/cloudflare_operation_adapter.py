"""Fail-closed Cloudflare operation boundary; tests inject a fake backend."""
from __future__ import annotations

import copy
import hashlib
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol

from publisher import artifact_contract as contracts
from publisher import effective_mutation_result as effective_result


_READBACK_FIELDS = {
    "desired_state_matches", "precondition_matches", "current_deployment_id",
    "resource_type", "resource_id",
}
_OPAQUE = re.compile(r"^[^\s\x00-\x1f\x7f]+$")


class OperationRejected(RuntimeError):
    """Invalid or mismatched operation contract; no backend mutation was attempted."""


class OperationBackend(Protocol):
    def read_state(self, intent: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def mutate(self, intent: Mapping[str, Any], build_bundle: Mapping[str, Any]) -> None: ...


def _opaque(value: object, label: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not _OPAQUE.fullmatch(value):
        raise OperationRejected(f"invalid {label}")
    return value


def _readback(value: object, operation: str) -> dict:
    if not isinstance(value, Mapping) or set(value) != _READBACK_FIELDS:
        raise OperationRejected("backend readback schema invalid")
    result = dict(value)
    for field in ("desired_state_matches", "precondition_matches"):
        if result[field] is not None and type(result[field]) is not bool:
            raise OperationRejected("backend readback flag invalid")
    _opaque(result["current_deployment_id"], "current deployment ID", nullable=True)
    expected_type = "version" if operation == "upload_version" else "deployment"
    if result["resource_type"] is not None and result["resource_type"] != expected_type:
        raise OperationRejected("backend readback resource type invalid")
    _opaque(result["resource_id"], "resource ID", nullable=True)
    if (result["resource_type"] is None) != (result["resource_id"] is None):
        raise OperationRejected("backend readback resource reference incomplete")
    return result


def _same_lineage(value: object, intent: dict,
                  referenced_artifacts: Mapping[str, Any] | None = None) -> dict:
    return contracts.validate_artifact(
        value,
        expected_transaction=intent["transaction"],
        expected_source_sha=intent["producer"]["source_sha"],
        referenced_artifacts=referenced_artifacts,
    )


def _validate_prerequisite(intent: dict, prerequisite: object,
                           prerequisite_intent: object | None,
                           referenced_artifacts: Mapping[str, Any] | None = None) -> dict:
    payload = intent["payload"]
    parent = _same_lineage(prerequisite, intent, referenced_artifacts)
    if parent["artifact_sha256"] != payload["prerequisite_artifact_sha256"]:
        raise OperationRejected("prerequisite artifact digest mismatch")
    operation = payload["operation_name"]
    desired = payload["desired_state"]
    if operation == "upload_version":
        if (parent["artifact_type"] != "admission_receipt"
                or parent["payload"]["decision"] != "ADMITTED"):
            raise OperationRejected("upload requires an ADMITTED receipt")
        return parent
    if operation == "rollback":
        if parent["artifact_type"] != "proof_evidence":
            raise OperationRejected("rollback requires proof evidence")
        if parent["payload"]["proof_state"] != "FAIL":
            raise OperationRejected("rollback requires failed proof evidence")
        identity = parent["payload"]["candidate_identity"]
        if (identity["candidate_version_id"] != desired["failed_candidate_version_id"]
                or identity["baseline_version_id"] != desired["baseline_version_id"]):
            raise OperationRejected("rollback proof identity mismatch")
        return parent
    if operation == "promote":
        if (parent["artifact_type"] != "pre_promotion_proof_evidence"
                or parent["payload"]["PASS"] is not True
                or parent["payload"]["build_bundle_artifact_sha256"] != payload["build_bundle_sha256"]):
            raise OperationRejected("promotion requires matching passing pre-promotion proof")
        identity = parent["payload"]["candidate_identity"]
        if (identity["candidate_version_id"] != payload["desired_state"]["candidate_version_id"]
                or identity["baseline_version_id"] != payload["desired_state"]["baseline_version_id"]
                or identity["zero_percent_deployment_id"]
                    != payload["desired_state"]["expected_current_deployment_id"]):
            raise OperationRejected("promotion proof identity mismatch")
        return parent
    if parent["artifact_type"] not in {"mutation_result", "recovered_mutation_result"} or prerequisite_intent is None:
        raise OperationRejected("operation requires its prior intent and result")
    prior_intent = _same_lineage(prerequisite_intent, intent)
    effective_parent = effective_result.validate_effective_applied_result(
        parent, prior_intent, referenced_artifacts=referenced_artifacts,
    )
    prior = prior_intent["payload"]
    if (effective_parent["payload"]["result_state"] != "APPLIED"
            or prior["build_bundle_sha256"] != payload["build_bundle_sha256"]):
        raise OperationRejected("prior operation is not an applied result for this build")
    expected_prior = "upload_version"
    if prior["operation_name"] != expected_prior:
        raise OperationRejected("prior operation type mismatch")
    ref = effective_parent["payload"]["readback_reference"]
    if operation == "deploy_zero_percent":
        if ref["resource_type"] != "version" or ref["resource_id"] != desired["candidate_version_id"]:
            raise OperationRejected("candidate version is not bound to upload readback")
    else:
        prior_state = prior["desired_state"]
        if (ref["resource_type"] != "deployment"
                or ref["resource_id"] != desired["expected_current_deployment_id"]
                or prior_state["candidate_version_id"] != desired["candidate_version_id"]
                or prior_state["baseline_version_id"] != desired["baseline_version_id"]):
            raise OperationRejected("promotion target is not bound to zero-percent readback")
    return parent


class WranglerOperationBackend:
    """Production-capable backend. Never invoked by the synthetic test suite."""

    def __init__(self, sealed_root: str | Path, config_path: str | Path):
        self.sealed_root = Path(sealed_root)
        self.config_path = Path(config_path)

    @staticmethod
    def _deployment_shape(deployment: Mapping[str, Any]) -> dict[str, int]:
        versions = deployment.get("versions")
        if not isinstance(versions, list):
            raise OperationRejected("deployment readback missing versions")
        shape: dict[str, int] = {}
        for item in versions:
            if (not isinstance(item, Mapping) or not isinstance(item.get("version_id"), str)
                    or isinstance(item.get("percentage"), bool)
                    or not isinstance(item.get("percentage"), int)
                    or not 0 <= item["percentage"] <= 100
                    or item["version_id"] in shape):
                raise OperationRejected("deployment readback malformed")
            shape[item["version_id"]] = item["percentage"]
        return shape

    @staticmethod
    def _target(operation: str, desired: Mapping[str, Any]) -> dict[str, int]:
        if operation == "deploy_zero_percent":
            return {desired["baseline_version_id"]: 100, desired["candidate_version_id"]: 0}
        if operation == "promote":
            return {desired["candidate_version_id"]: 100, desired["baseline_version_id"]: 0}
        return {desired["baseline_version_id"]: 100, desired["failed_candidate_version_id"]: 0}

    def read_state(self, intent: Mapping[str, Any]) -> Mapping[str, Any]:
        # Import only at operation time; unit tests use FakeBackend and never load Wrangler.
        from publisher import cloudflare_wrangler as wrangler

        tx, payload = intent["transaction"], intent["payload"]
        operation, desired = payload["operation_name"], payload["desired_state"]
        if operation == "upload_version":
            versions = wrangler.list_versions(tx["worker"])
            marker = f"MAHOON-A3:{payload['operation_id']}:{payload['attempt_id']}"
            matches = [item for item in versions if isinstance(item, Mapping)
                       and item.get("annotations", {}).get("workers/message") == marker
                       and isinstance(item.get("id"), str)]
            reference = matches[0]["id"] if matches else next(
                (item.get("id") for item in versions if isinstance(item, Mapping)
                 and isinstance(item.get("id"), str)), None
            )
            return {
                "desired_state_matches": bool(matches), "precondition_matches": None,
                "current_deployment_id": None,
                "resource_type": "version" if reference else None, "resource_id": reference,
            }

        deployment = wrangler.read_deployment(tx["worker"])
        deployment_id = deployment.get("id")
        _opaque(deployment_id, "deployment ID")
        actual = self._deployment_shape(deployment)
        target = self._target(operation, desired)
        desired_matches = actual == target
        expected = desired["expected_current_deployment_id"]
        if operation == "deploy_zero_percent":
            starting = {desired["baseline_version_id"]: 100}
        elif operation == "promote":
            starting = {desired["baseline_version_id"]: 100, desired["candidate_version_id"]: 0}
        else:
            starting = {desired["failed_candidate_version_id"]: 100}
        precondition = deployment_id == expected and actual == starting
        return {
            "desired_state_matches": desired_matches,
            "precondition_matches": precondition,
            "current_deployment_id": deployment_id,
            "resource_type": "deployment", "resource_id": deployment_id,
        }

    def mutate(self, intent: Mapping[str, Any], build_bundle: Mapping[str, Any]) -> None:
        from publisher import cloudflare_wrangler as wrangler

        tx, payload = intent["transaction"], intent["payload"]
        operation, desired = payload["operation_name"], payload["desired_state"]
        if operation == "upload_version":
            marker = f"MAHOON-A3:{payload['operation_id']}:{payload['attempt_id']}"
            wrangler.upload_version(tx["worker"], self.sealed_root, self.config_path, marker)
            return
        target = self._target(operation, desired)
        primary = next(version for version, percentage in target.items() if percentage == 100)
        secondary = next(version for version, percentage in target.items() if percentage == 0)
        wrangler.deploy_pair(tx["worker"], primary, 100, secondary, 0)


class CloudflareOperationAdapter:
    """Validates lineage, pre-reads once, mutates at most once, then reconciles."""

    def __init__(self, backend: OperationBackend, *, clock=None):
        self.backend = backend
        self.clock = clock or (lambda: datetime.now(timezone.utc).isoformat())
        self._attempted: set[tuple[str, str]] = set()

    def _result(self, intent: dict, readback: dict | None, result_state: str,
                referenced_artifacts: Mapping[str, Any] | None = None) -> dict:
        ip = intent["payload"]
        evidence = None
        reference = None
        if readback is not None:
            evidence = hashlib.sha256(contracts.canonical_json_bytes(readback)).hexdigest()
            if readback["resource_id"] is not None:
                reference = {
                    "resource_type": readback["resource_type"],
                    "worker": intent["transaction"]["worker"],
                    "resource_id": readback["resource_id"],
                }
        artifact = contracts.seal_artifact({
            "artifact_type": "mutation_result",
            "schema_version": contracts.SCHEMA_VERSION,
            "artifact_id": str(uuid.uuid4()),
            "created_at": self.clock(),
            "producer": {**intent["producer"], "job": "cloudflare-operation"},
            "transaction": copy.deepcopy(intent["transaction"]),
            "payload": {
                "operation_id": ip["operation_id"],
                "attempt_id": ip["attempt_id"],
                "result_state": result_state,
                "evidence_sha256": evidence,
                "intent_artifact_sha256": intent["artifact_sha256"],
                "build_bundle_sha256": ip["build_bundle_sha256"],
                "readback_reference": reference,
            },
        })
        contracts.validate_intent_result_pair(
            intent, artifact, referenced_artifacts=referenced_artifacts,
        )
        return artifact

    def execute(self, intent: object, build_bundle: object, prerequisite_artifact: object,
                *, prerequisite_intent: object | None = None,
                referenced_artifacts: Mapping[str, Any] | None = None) -> dict:
        operation_intent = contracts.validate_artifact(
            intent, referenced_artifacts=referenced_artifacts,
        )
        if operation_intent["artifact_type"] != "mutation_intent":
            raise OperationRejected("mutation_intent artifact required")
        payload = operation_intent["payload"]
        bundle = _same_lineage(build_bundle, operation_intent)
        if (bundle["artifact_type"] != "build_bundle"
                or bundle["artifact_sha256"] != payload["build_bundle_sha256"]):
            raise OperationRejected("build bundle identity mismatch")
        prerequisite = _validate_prerequisite(
            operation_intent, prerequisite_artifact, prerequisite_intent,
            referenced_artifacts,
        )
        operation = payload["operation_name"]
        if (operation == "upload_version"
                and bundle["payload"]["admission_receipt_sha256"] != prerequisite["artifact_sha256"]):
            raise OperationRejected("build bundle admission receipt mismatch")
        attempt_key = (payload["operation_id"], payload["attempt_id"])

        try:
            before = _readback(self.backend.read_state(operation_intent), operation)
        except Exception:
            return self._result(operation_intent, None, "UNKNOWN", referenced_artifacts)
        if before["desired_state_matches"] is True:
            return self._result(operation_intent, before, "APPLIED", referenced_artifacts)
        if attempt_key in self._attempted:
            return self._result(operation_intent, before, "UNKNOWN", referenced_artifacts)
        if operation != "upload_version":
            if before["precondition_matches"] is False:
                return self._result(operation_intent, before, "NOT_APPLIED", referenced_artifacts)
            if before["precondition_matches"] is not True:
                return self._result(operation_intent, before, "UNKNOWN", referenced_artifacts)
        elif before["desired_state_matches"] is not False or before["resource_id"] is None:
            return self._result(operation_intent, before, "UNKNOWN", referenced_artifacts)
        self._attempted.add(attempt_key)
        try:
            self.backend.mutate(operation_intent, bundle)
        except Exception:
            # Request outcome is uncertain: read back, never retry in this invocation.
            pass
        try:
            after = _readback(self.backend.read_state(operation_intent), operation)
        except Exception:
            return self._result(operation_intent, None, "UNKNOWN", referenced_artifacts)
        if after["desired_state_matches"] is True:
            return self._result(operation_intent, after, "APPLIED", referenced_artifacts)
        # Wrangler's version listing does not provide proof that an absent marker
        # is a complete, strongly consistent read; absence therefore stays UNKNOWN.
        not_applied = (operation != "upload_version"
                       and after["desired_state_matches"] is False
                       and after["precondition_matches"] is True)
        return self._result(
            operation_intent, after, "NOT_APPLIED" if not_applied else "UNKNOWN",
            referenced_artifacts,
        )
