"""Versioned, fail-closed MAHOON publisher transaction journal foundation."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

CONTRACT = "MAHOON_PUBLISHER_TRANSACTION_JOURNAL_V2"
JOURNAL_PATH = "publisher-state/production-transaction-journal.json"
OPERATIONS = ("upload_version", "deploy_zero_percent", "promote", "rollback")
REQUIRED_SUCCESSFUL_OPERATIONS = OPERATIONS[:3]
_FILE_LOCKS: dict[str, threading.RLock] = {}
_FILE_LOCKS_GUARD = threading.Lock()

ACTIVE_STATES = {
    "admitted", "build_ready", "intent_recorded", "operation_reported",
    "proof_ready", "recovery_required", "ready_to_persist",
}
TERMINAL_STATES = {"completed", "failed", "blocked", "superseded"}
ALL_STATES = ACTIVE_STATES | TERMINAL_STATES | {"pending"}


class JournalError(RuntimeError):
    """Base class for safe journal failures."""


class JournalInvalid(JournalError):
    pass


class JournalUnavailable(JournalError):
    pass


class JournalConflict(JournalError):
    pass


class RecoveryRequired(JournalError):
    pass


class DuplicateMutation(JournalError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def logical_transaction_id(worker: str, revision: int) -> str:
    if not isinstance(worker, str) or not worker or worker != worker.strip():
        raise JournalInvalid("worker identity is required")
    if not _is_int(revision) or revision < 1:
        raise JournalInvalid("content revision must be a positive integer")
    return hashlib.sha256(f"{worker}\0{revision}".encode("utf-8")).hexdigest()


def _operation_id(tx_id: str, operation: str) -> str:
    return hashlib.sha256(f"{tx_id}\0{operation}".encode("utf-8")).hexdigest()


def _canonical_bytes(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def journal_digest(value: dict) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def serialize_journal(value: dict) -> bytes:
    """Serialize the accepted journal representation used by local and Git writers."""
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def empty_journal(worker: str = "mahoon-art-magazine") -> dict:
    if not isinstance(worker, str) or not worker or worker != worker.strip():
        raise JournalInvalid("worker identity is required")
    return {
        "contract": CONTRACT,
        "schema_version": 2,
        "worker": worker,
        "generation": 0,
        "active": None,
        "pending": None,
        "history": [],
    }


def _valid_evidence(value: object, *, required: bool) -> bool:
    if value is None and not required:
        return True
    if not isinstance(value, dict) or set(value) != {"type", "reference", "sha256"}:
        return False
    return (
        all(isinstance(value.get(key), str) and value[key].strip() for key in ("type", "reference"))
        and _sha256(value.get("sha256"))
    )


def _result_digest(outcome: str, evidence: dict | None) -> str:
    return hashlib.sha256(_canonical_bytes({"outcome": outcome, "evidence": evidence})).hexdigest()


def canonical_result_digest(outcome: str, evidence: dict | None) -> str:
    """Expose the journal's accepted result identity to durable writers."""
    return _result_digest(outcome, evidence)


def _validate_attempt(item: object, index: int) -> None:
    legacy_fields = {
        "attempt_number", "attempt_id", "intent_state", "result_state",
        "intent_at", "result_at", "evidence", "result_digest",
    }
    current_fields = legacy_fields | {"intent_artifact_sha256"}
    if not isinstance(item, dict) or set(item) not in (legacy_fields, current_fields):
        raise JournalInvalid("operation attempt schema is invalid")
    intent_digest = item.get("intent_artifact_sha256")
    if intent_digest is not None and not _sha256(intent_digest):
        raise JournalInvalid("operation intent artifact digest is invalid")
    if item["attempt_number"] != index or not _uuid(item["attempt_id"]):
        raise JournalInvalid("operation attempt identity is invalid")
    if item["intent_state"] != "RECORDED" or item["result_state"] not in {"NOT_REPORTED", "APPLIED", "NOT_APPLIED", "UNKNOWN"}:
        raise JournalInvalid("operation attempt state is invalid")
    if not isinstance(item["intent_at"], str) or not item["intent_at"]:
        raise JournalInvalid("operation intent timestamp is invalid")
    outcome = item["result_state"]
    if outcome == "NOT_REPORTED":
        if item["result_at"] is not None or item["evidence"] is not None or item["result_digest"] is not None:
            raise JournalInvalid("unreported attempt contains result data")
        return
    if not isinstance(item["result_at"], str) or not item["result_at"]:
        raise JournalInvalid("reported attempt has no timestamp")
    if outcome in {"APPLIED", "NOT_APPLIED"} and not _valid_evidence(item["evidence"], required=True):
        raise JournalInvalid("conclusive result requires evidence")
    if outcome == "UNKNOWN" and not _valid_evidence(item["evidence"], required=False):
        raise JournalInvalid("unknown result evidence is malformed")
    if not _sha256(item["result_digest"]) or item["result_digest"] != _result_digest(outcome, item["evidence"]):
        raise JournalInvalid("mutation result digest is invalid")


def _validate_transaction(tx: object, worker: str, *, pending: bool = False) -> None:
    expected = {
        "logical_transaction_id", "worker", "content_revision", "state",
        "trigger_sources", "execution_attempts", "operations", "transitions",
        "recovery_status", "build_bundle_sha256", "proof_evidence_sha256",
        "state_commit_sha", "created_at", "updated_at",
    }
    if not isinstance(tx, dict) or set(tx) != expected:
        raise JournalInvalid("transaction record schema is invalid")
    revision = tx["content_revision"]
    tx_id = logical_transaction_id(worker, revision)
    if tx["worker"] != worker or tx["logical_transaction_id"] != tx_id:
        raise JournalInvalid("logical transaction identity mismatch")
    state = tx["state"]
    if state not in ALL_STATES or (pending and state != "pending") or (not pending and state == "pending"):
        raise JournalInvalid("invalid transaction state")
    sources = tx["trigger_sources"]
    attempts = tx["execution_attempts"]
    if not isinstance(sources, list) or not sources or any(not isinstance(s, str) or not s.strip() for s in sources):
        raise JournalInvalid("trigger sources are invalid")
    if not isinstance(attempts, list):
        raise JournalInvalid("execution attempts are invalid")
    for item in attempts:
        if not isinstance(item, dict) or set(item) != {"run_id", "attempt_id", "source", "timestamp"}:
            raise JournalInvalid("execution attempt metadata is invalid")
        if not isinstance(item["source"], str) or not item["source"].strip() or not isinstance(item["timestamp"], str):
            raise JournalInvalid("execution attempt metadata is invalid")
        if any(item[k] is not None and not isinstance(item[k], str) for k in ("run_id", "attempt_id")):
            raise JournalInvalid("execution attempt IDs are invalid")
    operations = tx["operations"]
    if not isinstance(operations, dict) or set(operations) != set(OPERATIONS):
        raise JournalInvalid("operation inventory is invalid")
    for name, operation in operations.items():
        if not isinstance(operation, dict) or set(operation) != {"operation_id", "intent_state", "result_state", "attempts"}:
            raise JournalInvalid("operation schema is invalid")
        if operation["operation_id"] != _operation_id(tx_id, name):
            raise JournalInvalid("operation identity mismatch")
        if operation["intent_state"] not in {"NOT_STARTED", "RECORDED"} or operation["result_state"] not in {"NOT_REPORTED", "APPLIED", "NOT_APPLIED", "UNKNOWN"}:
            raise JournalInvalid("operation state is invalid")
        op_attempts = operation["attempts"]
        if not isinstance(op_attempts, list):
            raise JournalInvalid("operation attempts are invalid")
        for index, item in enumerate(op_attempts, 1):
            _validate_attempt(item, index)
        if op_attempts:
            latest = op_attempts[-1]
            if operation["intent_state"] != latest["intent_state"] or operation["result_state"] != latest["result_state"]:
                raise JournalInvalid("operation summary differs from latest attempt")
        elif (operation["intent_state"], operation["result_state"]) != ("NOT_STARTED", "NOT_REPORTED"):
            raise JournalInvalid("empty operation has non-empty state")
    if tx["build_bundle_sha256"] is not None and not _sha256(tx["build_bundle_sha256"]):
        raise JournalInvalid("build bundle digest is invalid")
    if tx["proof_evidence_sha256"] is not None and not _sha256(tx["proof_evidence_sha256"]):
        raise JournalInvalid("proof evidence digest is invalid")
    if tx["state_commit_sha"] is not None and (not isinstance(tx["state_commit_sha"], str) or len(tx["state_commit_sha"]) != 40 or any(c not in "0123456789abcdef" for c in tx["state_commit_sha"])):
        raise JournalInvalid("state commit SHA is invalid")
    if tx["recovery_status"] not in {"NONE", "REQUIRED", "RECONCILED_APPLIED", "RECONCILED_NOT_APPLIED", "BLOCKED_UNKNOWN"}:
        raise JournalInvalid("recovery status is invalid")
    transitions = tx["transitions"]
    if not isinstance(transitions, list) or not transitions:
        raise JournalInvalid("transition history is invalid")
    allowed_edges = {
        (None, "admitted"), (None, "pending"),
        ("admitted", "build_ready"), ("admitted", "intent_recorded"),
        ("build_ready", "intent_recorded"),
        ("intent_recorded", "operation_reported"), ("intent_recorded", "recovery_required"),
        ("operation_reported", "intent_recorded"), ("operation_reported", "proof_ready"),
        ("operation_reported", "ready_to_persist"),
        ("proof_ready", "intent_recorded"), ("proof_ready", "ready_to_persist"),
        ("recovery_required", "operation_reported"), ("recovery_required", "recovery_required"),
        ("ready_to_persist", "completed"),
        ("pending", "admitted"), ("pending", "superseded"),
    }
    for source in list(ACTIVE_STATES):
        allowed_edges.add((source, "failed"))
        allowed_edges.add((source, "blocked"))
    for item in transitions:
        if not isinstance(item, dict) or set(item) != {"from", "to", "timestamp"}:
            raise JournalInvalid("transition schema is invalid")
        if (item["from"], item["to"]) not in allowed_edges or not isinstance(item["timestamp"], str):
            raise JournalInvalid("illegal state transition")
    if transitions[-1]["to"] != state:
        raise JournalInvalid("transaction state differs from last transition")
    unresolved = any(op["attempts"] and op["attempts"][-1]["result_state"] in {"NOT_REPORTED", "UNKNOWN"} for op in operations.values())
    if state == "recovery_required" and not unresolved:
        raise JournalInvalid("recovery_required has no unresolved operation")
    if state == "completed" and not tx["state_commit_sha"]:
        raise JournalInvalid("completed transaction requires confirmed state commit")


def validate_journal(value: object, worker: str | None = None) -> dict:
    expected = {"contract", "schema_version", "worker", "generation", "active", "pending", "history"}
    if not isinstance(value, dict) or set(value) != expected:
        raise JournalInvalid("journal schema is invalid")
    if value["contract"] != CONTRACT or value["schema_version"] != 2:
        raise JournalInvalid("journal contract or schema version mismatch")
    journal_worker = value["worker"]
    generation = value["generation"]
    if not isinstance(journal_worker, str) or not journal_worker.strip() or journal_worker != journal_worker.strip():
        raise JournalInvalid("journal worker is invalid")
    if worker is not None and journal_worker != worker:
        raise JournalInvalid("journal worker mismatch")
    if not _is_int(generation) or generation < 0 or not isinstance(value["history"], list):
        raise JournalInvalid("journal generation/history is invalid")
    if value["active"] is not None:
        _validate_transaction(value["active"], journal_worker)
        if value["active"]["state"] in TERMINAL_STATES:
            raise JournalInvalid("active slot cannot contain a terminal transaction")
    if value["pending"] is not None:
        if value["active"] is None:
            raise JournalInvalid("pending requires an active transaction")
        _validate_transaction(value["pending"], journal_worker, pending=True)
        if value["pending"]["content_revision"] <= value["active"]["content_revision"]:
            raise JournalInvalid("pending revision must be newer than active revision")
    seen = set()
    for item in value["history"]:
        _validate_transaction(item, journal_worker)
        if item["state"] not in TERMINAL_STATES:
            raise JournalInvalid("history contains a non-terminal transaction")
        key = item["logical_transaction_id"]
        if key in seen:
            raise JournalInvalid("history contains duplicate transaction identity")
        seen.add(key)
    return value


class FileJournalStore:
    """Atomic local CAS store for tests; not a cross-process production backend."""

    def __init__(self, path: Path):
        self.path = Path(path)
        key = str(self.path.resolve())
        with _FILE_LOCKS_GUARD:
            self._lock = _FILE_LOCKS.setdefault(key, threading.RLock())

    def read(self) -> tuple[dict, str]:
        try:
            raw = self.path.read_bytes()
        except OSError as exc:
            raise JournalUnavailable("journal file unavailable") from exc
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise JournalInvalid("journal JSON invalid") from exc
        return value, hashlib.sha256(raw).hexdigest()

    def initialize(self, worker: str) -> tuple[str, dict, str]:
        """Create the initial journal atomically without ever replacing existing state."""
        if self.path.is_symlink():
            raise JournalInvalid("journal initialization refuses a symlink")

        def existing() -> tuple[str, dict, str]:
            try:
                raw = self.path.read_bytes()
                value = json.loads(raw.decode("utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise JournalInvalid("existing journal is unavailable or malformed") from exc
            validate_journal(value, worker)
            return "ALREADY_INITIALIZED", value, journal_digest(value)

        try:
            return existing()
        except JournalInvalid:
            if self.path.exists() or self.path.is_symlink():
                raise

        initial = empty_journal(worker)
        validate_journal(initial, worker)
        raw = serialize_journal(initial)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                # A same-directory hard link is atomic and fails rather than replacing a racer.
                os.link(temporary, self.path)
                status = "INITIALIZED"
            except FileExistsError:
                status = "ALREADY_INITIALIZED"
        except OSError as exc:
            raise JournalUnavailable("atomic journal initialization failed") from exc
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

        try:
            installed = self.path.read_bytes()
            value = json.loads(installed.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise JournalInvalid("initialized journal readback is invalid") from exc
        validate_journal(value, worker)
        if status == "INITIALIZED" and installed != raw:
            raise JournalConflict("journal changed during initialization readback")
        return status, value, journal_digest(value)

    def compare_and_swap(self, expected: str, value: dict) -> str:
        with self._lock:
            _current, version = self.read()
            if version != expected:
                raise JournalConflict("journal changed during update")
            raw = serialize_journal(value)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            return hashlib.sha256(raw).hexdigest()


class TransactionJournal:
    def __init__(self, store: FileJournalStore, worker: str, clock: Callable[[], str] = _now, max_cas_retries: int = 3):
        if max_cas_retries < 1 or max_cas_retries > 3:
            raise ValueError("max_cas_retries must be between 1 and 3")
        if not isinstance(worker, str) or not worker or worker != worker.strip():
            raise ValueError("worker must be a nonempty trimmed string")
        self.store, self.worker, self.clock = store, worker, clock
        self.max_cas_retries = max_cas_retries

    @classmethod
    def from_file(cls, path: Path, worker: str) -> "TransactionJournal":
        return cls(FileJournalStore(path), worker)

    def snapshot(self) -> tuple[dict, int, str]:
        current, _raw = self.store.read()
        validate_journal(current, self.worker)
        return current, current["generation"], journal_digest(current)

    def _change(self, update: Callable[[dict], object], *, expected_generation: int | None = None, expected_digest: str | None = None, retry_coordination: bool = True) -> object:
        attempts = self.max_cas_retries if retry_coordination and expected_generation is None and expected_digest is None else 1
        for _ in range(attempts):
            current, raw_version = self.store.read()
            validate_journal(current, self.worker)
            if expected_generation is not None and current["generation"] != expected_generation:
                raise JournalConflict("journal generation does not match expected generation")
            if expected_digest is not None and journal_digest(current) != expected_digest:
                raise JournalConflict("journal digest does not match expected digest")
            changed = copy.deepcopy(current)
            result = update(changed)
            changed["generation"] = current["generation"] + 1
            validate_journal(changed, self.worker)
            try:
                self.store.compare_and_swap(raw_version, changed)
                return result
            except JournalConflict:
                if attempts == 1:
                    raise
        raise JournalConflict("journal update exceeded bounded CAS retries")

    def _record(self, revision: int, source: str, run_id: str, attempt_id: str, state: str) -> dict:
        stamp = self.clock()
        tx_id = logical_transaction_id(self.worker, revision)
        return {
            "logical_transaction_id": tx_id,
            "worker": self.worker,
            "content_revision": revision,
            "state": state,
            "trigger_sources": [source],
            "execution_attempts": [{
                "run_id": run_id or None, "attempt_id": attempt_id or None,
                "source": source, "timestamp": stamp,
            }],
            "operations": {
                name: {
                    "operation_id": _operation_id(tx_id, name),
                    "intent_state": "NOT_STARTED",
                    "result_state": "NOT_REPORTED",
                    "attempts": [],
                } for name in OPERATIONS
            },
            "transitions": [{"from": None, "to": state, "timestamp": stamp}],
            "recovery_status": "NONE",
            "build_bundle_sha256": None,
            "proof_evidence_sha256": None,
            "state_commit_sha": None,
            "created_at": stamp,
            "updated_at": stamp,
        }

    def _transition(self, tx: dict, state: str) -> None:
        old = tx["state"]
        if old != state:
            if old in TERMINAL_STATES:
                raise JournalInvalid("terminal transaction cannot be reopened")
            tx["transitions"].append({"from": old, "to": state, "timestamp": self.clock()})
            tx["state"] = state
        tx["updated_at"] = self.clock()

    @staticmethod
    def _unresolved(tx: dict) -> bool:
        return any(op["attempts"] and op["attempts"][-1]["result_state"] in {"NOT_REPORTED", "UNKNOWN"} for op in tx["operations"].values())

    def admit(self, revision: int, source: str, run_id: str = "", attempt_id: str = "", *, expected_generation: int | None = None, expected_digest: str | None = None) -> tuple[str, str]:
        tx_id = logical_transaction_id(self.worker, revision)
        if not isinstance(source, str) or not source.strip():
            raise JournalInvalid("trigger source is required")

        def update(journal: dict) -> str:
            active, pending = journal["active"], journal["pending"]
            stamp = self.clock()
            if active and active["logical_transaction_id"] == tx_id:
                active["execution_attempts"].append({"run_id": run_id or None, "attempt_id": attempt_id or None, "source": source, "timestamp": stamp})
                if source not in active["trigger_sources"]:
                    active["trigger_sources"].append(source)
                active["updated_at"] = stamp
                if active["state"] == "recovery_required":
                    return "RECOVERY_REQUIRED"
                return "COALESCED_ACTIVE"
            if any(item["logical_transaction_id"] == tx_id and item["state"] == "completed" for item in journal["history"]):
                return "COALESCED_COMPLETED"
            if active is None:
                journal["active"] = self._record(revision, source, run_id, attempt_id, "admitted")
                return "ADMITTED"
            if revision <= active["content_revision"]:
                return "STALE"
            if pending and revision <= pending["content_revision"]:
                if revision == pending["content_revision"]:
                    pending["execution_attempts"].append({"run_id": run_id or None, "attempt_id": attempt_id or None, "source": source, "timestamp": stamp})
                    if source not in pending["trigger_sources"]:
                        pending["trigger_sources"].append(source)
                    pending["updated_at"] = stamp
                    return "COALESCED_PENDING"
                return "SUPERSEDED"
            replacement = self._record(revision, source, run_id, attempt_id, "pending")
            if pending:
                self._transition(pending, "superseded")
                journal["history"].append(pending)
            journal["pending"] = replacement
            return "PENDING_REPLACED" if pending else "PENDING"

        status = self._change(update, expected_generation=expected_generation, expected_digest=expected_digest)
        return str(status), tx_id

    def _active(self, journal: dict, tx_id: str) -> dict:
        tx = journal.get("active")
        if not tx or tx["logical_transaction_id"] != tx_id:
            raise JournalInvalid("transaction does not own the active journal slot")
        if tx["state"] in TERMINAL_STATES:
            raise JournalInvalid("terminal transaction cannot be reopened")
        return tx

    def record_build_ready(self, tx_id: str, build_bundle_sha256: str, *, expected_generation: int | None = None, expected_digest: str | None = None) -> None:
        if not _sha256(build_bundle_sha256):
            raise JournalInvalid("build bundle digest is invalid")
        def update(journal: dict) -> None:
            tx = self._active(journal, tx_id)
            if tx["state"] != "admitted":
                raise JournalInvalid("build can become ready only from admitted state")
            tx["build_bundle_sha256"] = build_bundle_sha256
            self._transition(tx, "build_ready")
        self._change(update, expected_generation=expected_generation, expected_digest=expected_digest)

    def record_intent(self, tx_id: str, operation_name: str, *, attempt_id: str | None = None, intent_artifact_sha256: str | None = None, expected_generation: int | None = None, expected_digest: str | None = None) -> tuple[str, str]:
        if operation_name not in OPERATIONS:
            raise JournalInvalid("unknown mutation operation")
        if attempt_id is not None and not _uuid(attempt_id):
            raise JournalInvalid("attempt_id must be a canonical UUID")
        if intent_artifact_sha256 is not None and not _sha256(intent_artifact_sha256):
            raise JournalInvalid("intent artifact digest is invalid")
        result: list[str] = []
        def update(journal: dict) -> None:
            tx = self._active(journal, tx_id)
            if tx["state"] == "recovery_required":
                raise RecoveryRequired("transaction is blocked for recovery")
            if tx["state"] not in {"admitted", "build_ready", "operation_reported", "proof_ready"}:
                raise JournalInvalid("transaction cannot record intent in this state")
            operation = tx["operations"][operation_name]
            if attempt_id is not None and any(a["attempt_id"] == attempt_id for a in operation["attempts"]):
                raise DuplicateMutation("attempt identity is already recorded")
            if operation["result_state"] == "APPLIED":
                raise DuplicateMutation("operation is already applied")
            if operation["attempts"]:
                prior = operation["attempts"][-1]["result_state"]
                if prior in {"NOT_REPORTED", "UNKNOWN"}:
                    raise RecoveryRequired("previous operation attempt must be reconciled first")
                if prior == "NOT_APPLIED" and tx["recovery_status"] not in {"RECONCILED_NOT_APPLIED", "NONE"}:
                    raise RecoveryRequired("not-applied result has not been safely reconciled")
            number = len(operation["attempts"]) + 1
            attempt_key = attempt_id or str(uuid.uuid4())
            stamp = self.clock()
            operation["attempts"].append({
                "attempt_number": number,
                "attempt_id": attempt_key,
                "intent_state": "RECORDED",
                "intent_artifact_sha256": intent_artifact_sha256,
                "result_state": "NOT_REPORTED",
                "intent_at": stamp,
                "result_at": None,
                "evidence": None,
                "result_digest": None,
            })
            operation["intent_state"] = "RECORDED"
            operation["result_state"] = "NOT_REPORTED"
            tx["recovery_status"] = "NONE"
            self._transition(tx, "intent_recorded")
            result.append(attempt_key)
        self._change(update, expected_generation=expected_generation, expected_digest=expected_digest)
        return _operation_id(tx_id, operation_name), result[-1]

    @staticmethod
    def _evidence(outcome: str, evidence: object) -> dict | None:
        required = outcome in {"APPLIED", "NOT_APPLIED"}
        if not _valid_evidence(evidence, required=required):
            raise JournalInvalid("mutation outcome evidence is missing or malformed")
        return copy.deepcopy(evidence) if evidence is not None else None

    def record_result(self, tx_id: str, operation_id: str, attempt_id: str, outcome: str, evidence: dict | None = None, *, expected_generation: int | None = None, expected_digest: str | None = None) -> None:
        if outcome not in {"APPLIED", "NOT_APPLIED", "UNKNOWN"}:
            raise JournalInvalid("unsupported mutation result")
        checked_evidence = self._evidence(outcome, evidence)
        digest = _result_digest(outcome, checked_evidence)

        def update(journal: dict) -> None:
            tx = self._active(journal, tx_id)
            op = next((item for item in tx["operations"].values() if item["operation_id"] == operation_id), None)
            if op is None or not op["attempts"]:
                raise JournalInvalid("result has no matching operation intent")
            attempt = next((a for a in op["attempts"] if a["attempt_id"] == attempt_id), None)
            if attempt is None:
                raise RecoveryRequired("result does not match an operation attempt")
            if attempt is not op["attempts"][-1]:
                raise RecoveryRequired("only the latest attempt may receive a result")
            if attempt["result_state"] != "NOT_REPORTED":
                if attempt["result_digest"] == digest and attempt["result_state"] == outcome:
                    return
                raise DuplicateMutation("conflicting second result for the same attempt")
            if tx["state"] == "recovery_required":
                raise RecoveryRequired("transaction is blocked for recovery")
            stamp = self.clock()
            attempt.update(result_state=outcome, result_at=stamp, evidence=checked_evidence, result_digest=digest)
            op["result_state"] = outcome
            op["intent_state"] = "RECORDED"
            if outcome == "UNKNOWN":
                tx["recovery_status"] = "REQUIRED"
                self._transition(tx, "recovery_required")
            else:
                tx["recovery_status"] = "NONE"
                self._transition(tx, "operation_reported")
        self._change(update, expected_generation=expected_generation, expected_digest=expected_digest, retry_coordination=False)

    def reconcile(self, tx_id: str, operation_id: str, outcome: str, evidence: dict | None = None, *, expected_generation: int | None = None, expected_digest: str | None = None) -> None:
        if outcome not in {"APPLIED", "NOT_APPLIED", "UNKNOWN"}:
            raise JournalInvalid("unsupported reconciliation result")
        checked_evidence = self._evidence(outcome, evidence)
        digest = _result_digest(outcome, checked_evidence)

        def update(journal: dict) -> None:
            tx = self._active(journal, tx_id)
            op = next((item for item in tx["operations"].values() if item["operation_id"] == operation_id), None)
            if op is None or not op["attempts"]:
                raise JournalInvalid("reconciliation has no matching intent")
            attempt = op["attempts"][-1]
            if attempt["result_state"] not in {"NOT_REPORTED", "UNKNOWN"}:
                raise JournalInvalid("operation is not awaiting reconciliation")
            if tx["state"] not in {"intent_recorded", "recovery_required"}:
                raise JournalInvalid("transaction is not recoverable")
            stamp = self.clock()
            attempt.update(result_state=outcome, result_at=stamp, evidence=checked_evidence, result_digest=digest)
            op["result_state"] = outcome
            if outcome == "UNKNOWN":
                tx["recovery_status"] = "BLOCKED_UNKNOWN"
                self._transition(tx, "recovery_required")
                return
            tx["recovery_status"] = "RECONCILED_APPLIED" if outcome == "APPLIED" else "RECONCILED_NOT_APPLIED"
            self._transition(tx, "operation_reported")
        self._change(update, expected_generation=expected_generation, expected_digest=expected_digest, retry_coordination=False)

    def record_proof_ready(self, tx_id: str, proof_evidence_sha256: str, *, expected_generation: int | None = None, expected_digest: str | None = None) -> None:
        if not _sha256(proof_evidence_sha256):
            raise JournalInvalid("proof evidence digest is invalid")
        def update(journal: dict) -> None:
            tx = self._active(journal, tx_id)
            if tx["state"] != "operation_reported" or self._unresolved(tx):
                raise RecoveryRequired("proof cannot become ready with unresolved mutation")
            if any(tx["operations"][name]["result_state"] != "APPLIED" for name in REQUIRED_SUCCESSFUL_OPERATIONS):
                raise JournalInvalid("required operations are not all applied")
            tx["proof_evidence_sha256"] = proof_evidence_sha256
            self._transition(tx, "proof_ready")
        self._change(update, expected_generation=expected_generation, expected_digest=expected_digest)

    def mark_ready_to_persist(self, tx_id: str, proof_evidence_sha256: str | None = None, *, expected_generation: int | None = None, expected_digest: str | None = None) -> None:
        def update(journal: dict) -> None:
            tx = self._active(journal, tx_id)
            if proof_evidence_sha256 is not None:
                if not _sha256(proof_evidence_sha256):
                    raise JournalInvalid("proof evidence digest is invalid")
                if tx["proof_evidence_sha256"] is not None and tx["proof_evidence_sha256"] != proof_evidence_sha256:
                    raise JournalInvalid("proof evidence digest mismatch")
                tx["proof_evidence_sha256"] = proof_evidence_sha256
            if tx["state"] not in {"operation_reported", "proof_ready"} or self._unresolved(tx):
                raise RecoveryRequired("transaction is not ready for persistence")
            if not tx["proof_evidence_sha256"]:
                raise JournalInvalid("proof evidence is required before persistence")
            if any(tx["operations"][name]["result_state"] != "APPLIED" for name in REQUIRED_SUCCESSFUL_OPERATIONS):
                raise JournalInvalid("required mutation operations are not all applied")
            self._transition(tx, "ready_to_persist")
        self._change(update, expected_generation=expected_generation, expected_digest=expected_digest)

    def finalize_completed(self, tx_id: str, state_commit_sha: str, *, expected_generation: int | None = None, expected_digest: str | None = None) -> None:
        if not isinstance(state_commit_sha, str) or len(state_commit_sha) != 40 or any(c not in "0123456789abcdef" for c in state_commit_sha):
            raise JournalInvalid("confirmed state commit SHA is required")
        def update(journal: dict) -> None:
            tx = self._active(journal, tx_id)
            if tx["state"] != "ready_to_persist":
                raise JournalInvalid("transaction must be READY_TO_PERSIST before completion")
            tx["state_commit_sha"] = state_commit_sha
            self._transition(tx, "completed")
            journal["history"].append(tx)
            journal["history"] = journal["history"][-100:]
            journal["active"] = journal["pending"]
            journal["pending"] = None
            if journal["active"]:
                self._transition(journal["active"], "admitted")
        self._change(update, expected_generation=expected_generation, expected_digest=expected_digest, retry_coordination=False)

    def complete(self, tx_id: str) -> None:
        """Legacy compatibility guard: completion now requires a confirmed state commit."""
        raise JournalInvalid("complete() is disabled; use mark_ready_to_persist() and finalize_completed()")

    def mark_terminal(self, tx_id: str, state: str) -> None:
        if state not in {"failed", "blocked"}:
            raise JournalInvalid("terminal state must be failed or blocked")
        def update(journal: dict) -> None:
            tx = self._active(journal, tx_id)
            self._transition(tx, state)
            journal["history"].append(tx)
            journal["history"] = journal["history"][-100:]
            journal["active"] = journal["pending"]
            journal["pending"] = None
            if journal["active"]:
                self._transition(journal["active"], "admitted")
        self._change(update, retry_coordination=False)
