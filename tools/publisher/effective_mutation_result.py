"""One validation boundary for direct and recovery-proven applied results."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping
import uuid

from publisher import artifact_contract as contracts
from publisher.transaction_journal import canonical_result_digest


class EffectiveResultRejected(ValueError):
    """An operation has no acceptable applied-result authority."""


def _checked(value: object, intent: object,
             references: Mapping[str, Any] | None) -> tuple[dict, dict]:
    refs = references or {}
    try:
        intent_v = contracts.validate_artifact(intent, referenced_artifacts=refs)
        if intent_v["artifact_type"] != "mutation_intent":
            raise EffectiveResultRejected("sealed mutation intent is required")
        result_v = contracts.validate_artifact(
            value, expected_transaction=intent_v["transaction"],
            expected_source_sha=intent_v["producer"]["source_sha"],
            referenced_artifacts=refs,
        )
        if result_v["artifact_type"] == "mutation_result":
            contracts.validate_intent_result_pair(intent_v, result_v,
                                                  referenced_artifacts=refs)
            if result_v["payload"]["result_state"] != "APPLIED":
                raise EffectiveResultRejected("mutation result is not APPLIED")
            return intent_v, result_v
        if result_v["artifact_type"] != "recovered_mutation_result":
            raise EffectiveResultRejected("effective applied result type is unsupported")
        p, ip = result_v["payload"], intent_v["payload"]
        original = refs.get(p["original_result_artifact_sha256"])
        decision = refs.get(p["recovery_decision_artifact_sha256"])
        if original is None or decision is None:
            raise EffectiveResultRejected("original UNKNOWN result and recovery decision are required")
        original_v = contracts.validate_artifact(
            original, expected_transaction=intent_v["transaction"],
            expected_source_sha=intent_v["producer"]["source_sha"],
            referenced_artifacts=refs,
        )
        contracts.validate_intent_result_pair(intent_v, original_v,
                                              referenced_artifacts=refs)
        if original_v["artifact_type"] != "mutation_result" or original_v["payload"]["result_state"] != "UNKNOWN":
            raise EffectiveResultRejected("bridge must preserve the original UNKNOWN result")
        decision_v = contracts.validate_artifact(
            decision, expected_transaction=intent_v["transaction"],
            expected_source_sha=intent_v["producer"]["source_sha"],
            referenced_artifacts=refs,
        )
        dp = decision_v["payload"]
        expected = {
            "operation_id": ip["operation_id"], "operation_name": ip["operation_name"],
            "attempt_id": ip["attempt_id"], "result_state": "APPLIED",
            "intent_artifact_sha256": intent_v["artifact_sha256"],
            "original_result_artifact_sha256": original_v["artifact_sha256"],
            "recovery_decision_artifact_sha256": decision_v["artifact_sha256"],
            "recovery_evidence_sha256": p["recovery_evidence_sha256"],
            "recovery_decision_evidence_sha256": dp["evidence_sha256"],
            "evidence_sha256": dp["evidence_sha256"],
            "build_bundle_sha256": ip["build_bundle_sha256"],
            "readback_reference": p["readback_reference"],
        }
        if decision_v["artifact_type"] != "recovery_decision" or dp["decision"] != "RECONCILED_APPLIED":
            raise EffectiveResultRejected("bridge requires RECONCILED_APPLIED authority")
        if (dp["operation_id"] != ip["operation_id"]
                or dp["attempt_id"] != ip["attempt_id"]
                or dp["intent_artifact_sha256"] != intent_v["artifact_sha256"]
                or dp["result_artifact_sha256"] != original_v["artifact_sha256"]
                or dp["resume_allowed"] is not False
                or any(p.get(key) != expected_value for key, expected_value in expected.items())):
            raise EffectiveResultRejected("recovered result lineage does not match its authorities")
        readback_at = datetime.fromisoformat(p["recovery_readback_observed_at"].replace("Z", "+00:00"))
        created_at = datetime.fromisoformat(result_v["created_at"].replace("Z", "+00:00"))
        from publisher import recovery_readback
        if (readback_at.tzinfo is None or created_at.tzinfo is None
                or created_at < readback_at
                or (created_at - readback_at).total_seconds() > recovery_readback.MAX_AGE_SECONDS):
            raise EffectiveResultRejected("recovery readback was stale when the bridge was created")
        evidence = {"type": "recovery_decision", "reference": decision_v["artifact_sha256"],
                    "sha256": dp["evidence_sha256"]}
        if (p["journal_result_digest"] != canonical_result_digest("APPLIED", evidence)
                or p["journal_generation"] != dp["journal_generation"] + 1):
            raise EffectiveResultRejected("durable reconciliation generation or result digest mismatch")
        return intent_v, result_v
    except EffectiveResultRejected:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise EffectiveResultRejected("effective applied-result lineage is invalid") from exc


def validate_effective_applied_result(value: object, intent: object, *,
                                      referenced_artifacts: Mapping[str, Any] | None = None) -> dict:
    """Return an in-memory common view; never rewrites or reseals source artifacts."""
    intent_v, result_v = _checked(value, intent, referenced_artifacts)
    payload = dict(result_v["payload"])
    if result_v["artifact_type"] == "mutation_result":
        payload["operation_name"] = intent_v["payload"]["operation_name"]
    return {"artifact": result_v, "artifact_sha256": result_v["artifact_sha256"],
            "artifact_type": result_v["artifact_type"], "payload": payload,
            "transaction": result_v["transaction"], "producer": result_v["producer"]}


def create_recovered_mutation_result(*, intent: object, original_result: object,
                                     recovery_evidence: object,
                                     recovery_decision: object, journal_writer: object,
                                     referenced_artifacts: Mapping[str, Any],
                                     clock=None) -> dict:
    """Read the exact remote journal through the accepted writer, then seal the bridge."""
    from publisher.repository_persistence import GitJournalWriter
    if type(journal_writer) is not GitJournalWriter:
        raise EffectiveResultRejected("the accepted read-only Git journal writer is required")
    readback = journal_writer.read_reconciled_applied_result(
        recovery_decision, intent, original_result,
        referenced_artifacts=referenced_artifacts,
    )
    return _create_recovered_mutation_result_from_readback(
        intent=intent, original_result=original_result,
        recovery_evidence=recovery_evidence, recovery_decision=recovery_decision,
        journal_readback=readback, referenced_artifacts=referenced_artifacts,
        clock=clock,
    )


def _create_recovered_mutation_result_from_readback(*, intent: object, original_result: object,
                                                    recovery_evidence: object,
                                                    recovery_decision: object,
                                                    journal_readback: Mapping[str, Any],
                                                    referenced_artifacts: Mapping[str, Any],
                                                    clock=None) -> dict:
    """Internal sealing after a readback returned by GitJournalWriter."""
    intent_v = contracts.validate_artifact(intent, referenced_artifacts=referenced_artifacts)
    original_v = contracts.validate_artifact(
        original_result, expected_transaction=intent_v["transaction"],
        expected_source_sha=intent_v["producer"]["source_sha"],
        referenced_artifacts=referenced_artifacts,
    )
    contracts.validate_intent_result_pair(intent_v, original_v,
                                          referenced_artifacts=referenced_artifacts)
    ip, rp = intent_v["payload"], original_v["payload"]
    if (original_v["artifact_type"] != "mutation_result" or rp["result_state"] != "UNKNOWN"):
        raise EffectiveResultRejected("only the exact original UNKNOWN result can be bridged")
    from publisher import recovery_readback
    evidence = recovery_readback.validate_fresh_readback(
        recovery_evidence, intent_v, original_v,
        references=referenced_artifacts,
    )
    decision_v = contracts.validate_artifact(
        recovery_decision, expected_transaction=intent_v["transaction"],
        expected_source_sha=intent_v["producer"]["source_sha"],
        referenced_artifacts=referenced_artifacts,
    )
    dp = decision_v["payload"]
    if (decision_v["artifact_type"] != "recovery_decision"
            or dp["decision"] != "RECONCILED_APPLIED"
            or dp["resume_allowed"] is not False
            or dp["operation_id"] != ip["operation_id"]
            or dp["attempt_id"] != ip["attempt_id"]
            or dp["intent_artifact_sha256"] != intent_v["artifact_sha256"]
            or dp["result_artifact_sha256"] != original_v["artifact_sha256"]
            or dp["evidence_sha256"] != contracts.sha256_bytes(
                contracts.canonical_json_bytes(evidence["readback"]))):
        raise EffectiveResultRejected("recovery decision does not authorize this exact UNKNOWN attempt")
    expected_keys = {
        "worker", "logical_transaction_id", "content_revision", "operation_name",
        "operation_id", "attempt_id", "outcome", "result_digest",
        "recovery_status", "journal_generation", "journal_sha256", "remote_head",
    }
    if not isinstance(journal_readback, Mapping) or set(journal_readback) != expected_keys:
        raise EffectiveResultRejected("exact authoritative journal readback is required")
    now = clock or (lambda: datetime.now(timezone.utc).isoformat())
    created_at = now()
    instant = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    observed = datetime.fromisoformat(evidence["observed_at"].replace("Z", "+00:00"))
    if (instant.tzinfo is None or observed.tzinfo is None or instant < observed
            or (instant - observed).total_seconds() > recovery_readback.MAX_AGE_SECONDS):
        raise EffectiveResultRejected("fresh recovery readback expired before durable bridge creation")
    expected_identity = {
        "worker": intent_v["transaction"]["worker"],
        "logical_transaction_id": intent_v["transaction"]["logical_transaction_id"],
        "content_revision": intent_v["transaction"]["content_revision"],
        "operation_name": ip["operation_name"], "operation_id": ip["operation_id"],
        "attempt_id": ip["attempt_id"], "outcome": "APPLIED",
        "recovery_status": "RECONCILED_APPLIED",
        "journal_generation": dp["journal_generation"] + 1,
    }
    if any(journal_readback.get(key) != value for key, value in expected_identity.items()):
        raise EffectiveResultRejected("journal readback identity or generation mismatch")
    evidence_record = {"type": "recovery_decision", "reference": decision_v["artifact_sha256"],
                       "sha256": dp["evidence_sha256"]}
    result_digest = canonical_result_digest("APPLIED", evidence_record)
    if journal_readback.get("result_digest") != result_digest:
        raise EffectiveResultRejected("journal readback does not contain the exact recovery decision")
    for field in ("journal_sha256",):
        contracts._sha256(journal_readback.get(field), field)
    remote_head = journal_readback.get("remote_head")
    if not isinstance(remote_head, str) or len(remote_head) != 40 or any(c not in "0123456789abcdef" for c in remote_head):
        raise EffectiveResultRejected("journal remote head is invalid")
    readback = evidence["readback"]
    if readback["desired_state_matches"] is not True or not readback["resource_type"] or not readback["resource_id"]:
        raise EffectiveResultRejected("recovery evidence does not prove an applied resource")
    readback_reference = {"resource_type": readback["resource_type"],
                          "worker": intent_v["transaction"]["worker"],
                          "resource_id": readback["resource_id"]}
    payload = {
        "operation_id": ip["operation_id"], "operation_name": ip["operation_name"],
        "attempt_id": ip["attempt_id"], "result_state": "APPLIED",
        "intent_artifact_sha256": intent_v["artifact_sha256"],
        "original_result_artifact_sha256": original_v["artifact_sha256"],
        "recovery_decision_artifact_sha256": decision_v["artifact_sha256"],
        "recovery_evidence_sha256": evidence["evidence_sha256"],
        "recovery_decision_evidence_sha256": dp["evidence_sha256"],
        "recovery_readback_observed_at": evidence["observed_at"],
        "evidence_sha256": dp["evidence_sha256"],
        "build_bundle_sha256": ip["build_bundle_sha256"],
        "readback_reference": readback_reference,
        "journal_generation": journal_readback["journal_generation"],
        "journal_sha256": journal_readback["journal_sha256"],
        "journal_remote_head": remote_head, "journal_result_digest": result_digest,
    }
    bridge = contracts.seal_artifact({
        "artifact_type": "recovered_mutation_result",
        "schema_version": contracts.SCHEMA_VERSION,
        "artifact_id": str(uuid.uuid4()),
        "created_at": created_at,
        "producer": {**intent_v["producer"], "job": "recovery-result-bridge"},
        "transaction": dict(intent_v["transaction"]), "payload": payload,
    })
    refs = {**dict(referenced_artifacts),
            original_v["artifact_sha256"]: original_v,
            decision_v["artifact_sha256"]: decision_v}
    validate_effective_applied_result(bridge, intent_v, referenced_artifacts=refs)
    return bridge
