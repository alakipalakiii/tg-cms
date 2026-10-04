"""Read-only production proof assembly for an already-applied promotion."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol

from publisher import artifact_contract as contracts
from publisher import artifact_transport as transport
from publisher import effective_mutation_result as effective_result
from publisher.proof_recovery_runner import validate_proof


class ProductionProofRejected(ValueError):
    """Promotion evidence or read-only observations are incomplete or mismatched."""


class ReadOnlyProofBackend(Protocol):
    def collect(self, context: Mapping[str, Any]) -> Mapping[str, Any]: ...


class ObservationFileBackend:
    """Read pre-collected browser/crawler observations; never performs mutations."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def collect(self, context: Mapping[str, Any]) -> Mapping[str, Any]:
        del context
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ProductionProofRejected("production proof observations are unreadable") from exc
        if not isinstance(value, Mapping):
            raise ProductionProofRejected("production proof observations must be an object")
        return value


def _check_artifact(value: object, kind: str, tx: Mapping[str, Any], source_sha: str,
                    refs: Mapping[str, Any]) -> dict:
    checked = contracts.validate_artifact(
        value, expected_transaction=tx, expected_source_sha=source_sha,
        referenced_artifacts=refs,
    )
    accepted = {"mutation_result", "recovered_mutation_result"} if kind == "applied_result" else {kind}
    if checked["artifact_type"] not in accepted:
        raise ProductionProofRejected(f"{kind} artifact is required")
    return checked


def _check_pair(intent: dict, result: dict, operation: str, bundle_sha: str,
                refs: Mapping[str, Any]) -> None:
    if result["artifact_type"] == "recovered_mutation_result":
        applied = effective_result.validate_effective_applied_result(
            result, intent, referenced_artifacts=refs,
        )
    else:
        contracts.validate_intent_result_pair(intent, result, referenced_artifacts=refs)
        applied = {"payload": result["payload"]}
    ip, rp = intent["payload"], applied["payload"]
    if (ip["operation_name"] != operation or ip["build_bundle_sha256"] != bundle_sha
            or rp["build_bundle_sha256"] != bundle_sha or rp["result_state"] != "APPLIED"):
        raise ProductionProofRejected(f"{operation} must be APPLIED for this build bundle")


def _gate_map(value: object, names: tuple[str, ...], label: str) -> dict[str, bool]:
    if not isinstance(value, Mapping) or set(value) != set(names):
        raise ProductionProofRejected(f"{label} gate set is incomplete or unexpected")
    if any(type(value[name]) is not bool for name in names):
        raise ProductionProofRejected(f"{label} gates must be booleans")
    return dict(value)


def _observations(value: object, candidate: Mapping[str, Any], promotion_id: str,
                  bundle: Mapping[str, Any]) -> tuple[dict, dict, dict]:
    if not isinstance(value, Mapping) or set(value) != {
        "local", "identity_confirmation", "production",
    }:
        raise ProductionProofRejected("read-only observation contract is invalid")
    local = value["local"]
    if not isinstance(local, Mapping) or set(local) != {"evidence_sha256", "gates"}:
        raise ProductionProofRejected("local proof observations are invalid")
    if (local["evidence_sha256"] != bundle["payload"]["local_gate_evidence_sha256"]):
        raise ProductionProofRejected("local evidence does not match the sealed build bundle")
    local_gates = _gate_map(local["gates"], contracts.LOCAL_GATES, "local")
    local_stage = {"evidence_sha256": local["evidence_sha256"], "gates": local_gates,
                   "PASS": all(local_gates.values())}

    identity = value["identity_confirmation"]
    if not isinstance(identity, Mapping) or set(identity) != {
        "candidate_version_id", "baseline_version_id", "promotion_deployment_id",
        "candidate_percentage", "baseline_percentage", "PASS",
    }:
        raise ProductionProofRejected("production identity observation is invalid")
    identity_pass = (
        identity["candidate_version_id"] == candidate["candidate_version_id"]
        and identity["baseline_version_id"] == candidate["baseline_version_id"]
        and identity["promotion_deployment_id"] == promotion_id
        and identity["candidate_percentage"] == 100
        and identity["baseline_percentage"] == 0
        and identity["PASS"] is True
    )
    identity_confirmation = {
        "candidate_version_id": candidate["candidate_version_id"],
        "baseline_version_id": candidate["baseline_version_id"],
        "promotion_deployment_id": promotion_id,
        "candidate_percentage": identity.get("candidate_percentage"),
        "baseline_percentage": identity.get("baseline_percentage"),
        "PASS": identity_pass,
    }

    production = value["production"]
    if not isinstance(production, Mapping) or set(production) != {
        "crawler_evidence_sha256", "browser_evidence_sha256", "route_state_evidence_sha256", "gates",
    }:
        raise ProductionProofRejected("production proof evidence is invalid")
    for name in ("crawler_evidence_sha256", "browser_evidence_sha256", "route_state_evidence_sha256"):
        digest = production[name]
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ProductionProofRejected(f"{name} is invalid")
    production_gates = _gate_map(production["gates"], contracts.PRODUCTION_GATES, "production")
    production_stage = {
        "crawler_evidence_sha256": production["crawler_evidence_sha256"],
        "browser_evidence_sha256": production["browser_evidence_sha256"],
        "route_state_evidence_sha256": production["route_state_evidence_sha256"],
        "gates": production_gates,
        "PASS": all(production_gates.values()),
    }
    production_validation = {
        "identity_confirmation": identity_confirmation,
        "gates": production_gates,
        "PASS": identity_pass and all(production_gates.values()),
    }
    return local_stage, production_stage, production_validation


def create_production_proof(*, build_bundle: object, upload_intent: object,
                            upload_result: object, deploy_intent: object,
                            deploy_result: object, pre_promotion_proof: object,
                            promote_intent: object, promote_result: object,
                            backend: ReadOnlyProofBackend, producer: Mapping[str, Any] | None = None,
                            clock=None,
                            referenced_artifacts: Mapping[str, Any] | None = None) -> dict:
    """Seal proof after an APPLIED promotion, using observation-only backend data."""
    raw_bundle = contracts.validate_artifact(build_bundle)
    if raw_bundle["artifact_type"] != "build_bundle":
        raise ProductionProofRejected("build_bundle is required")
    tx, source_sha = raw_bundle["transaction"], raw_bundle["producer"]["source_sha"]
    refs = transport.references(*(referenced_artifacts or {}).values(),
        raw_bundle, upload_intent, upload_result, deploy_intent, deploy_result,
        pre_promotion_proof, promote_intent, promote_result,
    )
    bundle = _check_artifact(raw_bundle, "build_bundle", tx, source_sha, refs)
    upload_i = _check_artifact(upload_intent, "mutation_intent", tx, source_sha, refs)
    upload_r = _check_artifact(upload_result, "applied_result", tx, source_sha, refs)
    deploy_i = _check_artifact(deploy_intent, "mutation_intent", tx, source_sha, refs)
    deploy_r = _check_artifact(deploy_result, "applied_result", tx, source_sha, refs)
    preproof = _check_artifact(pre_promotion_proof, "pre_promotion_proof_evidence", tx, source_sha, refs)
    promote_i = _check_artifact(promote_intent, "mutation_intent", tx, source_sha, refs)
    promote_r = _check_artifact(promote_result, "applied_result", tx, source_sha, refs)
    bundle_sha = bundle["artifact_sha256"]
    _check_pair(upload_i, upload_r, "upload_version", bundle_sha, refs)
    _check_pair(deploy_i, deploy_r, "deploy_zero_percent", bundle_sha, refs)
    _check_pair(promote_i, promote_r, "promote", bundle_sha, refs)
    if (upload_i["payload"]["prerequisite_artifact_sha256"]
            != bundle["payload"]["admission_receipt_sha256"]
            or deploy_i["payload"]["prerequisite_artifact_sha256"] != upload_r["artifact_sha256"]
            or deploy_i["payload"]["desired_state"]["candidate_version_id"]
            != upload_r["payload"]["readback_reference"]["resource_id"]):
        raise ProductionProofRejected("upload/deploy lineage mismatch")
    candidate = preproof["payload"]["candidate_identity"]
    deploy_desired = deploy_i["payload"]["desired_state"]
    promote_desired = promote_i["payload"]["desired_state"]
    if (preproof["payload"]["PASS"] is not True
            or preproof["payload"]["build_bundle_artifact_sha256"] != bundle_sha
            or preproof["payload"]["deploy_zero_percent_result_artifact_sha256"] != deploy_r["artifact_sha256"]
            or candidate["content_fingerprint"] != bundle["payload"]["content_fingerprint"]
            or candidate["candidate_version_id"] != deploy_desired["candidate_version_id"]
            or candidate["baseline_version_id"] != deploy_desired["baseline_version_id"]
            or candidate["zero_percent_deployment_id"] != deploy_r["payload"]["readback_reference"]["resource_id"]
            or promote_i["payload"]["prerequisite_artifact_sha256"] != preproof["artifact_sha256"]
            or promote_desired["candidate_version_id"] != candidate["candidate_version_id"]
            or promote_desired["baseline_version_id"] != candidate["baseline_version_id"]
            or promote_desired["expected_current_deployment_id"] != candidate["zero_percent_deployment_id"]
            or promote_desired["candidate_percentage"] != 100
            or promote_desired["baseline_percentage"] != 0):
        raise ProductionProofRejected("pre-promotion/promote lineage mismatch")
    promotion_id = promote_r["payload"]["readback_reference"]["resource_id"]
    context = {
        "transaction": dict(tx), "source_sha": source_sha,
        "build_bundle_sha256": bundle_sha,
        "candidate_identity": dict(candidate), "promotion_deployment_id": promotion_id,
    }
    try:
        observed = backend.collect(context)
    except Exception as exc:
        raise ProductionProofRejected("read-only production proof backend failed") from exc
    local_stage, production_stage, production_validation = _observations(
        observed, candidate, promotion_id, bundle,
    )
    remote_stage = dict(preproof["payload"]["remote"])
    gate_results = {"local": local_stage, "remote": remote_stage, "production": production_stage}
    proof_state = "PASS" if (
        local_stage["PASS"] and remote_stage["PASS"] and production_stage["PASS"]
        and production_validation["PASS"]
    ) else "FAIL"
    now = clock or (lambda: datetime.now(timezone.utc).isoformat())
    producer_value = dict(producer or promote_r["producer"])
    producer_value["source_sha"] = source_sha
    proof = contracts.seal_artifact({
        "artifact_type": "proof_evidence",
        "schema_version": contracts.SCHEMA_VERSION,
        "artifact_id": str(uuid.uuid4()),
        "created_at": now(),
        "producer": producer_value,
        "transaction": dict(tx),
        "payload": {
            "build_bundle_sha256": bundle_sha,
            "operation_result_sha256s": {
                "upload_version": upload_r["artifact_sha256"],
                "deploy_zero_percent": deploy_r["artifact_sha256"],
                "promote": promote_r["artifact_sha256"], "rollback": None,
            },
            "gate_results": gate_results,
            "candidate_identity": dict(candidate),
            "production_validation": production_validation,
            # This is the previously sealed browser/runtime proof, not a traffic split claim.
            "zero_origin_validation": dict(preproof["payload"]["zero_origin_validation"]),
            "proof_state": proof_state,
        },
    })
    proof = contracts.validate_artifact(
        proof, expected_transaction=tx, expected_source_sha=source_sha,
    )
    return validate_proof(proof, bundle, {
        "upload_version": upload_r, "deploy_zero_percent": deploy_r, "promote": promote_r,
    }, referenced_artifacts=refs)
