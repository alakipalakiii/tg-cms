"""Static contracts for the MAHOON pre-cutover workflow safeguards."""
from pathlib import Path
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/mahoon-static-publisher.yml"


class PrecutoverRemediationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = WORKFLOW.read_text(encoding="utf-8")
        cls.workflow = yaml.load(cls.source, Loader=yaml.BaseLoader)
        cls.jobs = cls.workflow["jobs"]

    def test_mutation_credential_probe_is_removed(self):
        self.assertNotIn("ci-auth-probe", self.jobs)
        self.assertNotIn("auth_only", self.source)
        for name, job in self.jobs.items():
            if job.get("if") == "false":
                continue
            if "secrets.CLOUDFLARE_API_TOKEN" in str(job):
                self.assertTrue(name.startswith("cloudflare-") and name.endswith("-operation"), name)

    def test_schedule_safe_mode_fails_closed_to_check_only(self):
        job = self.jobs["check-only"]
        self.assertIn("vars.PUBLISHER_MODE_SCHEDULED != 'PUBLISH'", job["if"])
        self.assertIn("'PUBLISH' || 'CHECK_ONLY'", job["env"]["PUBLISHER_MODE"])
        self.assertIn("vars.PUBLISHER_MODE_SCHEDULED == 'PUBLISH'", self.source)
        self.assertIn("scheduled-policy-preflight.outputs.publish_allowed == 'true'", self.source)

    def test_manual_trigger_schedule_and_concurrency_are_preserved(self):
        self.assertIn("workflow_dispatch", self.workflow["on"])
        self.assertEqual([{"cron": "17,47 * * * *"}], self.workflow["on"]["schedule"])
        self.assertEqual("mahoon-production-publisher", self.workflow["concurrency"]["group"])
        self.assertEqual("false", self.workflow["concurrency"]["cancel-in-progress"])

    def test_read_only_probe_removal_preserves_a6_credential_boundaries(self):
        for name, job in self.jobs.items():
            text = str(job)
            if "secrets.CLOUDFLARE_READ_API_TOKEN" in text:
                self.assertNotIn("secrets.CLOUDFLARE_API_TOKEN", text, name)
                self.assertNotIn("contents: write", text, name)
            if "contents: write" in text:
                self.assertNotIn("CLOUDFLARE_API_TOKEN", text, name)
        self.assertIn("secrets.CLOUDFLARE_READ_API_TOKEN", self.source)
        self.assertIn("ref: '${{ github.sha }}', path: code", self.source)
        self.assertIn("ref: main, path: state", self.source)


if __name__ == "__main__":
    unittest.main()
