"""Repository-persisted, fail-closed guard for scheduled publishing."""

from __future__ import annotations

import argparse
import json
import os
import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CONTRACT = "MAHOON_SCHEDULED_PUBLISH_CIRCUIT_BREAKER_V1"
VALID_STATES = {"CLOSED", "OPEN"}
REQUIRED_KEYS = {
    "contract", "state", "reason", "failed_run_id", "failed_job",
    "head_sha", "updated_at",
}
PRETRANSACTION_RECOVERY_KIND = "PRETRANSACTION_TEST_FAILURE_RECOVERY_V1"
PRETRANSACTION_AUDIT_KEYS = {
    "recovery_kind", "incident_run", "fix_sha", "safety_test_run_id", "check_only_run_id",
}
AUTO_TICK_PROMOTION_WIRING_RECOVERY_KIND = "AUTO_TICK_PROMOTION_WIRING_RECOVERY_V1"
AUTO_TICK_PROMOTION_WIRING_AUDIT_KEYS = {
    "recovery_kind", "incident_run", "transaction_id", "candidate_version", "fix_sha",
    "promotion_resume_run_id", "production_pass",
}
A6_RECOVERY_KIND = "A6_VERIFIED_PRODUCTION_RECOVERY_V1"
A6_AUDIT_KEYS = {"recovery_kind", "incident_run", "fix_sha", "safety_test_run_id",
                 "check_only_run_id", "production_run_id", "transaction_id",
                 "candidate_version", "production_proof_sha256", "recovery_evidence_sha256"}
RELEVANT_JOBS = (
    "build-and-zero-percent",
    "remote-proof",
    "promote-and-validate",
    "persist-state",
)


def _valid_state(value: object) -> bool:
    keys = set(value) if isinstance(value, dict) else set()
    return (
        isinstance(value, dict)
        and keys in (
            REQUIRED_KEYS,
            REQUIRED_KEYS | PRETRANSACTION_AUDIT_KEYS,
            REQUIRED_KEYS | AUTO_TICK_PROMOTION_WIRING_AUDIT_KEYS,
            REQUIRED_KEYS | A6_AUDIT_KEYS,
        )
        and value.get("contract") == CONTRACT
        and value.get("state") in VALID_STATES
        and isinstance(value.get("updated_at"), str)
    )


def load_state(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return value if _valid_state(value) else None


def _journal(path: Path) -> dict:
    try:
        from .transaction_journal import validate_journal
    except ImportError:
        from transaction_journal import validate_journal
    value = json.loads(path.read_text(encoding="utf-8"))
    validate_journal(value, "mahoon-art-magazine")
    return value


def preflight(path: Path, journal_path: Path | None = None) -> dict[str, object]:
    state = load_state(path)
    if state is None:
        return {"publish_allowed": False, "breaker_state": "INVALID"}
    allowed = state["state"] == "CLOSED"
    if journal_path is not None:
        try:
            journal = _journal(journal_path)
            allowed = allowed and journal["active"] is None and journal["pending"] is None
        except (OSError, ValueError, RuntimeError):
            allowed = False
    return {"publish_allowed": allowed, "breaker_state": state["state"]}


def a6_failure(results: Mapping[str, dict], journal_path: Path) -> str | None:
    # Job success alone cannot prove APPLIED, a passing seal, or durable completion.
    for name, result in results.items():
        if result.get("result") in {"failure", "cancelled"}:
            return name
    completed_publication = results.get("final-persistence", {}).get("result") == "success"
    for stage in ("pre-promotion-proof", "production-proof"):
        item = results.get(stage, {})
        outputs = item.get("outputs")
        if (completed_publication and item.get("result") != "success") or (
            item.get("result") == "success"
            and (not isinstance(outputs, dict) or outputs.get("proof_state") != "PASS")
        ):
            return stage
    for stage, recovered in (("upload-result-write", "upload-create-recovered-result"),
                             ("zero-percent-result-write", "zero-create-recovered-result"),
                             ("promote-result-write", "promote-create-recovered-result")):
        item = results.get(stage, {})
        if (item.get("result") == "success" and item.get("outputs", {}).get("result_state") != "APPLIED"
                and results.get(recovered, {}).get("outputs", {}).get("recovered") != "true"):
            return stage
    try:
        journal = _journal(journal_path)
    except (OSError, ValueError, RuntimeError):
        return "journal-invalid"
    if journal["active"] is not None or journal["pending"] is not None:
        return "journal-incomplete"
    from publisher.superseded_build import verified_retirement
    if results.get("build-validate", {}).get("outputs", {}).get("superseded") == "true":
        return None if verified_retirement(results, journal) else "superseded-retirement-unproven"
    if (results.get("admission", {}).get("outputs", {}).get("decision") in {"ADMITTED", "COALESCED"}
            and results.get("final-persistence", {}).get("result") != "success"):
        return "final-persistence"
    return None


def a6_closed_state(state: dict, evidence: dict, repository: Path, *, authorized: bool) -> dict:
    """Close only against completed canonical A6 state and independently collected receipts."""
    if not _valid_state(state) or state["state"] != "OPEN" or not authorized:
        raise ValueError("A6 recovery requires authorized OPEN state")
    if (evidence.get("contract") != A6_RECOVERY_KIND
            or evidence.get("incident_run") != state["failed_run_id"]
            or evidence.get("failed_job") != state["failed_job"]):
        raise ValueError("A6 recovery incident mismatch")
    fix = evidence.get("fix_sha", "")
    if not re.fullmatch(r"[0-9a-f]{40}", fix):
        raise ValueError("A6 corrective source is invalid")
    for label in ("safety_test", "open_auto_tick"):
        run = evidence[label]
        if (run.get("head_sha") != fix
                or not str(run.get("id", "")).isdigit()):
            raise ValueError("A6 hosted recovery run is incomplete or has wrong source")
    tick = evidence["open_auto_tick"]
    unchanged = tick.get("decision") == "UNCHANGED" and tick.get("conclusion") == "success"
    changed_read_only = (tick.get("decision") == "CHANGED" and tick.get("conclusion") == "failure"
                         and tick.get("check_only_outcome") == "CHANGED_REVISION_DETECTED_CHECK_ONLY"
                         and tick.get("failed_jobs") == ["check-only"])
    if (evidence["safety_test"].get("conclusion") != "success"
            or tick.get("mode") != "AUTO_TICK" or not (unchanged or changed_read_only)
            or tick.get("mutation_jobs_executed") != []
            or tick.get("journal_unchanged") is not True
            or evidence.get("incident_media_regression") != "PASS"):
        raise ValueError("A6 OPEN idle path or media regression not proven")
    journal = _journal(repository / "publisher-state/production-transaction-journal.json")
    if journal["active"] is not None or journal["pending"] is not None:
        raise ValueError("A6 recovery has unfinished transactions")
    accepted = json.loads((repository / "publisher-state/published-static-state.json").read_text(encoding="utf-8"))
    published = json.loads((repository / "publisher-state/production-content-fingerprint.json").read_text(encoding="utf-8"))
    tx = next((x for x in reversed(journal["history"]) if x["state"] == "completed"), None)
    proof, persisted = evidence["production_proof"], evidence["persistence"]
    try:
        from . import artifact_contract as contracts
    except ImportError:
        import artifact_contract as contracts
    artifacts = evidence["sealed_artifacts"]
    references = {item["artifact_sha256"]: item for item in artifacts}
    for item in artifacts:
        contracts.validate_artifact(item, referenced_artifacts=references)
    if changed_read_only:
        revision = references[tick["revision_artifact_sha256"]]
        if (revision["artifact_type"] != "revision_resolution"
                or revision["producer"]["source_sha"] != fix
                or revision["producer"]["workflow_run_id"] != str(tick["id"])
                or revision["payload"]["decision"] != "CHANGED"
                or revision["payload"]["published_revision"] != published["published_content_revision"]
                or revision["payload"]["revision"] <= published["published_content_revision"]):
            raise ValueError("A6 changed CHECK_ONLY revision evidence mismatch")
    sealed_proof = references[proof["artifact_sha256"]]
    sealed_persistence = references[persisted["artifact_sha256"]]
    if (sealed_proof["artifact_type"] != "proof_evidence"
            or sealed_persistence["artifact_type"] != "final_persistence_payload"
            or sealed_persistence["transaction"] != sealed_proof["transaction"]
            or sealed_proof["payload"]["proof_state"] != proof["proof_state"]
            or sealed_proof["payload"]["candidate_identity"]["candidate_version_id"] != proof["candidate_version"]
            or sealed_proof["producer"]["workflow_run_id"] != str(proof["run_id"])
            or any(sealed_persistence["payload"][key] != persisted[key]
                   for key in ("state_commit_sha", "proof_evidence_sha256", "state_files"))):
        raise ValueError("A6 recovery sealed artifact mismatch")
    try:
        from .proof_recovery_runner import validate_proof
    except ImportError:
        from proof_recovery_runner import validate_proof
    validate_proof(sealed_proof, references[sealed_proof["payload"]["build_bundle_sha256"]],
                   {name: references[digest] for name, digest in sealed_proof["payload"]["operation_result_sha256s"].items() if digest},
                   referenced_artifacts=references)
    if (not tx or tx["content_revision"] != published["published_content_revision"]
            or tx["logical_transaction_id"] != evidence["transaction_id"]
            or tx["proof_evidence_sha256"] != proof["artifact_sha256"]
            or tx["state_commit_sha"] != persisted["state_commit_sha"]
            or persisted["proof_evidence_sha256"] != proof["artifact_sha256"]
            or proof["proof_state"] != "PASS" or persisted["status"] != "PERSISTED"
            or str(proof["run_id"]) not in {x["run_id"] for x in tx["execution_attempts"]}
            or evidence.get("artifact_lineage_verified") is not True):
        raise ValueError("A6 canonical production/proof/persistence lineage mismatch")
    for row in persisted["state_files"]:
        if row["path"] not in contracts.STATE_FILE_PATHS:
            raise ValueError("A6 recovery state path is not allowed")
        raw = (repository / row["path"]).read_bytes()
        if len(raw) != row["size_bytes"] or hashlib.sha256(raw).hexdigest() != row["sha256"]:
            raise ValueError("A6 persisted state differs from proof receipt")
    if len({row["path"] for row in persisted["state_files"]}) != 6:
        raise ValueError("A6 recovery requires exactly six persisted state files")
    live = evidence["live_website"]
    versions = live["versions"]
    if (not isinstance(versions, list) or not versions
            or any(not isinstance(v.get("version_id"), str) or not v["version_id"]
                   or type(v.get("percentage")) is not int or not 0 <= v["percentage"] <= 100 for v in versions)
            or len({v["version_id"] for v in versions}) != len(versions)):
        raise ValueError("A6 recovery live allocation is malformed")
    if (live["deployment_id"] != accepted["deployment_id"]
            or proof["candidate_version"] != accepted["current_version"]
            or {v["version_id"]: v["percentage"] for v in versions}.get(accepted["current_version"]) != 100
            or sum(v["percentage"] for v in versions) != 100):
        raise ValueError("A6 recovery live baseline drift")
    if journal["generation"] != evidence["journal_generation"]:
        raise ValueError("A6 recovery journal changed")
    return {"contract": CONTRACT, "state": "CLOSED",
            "reason": f"{A6_RECOVERY_KIND}: incident {state['failed_run_id']} regression resolved; completed sealed production, persistence and scheduled path verified",
            "failed_run_id": None, "failed_job": None, "head_sha": fix,
            "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "recovery_kind": A6_RECOVERY_KIND, "incident_run": state["failed_run_id"], "fix_sha": fix,
            "safety_test_run_id": str(evidence["safety_test"]["id"]),
            "check_only_run_id": str(evidence["open_auto_tick"]["id"]),
            "production_run_id": str(proof["run_id"]), "transaction_id": tx["logical_transaction_id"],
            "candidate_version": accepted["current_version"], "production_proof_sha256": proof["artifact_sha256"],
            "recovery_evidence_sha256": hashlib.sha256(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}


def failed_job(job_results: Mapping[str, str]) -> str | None:
    for job in RELEVANT_JOBS:
        if job_results.get(job) in {"failure", "cancelled"}:
            return job
    return None


def should_open_breaker(breaker_state: str, job_results: Mapping[str, str]) -> bool:
    return breaker_state == "CLOSED" and failed_job(job_results) is not None


def opened_state(state: dict, *, run_id: str, failed_stage: str, head_sha: str,
                 reason: str, updated_at: str | None = None) -> dict:
    if not _valid_state(state):
        raise ValueError("invalid circuit breaker state")
    if state["state"] == "OPEN":
        return state
    return {
        **state,
        "state": "OPEN",
        "reason": reason,
        "failed_run_id": str(run_id),
        "failed_job": failed_stage,
        "head_sha": head_sha,
        "updated_at": updated_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }



def closed_state(state: dict, *, recovery_run_id: str, transaction_id: str,
                 candidate_version: str, production_run_id: str, head_sha: str,
                 reason: str, updated_at: str | None = None) -> dict:
    if not _valid_state(state):
        raise ValueError("invalid circuit breaker state")
    required = (recovery_run_id, transaction_id, candidate_version, production_run_id, head_sha)
    if state["state"] != "OPEN" or any(not str(value).strip() for value in required):
        raise ValueError("recovery close requires OPEN breaker and complete proof identity")
    return {
        **state,
        "state": "CLOSED",
        "reason": reason,
        "failed_run_id": None,
        "failed_job": None,
        "head_sha": head_sha,
        "updated_at": updated_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def pretransaction_closed_state(
    state: dict,
    *,
    incident_run: str,
    failed_job: str,
    transaction_created: str,
    candidate_created: str,
    upload_performed: str,
    promotion_performed: str,
    production_mutation: str,
    fix_sha: str,
    safety_test_run_id: str,
    check_only_run_id: str,
    live_state_parity: str,
    authorized: bool,
    updated_at: str | None = None,
) -> dict:
    if not _valid_state(state) or state["state"] != "OPEN":
        raise ValueError("pretransaction recovery requires OPEN breaker")
    if state["failed_run_id"] != str(incident_run) or state["failed_job"] != failed_job:
        raise ValueError("pretransaction recovery incident identity mismatch")
    if any(value != "NO" for value in (
        transaction_created, candidate_created, upload_performed,
        promotion_performed, production_mutation,
    )):
        raise ValueError("pretransaction recovery requires proof of no mutation")
    if live_state_parity != "PASS" or not authorized:
        raise ValueError("pretransaction recovery authorization or parity missing")
    required = (fix_sha, safety_test_run_id, check_only_run_id)
    if not all(str(value).strip() for value in required):
        raise ValueError("pretransaction recovery evidence incomplete")
    return {
        **state,
        "state": "CLOSED",
        "reason": f"{PRETRANSACTION_RECOVERY_KIND} incident {incident_run} recovered before transaction creation",
        "failed_run_id": None,
        "failed_job": None,
        "head_sha": fix_sha,
        "updated_at": updated_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "recovery_kind": PRETRANSACTION_RECOVERY_KIND,
        "incident_run": str(incident_run),
        "fix_sha": fix_sha,
        "safety_test_run_id": str(safety_test_run_id),
        "check_only_run_id": str(check_only_run_id),
    }
def _write_output(values: Mapping[str, object]) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            for key, value in values.items():
                rendered = str(value).lower() if isinstance(value, bool) else value
                handle.write(f"{key}={rendered}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    preflight_parser = sub.add_parser("preflight")
    preflight_parser.add_argument("--path", type=Path, required=True)
    preflight_parser.add_argument("--journal", type=Path)
    observe = sub.add_parser("observe-a6")
    observe.add_argument("--path", type=Path, required=True)
    observe.add_argument("--journal", type=Path, required=True)
    observe.add_argument("--run-id", required=True)
    observe.add_argument("--head-sha", required=True)
    a6 = sub.add_parser("recover-a6")
    a6.add_argument("--path", type=Path, required=True)
    a6.add_argument("--evidence", type=Path, required=True)
    a6.add_argument("--repository", type=Path, required=True)
    a6.add_argument("--authorized", action="store_true")
    open_parser = sub.add_parser("open")
    open_parser.add_argument("--path", type=Path, required=True)
    open_parser.add_argument("--run-id", required=True)
    open_parser.add_argument("--failed-job", required=True)
    open_parser.add_argument("--head-sha", required=True)
    open_parser.add_argument("--reason", required=True)
    close_parser = sub.add_parser("close")
    close_parser.add_argument("--path", type=Path, required=True)
    close_parser.add_argument("--recovery-run-id", required=True)
    close_parser.add_argument("--transaction-id", required=True)
    close_parser.add_argument("--candidate-version", required=True)
    close_parser.add_argument("--production-run-id", required=True)
    close_parser.add_argument("--head-sha", required=True)
    close_parser.add_argument("--reason", required=True)
    recovery_parser = sub.add_parser("recover-pretransaction")
    recovery_parser.add_argument("--path", type=Path, required=True)
    recovery_parser.add_argument("--incident-run", required=True)
    recovery_parser.add_argument("--failed-job", required=True)
    for name in ("transaction-created", "candidate-created", "upload-performed", "promotion-performed", "production-mutation"):
        recovery_parser.add_argument(f"--{name}", choices=("YES", "NO"), required=True)
    recovery_parser.add_argument("--fix-sha", required=True)
    recovery_parser.add_argument("--safety-test-run-id", required=True)
    recovery_parser.add_argument("--check-only-run-id", required=True)
    recovery_parser.add_argument("--live-state-parity", choices=("PASS", "FAIL"), required=True)
    recovery_parser.add_argument("--authorized", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "preflight":
        result = preflight(args.path, args.journal)
        _write_output(result)
        print(json.dumps(result, sort_keys=True))
        return 0
    state = load_state(args.path)
    if state is None:
        raise SystemExit("CIRCUIT_BREAKER_STATE_INVALID")
    if args.command == "observe-a6":
        results = json.loads(os.environ["A6_RESULTS"])
        failed = a6_failure(results, args.journal)
        if state["state"] == "CLOSED" and failed:
            result = opened_state(state, run_id=args.run_id, failed_stage=failed,
                                  head_sha=args.head_sha, reason=f"scheduled A6 run {args.run_id}: {failed}; inspect evidence before recovery")
        else:
            print(json.dumps({"state": state["state"], "failure": failed, "changed": False}, sort_keys=True))
            return 0
    elif args.command == "recover-a6":
        result = a6_closed_state(state, json.loads(args.evidence.read_text(encoding="utf-8")), args.repository, authorized=args.authorized)
    elif args.command == "close":
        result = closed_state(
            state,
            recovery_run_id=args.recovery_run_id,
            transaction_id=args.transaction_id,
            candidate_version=args.candidate_version,
            production_run_id=args.production_run_id,
            head_sha=args.head_sha,
            reason=args.reason,
        )
    elif args.command == "recover-pretransaction":
        result = pretransaction_closed_state(
            state,
            incident_run=args.incident_run,
            failed_job=args.failed_job,
            transaction_created=args.transaction_created,
            candidate_created=args.candidate_created,
            upload_performed=args.upload_performed,
            promotion_performed=args.promotion_performed,
            production_mutation=args.production_mutation,
            fix_sha=args.fix_sha,
            safety_test_run_id=args.safety_test_run_id,
            check_only_run_id=args.check_only_run_id,
            live_state_parity=args.live_state_parity,
            authorized=args.authorized,
        )
    else:
        result = opened_state(state, run_id=args.run_id, failed_stage=args.failed_job,
                              head_sha=args.head_sha, reason=args.reason)
    args.path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output = {"state": result["state"], "failed_job": result["failed_job"]}
    if args.command == "observe-a6":
        output["failure"] = failed
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
