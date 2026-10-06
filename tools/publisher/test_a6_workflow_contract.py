"""Static contract checks for the separated A6 publisher workflow."""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/mahoon-static-publisher.yml"
ROOT = WORKFLOW.parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from publisher import artifact_contract, artifact_transport
from publisher import workflow_stage_cli
from publisher.transaction_journal import empty_journal, serialize_journal

TX_ID = "704bdb7d7161c7c5c89ef4865788e71a67df26fd2fe4cfb695d297c3900d18d2"
SOURCE_SHA = "f8d30ea474129c3630e309febe381b76b249de23"
REVISION_RAW_SHA = "3213bd781b7ac9cfa97e2957b3ee90e94e69f03258538d6cb39f2d2ad1fbd408"
ADMISSION_RAW_SHA = "2ade3405f29e62b58b974aace02b2f722a4e6a6ce2646840350e5a33eb2e1639"


def _run_workflow_script(script, cwd, env, offline_revision=None):
    launcher = """
import os, sys, types
source = sys.stdin.read()
if os.environ.get('TEST_OFFLINE_REVISION'):
    import publisher
    module = types.ModuleType('publisher.content_revision')
    module.fetch_public_content_revision = lambda: (('111' if os.environ['TEST_OFFLINE_REVISION'] == 'malformed' else int(os.environ['TEST_OFFLINE_REVISION'])), '2026-10-05T21:33:21+00:00', {'offline': True})
    sys.modules['publisher.content_revision'] = module
exec(compile(source, '<workflow-run-block>', 'exec'), {'__name__': '__main__'})
"""
    child_env = os.environ.copy()
    child_env.update(env)
    child_env["PYTHONPATH"] = os.pathsep.join((str(ROOT / "tools/publisher"), str(ROOT / "tools"), str(ROOT)))
    if offline_revision is not None:
        child_env["TEST_OFFLINE_REVISION"] = str(offline_revision)
    else:
        child_env.pop("TEST_OFFLINE_REVISION", None)
    return subprocess.run(
        [sys.executable, "-c", launcher], input=script, text=True, cwd=cwd,
        env=child_env, capture_output=True, check=False,
    )


def _python_heredoc(run_block):
    lines = run_block.splitlines()
    start = next(i for i, line in enumerate(lines)
                 if re.fullmatch(r"(?:[A-Z_]+=[^ ]+ )?python - <<'PY'", line))
    end = next(i for i in range(start + 1, len(lines)) if lines[i] == "PY")
    return "\n".join(lines[start + 1:end]) + "\n"


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
        inputs = self.workflow["on"]["workflow_dispatch"]["inputs"]
        self.assertIn("RESUME_ADMITTED", inputs["mode"]["options"])
        self.assertIn("resume_source_sha", inputs)
        self.assertIn("RETIRE_STALE_ADMITTED", inputs["mode"]["options"])
        self.assertEqual([{"cron": "17,47 * * * *"}], self.workflow["on"]["schedule"])
        self.assertEqual("mahoon-production-publisher", self.workflow["concurrency"]["group"])
        self.assertEqual("false", self.workflow["concurrency"]["cancel-in-progress"])

    def test_retirement_path_is_isolated_and_revision_gates_are_mandatory(self):
        retire = self.jobs["retire-stale-admitted"]
        self.assertEqual({"contents": "write"}, retire["permissions"])
        self.assertNotIn("CLOUDFLARE", str(retire))
        self.assertIn("RETIRE_STALE_ADMITTED", self.job("journal-bootstrap"))
        self.assertIn("STALE_ADMITTED", self.job("retire-stale-admitted"))
        self.assertIn("production-baseline-reconciliation", self.jobs)
        self.assertIn("secrets.CLOUDFLARE_READ_API_TOKEN", self.job("production-baseline-reconciliation"))
        self.assertNotIn("CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}", self.job("production-baseline-reconciliation"))
        self.assertIn("PUBLIC_REVISION_CHANGED_BEFORE_BUILD", self.job("build-validate"))
        self.assertIn("PUBLIC_REVISION_CHANGED_DURING_BUILD", self.job("build-validate"))
        self.assertLess(self.job("build-validate").index("PRE_BUILD_REVISION_STABLE"), self.job("build-validate").index("npm ci"))
        self.assertLess(self.job("build-validate").index("POST_BUILD_REVISION_STABLE"), self.job("build-validate").index("a6-build-${{ github.run_id }}"))
        self.assertIn("needs.production-baseline-reconciliation.result == 'success'", self.job("upload-intent-write"))

    def test_pre_and_post_build_gates_execute_with_dynamic_revisions_offline(self):
        pre = _python_heredoc(next(step["run"] for step in self.jobs["build-validate"]["steps"] if step.get("name") == "Validate current admission and public revision before build"))
        post = _python_heredoc(next(step["run"] for step in self.jobs["build-validate"]["steps"] if step.get("name") == "Recheck public content revision before build artifact handoff"))
        source = "a" * 40
        with tempfile.TemporaryDirectory(prefix="mahoon-a6-revision-gates-") as directory:
            cwd = Path(directory)
            state_dir = cwd / "state/publisher-state"
            state_dir.mkdir(parents=True)
            (state_dir / "production-transaction-journal.json").write_bytes(serialize_journal(empty_journal("mahoon-art-magazine")))
            (state_dir / "published-static-state.json").write_text(json.dumps({"published_content_revision": 80}), encoding="utf-8")
            revision = workflow_stage_cli.create_revision_resolution(
                state_dir / "published-static-state.json", source_sha=source,
                fetcher=lambda _endpoint: ({"revision": 111, "changed_at": "2026-10-06T00:00:00Z"}, {"offline": True}),
            )
            revision_path = cwd / "handoff/revision-resolution.json"
            admission_path = cwd / "handoff/admission.json"
            revision_path.parent.mkdir(parents=True)
            artifact_transport.write_artifact(revision_path, revision, expected_type="revision_resolution")
            admission = workflow_stage_cli.create_admission_receipt(
                revision_path, state_dir / "production-transaction-journal.json", "workflow_dispatch", "run-a6", "1",
            )
            artifact_transport.write_artifact(admission_path, admission, expected_type="admission_receipt",
                                              referenced_artifacts=artifact_transport.references(revision))
            env = {"EXECUTION_SHA": source, "RESUME_MODE": "false"}

            def run(script, public_revision):
                return _run_workflow_script(script, cwd, env, offline_revision=public_revision)

            for script in (pre, post):
                stable = run(script, 111)
                self.assertEqual(0, stable.returncode, stable.stderr)
            self.assertNotEqual(0, run(pre, 112).returncode)
            self.assertNotEqual(0, run(post, 112).returncode)
            for older in (109, 108, "malformed"):
                with self.subTest(public_revision=older):
                    self.assertNotEqual(0, run(pre, older).returncode)

    def test_source_is_pinned_and_state_branch_is_separate(self):
        self.assertIn("github.sha", self.source)
        self.assertIn("ref: main", self.source)
        self.assertIn("path: state", self.source)
        self.assertIn("--published-state state/publisher-state/production-content-fingerprint.json", self.source)
        self.assertNotIn("--published-state state/publisher-state/published-static-state.json", self.source)
        self.assertIn("MAHOON_EXECUTION_SHA: ${{ inputs.mode == 'RESUME_ADMITTED' && inputs.resume_source_sha || github.sha }}", self.source)
        self.assertIn("persist-credentials", self.job("journal-resume-verify"))

    def test_authoritative_cli_boundaries_are_present_in_order(self):
        for name in ("journal-bootstrap", "revision-resolve", "admission", "build-validate",
                     "build-ready-write", "upload-intent-write", "cloudflare-upload-operation",
                     "upload-result-write", "zero-percent-intent-write",
                     "cloudflare-zero-percent-operation", "zero-percent-result-write",
                     "pre-promotion-proof", "promote-intent-write", "cloudflare-promote-operation",
                     "promote-result-write", "production-proof", "final-state-materialization",
                     "final-persistence"):
            self.assertIn(name, self.jobs)
        self.assertIn("journal-resume-verify", self.jobs["revision-resolve"]["needs"])
        self.assertIn("needs.journal-resume-verify.result == 'success'", self.job("revision-resolve"))
        self.assertIn("needs.revision-resolve.result == 'success'", self.job("resume-admission"))
        self.assertIn("needs.resume-admission.result == 'success'", self.job("build-validate"))
        self.assertIn("inputs.ready", self.job("journal-resume-verify"))
        self.assertIn("a6-revision-${{ inputs.source_run_id }}", self.job("revision-resolve"))
        self.assertIn("a6-admission-${{ inputs.source_run_id }}", self.job("resume-admission"))
        self.assertIn("public_revision == 109", self.job("revision-resolve"))
        self.assertIn("RESUME_PUBLIC_REVISION_MISMATCH", self.job("build-validate"))

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
        self.assertIn("artifact_transport.references(revision)", self.job("resume-admission"))
        self.assertIn("shutil.copyfile(original, \"revision-resolution.json\")", self.job("revision-resolve"))
        self.assertIn("shutil.copyfile(original, \"runner-evidence/a6/admission.json\")", self.job("resume-admission"))
        self.assertIn(REVISION_RAW_SHA, self.job("revision-resolve"))
        self.assertIn(ADMISSION_RAW_SHA, self.job("resume-admission"))
        self.assertIn("artifact_contract.validate_artifact", self.job("revision-resolve"))
        self.assertIn("artifact_contract.validate_artifact", self.job("resume-admission"))
        self.assertIn('operation["intent_state"]', self.job("journal-resume-verify"))
        self.assertIn('operation["result_state"]', self.job("journal-resume-verify"))

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

    def test_resume_journal_guard_executes_against_journal_v2_and_fails_closed(self):
        job = self.jobs["journal-resume-verify"]
        script = _python_heredoc(next(step["run"] for step in job["steps"] if step.get("name") == "Verify the exact pristine admitted transaction without writing state"))
        journal_path = ROOT / "publisher-state/production-transaction-journal.json"
        baseline = json.loads(journal_path.read_text(encoding="utf-8"))
        self.assertEqual("admitted", baseline["active"]["state"])
        self.assertEqual(TX_ID, baseline["active"]["logical_transaction_id"])
        with tempfile.TemporaryDirectory(prefix="mahoon-h2-journal-") as directory:
            cwd = Path(directory)
            state = cwd / "state/publisher-state/production-transaction-journal.json"
            state.parent.mkdir(parents=True)
            env = {"REQUESTED_TRANSACTION_ID": TX_ID, "REQUESTED_READY": "YES"}

            def run(candidate, requested_tx=TX_ID):
                state.write_text(json.dumps(candidate), encoding="utf-8")
                run_env = dict(env, REQUESTED_TRANSACTION_ID=requested_tx)
                return _run_workflow_script(script, cwd, run_env)

            result = run(copy.deepcopy(baseline))
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("RESUME_JOURNAL=PRISTINE_ADMITTED_TRANSACTION_109", result.stdout)
            cases = []
            cases.append(("wrong transaction", copy.deepcopy(baseline), "0" * 64))
            changed = copy.deepcopy(baseline); changed["active"]["content_revision"] = 110; cases.append(("wrong revision", changed, TX_ID))
            changed = copy.deepcopy(baseline); changed["active"]["state"] = "build_ready"; cases.append(("wrong state", changed, TX_ID))
            changed = copy.deepcopy(baseline); changed["active"]["build_bundle_sha256"] = "a" * 64; cases.append(("build bundle", changed, TX_ID))
            changed = copy.deepcopy(baseline); changed["pending"] = {"content_revision": 110}; cases.append(("pending", changed, TX_ID))
            for operation_name in baseline["active"]["operations"]:
                changed = copy.deepcopy(baseline); changed["active"]["operations"][operation_name]["attempts"].append({}); cases.append((f"{operation_name} attempt", changed, TX_ID))
                changed = copy.deepcopy(baseline); changed["active"]["operations"][operation_name]["intent_state"] = "INTENT_RECORDED"; cases.append((f"{operation_name} intent state", changed, TX_ID))
                changed = copy.deepcopy(baseline); changed["active"]["operations"][operation_name]["result_state"] = "APPLIED"; cases.append((f"{operation_name} result state", changed, TX_ID))
            for label, candidate, requested_tx in cases:
                with self.subTest(label=label):
                    rejected = run(candidate, requested_tx)
                    self.assertNotEqual(0, rejected.returncode, label)

    def test_resume_artifact_scripts_validate_original_github_artifacts_offline(self):
        revision_path = os.environ.get("MAHOON_H2_REVISION_ARTIFACT")
        admission_path = os.environ.get("MAHOON_H2_ADMISSION_ARTIFACT")
        if not revision_path or not admission_path:
            self.skipTest("Download the immutable source-run artifacts and set MAHOON_H2_REVISION_ARTIFACT / MAHOON_H2_ADMISSION_ARTIFACT")
        revision_raw = Path(revision_path).read_bytes()
        admission_raw = Path(admission_path).read_bytes()
        self.assertEqual(REVISION_RAW_SHA, hashlib.sha256(revision_raw).hexdigest())
        self.assertEqual(ADMISSION_RAW_SHA, hashlib.sha256(admission_raw).hexdigest())
        revision_value = json.loads(revision_raw)
        admission_value = json.loads(admission_raw)
        revision = artifact_contract.validate_artifact(
            revision_value, expected_source_sha=SOURCE_SHA,
            trusted_producer={"workflow_run_id": "37379469235", "source_sha": SOURCE_SHA, "job": "revision-resolve"},
        )
        admission = artifact_contract.validate_artifact(
            admission_value, expected_transaction=revision["transaction"], expected_source_sha=SOURCE_SHA,
            expected_parents={"revision_resolution_sha256": revision["artifact_sha256"]},
            trusted_producer={"workflow_run_id": "37379469235", "source_sha": SOURCE_SHA, "job": "admission"},
            referenced_artifacts=artifact_transport.references(revision),
        )
        self.assertEqual("revision_resolution", revision["artifact_type"])
        self.assertEqual("admission_receipt", admission["artifact_type"])
        self.assertEqual("aece5876b4f9d71bc07f69fa2cad9f5a873ddf6e5e924adf58009a712d537dd3", revision["artifact_sha256"])
        self.assertEqual("12539a6d6369397664f4859a605d5332a97b328ec47fb9414445d5be203a7626", admission["artifact_sha256"])
        self.assertEqual(TX_ID, revision["transaction"]["logical_transaction_id"])
        self.assertEqual(revision["transaction"], admission["transaction"])
        self.assertEqual(109, revision["payload"]["revision"])
        self.assertEqual(81, revision["payload"]["published_revision"])
        self.assertEqual("CHANGED", revision["payload"]["decision"])
        self.assertEqual(1, revision["payload"]["request_count"])
        self.assertEqual("ADMITTED", admission["payload"]["decision"])
        self.assertEqual(revision["artifact_sha256"], admission["payload"]["revision_resolution_sha256"])
        self.assertEqual(SOURCE_SHA, revision["producer"]["source_sha"])
        self.assertEqual(SOURCE_SHA, admission["producer"]["source_sha"])
        self.assertEqual("37379469235", revision["producer"]["workflow_run_id"])
        self.assertEqual("37379469235", admission["producer"]["workflow_run_id"])

        revision_script = _python_heredoc(next(step["run"] for step in self.jobs["revision-resolve"]["steps"] if step.get("name") == "Revalidate and carry forward the original revision artifact unchanged"))
        admission_script = _python_heredoc(next(step["run"] for step in self.jobs["resume-admission"]["steps"] if step.get("id") == "admit"))

        def execute_revision(raw=revision_raw, requested_source=SOURCE_SHA, requested_tx=TX_ID, public_revision=109):
            with tempfile.TemporaryDirectory(prefix="mahoon-h2-revision-") as directory:
                cwd = Path(directory)
                artifact = cwd / "runner-temp/resume-revision/revision-resolution.json"
                artifact.parent.mkdir(parents=True)
                artifact.write_bytes(raw)
                result = _run_workflow_script(revision_script, cwd, {
                    "RUNNER_TEMP": str(cwd / "runner-temp"), "REQUESTED_SOURCE_RUN_ID": "37379469235",
                    "REQUESTED_SOURCE_SHA": requested_source, "REQUESTED_TRANSACTION_ID": requested_tx,
                }, offline_revision=public_revision)
                return result

        positive = execute_revision()
        self.assertEqual(0, positive.returncode, positive.stderr)
        self.assertIn("RESUME_REVISION_ARTIFACT=UNCHANGED; PUBLIC_REVISION=109", positive.stdout)
        modified_revision_payload = copy.deepcopy(revision_value)
        modified_revision_payload["payload"]["revision"] = 110
        modified_revision_raw = json.dumps(modified_revision_payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
        for label, raw, source, tx, public_revision in (
            ("modified raw bytes", revision_raw + b" ", SOURCE_SHA, TX_ID, 109),
            ("modified payload", modified_revision_raw, SOURCE_SHA, TX_ID, 109),
            ("incorrect source SHA", revision_raw, "0" * 40, TX_ID, 109),
            ("incorrect transaction", revision_raw, SOURCE_SHA, "0" * 64, 109),
            ("public revision 110", revision_raw, SOURCE_SHA, TX_ID, 110),
            ("public revision 108", revision_raw, SOURCE_SHA, TX_ID, 108),
        ):
            with self.subTest(label=label):
                self.assertNotEqual(0, execute_revision(raw, source, tx, public_revision).returncode)

        def execute_admission(raw=admission_raw, source=SOURCE_SHA, tx=TX_ID):
            with tempfile.TemporaryDirectory(prefix="mahoon-h2-admission-") as directory:
                cwd = Path(directory)
                (cwd / "handoff").mkdir()
                (cwd / "handoff/revision-resolution.json").write_bytes(revision_raw)
                original = cwd / "runner-temp/resume-admission/admission.json"
                original.parent.mkdir(parents=True)
                original.write_bytes(raw)
                output = cwd / "github-output.txt"
                output.write_text("", encoding="utf-8")
                result = _run_workflow_script(admission_script, cwd, {
                    "RUNNER_TEMP": str(cwd / "runner-temp"), "GITHUB_OUTPUT": str(output),
                    "REQUESTED_SOURCE_SHA": source, "REQUESTED_TRANSACTION_ID": tx,
                })
                copied = (cwd / "runner-evidence/a6/admission.json").read_bytes() if (cwd / "runner-evidence/a6/admission.json").exists() else None
                return result, output.read_text(encoding="utf-8"), copied

        admitted, output, copied = execute_admission()
        self.assertEqual(0, admitted.returncode, admitted.stderr)
        self.assertEqual("decision=ADMITTED\n", output)
        self.assertEqual(admission_raw, copied)
        changed = copy.deepcopy(admission_value)
        changed["payload"]["revision_resolution_sha256"] = "0" * 64
        bad_lineage = artifact_contract.seal_artifact(changed)
        bad_lineage_raw = json.dumps(bad_lineage, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        changed = copy.deepcopy(admission_value)
        changed["payload"]["decision"] = "DEFERRED"
        modified_admission_payload = json.dumps(changed, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
        negatives = (
            ("modified raw artifact", admission_raw + b" ", SOURCE_SHA, TX_ID),
            ("modified admission payload", modified_admission_payload, SOURCE_SHA, TX_ID),
            ("incorrect source SHA", admission_raw, "0" * 40, TX_ID),
            ("incorrect transaction", admission_raw, SOURCE_SHA, "0" * 64),
            ("incorrect artifact lineage", bad_lineage_raw, SOURCE_SHA, TX_ID),
        )
        for label, raw, source, tx in negatives:
            with self.subTest(label=label):
                result, _output, _copied = execute_admission(raw, source, tx)
                self.assertNotEqual(0, result.returncode, label)


if __name__ == "__main__":
    unittest.main()
