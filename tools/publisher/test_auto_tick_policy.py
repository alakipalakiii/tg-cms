from pathlib import Path
import unittest


class AutoTickPolicyTests(unittest.TestCase):
    def setUp(self):
        self.workflow = Path(".github/workflows/mahoon-static-publisher.yml").read_text(encoding="utf-8")

    def test_auto_tick_policy_tests(self):
        self.assertIn("AUTO_TICK", self.workflow)
        self.assertIn("github.event_name == 'workflow_dispatch' && inputs.mode == 'AUTO_TICK'", self.workflow)
        self.assertIn("vars.PUBLISHER_MODE_SCHEDULED == 'PUBLISH'", self.workflow)
        self.assertIn("needs.scheduled-policy-preflight.outputs.publish_allowed == 'true'", self.workflow)
        self.assertIn("scheduled_circuit_breaker.py preflight", self.workflow)

    def test_manual_publish_semantics_unchanged(self):
        self.assertIn("inputs.mode == 'PUBLISH' && inputs.ready == 'YES'", self.workflow)
        self.assertIn("inputs.mode == 'PROMOTE_AND_VALIDATE' && inputs.ready == 'YES'", self.workflow)

    def test_automation_source_is_deterministic_and_safe(self):
        self.assertIn("github_schedule", self.workflow)
        self.assertIn("cloudflare_cron", self.workflow)
        self.assertNotIn("GITHUB_ACTIONS_TOKEN", self.workflow)
        self.assertIn('"automation_source": automation_source()', Path("tools/m9/publisher_runner.py").read_text(encoding="utf-8"))

    def test_scheduler_concurrency_is_preserved(self):
        self.assertIn("group: mahoon-production-publisher", self.workflow)
        self.assertIn("cancel-in-progress: false", self.workflow)


if __name__ == "__main__":
    unittest.main()