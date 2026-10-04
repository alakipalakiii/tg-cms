"""Credential-free proof validation and recovery-decision artifact creation."""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from publisher import artifact_contract as contracts
from publisher import effective_mutation_result as effective_result


class ProofRecoveryRejected(ValueError):
    """Proof or recovery evidence is incomplete or mismatched."""


_READBACK_FIELDS = {
    "desired_state_matches", "precondition_matches", "current_deployment_id",
    "resource_type", "resource_id",
}


def _checked_readback(value: object, operation: str) -> dict:
    if not isinstance(value, Mapping) or set(value) != _READBACK_FIELDS:
        raise ProofRecoveryRejected("readback evidence schema invalid")
    result = dict(value)
    for key in ("desired_state_matches", "precondition_matches"):
        if result[key] is not None and type(result[key]) is not bool:
            raise ProofRecoveryRejected("readback evidence flag invalid")
    expected_type = "version" if operation == "upload_version" else "deployment"
    for key in ("current_deployment_id", "resource_id"):
        if result[key] is not None and (not isinstance(result[key], str) or not result[key].strip()):
            raise ProofRecoveryRejected("readback evidence identity invalid")
    if result["resource_type"] not in ({None, expected_type}):
        raise ProofRecoveryRejected("readback evidence resource type mismatch")
    if (result["resource_type"] is None) != (result["resource_id"] is None):
        raise ProofRecoveryRejected("readback resource reference is incomplete")
    return result


def recovery_decision(intent: object, result: object, readback: object,
                      journal_generation: int, *, clock=None,
                      referenced_artifacts: Mapping[str, Any] | None = None) -> dict:
    """Reconcile an UNKNOWN result from fresh read-only evidence; never executes mutation."""
    intent_v = contracts.validate_artifact(intent, referenced_artifacts=referenced_artifacts)
    result_v = contracts.validate_artifact(
        result, expected_transaction=intent_v["transaction"],
        expected_source_sha=intent_v["producer"]["source_sha"],
        referenced_artifacts=referenced_artifacts,
    )
    contracts.validate_intent_result_pair(
        intent_v, result_v, referenced_artifacts=referenced_artifacts,
    )
    ip, rp = intent_v["payload"], result_v["payload"]
    if rp["result_state"] != "UNKNOWN":
        raise ProofRecoveryRejected("only UNKNOWN results require reconciliation")
    if isinstance(journal_generation, bool) or not isinstance(journal_generation, int) or journal_generation < ip["journal_generation"]:
        raise ProofRecoveryRejected("journal generation predates mutation intent")

    observed = _checked_readback(readback, ip["operation_name"])
    if observed["desired_state_matches"] is True:
        decision, resume = "RECONCILED_APPLIED", False
    elif (ip["operation_name"] != "upload_version"
          and observed["desired_state_matches"] is False
          and observed["precondition_matches"] is True):
        decision, resume = "RECONCILED_NOT_APPLIED", True
    else:
        # Version listing absence is not sufficient proof that an upload did not apply.
        decision, resume = "BLOCKED_UNKNOWN", False

    now = clock or (lambda: datetime.now(timezone.utc).isoformat())
    return contracts.seal_artifact({
        "artifact_type": "recovery_decision",
        "schema_version": contracts.SCHEMA_VERSION,
        "artifact_id": str(uuid.uuid4()),
        "created_at": now(),
        "producer": {**intent_v["producer"], "job": "proof-recovery"},
        "transaction": dict(intent_v["transaction"]),
        "payload": {
            "operation_id": ip["operation_id"],
            "attempt_id": ip["attempt_id"],
            "decision": decision,
            "evidence_sha256": hashlib.sha256(contracts.canonical_json_bytes(observed)).hexdigest(),
            "intent_artifact_sha256": intent_v["artifact_sha256"],
            "result_artifact_sha256": result_v["artifact_sha256"],
            "journal_generation": journal_generation,
            "resume_allowed": resume,
        },
    })


def validate_proof(proof: object, build_bundle: object,
                   operation_results: Mapping[str, object], *,
                   referenced_artifacts: Mapping[str, Any] | None = None) -> dict:
    """Validate proof-to-build/result lineage; does not perform proof requests."""
    proof_v = contracts.validate_artifact(proof)
    bundle_v = contracts.validate_artifact(
        build_bundle, expected_transaction=proof_v["transaction"],
        expected_source_sha=proof_v["producer"]["source_sha"],
    )
    if proof_v["artifact_type"] != "proof_evidence" or bundle_v["artifact_type"] != "build_bundle":
        raise ProofRecoveryRejected("proof and build bundle artifacts are required")
    pp, bp = proof_v["payload"], bundle_v["payload"]
    if pp["build_bundle_sha256"] != bundle_v["artifact_sha256"]:
        raise ProofRecoveryRejected("proof references another build bundle")
    required = {"upload_version", "deploy_zero_percent", "promote"}
    if set(operation_results) != required:
        raise ProofRecoveryRejected("proof requires exactly the three applied operation results")
    for name, result in operation_results.items():
        checked = contracts.validate_artifact(
            result, expected_transaction=proof_v["transaction"],
            expected_source_sha=proof_v["producer"]["source_sha"],
            referenced_artifacts=referenced_artifacts,
        )
        if checked["artifact_type"] == "recovered_mutation_result":
            intent = next((item for item in (referenced_artifacts or {}).values()
                           if isinstance(item, Mapping)
                           and item.get("artifact_sha256") == checked["payload"]["intent_artifact_sha256"]), None)
            if intent is None:
                raise ProofRecoveryRejected(f"recovered operation intent missing: {name}")
            checked = effective_result.validate_effective_applied_result(
                checked, intent, referenced_artifacts=referenced_artifacts,
            )
            result_payload = checked["payload"]
            result_sha = checked["artifact_sha256"]
        else:
            if checked["artifact_type"] != "mutation_result":
                raise ProofRecoveryRejected(f"unsupported operation result type: {name}")
            result_payload, result_sha = checked["payload"], checked["artifact_sha256"]
        if (result_payload["operation_id"] != contracts.operation_id_for(
                    proof_v["transaction"]["logical_transaction_id"], name)
                or result_payload["result_state"] != "APPLIED"
                or result_payload["build_bundle_sha256"] != bundle_v["artifact_sha256"]
                or pp["operation_result_sha256s"][name] != result_sha):
            raise ProofRecoveryRejected(f"proof operation lineage invalid: {name}")
    if pp["operation_result_sha256s"]["rollback"] is not None:
        raise ProofRecoveryRejected("rollback result requires a separate post-rollback proof")
    # Keep the binding explicit; the validator already validates the build payload schema.
    if not bp["local_gate_evidence_sha256"]:
        raise ProofRecoveryRejected("build bundle local validation evidence missing")
    return proof_v


def authorize_rollback(proof: object, promote_intent: object,
                       promote_result: object, rollback_intent: object, *,
                       referenced_artifacts: Mapping[str, Any] | None = None) -> dict:
    """Require failed production proof and a distinct recorded rollback operation intent."""
    proof_v = contracts.validate_artifact(proof)
    promote_v = contracts.validate_artifact(
        promote_intent, expected_transaction=proof_v["transaction"],
        expected_source_sha=proof_v["producer"]["source_sha"],
        referenced_artifacts=referenced_artifacts,
    )
    result_view = effective_result.validate_effective_applied_result(
        promote_result, promote_v, referenced_artifacts=referenced_artifacts,
    )
    result_v = result_view["artifact"]
    rollback_v = contracts.validate_artifact(rollback_intent)
    pp = proof_v["payload"]
    mp, rp = promote_v["payload"], result_view["payload"]
    rb = rollback_v["payload"]
    if (proof_v["artifact_type"] != "proof_evidence" or pp["proof_state"] != "FAIL"
            or pp["production_validation"]["PASS"] is not False):
        raise ProofRecoveryRejected("breaker or non-production proof failure cannot authorize rollback")
    if (mp["operation_name"] != "promote" or rp["result_state"] != "APPLIED"
            or pp["operation_result_sha256s"]["promote"] != result_v["artifact_sha256"]
            or pp["build_bundle_sha256"] != mp["build_bundle_sha256"]
            or pp["candidate_identity"]["zero_percent_deployment_id"]
            != mp["desired_state"]["expected_current_deployment_id"]):
        raise ProofRecoveryRejected("failed proof is not bound to an applied promotion")
    if (rollback_v["artifact_type"] != "mutation_intent" or rb["operation_name"] != "rollback"
            or rb["intent_state"] != "RECORDED" or rb["attempt_id"] == mp["attempt_id"]):
        raise ProofRecoveryRejected("rollback requires a separate recorded attempt")
    if (rollback_v["transaction"] != proof_v["transaction"]
            or rollback_v["producer"]["source_sha"] != proof_v["producer"]["source_sha"]
            or rb["build_bundle_sha256"] != mp["build_bundle_sha256"]
            or rb["prerequisite_artifact_sha256"] != proof_v["artifact_sha256"]):
        raise ProofRecoveryRejected("rollback transaction or proof lineage mismatch")
    candidate = pp["candidate_identity"]
    target = rb["desired_state"]
    promotion_id = pp["production_validation"]["identity_confirmation"]["promotion_deployment_id"]
    if (target["failed_candidate_version_id"] != candidate["candidate_version_id"]
            or target["baseline_version_id"] != candidate["baseline_version_id"]
            or target["expected_current_deployment_id"] != promotion_id):
        raise ProofRecoveryRejected("rollback target does not match failed production deployment")
    return rollback_v
