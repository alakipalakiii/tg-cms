"""Repository-persisted, fail-closed guard for scheduled publishing."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

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


def preflight(path: Path) -> dict[str, object]:
    state = load_state(path)
    if state is None:
        return {"publish_allowed": False, "breaker_state": "INVALID"}
    return {"publish_allowed": state["state"] == "CLOSED", "breaker_state": state["state"]}


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
        result = preflight(args.path)
        _write_output(result)
        print(json.dumps(result, sort_keys=True))
        return 0
    state = load_state(args.path)
    if state is None:
        raise SystemExit("CIRCUIT_BREAKER_STATE_INVALID")
    if args.command == "close":
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
    print(json.dumps({"state": result["state"], "failed_job": result["failed_job"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
