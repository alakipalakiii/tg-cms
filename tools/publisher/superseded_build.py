"""Retire automatic snapshots only at the independently verified pre-mutation boundary."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from publisher import artifact_transport
from publisher.content_revision import fetch_public_content_revision
from publisher.repository_persistence import GitJournalWriter, _git
from publisher.transaction_journal import journal_digest

SKIPPED_JOBS = (
    "build-ready-write", "upload-intent-write", "cloudflare-upload-operation", "upload-result-write",
    "zero-percent-intent-write", "cloudflare-zero-percent-operation", "zero-percent-result-write",
    "pre-promotion-proof", "promote-intent-write", "cloudflare-promote-operation", "promote-result-write",
    "production-proof", "final-state-materialization", "final-persistence",
    "rollback-intent-write", "cloudflare-rollback-operation", "rollback-result-write",
)


def revision_disposition(expected: int, current: int, *, automatic: bool, resume: bool) -> str:
    if type(expected) is not int or type(current) is not int or min(expected, current) < 1:
        raise ValueError("invalid public revision")
    if current == expected:
        return "STABLE"
    if automatic and not resume and current > expected:
        return "SUPERSEDED"
    raise ValueError("public revision changed; publication forbidden")


def pristine(tx: dict) -> bool:
    return (tx["build_bundle_sha256"] is None and tx["proof_evidence_sha256"] is None
            and tx["state_commit_sha"] is None and tx["recovery_status"] == "NONE"
            and all(op["attempts"] == [] and op["intent_state"] == "NOT_STARTED"
                    and op["result_state"] == "NOT_REPORTED" for op in tx["operations"].values()))


def retire(repository: Path, revision_path: Path, admission_path: Path, context_path: Path,
           source_sha: str, run_id: str, *, api=None) -> dict:
    from publisher.workflow_stage_cli import _run_gh_api, validate_execution_source

    base = os.environ["GITHUB_REPOSITORY"]
    if os.environ.get("GITHUB_RUN_ID") != run_id or os.environ.get("GITHUB_RUN_ATTEMPT") != "1":
        raise ValueError("retirement must run in its original execution")
    if api is None:
        api = lambda path: json.loads(_run_gh_api(base, path, env=dict(os.environ)))
    context = json.loads(context_path.read_text(encoding="utf-8"))
    if (context.get("event") != "schedule" and not (
            context.get("event") == "workflow_dispatch" and context.get("mode") == "AUTO_TICK")):
        raise ValueError("only automatic snapshots may retire unattended")
    run = api(f"actions/runs/{run_id}")
    validate_execution_source(run, source_sha, base, run_id, 1, context)
    if (run.get("run_attempt") != 1 or run.get("status") != "in_progress"
            or run.get("head_repository", {}).get("full_name") != base):
        raise ValueError("retirement requires the original running workflow")
    revision = artifact_transport.read_artifact(revision_path, expected_type="revision_resolution",
                                                expected_source_sha=source_sha)
    admission = artifact_transport.read_artifact(admission_path, expected_type="admission_receipt",
        expected_transaction=revision["transaction"], expected_source_sha=source_sha,
        referenced_artifacts=artifact_transport.references(revision))
    for seal in (revision, admission):
        if seal["producer"]["workflow_run_id"] != run_id or seal["producer"]["run_attempt"] != 1:
            raise ValueError("snapshot belongs to another execution")
    if revision["payload"]["decision"] != "CHANGED" or admission["payload"]["decision"] != "ADMITTED":
        raise ValueError("retirement requires a fresh admission")
    tx_id = revision["transaction"]["logical_transaction_id"]
    if admission["payload"]["active_transaction_id"] != tx_id:
        raise ValueError("admission active identity differs")
    jobs_page = api(f"actions/runs/{run_id}/jobs?per_page=100")
    rows = jobs_page["jobs"]
    jobs = {row["name"]: row for row in rows}
    if jobs_page["total_count"] != len(rows) or len(jobs) != len(rows):
        raise ValueError("incomplete or ambiguous job evidence")
    if any(row.get("conclusion") in {"failure", "cancelled", "timed_out", "action_required"} for row in rows):
        raise ValueError("actual workflow failure cannot be retired automatically")
    if jobs.get("build-validate", {}).get("conclusion") != "success":
        raise ValueError("build did not finish safely")
    for name in SKIPPED_JOBS:
        row = jobs.get(name, {})
        if row.get("status") != "completed" or row.get("conclusion") != "skipped" or row.get("steps"):
            raise ValueError("pre-mutation boundary not proven: " + name)
    page = api(f"actions/runs/{run_id}/artifacts?per_page=100")
    if page["total_count"] != len(page["artifacts"]):
        raise ValueError("incomplete artifact evidence")
    allowed = {f"a6-{name}-{run_id}" for name in ("execution-source", "revision", "admission")}
    if ({row["name"] for row in page["artifacts"]} != allowed or len(page["artifacts"]) != len(allowed)
            or any(row.get("expired") is not False for row in page["artifacts"])):
        raise ValueError("unexpected build or operation artifact")
    writer = GitJournalWriter(repository, "mahoon-art-magazine")
    state, generation, digest = writer._confirm_current()
    # A queued old workflow may use current source; compare executable files, not state-only commits.
    if _git(repository, "diff", "--quiet", source_sha, "HEAD", "--", 
            ".github/workflows/mahoon-static-publisher.yml", "tools/publisher", "tools/m9/publisher_runner.py",
            check=False).returncode:
        raise ValueError("executable source changed during build")
    if _git(repository, "diff", "--quiet", run["head_sha"], source_sha, "--",
            ".github/workflows/mahoon-static-publisher.yml", check=False).returncode:
        raise ValueError("queued workflow differs from the executable workflow")
    active = state["active"]
    if (active is None or active["logical_transaction_id"] != tx_id or not pristine(active)
            or state["pending"] is not None or active["state"] != "admitted"
            or generation != admission["payload"]["journal_generation"]
            or digest != admission["payload"]["journal_sha256"]
            or [(x["run_id"], x["attempt_id"]) for x in active["execution_attempts"]] != [(run_id, "1")]):
        raise ValueError("journal no longer matches the untouched admission")
    current, _changed, _meta = fetch_public_content_revision()
    if revision_disposition(active["content_revision"], current, automatic=True, resume=False) != "SUPERSEDED":
        raise ValueError("snapshot is not superseded")
    result = writer.retire_stale_admitted_v2(tx_id, active["content_revision"],
        expected_generation=generation, expected_digest=digest)
    return {**result, "status": "RETIRED_SUPERSEDED", "observed_public_revision": current}


def verified_retirement(results: dict, journal: dict) -> bool:
    result = results.get("superseded-build-retirement", {})
    outputs = result.get("outputs", {})
    tx = next((item for item in journal["history"]
               if item["logical_transaction_id"] == outputs.get("retired_transaction_id")), None)
    return (result.get("result") == "success" and outputs.get("status") == "RETIRED_SUPERSEDED"
            and results.get("build-validate", {}).get("result") == "success"
            and results.get("build-validate", {}).get("outputs", {}).get("superseded") == "true"
            and all(results.get(name, {}).get("result") == "skipped" for name in SKIPPED_JOBS)
            and journal["active"] is None and journal["pending"] is None
            and str(journal["generation"]) == outputs.get("generation")
            and journal_digest(journal) == outputs.get("journal_sha256")
            and tx is not None and tx["state"] == "blocked" and pristine(tx))


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in ("repository", "revision", "admission", "execution-context", "source-sha", "run-id"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    result = retire(Path(args.repository), Path(args.revision), Path(args.admission),
                    Path(args.execution_context), args.source_sha, args.run_id)
    print(json.dumps(result, sort_keys=True))
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        for key in ("status", "generation", "journal_sha256", "retired_transaction_id"):
            output.write(f"{key}={result[key]}\n")


if __name__ == "__main__":
    main()
