"""Fail-closed evidence contract for abandoning a provably unexecuted upload intent.

The abandonment path must prove, from read-only evidence only, that a recorded
mutation intent never reached the Cloudflare backend: the source workflow run
showed the exact mutation job SKIPPED (not success, failure, cancelled, or
rerun), no mutation step executed, no result artifact exists, and production
still equals the pre-run baseline. The module exposes one function that
checks a caller-supplied evidence document against the sealed artifacts and
returns the validated document. It writes nothing and accepts no credentials.
"""
from __future__ import annotations

import hashlib
from typing import Any, Mapping

from publisher import artifact_contract as contracts

EVIDENCE_TYPE = "MAHOON_UNEXECUTED_INTENT_ABANDONMENT_EVIDENCE_V1"
_FIELDS = {
    "evidence_type", "transaction_id", "content_revision",
    "source_run_id", "source_run_attempt", "source_run_head",
    "github_run_status", "github_run_conclusion", "github_attempts_count",
    "mutation_job_conclusion", "mutation_job_restarted",
    "upload_result_artifact_present", "upload_result_attempt_reported",
    "production_version_id", "production_deployment_id", "production_type",
    "production_baseline_equal", "production_evidence_sha256",
    "admission_artifact_sha256", "build_bundle_artifact_sha256",
    "upload_intent_artifact_sha256", "upload_attempt_id",
    "upload_operation_id", "evidence_sha256",
}
_GITHUB_EXACT = {
    "github_run_status": "completed",
    "github_run_conclusion": "failure",
    "github_attempts_count": 1,
    "mutation_job_conclusion": "skipped",
    "mutation_job_restarted": False,
}


class AbandonmentEvidenceRejected(ValueError):
    """Abandonment evidence is missing, drifted, or shows executed mutation."""


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or \
            any(c not in "0123456789abcdef" for c in value):
        raise AbandonmentEvidenceRejected(f"{label} is invalid")
    return value


def _body_sha(body: Mapping[str, Any]) -> str:
    return hashlib.sha256(contracts.canonical_json_bytes(dict(body))).hexdigest()


def _production_evidence_sha(evidence: Mapping[str, Any]) -> str:
    return _body_sha({
        "production_version_id": evidence.get("production_version_id"),
        "production_deployment_id": evidence.get("production_deployment_id"),
        "production_type": evidence.get("production_type"),
    })


def seal_abandonment_evidence(evidence: Mapping[str, Any]) -> dict:
    """Seal a caller-composed evidence document into its canonical form.

    The caller composes every field in ``_FIELDS`` except ``evidence_sha256``;
    sealing fills the digest and re-validates the schema.
    """
    body = {k: evidence.get(k) for k in _FIELDS if k != "evidence_sha256"}
    body["evidence_sha256"] = _body_sha(body)
    if set(body) != _FIELDS:
        raise AbandonmentEvidenceRejected("abandonment evidence is incomplete")
    return body


def validate_abandonment_evidence(value: object, *,
                                  transaction_id: str,
                                  expected_content_revision: int,
                                  expected_source_run_id: str,
                                  expected_source_run_attempt: int,
                                  expected_source_sha: str,
                                  build_bundle_sha256: str,
                                  upload_attempt: Mapping[str, Any],
                                  production_baseline: Mapping[str, Any] | None = None,
                                  ) -> dict:
    """Validate a caller-supplied evidence document. Write nothing.

    Fails closed on any of: a non-skipped mutation job conclusion, a rerun
    (attempts != 1), a present result artifact, a reported upload attempt,
    a drifted production baseline, a drifted artifact digest, or a
    transaction identity mismatch.
    """
    if not isinstance(value, Mapping) or set(value) != _FIELDS:
        raise AbandonmentEvidenceRejected("abandonment evidence schema is invalid")
    if value.get("evidence_type") != EVIDENCE_TYPE:
        raise AbandonmentEvidenceRejected("abandonment evidence type is invalid")
    if not isinstance(value.get("transaction_id"), str) or not value.get("transaction_id"):
        raise AbandonmentEvidenceRejected("transaction identity is missing")
    if value.get("transaction_id") != transaction_id:
        raise AbandonmentEvidenceRejected("transaction identity mismatch")
    if type(value.get("content_revision")) is not int \
            or isinstance(value.get("content_revision"), bool) \
            or value.get("content_revision") != expected_content_revision:
        raise AbandonmentEvidenceRejected("content revision does not match the expected revision")
    if not isinstance(value.get("source_run_id"), str) \
            or value.get("source_run_id") != expected_source_run_id:
        raise AbandonmentEvidenceRejected("source run ID does not match the expected run")
    if type(value.get("source_run_attempt")) is not int \
            or isinstance(value.get("source_run_attempt"), bool) \
            or value.get("source_run_attempt") != expected_source_run_attempt:
        raise AbandonmentEvidenceRejected("source run attempt does not match the expected attempt")
    if value.get("source_run_head") != expected_source_sha:
        raise AbandonmentEvidenceRejected("source run head SHA does not match the sealed build")
    if value.get("admission_artifact_sha256") is None:
        raise AbandonmentEvidenceRejected("admission artifact digest is missing")
    _sha(value.get("admission_artifact_sha256"), "admission_artifact_sha256")
    if value.get("build_bundle_artifact_sha256") != build_bundle_sha256:
        raise AbandonmentEvidenceRejected("build bundle digest does not match the sealed build")
    expected_intent_sha = _sha(upload_attempt.get("intent_artifact_sha256"), "upload intent digest")
    if value.get("upload_intent_artifact_sha256") != expected_intent_sha:
        raise AbandonmentEvidenceRejected("upload intent digest does not match the recorded attempt")
    if value.get("upload_attempt_id") != upload_attempt.get("attempt_id"):
        raise AbandonmentEvidenceRejected("upload attempt ID does not match the recorded attempt")
    if value.get("upload_operation_id") != upload_attempt.get("operation_id"):
        raise AbandonmentEvidenceRejected("upload operation ID does not match the recorded attempt")
    if value.get("upload_result_artifact_present") is not False:
        raise AbandonmentEvidenceRejected("a direct upload result artifact exists; mutation ran")
    if value.get("upload_result_attempt_reported") is not False:
        raise AbandonmentEvidenceRejected("an upload result was reported in the journal; mutation ran")
    if value.get("github_attempts_count") != 1:
        raise AbandonmentEvidenceRejected("source run was rerun; abandonment is not provable")
    for key, expected in _GITHUB_EXACT.items():
        if value.get(key) != expected:
            raise AbandonmentEvidenceRejected(
                f"github execution evidence: {key} is {value.get(key)!r}, expected {expected!r}")
    if value.get("production_baseline_equal") is not True:
        raise AbandonmentEvidenceRejected(
            "production baseline readback does not prove production is unchanged")
    expected_prod_sha = _production_evidence_sha(value)
    if _sha(value.get("production_evidence_sha256"), "production_evidence_sha256") != expected_prod_sha:
        raise AbandonmentEvidenceRejected("production evidence digest mismatch")
    if production_baseline:
        for key in ("production_version_id", "production_deployment_id", "production_type"):
            if value.get(key) != production_baseline.get(key):
                raise AbandonmentEvidenceRejected(
                    f"production readback {key} does not match the baseline")
    observed_body = {k: value[k] for k in _FIELDS if k != "evidence_sha256"}
    observed_sha = _body_sha(observed_body)
    if _sha(value.get("evidence_sha256"), "evidence_sha256") != observed_sha:
        raise AbandonmentEvidenceRejected("abandonment evidence digest mismatch")
    return dict(value)
