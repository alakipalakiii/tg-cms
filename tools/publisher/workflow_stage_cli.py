"""Validated source-level handoffs for the MAHOON publisher workflow."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

# Support both `python -m publisher.workflow_stage_cli` and direct file execution.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from publisher import artifact_contract as contracts
from publisher import artifact_transport as transport
from publisher import final_state_materializer as materializer
from publisher import final_persistence_runner as persistence
from publisher import proof_recovery_runner as recovery
from publisher import recovery_readback as recovery_readback
from publisher import effective_mutation_result as effective_result
from publisher import production_proof_runner as production_proof
from publisher.repository_persistence import GitJournalWriter, GitRepositoryWriter
from publisher.transaction_journal import TransactionJournal, journal_digest
from publisher.content_revision import DEFAULT_ENDPOINT as REVISION_ENDPOINT
from publisher.content_revision import fetch_public_content_revision


DEFAULT_WORKER = "mahoon-art-magazine"


def _json(path: str | Path) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("input JSON is unreadable or malformed") from exc
    if not isinstance(value, dict):
        raise ValueError("input JSON must be an object")
    return value


def _read(path: str | Path, kind: str | None = None,
          refs: Mapping[str, Any] | None = None) -> dict:
    return transport.read_artifact(path, expected_type=kind, referenced_artifacts=refs)


def _many(paths: list[str] | None) -> list[dict]:
    return list(transport.read_references(paths or []).values())


def _refs(*values: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return transport.references(*values)


def _writer(repository: str | Path, worker: str, remote: str, branch: str) -> GitJournalWriter:
    return GitJournalWriter(repository, worker, remote=remote, branch=branch)


def _writer_journal_path(writer: GitJournalWriter) -> Path:
    return writer.root / "publisher-state/production-transaction-journal.json"


def _producer(source: Mapping[str, Any], job: str) -> dict:
    run_id = os.environ.get("GITHUB_RUN_ID", "local-synthetic")
    attempt_text = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    try:
        attempt = int(attempt_text)
    except ValueError as exc:
        raise ValueError("workflow run attempt is invalid") from exc
    if not run_id.strip() or attempt < 1:
        raise ValueError("workflow producer identity is invalid")
    return {
        "workflow_run_id": run_id,
        "run_attempt": attempt,
        "job": os.environ.get("GITHUB_JOB", job).strip() or job,
        "source_sha": source["producer"]["source_sha"],
    }


def _envelope(kind: str, source: Mapping[str, Any], transaction: Mapping[str, Any],
              payload: Mapping[str, Any], job: str) -> dict:
    return contracts.seal_artifact({
        "artifact_type": kind,
        "schema_version": contracts.SCHEMA_VERSION,
        "artifact_id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "producer": _producer(source, job),
        "transaction": dict(transaction),
        "payload": dict(payload),
    })


def validate_artifact_file(path: str | Path, expected_type: str | None = None,
                           reference_paths: list[str] | None = None) -> dict:
    refs = _refs(*_many(reference_paths))
    return _read(path, expected_type, refs)


def create_revision_resolution(published_state_path: str | Path, *, worker: str = DEFAULT_WORKER,
                               source_sha: str | None = None, endpoint: str | None = None,
                               fetcher=None) -> dict:
    state = _json(published_state_path)
    published = state.get("published_content_revision")
    if isinstance(published, bool) or not isinstance(published, int) or published < 1:
        raise ValueError("published revision state is missing or invalid")
    if worker != DEFAULT_WORKER:
        raise ValueError("revision worker differs from the accepted publisher worker")
    source = source_sha or os.environ.get("GITHUB_SHA")
    if not isinstance(source, str) or len(source) != 40 or any(c not in "0123456789abcdef" for c in source):
        raise ValueError("revision producer source SHA is invalid")
    if endpoint is not None and endpoint != REVISION_ENDPOINT:
        raise ValueError("revision endpoint differs from the accepted public revision service")
    kwargs = {"endpoint": REVISION_ENDPOINT}
    if fetcher is not None:
        kwargs["fetcher"] = fetcher
    revision, changed_at, _metadata = fetch_public_content_revision(**kwargs)
    tx = {"worker": worker, "content_revision": revision,
          "logical_transaction_id": contracts.logical_transaction_id(worker, revision)}
    value = _envelope("revision_resolution", {"producer": {"source_sha": source}}, tx, {
        "revision": revision,
        "published_revision": published,
        "changed_at": changed_at,
        "endpoint_id": "mahoon-content-revision-v1",
        "request_count": 1,
        "decision": "UNCHANGED" if revision == published else "CHANGED",
    }, "revision-resolver")
    return contracts.validate_artifact(value, expected_transaction=tx, expected_source_sha=source)


def create_admission_receipt(revision_path: str | Path, journal_path: str | Path,
                             source: str, run_id: str = "", attempt_id: str = "",
                             remote_writer: GitJournalWriter | None = None) -> dict:
    revision = _read(revision_path, "revision_resolution")
    rp = revision["payload"]
    if rp["decision"] != "CHANGED":
        raise ValueError("only a changed revision may be admitted for publishing")
    worker = revision["transaction"]["worker"]
    journal = TransactionJournal.from_file(Path(journal_path), worker)
    if remote_writer is None:
        decision, _tx_id = journal.admit(rp["revision"], source, run_id, attempt_id)
    else:
        decision, _tx_id, _generation, _digest = remote_writer.admit_revision(
            rp["revision"], source, run_id, attempt_id,
        )
    value, generation, digest = journal.snapshot()
    active, pending = value["active"], value["pending"]
    mapped = {
        "ADMITTED": "ADMITTED", "COALESCED_ACTIVE": "COALESCED",
        "COALESCED_COMPLETED": "COALESCED", "PENDING": "DEFERRED",
        "PENDING_REPLACED": "DEFERRED", "SUPERSEDED": "SUPERSEDED",
        "STALE": "DEFERRED", "RECOVERY_REQUIRED": "DEFERRED",
    }.get(decision)
    if mapped is None:
        raise ValueError("journal admission returned an unsupported decision")
    return _envelope("admission_receipt", revision, revision["transaction"], {
        "decision": mapped,
        "journal_generation": generation,
        "journal_sha256": digest,
        "revision_resolution_sha256": revision["artifact_sha256"],
        "pending_revision": pending["content_revision"] if pending else None,
        "active_transaction_id": active["logical_transaction_id"] if active else None,
    }, "admission-writer")


def record_build_ready(bundle_path: str | Path, admission_path: str | Path,
                       journal_path: str | Path, *, remote_writer: GitJournalWriter | None = None) -> dict:
    admission = _read(admission_path, "admission_receipt")
    bundle = _read(bundle_path, "build_bundle", _refs(admission))
    tx = bundle["transaction"]
    if (admission["transaction"] != tx or admission["payload"]["decision"] != "ADMITTED"
            or bundle["payload"]["admission_receipt_sha256"] != admission["artifact_sha256"]):
        raise ValueError("BUILD_READY requires the exact admitted bundle lineage")
    if remote_writer is None:
        journal = TransactionJournal.from_file(Path(journal_path), tx["worker"])
        before, generation, digest = journal.snapshot()
        active = before["active"]
        if not active or active["logical_transaction_id"] != tx["logical_transaction_id"]:
            raise ValueError("journal does not own BUILD_READY transaction")
        journal.record_build_ready(tx["logical_transaction_id"], bundle["artifact_sha256"],
                                   expected_generation=generation, expected_digest=digest)
        _after, new_generation, new_digest = journal.snapshot()
    else:
        if Path(journal_path).resolve() != _writer_journal_path(remote_writer).resolve():
            raise ValueError("journal path differs from durable remote writer")
        new_generation, new_digest = remote_writer.record_build_ready(
            tx["logical_transaction_id"], bundle["artifact_sha256"],
        )
    return {"status": "BUILD_READY", "transaction_id": tx["logical_transaction_id"],
            "build_bundle_sha256": bundle["artifact_sha256"],
            "generation": new_generation, "journal_sha256": new_digest}


def create_mutation_intent(operation: str, build_path: str | Path,
                           prerequisite_path: str | Path, desired_path: str | Path | None,
                           journal_path: str | Path, *, prerequisite_intent_path: str | Path | None = None,
                           reference_paths: list[str] | None = None,
                           promotion_intent_path: str | Path | None = None,
                           promotion_result_path: str | Path | None = None) -> dict:
    bundle = _read(build_path, "build_bundle")
    extra = _many(reference_paths)
    base_refs = _refs(bundle, *extra)
    prior_intent = (_read(prerequisite_intent_path, "mutation_intent", base_refs)
                    if prerequisite_intent_path else None)
    promotion_intent = (_read(promotion_intent_path, "mutation_intent", base_refs)
                        if promotion_intent_path else None)
    promotion_refs = _refs(*base_refs.values(), *([promotion_intent] if promotion_intent else []))
    promotion_result = (_read(promotion_result_path, refs=promotion_refs)
                        if promotion_result_path else None)
    supporting_refs = _refs(bundle, *([prior_intent] if prior_intent else []),
                            *extra, *([promotion_intent] if promotion_intent else []),
                            *([promotion_result] if promotion_result else []))
    prerequisite = _read(prerequisite_path, refs=supporting_refs)
    refs = _refs(*supporting_refs.values(), prerequisite)
    tx = bundle["transaction"]
    for parent in (prerequisite, prior_intent, *extra, promotion_intent, promotion_result):
        if parent and (parent["transaction"] != tx
                       or parent["producer"]["source_sha"] != bundle["producer"]["source_sha"]):
            raise ValueError("prerequisite transaction/source lineage mismatch")
    if desired_path is not None:
        desired = _json(desired_path)
    elif operation == "upload_version":
        desired = {"worker": tx["worker"], "build_bundle_sha256": bundle["artifact_sha256"]}
    elif operation == "deploy_zero_percent":
        reference = prerequisite.get("payload", {}).get("readback_reference")
        static_state = _json(Path(journal_path).with_name("published-static-state.json"))
        if (not isinstance(reference, Mapping) or reference.get("resource_type") != "version"
                or static_state.get("current_version_type") != "STATIC"):
            raise ValueError("zero-percent desired state lacks uploaded candidate or static baseline")
        desired = {"worker": tx["worker"], "candidate_version_id": reference["resource_id"],
                   "baseline_version_id": static_state["current_version"],
                   "expected_current_deployment_id": static_state["deployment_id"],
                   "candidate_percentage": 0, "baseline_percentage": 100}
    elif operation == "promote":
        identity = prerequisite.get("payload", {}).get("candidate_identity", {})
        desired = {"worker": tx["worker"],
                   "candidate_version_id": identity.get("candidate_version_id"),
                   "baseline_version_id": identity.get("baseline_version_id"),
                   "expected_current_deployment_id": identity.get("zero_percent_deployment_id"),
                   "candidate_percentage": 100, "baseline_percentage": 0}
    elif operation == "rollback":
        payload = prerequisite.get("payload", {})
        identity = payload.get("candidate_identity", {})
        promotion = payload.get("production_validation", {}).get("identity_confirmation", {})
        desired = {"worker": tx["worker"],
                   "failed_candidate_version_id": identity.get("candidate_version_id"),
                   "baseline_version_id": identity.get("baseline_version_id"),
                   "expected_current_deployment_id": promotion.get("promotion_deployment_id"),
                   "candidate_percentage": 0, "baseline_percentage": 100}
    else:
        raise ValueError("operation has no approved desired-state derivation")
    journal = TransactionJournal.from_file(Path(journal_path), tx["worker"])
    journal_value, generation, _digest = journal.snapshot()
    active = journal_value["active"]
    if not active or active["logical_transaction_id"] != tx["logical_transaction_id"]:
        raise ValueError("journal does not own the prerequisite transaction")
    attempt_id = str(uuid.uuid4())
    payload = {
        "operation_id": contracts.operation_id_for(tx["logical_transaction_id"], operation),
        "operation_name": operation,
        "attempt_id": attempt_id,
        "intent_state": "RECORDED",
        "build_bundle_sha256": bundle["artifact_sha256"],
        "prerequisite_artifact_sha256": prerequisite["artifact_sha256"],
        "journal_generation": generation + 1,
        "desired_state": desired,
    }
    intent = _envelope("mutation_intent", bundle, tx, payload, "intent-writer")
    intent = contracts.validate_artifact(intent, expected_transaction=tx,
                                         expected_source_sha=bundle["producer"]["source_sha"],
                                         referenced_artifacts=refs)
    # Reuse A3 prerequisite classification; producer and executor share one rule.
    from publisher import cloudflare_operation_adapter as operations
    operations._validate_prerequisite(intent, prerequisite, prior_intent, refs)
    if operation == "upload_version":
        admission = prerequisite
        if (admission["artifact_type"] != "admission_receipt"
                or admission["payload"]["decision"] != "ADMITTED"
                or bundle["payload"]["admission_receipt_sha256"] != admission["artifact_sha256"]):
            raise ValueError("upload requires the exact admitted build prerequisite")
    if operation == "rollback":
        if not promotion_intent or not promotion_result:
            raise ValueError("rollback requires promotion intent and applied result evidence")
        recovery.authorize_rollback(
            prerequisite, promotion_intent, promotion_result, intent,
            referenced_artifacts=refs,
        )
    return intent


def record_intent(journal_path: str | Path, intent_path: str | Path,
                  reference_paths: list[str] | None = None,
                  remote_writer: GitJournalWriter | None = None) -> dict:
    intent = _read(intent_path, "mutation_intent", _refs(*_many(reference_paths)))
    payload, tx = intent["payload"], intent["transaction"]
    if remote_writer is not None:
        if Path(journal_path).resolve() != _writer_journal_path(remote_writer).resolve():
            raise ValueError("journal path differs from durable remote writer")
        generation, digest, idempotent = remote_writer.record_intent(
            tx["logical_transaction_id"], payload["operation_name"], payload["attempt_id"],
            intent["artifact_sha256"], payload["journal_generation"],
        )
        return {"status": "INTENT_RECORDED", "operation_id": payload["operation_id"],
                "attempt_id": payload["attempt_id"], "generation": generation,
                "journal_sha256": digest, "idempotent": idempotent}
    journal = TransactionJournal.from_file(Path(journal_path), tx["worker"])
    before, generation, digest = journal.snapshot()
    if generation + 1 != payload["journal_generation"]:
        raise ValueError("journal generation changed after intent creation")
    operation_id, attempt_id = journal.record_intent(
        tx["logical_transaction_id"], payload["operation_name"],
        attempt_id=payload["attempt_id"], intent_artifact_sha256=intent["artifact_sha256"],
        expected_generation=generation,
        expected_digest=digest,
    )
    after, new_generation, _new_digest = journal.snapshot()
    active = after["active"]
    op = next(item for item in active["operations"].values() if item["operation_id"] == operation_id)
    if (active["logical_transaction_id"] != tx["logical_transaction_id"]
            or attempt_id != payload["attempt_id"]
            or new_generation != payload["journal_generation"]
            or op["attempts"][-1]["result_state"] != "NOT_REPORTED"):
        raise ValueError("journal did not durably record the exact sealed intent")
    return {"status": "INTENT_RECORDED", "operation_id": operation_id,
            "attempt_id": attempt_id, "generation": new_generation}


def _check_run_identity(intent: Mapping[str, Any]) -> None:
    producer = intent["producer"]
    run_id = os.environ.get("GITHUB_RUN_ID")
    run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT")
    if run_id is None or run_attempt is None:
        raise ValueError("operation execution requires the current workflow run identity")
    if (producer["workflow_run_id"] != run_id
            or producer["run_attempt"] != int(run_attempt)):
        raise ValueError("mutation intent belongs to another workflow run attempt")


def execute_operation(intent_path: str | Path, bundle_path: str | Path,
                      prerequisite_path: str | Path, journal_path: str | Path,
                      sealed_root: str | Path, config_path: str | Path, *,
                      backend: Any, prerequisite_intent_path: str | Path | None = None,
                      reference_paths: list[str] | None = None,
                      output_path: str | Path | None = None) -> dict:
    extra = _many(reference_paths)
    initial_refs = _refs(*extra)
    intent = _read(intent_path, "mutation_intent", initial_refs)
    bundle = _read(bundle_path, "build_bundle")
    prerequisite = _read(prerequisite_path, refs=initial_refs)
    prior = (_read(prerequisite_intent_path, "mutation_intent", initial_refs)
             if prerequisite_intent_path else None)
    refs = _refs(intent, bundle, prerequisite, *([prior] if prior else []), *extra)
    _check_run_identity(intent)
    tx, payload = intent["transaction"], intent["payload"]
    journal = TransactionJournal.from_file(Path(journal_path), tx["worker"])
    state, generation, _digest = journal.snapshot()
    if generation < payload["journal_generation"]:
        raise ValueError("journal has not durably recorded this mutation intent")
    active = state["active"]
    op = next((value for value in active["operations"].values()
               if value["operation_id"] == payload["operation_id"]), None) if active else None
    if (not op or active["logical_transaction_id"] != tx["logical_transaction_id"]
            or not op["attempts"] or op["attempts"][-1]["attempt_id"] != payload["attempt_id"]
            or op["attempts"][-1]["result_state"] != "NOT_REPORTED"):
        raise ValueError("journal does not authorize this exact pending operation attempt")
    from publisher import cloudflare_operation_adapter as operations
    result = operations.CloudflareOperationAdapter(backend).execute(
        intent, bundle, prerequisite, prerequisite_intent=prior,
        referenced_artifacts=refs,
    )
    result = contracts.validate_artifact(result, expected_transaction=tx,
                                         expected_source_sha=intent["producer"]["source_sha"])
    contracts.validate_intent_result_pair(intent, result, referenced_artifacts=refs)
    if output_path is not None:
        transport.write_artifact(output_path, result, expected_type="mutation_result",
                                 referenced_artifacts=refs)
    return result


def record_result(journal_path: str | Path, intent_path: str | Path,
                  result_path: str | Path, reference_paths: list[str] | None = None,
                  remote_writer: GitJournalWriter | None = None) -> dict:
    extras = _many(reference_paths)
    supporting_refs = _refs(*extras)
    intent = _read(intent_path, "mutation_intent", supporting_refs)
    result = _read(result_path, "mutation_result", supporting_refs)
    refs = _refs(*supporting_refs.values(), intent, result)
    contracts.validate_intent_result_pair(intent, result, referenced_artifacts=refs)
    ip, rp, tx = intent["payload"], result["payload"], intent["transaction"]
    journal = TransactionJournal.from_file(Path(journal_path), tx["worker"])
    before, generation, digest = journal.snapshot()
    active = before["active"]
    op = next((value for value in active["operations"].values()
               if value["operation_id"] == ip["operation_id"]), None) if active else None
    if (not op or active["logical_transaction_id"] != tx["logical_transaction_id"]
            or not op["attempts"] or op["attempts"][-1]["attempt_id"] != ip["attempt_id"]):
        raise ValueError("result does not match the durable latest journal intent")
    evidence = None
    if rp["evidence_sha256"]:
        evidence = {"type": "mutation_result_artifact", "reference": result["artifact_sha256"],
                    "sha256": rp["evidence_sha256"]}
    if remote_writer is not None:
        if Path(journal_path).resolve() != _writer_journal_path(remote_writer).resolve():
            raise ValueError("journal path differs from durable remote writer")
        new_generation, new_digest, idempotent = remote_writer.record_result(
            tx["logical_transaction_id"], ip["operation_id"], ip["attempt_id"],
            rp["result_state"], rp["evidence_sha256"], intent["artifact_sha256"],
            result["artifact_sha256"],
        )
        return {"status": rp["result_state"], "generation": new_generation,
                "journal_sha256": new_digest,
                "recovery_required": rp["result_state"] == "UNKNOWN", "idempotent": idempotent}
    journal.record_result(tx["logical_transaction_id"], ip["operation_id"], ip["attempt_id"],
                          rp["result_state"], evidence,
                          expected_generation=generation, expected_digest=digest)
    after, new_generation, _ = journal.snapshot()
    return {"status": rp["result_state"], "generation": new_generation,
            "recovery_required": bool(after["active"] and after["active"]["state"] == "recovery_required")}


def create_pre_promotion_proof(bundle_path: str | Path, deploy_intent_path: str | Path,
                               deploy_result_path: str | Path, remote_path: str | Path,
                               zero_origin_path: str | Path,
                               reference_paths: list[str] | None = None) -> dict:
    bundle = _read(bundle_path, "build_bundle")
    intent = _read(deploy_intent_path, "mutation_intent")
    result = _read(deploy_result_path)
    remote, zero = _json(remote_path), _json(zero_origin_path)
    extras = _many(reference_paths)
    refs = _refs(bundle, intent, result, *extras)
    tx = bundle["transaction"]
    applied = effective_result.validate_effective_applied_result(
        result, intent, referenced_artifacts=refs,
    )
    remote_names = {"crawler_evidence_sha256", "browser_evidence_sha256", "gates", "PASS"}
    if set(remote) != remote_names:
        raise ValueError("remote evidence must match the frozen gate contract exactly")
    deployment_id = applied["payload"]["readback_reference"]["resource_id"]
    desired = intent["payload"]["desired_state"]
    payload = {
        "build_bundle_artifact_sha256": bundle["artifact_sha256"],
        "deploy_zero_percent_result_artifact_sha256": result["artifact_sha256"],
        "candidate_identity": {
            "worker": tx["worker"],
            "candidate_version_id": desired["candidate_version_id"],
            "baseline_version_id": desired["baseline_version_id"],
            "zero_percent_deployment_id": deployment_id,
            "content_fingerprint": bundle["payload"]["content_fingerprint"],
        },
        "remote": remote,
        "zero_origin_validation": zero,
        "PASS": remote["PASS"] is True and zero.get("PASS") is True,
    }
    proof = _envelope("pre_promotion_proof_evidence", bundle, tx, payload,
                      "pre-promotion-remote-proof")
    return contracts.validate_artifact(proof, expected_transaction=tx,
                                       expected_source_sha=bundle["producer"]["source_sha"],
                                       referenced_artifacts=refs)


def create_proof_evidence(payload_path: str | Path, bundle_path: str | Path,
                          result_paths: Mapping[str, str | Path],
                          reference_paths: list[str] | None = None) -> dict:
    bundle = _read(bundle_path, "build_bundle")
    payload = _json(payload_path)
    extra = _many(reference_paths)
    refs = _refs(bundle, *extra)
    results = {name: _read(path, refs=refs) for name, path in result_paths.items()}
    refs = _refs(*refs.values(), *results.values())
    proof = _envelope("proof_evidence", bundle, bundle["transaction"], payload,
                      "production-proof-recovery")
    return recovery.validate_proof(proof, bundle, results, referenced_artifacts=refs)


def create_recovery_readback(intent_path: str | Path, result_path: str | Path,
                             reference_paths: list[str] | None = None, *,
                             backend=None, output_path: str | Path | None = None) -> dict:
    extras = _many(reference_paths)
    refs = _refs(*extras)
    intent = _read(intent_path, "mutation_intent", refs)
    result = _read(result_path, "mutation_result", refs)
    refs = _refs(*refs.values(), intent, result)
    collector = backend or recovery_readback.WranglerReadOnlyBackend()
    value = recovery_readback.collect_fresh_readback(
        intent, result, references=refs, backend=collector,
    )
    if output_path is not None:
        recovery_readback.write_evidence(
            output_path, value, intent=intent, result=result, references=refs,
        )
    return value


def make_recovery_decision(intent_path: str | Path, result_path: str | Path,
                           readback_path: str | Path, journal_path: str | Path,
                           reference_paths: list[str] | None = None) -> dict:
    extras = _many(reference_paths)
    refs = _refs(*extras)
    intent = _read(intent_path, "mutation_intent", refs)
    result = _read(result_path, "mutation_result", refs)
    refs = _refs(*refs.values(), intent, result)
    readback = recovery_readback.read_evidence(
        readback_path, intent=intent, result=result, references=refs,
    )
    journal = TransactionJournal.from_file(Path(journal_path), intent["transaction"]["worker"])
    state, generation, _ = journal.snapshot()
    active = state["active"]
    if (not active or active["logical_transaction_id"] != intent["transaction"]["logical_transaction_id"]
            or active["state"] != "recovery_required"):
        raise ValueError("journal is not in recovery_required for this transaction")
    operation = active["operations"].get(intent["payload"]["operation_name"])
    if (not operation or not operation["attempts"]
            or operation["attempts"][-1]["attempt_id"] != intent["payload"]["attempt_id"]
            or operation["attempts"][-1]["result_state"] != "UNKNOWN"
            or result["payload"]["result_state"] != "UNKNOWN"):
        raise ValueError("recovery artifacts do not match the journal's latest unknown attempt")
    return recovery.recovery_decision(intent, result, readback["readback"], generation,
                                      referenced_artifacts=refs)


def create_recovered_result(intent_path: str | Path, result_path: str | Path,
                            readback_path: str | Path, decision_path: str | Path,
                            repository: str | Path, remote: str, branch: str,
                            reference_paths: list[str] | None = None) -> dict:
    extras = _many(reference_paths)
    refs = _refs(*extras)
    intent = _read(intent_path, "mutation_intent", refs)
    original = _read(result_path, "mutation_result", refs)
    refs = _refs(*refs.values(), intent, original)
    decision = _read(decision_path, "recovery_decision", refs)
    readback = recovery_readback.read_evidence(
        readback_path, intent=intent, result=original, references=refs,
    )
    writer = _writer(repository, intent["transaction"]["worker"], remote, branch)
    return effective_result.create_recovered_mutation_result(
        intent=intent, original_result=original, recovery_evidence=readback,
        recovery_decision=decision, journal_writer=writer,
        referenced_artifacts=refs,
    )


def authorize_rollback(proof_path: str | Path, promote_intent_path: str | Path,
                       promote_result_path: str | Path, rollback_intent_path: str | Path,
                       reference_paths: list[str] | None = None) -> dict:
    extra = _many(reference_paths)
    supporting_refs = _refs(*extra)
    proof = _read(proof_path, "proof_evidence", supporting_refs)
    promote = _read(promote_intent_path, "mutation_intent", supporting_refs)
    promoted = _read(promote_result_path, refs=supporting_refs)
    refs = _refs(*supporting_refs.values(), proof, promote, promoted)
    rollback = _read(rollback_intent_path, "mutation_intent", refs)
    refs = _refs(*refs.values(), rollback)
    return recovery.authorize_rollback(proof, promote, promoted, rollback,
                                       referenced_artifacts=refs)


def validate_final_persistence(proof_path: str | Path, bundle_path: str | Path,
                               result_paths: Mapping[str, str | Path], state_dir: str | Path,
                               journal_path: str | Path,
                               reference_paths: list[str] | None = None) -> dict:
    refs = _refs(*_many(reference_paths))
    proof = _read(proof_path, "proof_evidence", refs)
    bundle = _read(bundle_path, "build_bundle", refs)
    results = {name: _read(path, refs=refs) for name, path in result_paths.items()}
    refs = _refs(*refs.values(), proof, bundle, *results.values())
    root = Path(state_dir).resolve()
    files = {}
    for relative in contracts.STATE_FILE_PATHS:
        candidate = root.joinpath(*relative.split("/"))
        if candidate.is_symlink() or not candidate.resolve().is_relative_to(root) or not candidate.is_file():
            raise ValueError("allowlisted persistence state file is missing or unsafe")
        files[relative] = candidate.read_bytes()
    journal = TransactionJournal.from_file(Path(journal_path), bundle["transaction"]["worker"])
    state, generation, digest = journal.snapshot()
    active = state["active"]
    if (not active or active["logical_transaction_id"] != bundle["transaction"]["logical_transaction_id"]
            or active["state"] != "ready_to_persist"
            or active["proof_evidence_sha256"] != proof["artifact_sha256"]):
        raise ValueError("journal READY_TO_PERSIST state does not match proof transaction")
    persistence.validate_finalization_inputs(proof, bundle, results, files, generation,
                                             referenced_artifacts=refs)
    return {"status": "FINAL_PERSISTENCE_INPUTS_VALID", "transaction_id": active["logical_transaction_id"],
            "journal_generation": generation, "journal_digest": digest}


def execute_production_proof(*, build_path: str | Path, upload_intent_path: str | Path,
                             upload_result_path: str | Path, deploy_intent_path: str | Path,
                             deploy_result_path: str | Path, preproof_path: str | Path,
                             promote_intent_path: str | Path, promote_result_path: str | Path,
                             observations_path: str | Path, output_path: str | Path,
                             reference_paths: list[str] | None = None) -> dict:
    raw = _many([build_path, upload_intent_path, upload_result_path, deploy_intent_path,
                 deploy_result_path, preproof_path, promote_intent_path, promote_result_path])
    refs = _refs(*raw, *_many(reference_paths))
    paths = [build_path, upload_intent_path, upload_result_path, deploy_intent_path,
             deploy_result_path, preproof_path, promote_intent_path, promote_result_path]
    types = ["build_bundle", "mutation_intent", None, "mutation_intent",
             None, "pre_promotion_proof_evidence", "mutation_intent", None]
    artifacts = {name: _read(path, kind, refs) for name, path, kind in zip(
        ("build", "upload_intent", "upload_result", "deploy_intent", "deploy_result",
         "preproof", "promote_intent", "promote_result"), paths, types,
    )}
    value = production_proof.create_production_proof(
        build_bundle=artifacts["build"], upload_intent=artifacts["upload_intent"],
        upload_result=artifacts["upload_result"], deploy_intent=artifacts["deploy_intent"],
        deploy_result=artifacts["deploy_result"], pre_promotion_proof=artifacts["preproof"],
        promote_intent=artifacts["promote_intent"], promote_result=artifacts["promote_result"],
        backend=production_proof.ObservationFileBackend(observations_path),
        producer=_producer(artifacts["build"], "production-proof"),
        referenced_artifacts=refs,
    )
    transport.write_artifact(output_path, value, expected_type="proof_evidence",
                             referenced_artifacts=refs)
    return {"status": value["payload"]["proof_state"],
            "artifact_sha256": value["artifact_sha256"]}


def execute_observed_pre_promotion_proof(*, build_path: str | Path,
                                         deploy_intent_path: str | Path,
                                         deploy_result_path: str | Path,
                                         sealed_root: str | Path, snapshot_path: str | Path,
                                         route_manifest_path: str | Path,
                                         media_manifest_path: str | Path,
                                         base_url: str, evidence_dir: str | Path,
                                         output_path: str | Path,
                                         reference_paths: list[str] | None = None,
                                         backend=None) -> dict:
    from publisher import proof_observation_runner as observation
    collector = backend or observation.RuntimeObservationBackend(
        stage="pre-promotion", base_url=base_url, evidence_root=evidence_dir,
        sealed_root=sealed_root, snapshot=snapshot_path, routes=route_manifest_path,
        media=media_manifest_path,
    )
    return observation.execute_pre_promotion_observation(
        build_path=build_path, deploy_intent_path=deploy_intent_path,
        deploy_result_path=deploy_result_path, sealed_root=sealed_root,
        snapshot_path=snapshot_path, route_manifest_path=route_manifest_path,
        media_manifest_path=media_manifest_path, evidence_dir=evidence_dir,
        output_path=output_path, backend=collector, reference_paths=reference_paths,
    )


def execute_observed_production_proof(*, artifact_paths: Mapping[str, str | Path],
                                      sealed_root: str | Path, snapshot_path: str | Path,
                                      route_manifest_path: str | Path,
                                      media_manifest_path: str | Path,
                                      local_gates_path: str | Path, base_url: str,
                                      evidence_dir: str | Path, output_path: str | Path,
                                      backend=None,
                                      reference_paths: list[str | Path] | None = None) -> dict:
    from publisher import proof_observation_runner as observation
    collector = backend or observation.RuntimeObservationBackend(
        stage="production", base_url=base_url, evidence_root=evidence_dir,
        sealed_root=sealed_root, snapshot=snapshot_path, routes=route_manifest_path,
        media=media_manifest_path, local_gates=local_gates_path,
    )
    return observation.execute_production_observation(
        artifact_paths=artifact_paths, sealed_root=sealed_root,
        snapshot_path=snapshot_path, route_manifest_path=route_manifest_path,
        media_manifest_path=media_manifest_path, local_gates_path=local_gates_path,
        evidence_dir=evidence_dir, output_path=output_path, backend=collector,
        reference_paths=reference_paths,
    )


def execute_final_persistence(*, proof_path: str | Path, build_path: str | Path,
                              upload_result_path: str | Path,
                              deploy_result_path: str | Path, promote_result_path: str | Path,
                              repository: str | Path, state_dir: str | Path,
                              journal_path: str | Path, remote: str, branch: str,
                              output_path: str | Path,
                              reference_paths: list[str] | None = None) -> dict:
    refs = _refs(*_many(reference_paths))
    proof = _read(proof_path, "proof_evidence", refs)
    bundle = _read(build_path, "build_bundle", refs)
    results = {
        "upload_version": _read(upload_result_path, refs=refs),
        "deploy_zero_percent": _read(deploy_result_path, refs=refs),
        "promote": _read(promote_result_path, refs=refs),
    }
    refs = _refs(*refs.values(), proof, bundle, *results.values())
    root = Path(repository).resolve()
    raw_state_root = Path(state_dir)
    if raw_state_root.is_symlink():
        raise ValueError("state staging directory symlink is forbidden")
    state_root = raw_state_root.resolve()
    if not state_root.is_dir() or state_root == root or state_root.is_relative_to(root):
        raise ValueError("state input must be a separate staging directory")
    actual_files = set()
    for item in state_root.rglob("*"):
        if item.is_symlink():
            raise ValueError("symlinks are forbidden in state staging input")
        if item.is_file():
            actual_files.add(item.relative_to(state_root).as_posix())
    if actual_files != set(contracts.STATE_FILE_PATHS):
        raise ValueError("state staging input must contain exactly the six allowlisted files")
    state_files: dict[str, bytes] = {}
    for relative in contracts.STATE_FILE_PATHS:
        candidate = state_root.joinpath(*relative.split("/"))
        if candidate.is_symlink() or not candidate.resolve().is_relative_to(state_root) or not candidate.is_file():
            raise ValueError("allowlisted persistence state file is missing or unsafe")
        state_files[relative] = candidate.read_bytes()
    journal_file = Path(journal_path)
    if not journal_file.is_absolute():
        journal_file = root / journal_file
    journal_file = journal_file.resolve()
    journal_rel = journal_file.relative_to(root).as_posix()
    journal = TransactionJournal.from_file(journal_file, bundle["transaction"]["worker"])
    _state, generation, _digest = journal.snapshot()
    repository_writer = GitRepositoryWriter(root, remote=remote, branch=branch)
    journal_writer = GitJournalWriter(root, bundle["transaction"]["worker"],
                                      remote=remote, branch=branch,
                                      journal_path=journal_rel)
    artifact = persistence.finalize(
        proof, bundle, results, state_files, generation, journal_writer, repository_writer,
        referenced_artifacts=refs,
    )
    transport.write_artifact(output_path, artifact, expected_type="final_persistence_payload")
    return {"status": "COMPLETED", "artifact_sha256": artifact["artifact_sha256"],
            "state_commit_sha": artifact["payload"]["state_commit_sha"]}


def _staged_state_files(root: Path) -> dict[str, bytes]:
    files = {}
    directories = set()
    for current, dirs, names in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in dirs:
            child = current_path / name
            if child.is_symlink():
                raise ValueError("state staging symlinks are forbidden")
            directories.add(child.relative_to(root).as_posix())
        for name in names:
            child = current_path / name
            if child.is_symlink() or not child.is_file():
                raise ValueError("state staging contains an unsafe entry")
            files[child.relative_to(root).as_posix()] = child.read_bytes()
    if directories != {"publisher-state"} or set(files) != set(contracts.STATE_FILE_PATHS):
        raise ValueError("state staging must contain exactly the six publisher-state files")
    return files


def _stage_materialized_state(files: Mapping[str, bytes], transaction_id: str) -> Path:
    if (set(files) != set(contracts.STATE_FILE_PATHS)
            or any(not isinstance(data, bytes) for data in files.values())
            or len(transaction_id) != 64
            or any(char not in "0123456789abcdef" for char in transaction_id)):
        raise ValueError("exact-six state bytes and a transaction ID are required")
    raw_temp = Path(os.environ.get("RUNNER_TEMP", ""))
    if not raw_temp.is_absolute() or raw_temp.is_symlink() or not raw_temp.is_dir():
        raise ValueError("RUNNER_TEMP must be an existing non-symlink directory")
    temp_root = raw_temp.resolve(strict=True)
    repository = Path(__file__).resolve().parents[2]
    if temp_root == repository or temp_root.is_relative_to(repository):
        raise ValueError("state staging must remain outside the repository")
    base = temp_root / "mahoon-final-state"
    if base.is_symlink():
        raise ValueError("state staging root symlink is forbidden")
    base.mkdir(exist_ok=True)
    base = base.resolve(strict=True)
    if not base.is_relative_to(temp_root) or base.is_relative_to(repository):
        raise ValueError("state staging root escaped its controlled temp directory")
    target = base / transaction_id
    if target.is_symlink():
        raise ValueError("state staging destination symlink is forbidden")
    if target.exists():
        if _staged_state_files(target) != dict(files):
            raise ValueError("existing state staging destination conflicts")
        return target

    staging = Path(tempfile.mkdtemp(prefix=f".{transaction_id}.", dir=base))
    try:
        for relative, data in files.items():
            destination = staging.joinpath(*relative.split("/"))
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        if _staged_state_files(staging) != dict(files):
            raise ValueError("staged state bytes failed exact-six readback")
        os.rename(staging, target)
        return target
    except OSError:
        if target.exists() and not target.is_symlink() and _staged_state_files(target) == dict(files):
            return target
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def materialize_final_state(*, proof_path: str | Path, build_path: str | Path,
                            operation_intent_paths: Mapping[str, str | Path],
                            operation_result_paths: Mapping[str, str | Path],
                            sealed_root: str | Path, seal_path: str | Path,
                            snapshot_path: str | Path, media_manifest_path: str | Path,
                            route_manifest_path: str | Path,
                            reference_paths: list[str] | None = None) -> dict:
    support = _many(reference_paths)
    refs = _refs(*support)
    proof = _read(proof_path, "proof_evidence", refs)
    bundle = _read(build_path, "build_bundle", refs)
    intents = {name: _read(path, "mutation_intent", refs)
               for name, path in operation_intent_paths.items()}
    results = {name: _read(path, refs=refs)
               for name, path in operation_result_paths.items()}
    refs = _refs(*support, proof, bundle, *intents.values(), *results.values())
    files = materializer.materialize_final_state(
        proof=proof, build_bundle=bundle, operation_intents=intents,
        operation_results=results, snapshot_bytes=Path(snapshot_path).read_bytes(),
        media_manifest_bytes=Path(media_manifest_path).read_bytes(),
        route_manifest_bytes=Path(route_manifest_path).read_bytes(),
        sealed_root=sealed_root, artifact_seal=_json(seal_path),
        referenced_artifacts=refs,
    )
    output = _stage_materialized_state(files, proof["transaction"]["logical_transaction_id"])
    return {"status": "FINAL_STATE_MATERIALIZED", "transaction_id": proof["transaction"]["logical_transaction_id"],
            "state_dir": str(output), "file_count": len(files)}




def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate-artifact")
    validate.add_argument("--input", required=True); validate.add_argument("--type")
    validate.add_argument("--reference", action="append", default=[])

    resolve = commands.add_parser("resolve-revision")
    resolve.add_argument("--published-state", default="publisher-state/published-static-state.json")
    resolve.add_argument("--output", required=True)

    bootstrap = commands.add_parser("bootstrap-journal")
    bootstrap.add_argument("--repository", required=True)
    bootstrap.add_argument("--worker", default=DEFAULT_WORKER)
    bootstrap.add_argument("--remote", default="origin")
    bootstrap.add_argument("--branch", default="main")

    admit = commands.add_parser("admit")
    admit.add_argument("--revision", required=True)
    admit.add_argument("--repository", required=True)
    admit.add_argument("--source", required=True)
    admit.add_argument("--run-id", default="")
    admit.add_argument("--trigger-attempt", default="")
    admit.add_argument("--remote", default="origin")
    admit.add_argument("--branch", default="main")
    admit.add_argument("--output", required=True)

    build_ready = commands.add_parser("record-build-ready")
    build_ready.add_argument("--build-bundle", required=True)
    build_ready.add_argument("--admission", required=True)
    build_ready.add_argument("--journal", required=True)
    build_ready.add_argument("--repository", required=True)
    build_ready.add_argument("--remote", default="origin")
    build_ready.add_argument("--branch", default="main")

    admission = commands.add_parser("create-admission-receipt")
    admission.add_argument("--revision", required=True); admission.add_argument("--journal", required=True)
    admission.add_argument("--source", required=True); admission.add_argument("--run-id", default="")
    admission.add_argument("--trigger-attempt", default=""); admission.add_argument("--output", required=True)

    for name in ("create-mutation-intent", "create-promote-intent"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--operation", choices=contracts.OPERATION_NAMES,
                         required=(name == "create-mutation-intent"))
        cmd.add_argument("--build-bundle", required=True); cmd.add_argument("--prerequisite", required=True)
        cmd.add_argument("--desired-state"); cmd.add_argument("--journal", required=True)
        cmd.add_argument("--prerequisite-intent"); cmd.add_argument("--promotion-intent")
        cmd.add_argument("--promotion-result"); cmd.add_argument("--reference", action="append", default=[])
        cmd.add_argument("--output", required=True)

    record = commands.add_parser("record-intent")
    record.add_argument("--journal", required=True); record.add_argument("--intent", required=True)
    record.add_argument("--reference", action="append", default=[])
    record.add_argument("--repository")
    record.add_argument("--remote", default="origin")
    record.add_argument("--branch", default="main")

    execute = commands.add_parser("execute-operation")
    execute.add_argument("--intent", required=True); execute.add_argument("--build-bundle", required=True)
    execute.add_argument("--prerequisite", required=True); execute.add_argument("--journal", required=True)
    execute.add_argument("--sealed-root", required=True); execute.add_argument("--config", required=True)
    execute.add_argument("--backend", choices=("wrangler",), required=True)
    execute.add_argument("--prerequisite-intent"); execute.add_argument("--reference", action="append", default=[])
    execute.add_argument("--output", required=True)

    result = commands.add_parser("record-result")
    result.add_argument("--journal", required=True); result.add_argument("--intent", required=True)
    result.add_argument("--result", required=True); result.add_argument("--reference", action="append", default=[])
    result.add_argument("--repository")
    result.add_argument("--remote", default="origin")
    result.add_argument("--branch", default="main")

    pre = commands.add_parser("create-pre-promotion-proof")
    pre.add_argument("--build-bundle", required=True); pre.add_argument("--deploy-intent", required=True)
    pre.add_argument("--deploy-result", required=True); pre.add_argument("--remote", required=True)
    pre.add_argument("--zero-origin", required=True); pre.add_argument("--reference", action="append", default=[])
    pre.add_argument("--output", required=True)

    observe_pre = commands.add_parser("pre-promotion-proof-observe")
    for arg in ("build-bundle", "deploy-intent", "deploy-result", "sealed-root",
                "snapshot", "route-manifest", "media-manifest", "base-url",
                "evidence-dir", "output"):
        observe_pre.add_argument("--" + arg, required=True)
    observe_pre.add_argument("--reference", action="append", default=[])

    observe_prod = commands.add_parser("production-proof-observe")
    for arg in ("build-bundle", "upload-intent", "upload-result", "deploy-intent",
                "deploy-result", "pre-promotion-proof", "promote-intent", "promote-result",
                "sealed-root", "snapshot", "route-manifest", "media-manifest",
                "local-gates", "base-url", "evidence-dir", "output"):
        observe_prod.add_argument("--" + arg, required=True)
    observe_prod.add_argument("--reference", action="append", default=[])

    proof = commands.add_parser("production-proof")
    for arg in ("build-bundle", "upload-intent", "upload-result", "deploy-intent",
                "deploy-result", "pre-promotion-proof", "promote-intent", "promote-result",
                "observations", "output"):
        proof.add_argument("--" + arg, required=True)
    proof.add_argument("--reference", action="append", default=[])

    recovery_cmd = commands.add_parser("proof-recovery")
    recovery_sub = recovery_cmd.add_subparsers(dest="action", required=True)
    create_proof = recovery_sub.add_parser("create-proof-evidence")
    create_proof.add_argument("--payload", required=True); create_proof.add_argument("--build-bundle", required=True)
    for op in ("upload_version", "deploy_zero_percent", "promote"):
        create_proof.add_argument("--" + op.replace("_", "-"), required=True)
    create_proof.add_argument("--output", required=True)
    create_proof.add_argument("--reference", action="append", default=[])
    decision = recovery_sub.add_parser("recovery-decision")
    decision.add_argument("--intent", required=True); decision.add_argument("--result", required=True)
    decision.add_argument("--readback", required=True); decision.add_argument("--journal", required=True)
    decision.add_argument("--reference", action="append", default=[])
    decision.add_argument("--output", required=True)
    observe_recovery = recovery_sub.add_parser("recovery-readback-observe")
    observe_recovery.add_argument("--intent", required=True)
    observe_recovery.add_argument("--result", required=True)
    observe_recovery.add_argument("--reference", action="append", default=[])
    observe_recovery.add_argument("--output", required=True)
    rollback = recovery_sub.add_parser("authorize-rollback")
    rollback.add_argument("--proof", required=True); rollback.add_argument("--promote-intent", required=True)
    rollback.add_argument("--promote-result", required=True); rollback.add_argument("--rollback-intent", required=True)
    rollback.add_argument("--reference", action="append", default=[])

    reconcile = commands.add_parser("reconcile-recovery-decision")
    reconcile.add_argument("--decision", required=True)
    reconcile.add_argument("--repository", required=True)
    reconcile.add_argument("--remote", default="origin")
    reconcile.add_argument("--branch", default="main")

    recovered = commands.add_parser("create-recovered-result")
    recovered.add_argument("--intent", required=True)
    recovered.add_argument("--result", required=True)
    recovered.add_argument("--readback", required=True)
    recovered.add_argument("--decision", required=True)
    recovered.add_argument("--repository", required=True)
    recovered.add_argument("--remote", default="origin")
    recovered.add_argument("--branch", default="main")
    recovered.add_argument("--reference", action="append", default=[])
    recovered.add_argument("--output", required=True)

    final = commands.add_parser("final-persistence-validate")
    final.add_argument("--proof", required=True); final.add_argument("--build-bundle", required=True)
    final.add_argument("--state-dir", required=True); final.add_argument("--journal", required=True)
    final.add_argument("--reference", action="append", default=[])
    for op in ("upload_version", "deploy_zero_percent", "promote"):
        final.add_argument("--" + op.replace("_", "-"), required=True)

    execute_final = commands.add_parser("final-persistence-execute")
    for arg in ("proof", "build-bundle", "upload-result", "deploy-result", "promote-result",
                "repository", "state-dir", "journal", "remote", "branch", "output"):
        execute_final.add_argument("--" + arg, required=True)
    execute_final.add_argument("--reference", action="append", default=[])

    materialize = commands.add_parser("materialize-final-state")
    for arg in ("proof", "build-bundle", "sealed-root", "artifact-seal", "snapshot",
                "media-manifest", "route-manifest"):
        materialize.add_argument("--" + arg, required=True)
    for operation in ("upload-version", "deploy-zero-percent", "promote"):
        materialize.add_argument("--" + operation + "-intent", required=True)
        materialize.add_argument("--" + operation + "-result", required=True)
    materialize.add_argument("--reference", action="append", default=[])

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "bootstrap-journal":
            output = _writer(args.repository, args.worker, args.remote, args.branch).bootstrap()
        elif args.command == "validate-artifact":
            value = validate_artifact_file(args.input, args.type, args.reference)
            output = {"status": "VALID", "artifact_type": value["artifact_type"],
                      "artifact_sha256": value["artifact_sha256"]}
        elif args.command == "resolve-revision":
            value = create_revision_resolution(args.published_state)
            transport.write_artifact(args.output, value, expected_type="revision_resolution")
            output = {"status": value["payload"]["decision"],
                      "artifact_sha256": value["artifact_sha256"]}
        elif args.command == "admit":
            revision = _read(args.revision, "revision_resolution")
            worker = revision["transaction"]["worker"]
            writer = _writer(args.repository, worker, args.remote, args.branch)
            value = create_admission_receipt(
                args.revision, _writer_journal_path(writer), args.source,
                args.run_id, args.trigger_attempt, remote_writer=writer,
            )
            transport.write_artifact(args.output, value, expected_type="admission_receipt")
            output = {"status": value["payload"]["decision"],
                      "artifact_sha256": value["artifact_sha256"],
                      "journal_generation": value["payload"]["journal_generation"],
                      "journal_sha256": value["payload"]["journal_sha256"]}
        elif args.command == "record-build-ready":
            bundle = _read(args.build_bundle, "build_bundle")
            writer = _writer(args.repository, bundle["transaction"]["worker"], args.remote, args.branch)
            output = record_build_ready(args.build_bundle, args.admission,
                                        args.journal, remote_writer=writer)
        elif args.command == "create-admission-receipt":
            value = create_admission_receipt(args.revision, args.journal, args.source,
                                             args.run_id, args.trigger_attempt)
            transport.write_artifact(args.output, value, expected_type="admission_receipt")
            output = {"status": value["payload"]["decision"], "artifact_sha256": value["artifact_sha256"]}
        elif args.command in {"create-mutation-intent", "create-promote-intent"}:
            op = "promote" if args.command == "create-promote-intent" else args.operation
            value = create_mutation_intent(
                op, args.build_bundle, args.prerequisite, args.desired_state, args.journal,
                prerequisite_intent_path=args.prerequisite_intent,
                reference_paths=args.reference, promotion_intent_path=args.promotion_intent,
                promotion_result_path=args.promotion_result,
            )
            transport.write_artifact(args.output, value, expected_type="mutation_intent")
            output = {"status": "SEALED_INTENT", "operation_id": value["payload"]["operation_id"],
                      "attempt_id": value["payload"]["attempt_id"],
                      "artifact_sha256": value["artifact_sha256"]}
        elif args.command == "record-intent":
            writer = None
            if args.repository:
                intent = _read(args.intent, "mutation_intent", _refs(*_many(args.reference)))
                writer = _writer(args.repository, intent["transaction"]["worker"],
                                 args.remote, args.branch)
            output = record_intent(args.journal, args.intent, args.reference, writer)
        elif args.command == "execute-operation":
            if not os.environ.get("GITHUB_RUN_ID"):
                raise ValueError("execute-operation requires a workflow execution identity")
            from publisher import cloudflare_operation_adapter as operations
            backend = operations.WranglerOperationBackend(args.sealed_root, args.config)
            value = execute_operation(
                args.intent, args.build_bundle, args.prerequisite, args.journal,
                args.sealed_root, args.config, backend=backend,
                prerequisite_intent_path=args.prerequisite_intent,
                reference_paths=args.reference,
            )
            transport.write_artifact(args.output, value, expected_type="mutation_result")
            output = {"status": value["payload"]["result_state"],
                      "artifact_sha256": value["artifact_sha256"]}
        elif args.command == "record-result":
            writer = None
            if args.repository:
                intent = _read(args.intent, "mutation_intent", _refs(*_many(args.reference)))
                writer = _writer(args.repository, intent["transaction"]["worker"],
                                 args.remote, args.branch)
            output = record_result(args.journal, args.intent, args.result, args.reference, writer)
        elif args.command == "create-pre-promotion-proof":
            value = create_pre_promotion_proof(
                args.build_bundle, args.deploy_intent, args.deploy_result,
                args.remote, args.zero_origin, args.reference,
            )
            transport.write_artifact(args.output, value,
                                     expected_type="pre_promotion_proof_evidence")
            output = {"status": "PASS" if value["payload"]["PASS"] else "FAIL",
                      "artifact_sha256": value["artifact_sha256"]}
        elif args.command == "pre-promotion-proof-observe":
            output = execute_observed_pre_promotion_proof(
                build_path=args.build_bundle, deploy_intent_path=args.deploy_intent,
                deploy_result_path=args.deploy_result, sealed_root=args.sealed_root,
                snapshot_path=args.snapshot, route_manifest_path=args.route_manifest,
                media_manifest_path=args.media_manifest, base_url=args.base_url,
                evidence_dir=args.evidence_dir, output_path=args.output,
                reference_paths=args.reference,
            )
        elif args.command == "production-proof":
            output = execute_production_proof(
                build_path=args.build_bundle, upload_intent_path=args.upload_intent,
                upload_result_path=args.upload_result, deploy_intent_path=args.deploy_intent,
                deploy_result_path=args.deploy_result, preproof_path=args.pre_promotion_proof,
                promote_intent_path=args.promote_intent, promote_result_path=args.promote_result,
                observations_path=args.observations, output_path=args.output,
                reference_paths=args.reference,
            )
        elif args.command == "production-proof-observe":
            artifact_paths = {
                "build": args.build_bundle, "upload_intent": args.upload_intent,
                "upload_result": args.upload_result, "deploy_intent": args.deploy_intent,
                "deploy_result": args.deploy_result, "preproof": args.pre_promotion_proof,
                "promote_intent": args.promote_intent, "promote_result": args.promote_result,
            }
            output = execute_observed_production_proof(
                artifact_paths=artifact_paths, sealed_root=args.sealed_root,
                snapshot_path=args.snapshot, route_manifest_path=args.route_manifest,
                media_manifest_path=args.media_manifest, local_gates_path=args.local_gates,
                base_url=args.base_url, evidence_dir=args.evidence_dir, output_path=args.output,
                reference_paths=args.reference,
            )
        elif args.command == "proof-recovery":
            if args.action == "create-proof-evidence":
                paths = {name: getattr(args, name.replace("-", "_")) for name in (
                    "upload_version", "deploy_zero_percent", "promote")}
                value = create_proof_evidence(args.payload, args.build_bundle, paths, args.reference)
                transport.write_artifact(args.output, value, expected_type="proof_evidence")
                output = {"status": value["payload"]["proof_state"],
                          "artifact_sha256": value["artifact_sha256"]}
            elif args.action == "recovery-readback-observe":
                value = create_recovery_readback(
                    args.intent, args.result, args.reference, output_path=args.output,
                )
                output = {"status": "FRESH_READBACK_OBSERVED",
                          "operation_name": value["operation_name"],
                          "readback_sha256": value["readback_sha256"],
                          "evidence_sha256": value["evidence_sha256"]}
            elif args.action == "recovery-decision":
                value = make_recovery_decision(args.intent, args.result, args.readback,
                                               args.journal, args.reference)
                transport.write_artifact(args.output, value, expected_type="recovery_decision")
                output = {"status": value["payload"]["decision"],
                          "artifact_sha256": value["artifact_sha256"]}
            else:
                value = authorize_rollback(args.proof, args.promote_intent, args.promote_result,
                                           args.rollback_intent, args.reference)
                output = {"status": "ROLLBACK_AUTHORIZED",
                          "attempt_id": value["payload"]["attempt_id"]}
        elif args.command == "reconcile-recovery-decision":
            decision = _read(args.decision, "recovery_decision")
            writer = _writer(args.repository, decision["transaction"]["worker"],
                             args.remote, args.branch)
            output = writer.reconcile_recovery_decision(decision)
        elif args.command == "create-recovered-result":
            value = create_recovered_result(
                args.intent, args.result, args.readback, args.decision,
                args.repository, args.remote, args.branch, args.reference,
            )
            support = _many(args.reference)
            refs = _refs(*support)
            intent = _read(args.intent, "mutation_intent", refs)
            original = _read(args.result, "mutation_result", refs)
            decision = _read(args.decision, "recovery_decision", refs)
            refs = _refs(*refs.values(), intent, original, decision)
            transport.write_artifact(
                args.output, value, expected_type="recovered_mutation_result",
                referenced_artifacts=refs,
            )
            output = {"status": "RECONCILED_APPLIED", "artifact_sha256": value["artifact_sha256"]}
        elif args.command == "final-persistence-validate":
            results = {name: getattr(args, name) for name in (
                "upload_version", "deploy_zero_percent", "promote")}
            output = validate_final_persistence(args.proof, args.build_bundle, results,
                                                args.state_dir, args.journal, args.reference)
        elif args.command == "final-persistence-execute":
            output = execute_final_persistence(
                proof_path=args.proof, build_path=args.build_bundle,
                upload_result_path=args.upload_result, deploy_result_path=args.deploy_result,
                promote_result_path=args.promote_result, repository=args.repository,
                state_dir=args.state_dir, journal_path=args.journal,
                remote=args.remote, branch=args.branch, output_path=args.output,
                reference_paths=args.reference,
            )
        elif args.command == "materialize-final-state":
            output = materialize_final_state(
                proof_path=args.proof, build_path=args.build_bundle,
                operation_intent_paths={
                    "upload_version": args.upload_version_intent,
                    "deploy_zero_percent": args.deploy_zero_percent_intent,
                    "promote": args.promote_intent,
                },
                operation_result_paths={
                    "upload_version": args.upload_version_result,
                    "deploy_zero_percent": args.deploy_zero_percent_result,
                    "promote": args.promote_result,
                },
                sealed_root=args.sealed_root, seal_path=args.artifact_seal,
                snapshot_path=args.snapshot, media_manifest_path=args.media_manifest,
                route_manifest_path=args.route_manifest, reference_paths=args.reference,
            )
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        return 3 if (args.command in {"pre-promotion-proof-observe", "production-proof-observe"}
                     and output.get("status") == "FAIL") else 0
    except Exception as exc:
        # Exception messages from external backends may contain sensitive diagnostics.
        print("WORKFLOW_STAGE_BLOCKED: " + type(exc).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
