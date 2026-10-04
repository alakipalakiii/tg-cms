from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from tools.publisher.journal_cli import main
from tools.publisher.transaction_journal import empty_journal


class JournalCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "journal.json"
        self.path.write_text(json.dumps(empty_journal("synthetic-worker")), encoding="utf-8")
        self.base = ["--journal", str(self.path), "--worker", "synthetic-worker"]

    def _run(self, args: list[str]) -> tuple[int, dict]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(self.base + args)
        return code, json.loads(output.getvalue())

    def test_admit_and_record_intent_cli(self):
        code, admitted = self._run(["admit", "--revision", "41", "--source", "synthetic"])
        self.assertEqual(0, code)
        code, intent = self._run(["record-intent", "--transaction-id", admitted["transaction_id"],
                                  "--operation", "upload_version"])
        self.assertEqual(0, code)
        self.assertEqual("RECORDED", intent["status"])
        self.assertTrue(intent["operation_id"])
        self.assertTrue(intent["attempt_id"])

    def test_result_cli_requires_matching_intent_and_synthetic_evidence(self):
        _code, admitted = self._run(["admit", "--revision", "41", "--source", "synthetic"])
        _code, intent = self._run(["record-intent", "--transaction-id", admitted["transaction_id"],
                                   "--operation", "upload_version"])
        evidence = json.dumps({"type": "synthetic", "reference": "cli-test", "sha256": "b" * 64})
        code, result = self._run(["record-result", "--transaction-id", admitted["transaction_id"],
                                  "--operation-id", intent["operation_id"],
                                  "--attempt-id", intent["attempt_id"], "--outcome", "APPLIED",
                                  "--evidence-json", evidence])
        self.assertEqual(0, code)
        self.assertEqual("APPLIED", result["status"])

    def test_missing_journal_fails_closed(self):
        self.path.unlink()
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            code = main(self.base + ["admit", "--revision", "41", "--source", "synthetic"])
        self.assertEqual(2, code)
        self.assertEqual("JournalUnavailable", json.loads(errors.getvalue())["error"])


if __name__ == "__main__":
    unittest.main()
