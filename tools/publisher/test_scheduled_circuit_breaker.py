from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.publisher.scheduled_circuit_breaker import (
    CONTRACT, closed_state as close_state, failed_job, load_state, opened_state, preflight, should_open_breaker,
)


def closed_state() -> dict:
    return {"contract": CONTRACT, "state": "CLOSED", "reason": None,
            "failed_run_id": None, "failed_job": None, "head_sha": None,
            "updated_at": "2026-09-20T00:00:00Z"}


class ScheduledCircuitBreakerTests(unittest.TestCase):
    def test_contract_and_closed_preflight_allow_publish(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "breaker.json"
            path.write_text(json.dumps(closed_state()), encoding="utf-8")
            self.assertEqual({"publish_allowed": True, "breaker_state": "CLOSED"}, preflight(path))

    def test_missing_malformed_and_unknown_state_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "breaker.json"
            self.assertEqual({"publish_allowed": False, "breaker_state": "INVALID"}, preflight(path))
            path.write_text("{}", encoding="utf-8")
            self.assertIsNone(load_state(path))
            broken = closed_state()
            broken["contract"] = "UNKNOWN"
            path.write_text(json.dumps(broken), encoding="utf-8")
            self.assertEqual({"publish_allowed": False, "breaker_state": "INVALID"}, preflight(path))

    def test_open_state_forces_check_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "breaker.json"
            state = closed_state()
            state["state"] = "OPEN"
            path.write_text(json.dumps(state), encoding="utf-8")
            self.assertEqual({"publish_allowed": False, "breaker_state": "OPEN"}, preflight(path))

    def test_no_change_keeps_breaker_closed(self):
        results = {"build-and-zero-percent": "success", "remote-proof": "skipped",
                   "promote-and-validate": "skipped", "persist-state": "skipped"}
        self.assertIsNone(failed_job(results))
        self.assertFalse(should_open_breaker("CLOSED", results))

    def test_build_failure_opens_breaker(self):
        self.assertTrue(should_open_breaker("CLOSED", {"build-and-zero-percent": "failure"}))

    def test_remote_failure_opens_breaker(self):
        self.assertTrue(should_open_breaker("CLOSED", {"remote-proof": "failure"}))

    def test_production_failure_after_rollback_opens_breaker(self):
        self.assertTrue(should_open_breaker("CLOSED", {"promote-and-validate": "failure"}))

    def test_persist_failure_opens_breaker(self):
        self.assertTrue(should_open_breaker("CLOSED", {"persist-state": "cancelled"}))

    def test_close_requires_complete_recovery_identity_and_clears_failure(self):
        state = closed_state()
        state["state"] = "OPEN"
        closed = close_state(state, recovery_run_id="35712700208",
                            transaction_id="revision-58-run-35708523802-attempt-1",
                            candidate_version="candidate",
                            production_run_id="35712700208",
                            head_sha="a" * 40, reason="verified recovery",
                            updated_at="2026-09-22T10:30:00Z")
        self.assertEqual("CLOSED", closed["state"])
        self.assertIsNone(closed["failed_run_id"])
        self.assertIsNone(closed["failed_job"])
        with self.assertRaises(ValueError):
            close_state(state, recovery_run_id="", transaction_id="tx",
                        candidate_version="candidate", production_run_id="run",
                        head_sha="a" * 40, reason="bad")
    def test_open_breaker_does_not_reopen(self):
        results = {job: "skipped" for job in ("build-and-zero-percent", "remote-proof",
                   "promote-and-validate", "persist-state")}
        self.assertFalse(should_open_breaker("OPEN", results))
        opened = opened_state(closed_state(), run_id="123", failed_stage="build-and-zero-percent",
                              head_sha="a" * 40, reason="build failed",
                              updated_at="2026-09-20T16:00:00Z")
        self.assertEqual("OPEN", opened["state"])
        self.assertEqual("123", opened["failed_run_id"])
        self.assertEqual("build-and-zero-percent", opened["failed_job"])
        self.assertEqual("a" * 40, opened["head_sha"])
        self.assertEqual("OPEN", opened_state(opened, run_id="456", failed_stage="x",
                                               head_sha="b" * 40, reason="new")["state"])

    def test_manual_recovery_contract_is_not_guarded_by_schedule_preflight(self):
        workflow = Path(".github/workflows/mahoon-static-publisher.yml").read_text(encoding="utf-8")
        self.assertIn("github.event_name == 'schedule'", workflow)
        self.assertIn("github.event_name == 'workflow_dispatch' && inputs.mode == 'PUBLISH'", workflow)
        self.assertIn("scheduled-policy-preflight", workflow)
        self.assertIn("PUBLISHER_MODE_SCHEDULED", workflow)

    def test_breaker_state_does_not_contain_secret_fields(self):
        state = closed_state()
        self.assertNotIn("token", state)
        self.assertNotIn("authorization", state)


if __name__ == "__main__":
    unittest.main()
