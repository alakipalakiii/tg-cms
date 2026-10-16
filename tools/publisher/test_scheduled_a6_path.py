"""Execute the active workflow conditions, not the retired combined publisher jobs."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from tools.publisher import scheduled_circuit_breaker as breaker
from tools.publisher import transaction_journal as journal
from tools.publisher import workflow_stage_cli as cli

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/mahoon-static-publisher.yml"


def expression(text, context, *, cancelled=False):
    """Evaluate this workflow's boolean subset against only direct GitHub needs."""
    text = text.removeprefix("${{").removesuffix("}}").strip()
    text = re.sub(r"'[^']*'|\b(?:needs|inputs|github|vars)\.[\w.-]+", lambda m:
                  m[0] if m[0].startswith("'") else repr(context.get(m[0], "")), text)
    text = text.replace("always()", "True").replace("cancelled()", str(cancelled)).replace("success()", "True")
    text = text.replace("&&", " and ").replace("||", " or ")
    text = re.sub(r"!(?!=)", "not ", text).replace("null", "None")
    return eval("(" + text.strip() + ")", {"__builtins__": {}}, {})


class ScheduledA6PathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        cls.jobs = cls.workflow["jobs"]

    def context(self, event="schedule", mode="", policy="PUBLISH", allowed="true", changed="CHANGED"):
        c = {"github.event_name": event, "inputs.mode": mode, "inputs.ready": "NO",
             "vars.PUBLISHER_MODE_SCHEDULED": policy, "needs.scheduled-policy-preflight.outputs.publish_allowed": allowed,
             "needs.revision-resolve.outputs.decision": changed}
        for name in self.jobs:
            c[f"needs.{name}.result"] = "success"
        for name in ("resume-admission", "journal-resume-verify", "resume-source-carryforward", "resume-zero-carryforward",
                     "resume-promote-carryforward", "upload-create-recovered-result", "zero-create-recovered-result",
                     "promote-create-recovered-result"):
            c[f"needs.{name}.result"] = "skipped"
        c["needs.admission.outputs.decision"] = "ADMITTED"
        c["needs.pre-promotion-proof.outputs.proof_state"] = "PASS"
        c["needs.production-proof.outputs.proof_state"] = "PASS"
        for name in ("upload-result-write", "zero-percent-result-write", "promote-result-write"):
            c[f"needs.{name}.outputs.result_state"] = "APPLIED"
        return c

    def enabled(self, name, context, **kwargs):
        job = self.jobs[name]
        needs = job.get("needs", [])
        needs = [needs] if isinstance(needs, str) else needs
        direct = {k: v for k, v in context.items() if not k.startswith("needs.") or k.split(".")[1] in needs}
        return bool(expression(job.get("if", "${{ success() }}"), direct, **kwargs))

    def test_native_schedule_and_auto_tick_cross_the_complete_direct_a6_chain(self):
        chain = ("admission", "build-validate", "build-ready-write", "production-baseline-reconciliation",
                 "upload-intent-write", "cloudflare-upload-operation", "upload-result-write", "zero-percent-intent-write",
                 "cloudflare-zero-percent-operation", "zero-percent-result-write", "pre-promotion-proof",
                 "promote-intent-write", "cloudflare-promote-operation", "promote-result-write", "production-proof",
                 "final-state-materialization", "final-persistence", "scheduled-circuit-breaker")
        for event, mode in (("schedule", ""), ("workflow_dispatch", "AUTO_TICK")):
            for name in chain:
                with self.subTest(event=event, job=name):
                    self.assertTrue(self.enabled(name, self.context(event, mode)), name)

    def test_all_needs_references_are_direct_and_breaker_observes_all_active_a6_jobs(self):
        watched = set(self.jobs["scheduled-circuit-breaker"]["needs"])
        for name, job in self.jobs.items():
            needs = job.get("needs", [])
            needs = [needs] if isinstance(needs, str) else needs
            for ref in re.findall(r"needs\.([\w-]+)\.", str(job)):
                self.assertIn(ref, needs, name)
            if any((s.get("with") or {}).get("path") == "code" for s in job.get("steps", [])) and name not in {"retire-stale-admitted", "scheduled-circuit-breaker"}:
                self.assertIn(name, watched)

    def test_open_or_check_only_never_admits_and_unchanged_does_not_build(self):
        for policy, allowed, changed in (("CHECK_ONLY", "true", "CHANGED"), ("PUBLISH", "false", "CHANGED"),
                                         ("PUBLISH", "true", "UNCHANGED")):
            c = self.context(policy=policy, allowed=allowed, changed=changed)
            self.assertFalse(self.enabled("admission", c))
            c["needs.admission.result"] = "skipped"
            c["needs.admission.outputs.decision"] = ""
            self.assertFalse(self.enabled("build-validate", c))
        self.assertTrue(self.enabled("check-only", self.context(allowed="false")))

    def test_manual_readiness_and_resume_remain_separate(self):
        c = self.context("workflow_dispatch", "PUBLISH", allowed="false")
        self.assertFalse(self.enabled("admission", c))
        c["inputs.ready"] = "YES"
        self.assertTrue(self.enabled("admission", c))
        c["inputs.mode"] = "RESUME_ADMITTED"
        self.assertFalse(self.enabled("admission", c))
        c["needs.admission.result"] = "skipped"
        c["needs.resume-admission.result"] = "success"
        c["needs.resume-admission.outputs.decision"] = "ADMITTED"
        self.assertTrue(self.enabled("build-ready-write", c))
        self.assertFalse(self.enabled("build-ready-write", c, cancelled=True))

    def test_build_baseline_and_proof_failures_block_mutation_or_persistence(self):
        for prerequisite, target in (("build-validate", "build-ready-write"),
                                     ("production-baseline-reconciliation", "upload-intent-write"),
                                     ("pre-promotion-proof", "promote-intent-write"),
                                     ("production-proof", "final-state-materialization"),
                                     ("final-state-materialization", "final-persistence")):
            for result in ("failure", "cancelled", "skipped"):
                c = self.context()
                c[f"needs.{prerequisite}.result"] = result
                c[f"needs.{prerequisite}.outputs.proof_state"] = ""
                self.assertFalse(self.enabled(target, c), (prerequisite, target, result))
        for job in ("cloudflare-upload-operation", "cloudflare-zero-percent-operation", "cloudflare-promote-operation"):
            self.assertFalse(self.enabled(job, self.context(), cancelled=True))

    def test_source_pin_resolves_main_once_and_carries_it_past_stale_event(self):
        policy = self.jobs["scheduled-policy-preflight"]
        checkout = policy["steps"][0]["with"]["ref"]
        self.assertEqual("main", expression(checkout, self.context()))
        stale, current = "a" * 40, "b" * 40
        c = self.context()
        c.update({"github.sha": stale, "needs.scheduled-policy-preflight.outputs.source_sha": current})
        for name in self.jobs["scheduled-circuit-breaker"]["needs"]:
            if name == "scheduled-policy-preflight" or not self.enabled(name, c): continue
            for step in self.jobs[name].get("steps", []):
                w = step.get("with") or {}
                if w.get("path") in {"code", "diagnostics"}:
                    self.assertEqual(current, expression(w["ref"], c), name)
        resolve = next(s for s in self.jobs["revision-resolve"]["steps"] if s.get("name") == "Resolve revision for a new transaction")
        self.assertIn("--source-sha '${{ needs.scheduled-policy-preflight.outputs.source_sha }}'", resolve["run"])

    def test_real_unchanged_resolution_cannot_admit_or_mutate_the_journal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "published.json").write_text('{"published_content_revision":203}')
            path = root / "journal.json"
            path.write_text(json.dumps(journal.empty_journal()))
            before = path.read_bytes()
            revision = cli.create_revision_resolution(root / "published.json", source_sha="a" * 40,
                fetcher=lambda *args, **kwargs: ({"revision":203,"changed_at":"2026-10-15T19:38:27Z"}, {}))
            from tools.publisher.artifact_transport import write_artifact
            write_artifact(root / "revision.json", revision)
            with self.assertRaises(ValueError):
                cli.create_admission_receipt(root / "revision.json", path, "schedule")
            self.assertEqual(before, path.read_bytes())

    def test_real_journal_blocks_ambiguous_or_pending_transactions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal.json"
            path.write_text(json.dumps(journal.empty_journal()))
            self.assertIsNone(breaker.a6_failure({}, path))
            for stage in ("pre-promotion-proof", "production-proof"):
                self.assertEqual(stage, breaker.a6_failure({stage:{"result":"success","outputs":{"proof_state":"FAIL"}}},path))
            for state in ("UNKNOWN", "NOT_APPLIED"):
                results = {"promote-result-write":{"result":"success","outputs":{"result_state":state}}}
                self.assertEqual("promote-result-write",breaker.a6_failure(results,path))
                results["promote-create-recovered-result"] = {"result":"success","outputs":{"recovered":"true"}}
                self.assertIsNone(breaker.a6_failure(results,path))
            store = journal.TransactionJournal.from_file(path, "mahoon-art-magazine")
            store.admit(204, "schedule", "fixture", "1")
            store.admit(205, "schedule", "fixture2", "1")
            self.assertEqual("journal-incomplete", breaker.a6_failure({}, path))
            for stage in ("build-validate", "pre-promotion-proof", "production-proof", "final-persistence",
                          "cloudflare-upload-operation", "promote-result-write"):
                for result in ("failure", "cancelled"):
                    self.assertEqual(stage, breaker.a6_failure({stage:{"result":result}}, path))
            path.write_text("{}")
            self.assertEqual("journal-invalid", breaker.a6_failure({}, path))

    def test_single_resource_conscious_schedule_and_global_concurrency(self):
        self.assertEqual([{"cron":"17,47 * * * *"}], self.workflow["on"]["schedule"])
        self.assertEqual("mahoon-production-publisher", self.workflow["concurrency"]["group"])
        self.assertEqual("false", self.workflow["concurrency"]["cancel-in-progress"])
        heartbeat = json.loads((ROOT / "workers/scheduler-heartbeat/wrangler.jsonc").read_text())
        self.assertEqual([], heartbeat["triggers"]["crons"])

    def test_stale_event_recovery_requires_bound_automatic_execution_receipt(self):
        run = {"head_sha":"a" * 40, "event":"schedule", "head_branch":"main",
               "path":".github/workflows/mahoon-static-publisher.yml"}
        context = {"contract":"MAHOON_EXECUTION_SOURCE_V1", "event_sha":"a" * 40,"source_sha":"b" * 40,
                   "event":"schedule", "ref":"refs/heads/main", "repository":"owner/repo", "run_id":"123",
                   "run_attempt":1,"mode":""}
        cli.validate_execution_source(run, "b" * 40, "owner/repo", "123", 1, context)
        for field, value in (("event_sha","c" * 40),("source_sha","c" * 40),("repository","attacker/repo"),
                             ("run_id","456"),("run_attempt",2),("ref","refs/heads/untrusted"),("event","pull_request")):
            with self.subTest(field=field), self.assertRaises(ValueError):
                cli.validate_execution_source(run,"b" * 40,"owner/repo","123",1,{**context,field:value})
        with self.assertRaises(ValueError):
            cli.validate_execution_source(run,"b" * 40,"owner/repo","123",1)
        with self.assertRaises(ValueError):
            cli.validate_execution_source({**run,"event":"workflow_dispatch"},"b" * 40,"owner/repo","123",1,
                                         {**context,"event":"workflow_dispatch","mode":"PUBLISH"})
        cli.validate_execution_source(run,"a" * 40,"owner/repo","123",1)

    def test_actual_source_receipt_script_pins_checkout_instead_of_stale_event(self):
        from test_a6_workflow_contract import _python_heredoc
        step = next(s for s in self.jobs["scheduled-policy-preflight"]["steps"] if s.get("id") == "source")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for args in (("init",), ("-c","user.name=Fixture","-c","user.email=fixture@example.invalid",
                                     "commit","--allow-empty","-m","fixture")):
                subprocess.run(["git",*args],cwd=root,capture_output=True,check=True)
            current = subprocess.check_output(["git","rev-parse","HEAD"],cwd=root,text=True).strip()
            env = {**os.environ,"GITHUB_SHA":"a" * 40,"GITHUB_RUN_ID":"123","GITHUB_RUN_ATTEMPT":"1",
                   "GITHUB_REPOSITORY":"owner/repo","GITHUB_REF":"refs/heads/main","GITHUB_EVENT_NAME":"schedule",
                   "GITHUB_OUTPUT":str(root / "output"),"MAHOON_TRIGGER_MODE":""}
            result = subprocess.run([sys.executable,"-c",_python_heredoc(step["run"])],cwd=root,env=env,capture_output=True,text=True)
            self.assertEqual(0,result.returncode,result.stderr)
            receipt = json.loads((root / "execution-source.json").read_text())
            self.assertEqual(current,receipt["source_sha"])
            self.assertEqual("a" * 40,receipt["event_sha"])
            self.assertEqual("source_sha=" + current,(root / "output").read_text().strip())

    def test_a6_observer_persists_open_and_does_not_rewrite_existing_open_or_idle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = {"contract":breaker.CONTRACT,"state":"CLOSED","reason":None,"failed_run_id":None,
                     "failed_job":None,"head_sha":None,"updated_at":"2026-10-15T00:00:00Z"}
            path, jpath = root / "breaker.json", root / "journal.json"
            path.write_text(json.dumps(state))
            jpath.write_text(json.dumps(journal.empty_journal()))
            args = ["observe-a6","--path",str(path),"--journal",str(jpath),"--run-id","123","--head-sha","a" * 40]
            before = path.read_bytes()
            with patch.dict(os.environ,{"A6_RESULTS":json.dumps({"admission":{"result":"skipped"}})}):
                self.assertEqual(0,breaker.main(args))
            self.assertEqual(before,path.read_bytes())
            with patch.dict(os.environ,{"A6_RESULTS":json.dumps({"pre-promotion-proof":{"result":"failure"}})}):
                self.assertEqual(0,breaker.main(args))
            opened = path.read_bytes()
            self.assertEqual("OPEN",json.loads(opened)["state"])
            with patch.dict(os.environ,{"A6_RESULTS":json.dumps({"production-proof":{"result":"cancelled"}})}):
                breaker.main(args)
            self.assertEqual(opened,path.read_bytes())

    def test_incident_36727673538_http_and_version_failures_still_block_current_media_gate(self):
        from tools.publisher import candidate_override_crawl as crawl
        media = {"records":[{"immutable_path":"/media/fixture.jpg","mime":"image/jpeg"}],"stats":{"unresolved":0}}
        good = {"status":200,"actual_version":"candidate","version_attribution_status":"PROVEN","mime_pass":True}
        for response, expected in ((good,True), ({**good,"status":404},False),
                                   ({**good,"actual_version":"baseline"},False),
                                   ({**good,"version_attribution_status":"NOT_PROVEN"},False),
                                   ({**good,"mime_pass":False},False)):
            with self.subTest(response=response), patch.object(crawl,"VERSION","candidate"), \
                 patch.dict(os.environ,{"MAHOON_DISABLE_VERSION_OVERRIDE":"0"}), \
                 patch.object(crawl,"_head_media",return_value=response):
                result = crawl._measure([], {"routes":{}},
                    {"contract":"POSTS_FULL_PUBLIC_SNAPSHOT_V2","payload":{"posts":[]}},
                    {"status":200,"body":b'{"records":[]}'},media)
                self.assertEqual(expected,result["gates"]["remote_media"]["PASS"])


class A6RecoveryTests(unittest.TestCase):
    def setUp(self):
        import test_final_state_materializer as fixtures
        from tools.publisher import artifact_contract as contracts
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.f = fixtures._fixture(self.root)
        self.addCleanup(self.f.doCleanups)
        self.path = self.root / "publisher-state/production-transaction-journal.json"
        self.path.parent.mkdir()
        self.path.write_text(json.dumps(journal.empty_journal()))
        store = journal.TransactionJournal.from_file(self.path, "mahoon-art-magazine")
        proof = self.f.proof
        _, tx = store.admit(proof["transaction"]["content_revision"], "schedule", proof["producer"]["workflow_run_id"], "1")
        for operation in ("upload_version", "deploy_zero_percent", "promote"):
            op, attempt = store.record_intent(tx, operation)
            store.record_result(tx, op, attempt, "APPLIED", {"type":"fixture","reference":operation,"sha256":"a" * 64})
        store.mark_ready_to_persist(tx, proof["artifact_sha256"])
        store.finalize_completed(tx, "c" * 40)
        for path, raw in self.f.output.items():
            (self.root / path).write_bytes(raw)
        files = [{"path":p, "sha256":hashlib.sha256(raw).hexdigest(), "size_bytes":len(raw)}
                 for p, raw in sorted(self.f.output.items())]
        payload = {"build_bundle_sha256":self.f.bundle["artifact_sha256"],
                   "journal_generation":store.snapshot()[1] - 1,
                   "operation_result_sha256s":proof["payload"]["operation_result_sha256s"],
                   "proof_evidence_sha256":proof["artifact_sha256"], "state_commit_sha":"c" * 40, "state_files":files}
        persisted = contracts.seal_artifact({**proof, "artifact_type":"final_persistence_payload", "payload":payload})
        static = json.loads(self.f.output["publisher-state/published-static-state.json"])
        self.state = {"contract":breaker.CONTRACT, "state":"OPEN", "reason":"fixture",
                      "failed_run_id":"123", "failed_job":"remote-proof", "head_sha":"a" * 40,
                      "updated_at":"2026-10-15T00:00:00Z"}
        self.evidence = {"contract":breaker.A6_RECOVERY_KIND, "incident_run":"123", "failed_job":"remote-proof",
            "fix_sha":"b" * 40, "safety_test":{"id":"234", "head_sha":"b" * 40,"conclusion":"success"},
            "open_auto_tick":{"id":"235", "head_sha":"b" * 40,"conclusion":"success","mode":"AUTO_TICK",
                              "decision":"UNCHANGED","mutation_jobs_executed":[],"journal_unchanged":True},
            "incident_media_regression":"PASS", "journal_generation":store.snapshot()[1], "transaction_id":tx,
            "production_proof":{"artifact_sha256":proof["artifact_sha256"],"proof_state":"PASS",
                                "run_id":proof["producer"]["workflow_run_id"],"candidate_version":static["current_version"]},
            "persistence":{**payload,"artifact_sha256":persisted["artifact_sha256"],"status":"PERSISTED"},
            "sealed_artifacts":[*self.f.references.values(),persisted], "artifact_lineage_verified":True,
            "live_website":{"deployment_id":static["deployment_id"],"versions":[{"version_id":static["current_version"],"percentage":100}]}}

    def test_exact_sealed_completed_recovery_closes_without_touching_journal_or_replaying(self):
        before = self.path.read_bytes()
        result = breaker.a6_closed_state(self.state, self.evidence, self.root, authorized=True)
        self.assertEqual("CLOSED", result["state"])
        self.assertEqual(breaker.A6_RECOVERY_KIND, result["recovery_kind"])
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual("123", result["incident_run"])
        self.assertEqual("234", result["safety_test_run_id"])

    def test_real_preproof_output_contract_and_changed_publication_watcher(self):
        from test_a6_workflow_contract import _python_heredoc, _run_workflow_script
        from tools.publisher import artifact_contract as contracts
        jobs = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)["jobs"]
        job = jobs["pre-promotion-proof"]
        step = next(s for s in job["steps"] if s.get("id") == "proof-state")
        self.assertEqual("${{ steps.proof-state.outputs.proof_state }}", job["outputs"]["proof_state"])
        self.assertIn("validate-artifact", step["run"])
        self.assertIn('--type pre_promotion_proof_evidence', step["run"])
        proof_path, status_path, output = (self.root / n for n in
            ("pre-promotion-proof.json", "preproof-status.json", "github-output"))
        proof = self.f.prepromotion_proof
        status = {"status":"PASS", "artifact_sha256":proof["artifact_sha256"]}
        script = _python_heredoc(step["run"])
        for change in ("good", "missing-proof", "missing-status", "bad-json", "tampered", "status-mismatch"):
            with self.subTest(change=change):
                proof_path.write_text(json.dumps(proof))
                status_path.write_text(json.dumps(status))
                output.unlink(missing_ok=True)
                if change == "missing-proof": proof_path.unlink()
                if change == "missing-status": status_path.unlink()
                if change == "bad-json": status_path.write_text("{")
                if change == "tampered":
                    proof_path.write_text(json.dumps({**proof,"artifact_sha256":"0" * 64}))
                if change == "status-mismatch": status_path.write_text(json.dumps({**status,"status":"FAIL"}))
                result = _run_workflow_script(script, self.root, {"GITHUB_OUTPUT":str(output)})
                if change != "good":
                    self.assertNotEqual(0, result.returncode)
                    self.assertFalse(output.exists())
                    continue
                self.assertEqual(0, result.returncode, result.stderr)
                actual = dict(line.split("=",1) for line in output.read_text().splitlines())
                self.assertEqual({"proof_state":"PASS"}, actual)
                results = {"pre-promotion-proof":{"result":"success","outputs":actual},
                           "production-proof":{"result":"success","outputs":{"proof_state":"PASS"}},
                           "admission":{"result":"success","outputs":{"decision":"ADMITTED"}},
                           "final-persistence":{"result":"success"}}
                self.assertIsNone(breaker.a6_failure(results, self.path))
                for stage in ("pre-promotion-proof", "production-proof"):
                    for item in ({"result":"failure"}, {"result":"cancelled"}, {"result":"skipped"},
                                 {"result":"success"}, {"result":"success","outputs":None},
                                 {"result":"success","outputs":{"proof_state":"FAIL"}},
                                 {"result":"success","outputs":{"proof_state":True}},
                                 {"result":"success","outputs":{"proof_state":"PASS "}}):
                        with self.subTest(stage=stage,item=item):
                            self.assertEqual(stage, breaker.a6_failure({**results,stage:item}, self.path))
        # A self-consistent failed seal emits FAIL and the watcher must reject it.
        failed = copy.deepcopy(proof)
        failed["payload"]["PASS"] = False
        failed = contracts.seal_artifact(failed)
        proof_path.write_text(json.dumps(failed))
        status_path.write_text(json.dumps({"status":"FAIL","artifact_sha256":failed["artifact_sha256"]}))
        output.unlink(missing_ok=True)
        result = _run_workflow_script(script,self.root,{"GITHUB_OUTPUT":str(output)})
        self.assertEqual(0,result.returncode,result.stderr)
        self.assertEqual("proof_state=FAIL\n",output.read_text())
        with self.assertRaises(ValueError):
            contracts.validate_artifact(failed,referenced_artifacts=self.f.references)
        self.assertIsNone(breaker.a6_failure({}, self.path))

    def test_changed_open_tick_recovery_requires_sealed_readonly_revision_and_exact_failure(self):
        with patch.dict(os.environ,{"GITHUB_RUN_ID":"235","GITHUB_RUN_ATTEMPT":"1","GITHUB_JOB":"revision-resolve"}):
            revision = cli.create_revision_resolution(self.root / "publisher-state/production-content-fingerprint.json",
                source_sha="b" * 40, fetcher=lambda *a,**kw: ({"revision":38,"changed_at":"2026-10-16T11:30:09Z"},{}))
        evidence = copy.deepcopy(self.evidence)
        evidence["sealed_artifacts"].append(revision)
        evidence["open_auto_tick"].update({"decision":"CHANGED","conclusion":"failure",
            "check_only_outcome":"CHANGED_REVISION_DETECTED_CHECK_ONLY","failed_jobs":["check-only"],
            "revision_artifact_sha256":revision["artifact_sha256"]})
        self.assertEqual("CLOSED",breaker.a6_closed_state(self.state,evidence,self.root,authorized=True)["state"])
        for field,value in (("failed_jobs",["check-only","revision-resolve"]), ("failed_jobs",[]),
                            ("check_only_outcome","UNKNOWN"), ("revision_artifact_sha256",self.f.proof["artifact_sha256"]),
                            ("id","236"), ("journal_unchanged",False), ("mutation_jobs_executed",["admission"])):
            bad = copy.deepcopy(evidence)
            bad["open_auto_tick"][field] = value
            with self.subTest(field=field),self.assertRaises(ValueError):
                breaker.a6_closed_state(self.state,bad,self.root,authorized=True)

    def test_bad_incident_tests_idle_seal_persistence_live_or_journal_cannot_close(self):
        changes = [("incident_run", "999"), ("incident_media_regression","FAIL"),
                   ("artifact_lineage_verified",False), ("journal_generation",0)]
        for key, value in changes:
            with self.subTest(key=key), self.assertRaises(ValueError):
                breaker.a6_closed_state(self.state, {**self.evidence,key:value}, self.root, authorized=True)
        for key, field, value in [("safety_test","conclusion","failure"), ("safety_test","head_sha","d" * 40),
                                  ("open_auto_tick","decision","CHANGED"), ("open_auto_tick","journal_unchanged",False),
                                  ("open_auto_tick","mutation_jobs_executed",["upload"]),
                                  ("live_website","deployment_id","wrong"), ("production_proof","proof_state","FAIL")]:
            bad = copy.deepcopy(self.evidence)
            bad[key][field] = value
            with self.subTest(key=key,field=field), self.assertRaises(ValueError):
                breaker.a6_closed_state(self.state,bad,self.root,authorized=True)
        bad = copy.deepcopy(self.evidence)
        bad["sealed_artifacts"][0]["payload"]["decision"] = "tampered"
        with self.assertRaises(ValueError):
            breaker.a6_closed_state(self.state,bad,self.root,authorized=True)
        with self.assertRaises(ValueError):
            breaker.a6_closed_state(self.state,self.evidence,self.root,authorized=False)
        journal.TransactionJournal.from_file(self.path,"mahoon-art-magazine").admit(38,"schedule","fixture","1")
        with self.assertRaises(ValueError):
            breaker.a6_closed_state(self.state,self.evidence,self.root,authorized=True)
        # Restore only this isolated fixture to check the independent file-tamper gate.
        stored = json.loads(self.path.read_text())
        stored["active"] = None
        self.path.write_text(json.dumps(stored))
        self.evidence["journal_generation"] = stored["generation"]
        target = self.root / self.evidence["persistence"]["state_files"][0]["path"]
        target.write_bytes(b"tampered persisted file")
        with self.assertRaises(ValueError):
            breaker.a6_closed_state(self.state,self.evidence,self.root,authorized=True)


if __name__ == "__main__":
    unittest.main()
