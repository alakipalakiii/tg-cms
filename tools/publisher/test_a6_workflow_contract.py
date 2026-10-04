"""Static contract checks for the separated A6 publisher workflow."""
from pathlib import Path
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/mahoon-static-publisher.yml"


class A6WorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = WORKFLOW.read_text(encoding="utf-8")
        cls.workflow = yaml.load(cls.source, Loader=yaml.BaseLoader)
        cls.jobs = cls.workflow["jobs"]

    def job(self, name):
        return str(self.jobs[name])

    def test_workflow_parses_and_preserves_dispatch_schedule_concurrency(self):
        self.assertIn("workflow_dispatch", self.workflow["on"])
        self.assertEqual([{"cron": "17,47 * * * *"}], self.workflow["on"]["schedule"])
        self.assertEqual("mahoon-production-publisher", self.workflow["concurrency"]["group"])
        self.assertEqual("false", self.workflow["concurrency"]["cancel-in-progress"])

    def test_source_is_pinned_and_state_branch_is_separate(self):
        self.assertIn("github.sha", self.source)
        self.assertIn("ref: main", self.source)
        self.assertIn("path: state", self.source)
        self.assertIn("--published-state state/publisher-state/production-content-fingerprint.json", self.source)
        self.assertNotIn("--published-state state/publisher-state/published-static-state.json", self.source)

    def test_authoritative_cli_boundaries_are_present_in_order(self):
        for name in ("journal-bootstrap", "revision-resolve", "admission", "build-validate",
                     "build-ready-write", "upload-intent-write", "cloudflare-upload-operation",
                     "upload-result-write", "zero-percent-intent-write",
                     "cloudflare-zero-percent-operation", "zero-percent-result-write",
                     "pre-promotion-proof", "promote-intent-write", "cloudflare-promote-operation",
                     "promote-result-write", "production-proof", "final-state-materialization",
                     "final-persistence"):
            self.assertIn(name, self.jobs)

    def test_no_legacy_combined_mutating_authority(self):
        for name in ("build-and-zero-percent", "remote-proof", "promote-and-validate",
                     "persist-state", "scheduled-circuit-breaker"):
            self.assertEqual("false", self.jobs[name].get("if"), name)
        for name, job in self.jobs.items():
            needs = job.get("needs", [])
            needs = [needs] if isinstance(needs, str) else needs
            if name not in {"promote-and-validate"} and name.startswith(("upload-", "zero-", "promote-", "rollback-", "cloudflare-")):
                self.assertTrue(not set(needs).intersection({"build-and-zero-percent", "remote-proof",
                                  "promote-and-validate", "persist-state"}), name)

    def test_recovery_is_fail_closed_and_never_retries(self):
        self.assertIn("RECONCILED_APPLIED", self.source)
        self.assertIn("UNKNOWN", self.source)
        self.assertNotRegex(self.source, r"(?i)retry.{0,40}mutation")
        self.assertNotIn("mutation_result.json', 'w'", self.source)
        for route in ("upload", "zero", "promote", "rollback"):
            bridge = self.job(f"{route}-create-recovered-result")
            self.assertIn("RECONCILED_APPLIED", bridge)
            self.assertNotIn("RECONCILED_NOT_APPLIED", bridge)
            self.assertNotIn("BLOCKED_UNKNOWN", bridge)

    def test_artifacts_are_transport_and_cli_revalidates_consumers(self):
        self.assertIn("actions/upload-artifact@v4", self.source)
        self.assertIn("actions/download-artifact@v4", self.source)
        self.assertIn("create-recovered-result", self.source)

    def test_credential_classes_are_separated_by_job_permissions(self):
        for job_name, job in self.jobs.items():
            text = str(job)
            if "CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}" in text:
                self.assertNotIn("contents: write", text, job_name)
                self.assertNotIn("CLOUDFLARE_READ_API_TOKEN", text, job_name)
            if "secrets.CLOUDFLARE_READ_API_TOKEN" in text:
                self.assertNotIn("contents: write", text, job_name)
                self.assertNotIn("secrets.CLOUDFLARE_API_TOKEN", text, job_name)
            if "contents: write" in text:
                self.assertNotIn("CLOUDFLARE_API_TOKEN", text, job_name)

    def test_finalization_uses_materializer_then_integrated_executor(self):
        self.assertIn("production-proof", str(self.jobs["final-state-materialization"].get("needs")))
        self.assertIn("final-state-materialization", str(self.jobs["final-persistence"].get("needs")))
        self.assertNotIn("final-persistence-validate", self.source)

    def test_all_unknown_recovery_routes_are_applied_only_and_fail_closed(self):
        routes = {
            "upload": ("upload-recovery-readback-observe", "upload-recovery-decision",
                       "upload-reconcile-recovery-decision", "upload-create-recovered-result"),
            "zero": ("zero-recovery-readback-observe", "zero-recovery-decision",
                     "zero-reconcile-recovery-decision", "zero-create-recovered-result"),
            "promote": ("promote-recovery-readback-observe", "promote-recovery-decision",
                        "promote-reconcile-recovery-decision", "promote-create-recovered-result"),
            "rollback": ("rollback-recovery-readback-observe", "rollback-recovery-decision",
                         "rollback-reconcile-recovery-decision", "rollback-create-recovered-result"),
        }
        self.assertEqual(4, len(routes))
        for route, (readback, decision, reconcile, bridge) in routes.items():
            with self.subTest(route=route):
                self.assertIn("UNKNOWN", str(self.jobs[readback]))
                self.assertIn("recovery-readback-observe", str(self.jobs[readback]))
                self.assertIn("recovery-decision", str(self.jobs[decision]))
                self.assertIn(readback, str(self.jobs[decision].get("needs")))
                self.assertIn("reconcile-recovery-decision", str(self.jobs[reconcile]))
                self.assertIn(decision, str(self.jobs[reconcile].get("needs")))
                self.assertIn("RECONCILED_APPLIED", str(self.jobs[bridge]))
                self.assertIn(reconcile, str(self.jobs[bridge].get("needs")))
                self.assertIn("create-recovered-result", str(self.jobs[bridge]))
                for job in (readback, decision, reconcile, bridge):
                    self.assertNotIn("execute-operation", str(self.jobs[job]), job)

    def test_recovered_results_rejoin_their_success_paths_only(self):
        self.assertIn("upload-create-recovered-result", str(self.jobs["zero-percent-intent-write"].get("needs")))
        self.assertIn("zero-create-recovered-result", str(self.jobs["pre-promotion-proof"].get("needs")))
        self.assertIn("promote-create-recovered-result", str(self.jobs["production-proof"].get("needs")))
        self.assertNotIn("rollback-create-recovered-result", str(self.jobs["final-persistence"].get("needs")))

    def test_direct_applied_routes_bypass_recovery(self):
        self.assertIn("result_state == 'APPLIED'", self.job("zero-percent-intent-write"))
        self.assertIn("result_state == 'APPLIED'", self.job("pre-promotion-proof"))
        self.assertIn("result_state == 'APPLIED'", self.job("production-proof"))
        for route, result_writer in (("upload", "upload-result-write"),
                                     ("zero", "zero-percent-result-write"),
                                     ("promote", "promote-result-write"),
                                     ("rollback", "rollback-result-write")):
            with self.subTest(route=route):
                self.assertIn("result_state", self.job(result_writer))
                self.assertIn("UNKNOWN", self.job(f"{route}-recovery-readback-observe"))

    def test_applied_bridge_paths_are_consumed_as_files(self):
        self.assertIn("handoff/recovered-upload-result.json", self.job("zero-percent-intent-write"))
        self.assertIn("handoff/recovered-upload-result.json", self.job("cloudflare-zero-percent-operation"))
        self.assertIn("handoff/recovered-zero-result.json", self.job("pre-promotion-proof"))
        self.assertIn("handoff/recovered-zero-result.json", self.job("promote-intent-write"))
        self.assertIn("handoff/recovered-promote-result.json", self.job("production-proof"))
        self.assertIn("handoff/recovered-promote-result.json", self.job("final-state-materialization"))
        self.assertIn("handoff/recovered-promote-result.json", self.job("final-persistence"))
        self.assertNotIn("rollback-create-recovered-result", self.job("final-state-materialization"))

    def test_recovery_bridges_are_applied_only_and_never_reexecute_mutations(self):
        for route in ("upload", "zero", "promote", "rollback"):
            bridge = self.job(f"{route}-create-recovered-result")
            self.assertIn("RECONCILED_APPLIED", bridge)
            self.assertNotIn("RECONCILED_NOT_APPLIED", bridge)
            self.assertNotIn("BLOCKED_UNKNOWN", bridge)
            self.assertNotIn("execute-operation", bridge)
        self.assertNotIn("A6 upload intent requires", self.source)
        self.assertNotIn("A6 zero-percent intent boundary", self.source)
        self.assertNotIn("A6 rollback mutation boundary", self.source)

    def test_recovery_routes_use_the_matching_original_intent_and_result(self):
        originals = {
            "upload": ("upload-intent.json", "upload-result.json"),
            "zero": ("zero-percent-intent.json", "zero-percent-result.json"),
            "promote": ("promote-intent.json", "promote-result.json"),
            "rollback": ("rollback-intent.json", "rollback-result.json"),
        }
        self.assertEqual(4, len(originals))
        for route, (intent, result) in originals.items():
            with self.subTest(route=route):
                self.assertIn(intent, self.job(f"{route}-recovery-readback-observe"))
                self.assertIn(result, self.job(f"{route}-recovery-readback-observe"))
                self.assertIn(intent, self.job(f"{route}-recovery-decision"))
                self.assertIn(result, self.job(f"{route}-recovery-decision"))
                self.assertIn("recovery-readback-observe", self.job(f"{route}-recovery-readback-observe"))
                self.assertIn("reconcile-recovery-decision", self.job(f"{route}-reconcile-recovery-decision"))

    def test_no_implementation_echoes_remain(self):
        self.assertNotRegex(self.source, r'(?im)^\s*-?\s*run:\s*echo\s+["\']A6\b')


if __name__ == "__main__":
    unittest.main()
