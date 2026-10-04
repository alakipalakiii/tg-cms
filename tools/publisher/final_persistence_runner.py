"""Final state persistence coordinator; external effects are adapter-injected."""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Mapping, Protocol

from publisher import artifact_contract as contracts
from publisher.proof_recovery_runner import validate_proof


class PersistenceBlocked(RuntimeError):
    """Final state could not be safely persisted and remotely verified."""


class JournalWriter(Protocol):
    def mark_ready_to_persist(self, transaction_id: str, proof_sha256: str,
                              expected_generation: int) -> int: ...
    def finalize_completed(self, transaction_id: str, state_commit_sha: str,
                           expected_generation: int) -> None: ...


class RepositoryWriter(Protocol):
    def persist_once(self, files: Mapping[str, bytes]) -> str: ...
    def read_exact(self, commit_sha: str) -> Mapping[str, object]: ...


def validate_finalization_inputs(proof: object, build_bundle: object,
                                operation_results: Mapping[str, object],
                                state_files: Mapping[str, bytes],
                                journal_generation: int, *,
                                referenced_artifacts: Mapping[str, object] | None = None
                                ) -> tuple[dict, dict, dict, dict]:
    """Pure A5 preflight shared by the executable validator and finalizer."""
    proof_v = validate_proof(proof, build_bundle, operation_results,
                             referenced_artifacts=referenced_artifacts)
    bundle_v = contracts.validate_artifact(build_bundle)
    if "prior_immutable_media_index" not in bundle_v["payload"]:
        raise PersistenceBlocked("new final persistence requires prior index authority binding")
    pp = proof_v["payload"]
    if pp["proof_state"] != "PASS" or pp["production_validation"]["PASS"] is not True:
        raise PersistenceBlocked("production proof must pass before persistence")
    if pp["candidate_identity"]["content_fingerprint"] != bundle_v["payload"]["content_fingerprint"]:
        raise PersistenceBlocked("proof and bundle content identity mismatch")
    if (isinstance(journal_generation, bool) or not isinstance(journal_generation, int)
            or journal_generation < 0):
        raise PersistenceBlocked("journal generation is invalid")
    if set(state_files) != set(contracts.STATE_FILE_PATHS) or any(
        not isinstance(path, str) or not isinstance(data, bytes)
        for path, data in state_files.items()
    ):
        raise PersistenceBlocked("complete allowlisted state files are required")
    files = {path: bytes(data) for path, data in sorted(state_files.items())}
    hashes = {path: hashlib.sha256(data).hexdigest() for path, data in files.items()}
    return proof_v, bundle_v, files, hashes


def finalize(proof: object, build_bundle: object,
             operation_results: Mapping[str, object], state_files: Mapping[str, bytes],
             journal_generation: int, journal_writer: JournalWriter,
             repository_writer: RepositoryWriter, *, clock=None,
             referenced_artifacts: Mapping[str, object] | None = None) -> dict:
    """Persist one repository state transaction, read it back exactly, then close journal."""
    proof_v, bundle_v, files, expected_hashes = validate_finalization_inputs(
        proof, build_bundle, operation_results, state_files, journal_generation,
        referenced_artifacts=referenced_artifacts,
    )
    pp, tx = proof_v["payload"], proof_v["transaction"]
    try:
        ready_generation = journal_writer.mark_ready_to_persist(
            tx["logical_transaction_id"], proof_v["artifact_sha256"], journal_generation,
        )
        if (isinstance(ready_generation, bool) or not isinstance(ready_generation, int)
                or ready_generation < journal_generation):
            raise PersistenceBlocked("journal did not confirm READY_TO_PERSIST")
        commit_sha = repository_writer.persist_once(files)
        if (not isinstance(commit_sha, str) or len(commit_sha) != 40
                or any(char not in "0123456789abcdef" for char in commit_sha)):
            raise PersistenceBlocked("repository persistence returned invalid commit identity")
        readback = repository_writer.read_exact(commit_sha)
        if (not isinstance(readback, Mapping) or set(readback) != {"commit_sha", "file_hashes"}
                or readback["commit_sha"] != commit_sha
                or not isinstance(readback["file_hashes"], Mapping)
                or dict(readback["file_hashes"]) != expected_hashes):
            raise PersistenceBlocked("exact remote state readback failed")
    except PersistenceBlocked:
        raise
    except Exception as exc:
        # Do not expose child-process diagnostics, which could contain credentials.
        raise PersistenceBlocked("persistence transaction or readback failed; recovery required") from exc

    now = clock or (lambda: datetime.now(timezone.utc).isoformat())
    result_sha = {
        name: artifact["artifact_sha256"] for name, artifact in operation_results.items()
    }
    entries = [{"path": path, "size_bytes": len(data), "sha256": expected_hashes[path]}
               for path, data in files.items()]
    payload = {
        "build_bundle_sha256": bundle_v["artifact_sha256"],
        "proof_evidence_sha256": proof_v["artifact_sha256"],
        "operation_result_sha256s": {**result_sha, "rollback": None},
        "state_files": entries,
        "state_commit_sha": commit_sha,
        "journal_generation": ready_generation,
    }
    try:
        final_artifact = contracts.seal_artifact({
            "artifact_type": "final_persistence_payload",
            "schema_version": contracts.SCHEMA_VERSION,
            "artifact_id": str(uuid.uuid4()),
            "created_at": now(),
            "producer": {**proof_v["producer"], "job": "final-persistence"},
            "transaction": dict(tx),
            "payload": payload,
        })
        contracts.validate_artifact(
            final_artifact, expected_transaction=tx,
            expected_source_sha=proof_v["producer"]["source_sha"],
        )
        journal_writer.finalize_completed(
            tx["logical_transaction_id"], commit_sha, ready_generation,
        )
    except Exception as exc:
        raise PersistenceBlocked("verified state is not journal-complete; recovery required") from exc
    return final_artifact
