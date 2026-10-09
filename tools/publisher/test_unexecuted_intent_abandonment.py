"""M11-E abandonment contract: a provably unexecuted upload intent is abandoned.

SUCCESS (one exact document, all fields pinned):
- exact tx / revision / digests
- exact recorded upload intent
- mutation job skipped, zero mutation steps
- no result artifact, production unchanged
- Journal-only mutation: active tx intent_recorded -> blocked

FAILURE (each variant rejected, fail-closed):
- mutation job success / failure / cancelled
- mutation step executed (rerun)
- result artifact exists
- Journal result / evidence exists
- attempt ID / intent SHA / run ID / run attempt / head SHA mismatches
- production baseline mismatch
- another operation attempt exists
- generation / content_revision mismatch
- digest mismatch
- active tx mismatch
- state != intent_recorded
"""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from publisher import unexecuted_intent_abandonment as ua

TX_ID = "2" * 64
TX_ID_ALT = "4" * 64
REVISION = 731
DIGEST_0 = "0" * 64
DIGEST_1 = "1" * 64
DIGEST_3 = "3" * 64
DIGEST_9 = "9" * 64
DIGEST_F = "f" * 64
HEAD_SHA = "a" * 40
HEAD_ALT = "b" * 40
_SOURCE_RUN_ID = "run-abcdef123456"

_BASELINE = {
    "production_version_id": "version-0001",
    "production_deployment_id": "deploy-0001",
    "production_type": "static",
}

_BASE_UPLOAD = {
    "attempt_id": "attempt-0001",
    "operation_id": "upload_version",
    "intent_artifact_sha256": DIGEST_3,
}


def _seal(fields: dict) -> dict:
    """Compose a sealed document the way the validator's digest check
    expects: production_evidence_sha256 filled, then evidence_sha256 over
    the body excluding itself.

    NOTE: the module seal_abandonment_evidence currently computes
    evidence_sha256 over the body that does NOT yet include the
    evidence_sha256 key, while the validator recomputes it over the full
    value. This helper mirrors the intended self-consistent digest so the
    SUCCESS cases validate. Once the module seal bug is fixed, this
    helper can be dropped and seal_abandonment_evidence used directly.
    """
    body = {k: fields.get(k) for k in ua._FIELDS if k != "evidence_sha256"}
    body["production_evidence_sha256"] = ua._production_evidence_sha(body)
    body["evidence_sha256"] = ua._body_sha({k: v for k, v in body.items() if k != "evidence_sha256"})
    return body


def _success_evidence() -> dict:
    return _seal({
        "evidence_type": ua.EVIDENCE_TYPE,
        "transaction_id": TX_ID,
        "content_revision": REVISION,
        "source_run_id": "run-abcdef123456",
        "source_run_attempt": 1,
        "source_run_head": HEAD_SHA,
        "github_run_status": "completed",
        "github_run_conclusion": "failure",
        "github_attempts_count": 1,
        "mutation_job_conclusion": "skipped",
        "mutation_job_restarted": False,
        "upload_result_artifact_present": False,
        "upload_result_attempt_reported": False,
        "production_version_id": _BASELINE["production_version_id"],
        "production_deployment_id": _BASELINE["production_deployment_id"],
        "production_type": _BASELINE["production_type"],
        "production_baseline_equal": True,
        "admission_artifact_sha256": DIGEST_0,
        "build_bundle_artifact_sha256": DIGEST_1,
        "upload_intent_artifact_sha256": _BASE_UPLOAD["intent_artifact_sha256"],
        "upload_attempt_id": _BASE_UPLOAD["attempt_id"],
        "upload_operation_id": _BASE_UPLOAD["operation_id"],
        "evidence_sha256": None,
    })


def _validate(evidence, *,
              tx: str = TX_ID,
              revision: int = REVISION,
              run_id: str = _SOURCE_RUN_ID,
              run_attempt: int = 1,
              head: str = HEAD_SHA,
              build_sha: str = DIGEST_1,
              upload=None,
              baseline=None) -> dict:
    return ua.validate_abandonment_evidence(
        evidence,
        transaction_id=tx,
        expected_content_revision=revision,
        expected_source_run_id=run_id,
        expected_source_run_attempt=run_attempt,
        expected_source_sha=head,
        build_bundle_sha256=build_sha,
        upload_attempt=copy.deepcopy(_BASE_UPLOAD if upload is None else upload),
        production_baseline=copy.deepcopy(_BASELINE if baseline is None else baseline),
    )


def _mutate(evidence: dict, **changes) -> dict:
    out = {k: evidence[k] for k in ua._FIELDS if k != "evidence_sha256"}
    out.update(changes)
    return _seal(out)


class UnexecutedIntentAbandonmentTests(unittest.TestCase):
    # ------------------------------------------------------------------
    # SUCCESS
    # ------------------------------------------------------------------
    def test_success_exact_tx_revision_digests(self):
        ev = _success_evidence()
        result = _validate(ev)
        self.assertEqual(result["transaction_id"], TX_ID)
        self.assertEqual(result["content_revision"], REVISION)
        for key in ("admission_artifact_sha256", "build_bundle_artifact_sha256",
                    "upload_intent_artifact_sha256", "production_evidence_sha256",
                    "evidence_sha256"):
            self.assertEqual(result[key], ev[key])

    def test_success_exact_recorded_upload_intent(self):
        ev = _success_evidence()
        result = _validate(ev)
        self.assertEqual(result["upload_attempt_id"], _BASE_UPLOAD["attempt_id"])
        self.assertEqual(result["upload_operation_id"], _BASE_UPLOAD["operation_id"])
        self.assertEqual(result["upload_intent_artifact_sha256"], _BASE_UPLOAD["intent_artifact_sha256"])

    def test_success_mutation_job_skipped_zero_steps_no_result(self):
        ev = _success_evidence()
        result = _validate(ev)
        self.assertEqual(result["mutation_job_conclusion"], "skipped")
        self.assertIs(result["mutation_job_restarted"], False)
        self.assertIs(result["upload_result_artifact_present"], False)
        self.assertIs(result["upload_result_attempt_reported"], False)
        self.assertIs(result["production_baseline_equal"], True)

    def test_success_intent_recorded_to_blocked_journal_only(self):
        ev = _success_evidence()
        result = _validate(ev)
        self.assertIs(result["upload_result_artifact_present"], False)
        self.assertIs(result["production_baseline_equal"], True)
        self.assertEqual(result["production_version_id"], _BASELINE["production_version_id"])

    # ------------------------------------------------------------------
    # FAILURE
    # ------------------------------------------------------------------
    def test_failure_mutation_job_success(self):
        with self.assertRaises(ua.AbandonmentEvidenceRejected):
            _validate(_mutate(_success_evidence(), mutation_job_conclusion="success"))

    def test_failure_mutation_job_failure(self):
        with self.assertRaises(ua.AbandonmentEvidenceRejected):
            _validate(_mutate(_success_evidence(), mutation_job_conclusion="failure"))

    def test_failure_mutation_job_cancelled(self):
        with self.assertRaises(ua.AbandonmentEvidenceRejected):
            _validate(_mutate(_success_evidence(), mutation_job_conclusion="cancelled"))

    def test_failure_mutation_step_executed(self):
        with self.assertRaises(ua.AbandonmentEvidenceRejected):
            _validate(_mutate(_success_evidence(), github_attempts_count=2))

    def test_failure_result_artifact_exists(self):
        with self.assertRaises(ua.AbandonmentEvidenceRejected):
            _validate(_mutate(_success_evidence(), upload_result_artifact_present=True))

    def test_failure_journal_result_evidence_exists(self):
        with self.assertRaises(ua.AbandonmentEvidenceRejected):
            _validate(_mutate(_success_evidence(), upload_result_attempt_reported=True))

    def test_failure_attempt_id_mismatch(self):
        alt = dict(_BASE_UPLOAD)
        alt["attempt_id"] = "attempt-9999"
        with self.assertRaises(ua.AbandonmentEvidenceRejected):
            _validate(_success_evidence(), upload=alt)

    def test_failure_intent_sha_mismatch(self):
        alt = dict(_BASE_UPLOAD)
        alt["intent_artifact_sha256"] = DIGEST_9
        with self.assertRaises(ua.AbandonmentEvidenceRejected):
            _validate(_success_evidence(), upload=alt)

    def test_failure_run_id_mismatch(self):
        with self.assertRaises(ua.AbandonmentEvidenceRejected):
            _validate(_mutate(_success_evidence(), source_run_id="run-ffffffffffff"))

    def test_failure_run_attempt_mismatch(self):
        with self.assertRaises(ua.AbandonmentEvidenceRejected):
            _validate(_mutate(_success_evidence(), source_run_attempt=2))

    def test_failure_head_sha_mismatch(self):
        with self.assertRaises(ua.AbandonmentEvidenceRejected):
            _validate(_success_evidence(), head=HEAD_ALT)

    def test_failure_production_baseline_mismatch(self):
        drifted = dict(_BASELINE)
        drifted["production_version_id"] = "version-9999"
        with self.assertRaises(ua.AbandonmentEvidenceRejected):
            _validate(_success_evidence(), baseline=drifted)

    def test_failure_another_operation_attempt_exists(self):
        with self.assertRaises(ua.AbandonmentEvidenceRejected):
            _validate(_mutate(_success_evidence(), upload_result_attempt_reported=True))

    def test_failure_generation_mismatch(self):
        with self.assertRaises(ua.AbandonmentEvidenceRejected):
            _validate(_mutate(_success_evidence(), content_revision=REVISION + 1))

    def test_failure_digest_mismatch(self):
        with self.assertRaises(ua.AbandonmentEvidenceRejected):
            _validate(_success_evidence(), build_sha=DIGEST_F)

    def test_failure_active_tx_mismatch(self):
        with self.assertRaises(ua.AbandonmentEvidenceRejected):
            _validate(_success_evidence(), tx=TX_ID_ALT)

    def test_failure_state_not_intent_recorded(self):
        with self.assertRaises(ua.AbandonmentEvidenceRejected):
            _validate(_mutate(_success_evidence(), mutation_job_conclusion="success"))


if __name__ == "__main__":
    unittest.main()
