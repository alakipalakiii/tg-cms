"""Exercise retirement against real Git CAS and sealed admission fixtures, without live mutations."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from publisher import artifact_transport, repository_persistence as persistence
from publisher import scheduled_circuit_breaker as breaker, superseded_build as superseded
from publisher import workflow_stage_cli as cli
from publisher.transaction_journal import empty_journal, serialize_journal, journal_digest
from test_stale_transaction_retirement import RetirementRepository, JOURNAL, git
from test_a6_workflow_contract import _python_heredoc, _run_workflow_script, WORKFLOW


class SupersededBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mahoon-superseded-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = RetirementRepository(self.root)
        (self.repo.root / JOURNAL).write_bytes(serialize_journal(empty_journal("mahoon-art-magazine")))
        git(self.repo.root, "add", JOURNAL)
        git(self.repo.root, "commit", "-m", "empty journal fixture")
        git(self.repo.root, "push", "origin", "main")
        self.source = git(self.repo.root, "rev-parse", "HEAD")
        self.env = patch.dict(os.environ, {"GITHUB_REPOSITORY": "fixture/repo", "GITHUB_RUN_ID": "123",
            "GITHUB_RUN_ATTEMPT": "1", "GITHUB_JOB": "fixture"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.revision = self.root / "revision.json"
        self.admission = self.root / "admission.json"
        self.context = self.root / "context.json"
        state = self.root / "published.json"
        state.write_text('{"published_content_revision":117}')
        revision = cli.create_revision_resolution(state, source_sha=self.source,
            fetcher=lambda *a, **kw: ({"revision":118,"changed_at":"2026-10-17T17:00:00Z"}, {}))
        artifact_transport.write_artifact(self.revision, revision)
        admission = cli.create_admission_receipt(self.revision, self.repo.root / JOURNAL,
            "schedule", "123", "1", remote_writer=self.repo.writer())
        artifact_transport.write_artifact(self.admission, admission,
            referenced_artifacts=artifact_transport.references(revision))
        self.context.write_text(json.dumps({"contract":"MAHOON_EXECUTION_SOURCE_V1", "event_sha":self.source,
            "source_sha":self.source,"run_id":"123","run_attempt":1,"repository":"fixture/repo",
            "event":"schedule","ref":"refs/heads/main","mode":""}))
        self.run = {"head_sha":self.source,"run_attempt":1,"status":"in_progress","event":"schedule",
            "head_repository":{"full_name":"fixture/repo"},"head_branch":"main",
            "path":".github/workflows/mahoon-static-publisher.yml"}
        self.jobs = {"jobs":[{"name":name,"status":"completed","conclusion":"skipped","steps":[]}
            for name in superseded.SKIPPED_JOBS] + [
                {"name":"build-validate","status":"completed","conclusion":"success"}]}
        self.jobs["total_count"] = len(self.jobs["jobs"])
        self.artifacts = {"total_count":3,"artifacts":[{"name":f"a6-{name}-123","expired":False}
            for name in ("revision","admission","execution-source")]}

    def api(self, path):
        if "/jobs?" in path: return copy.deepcopy(self.jobs)
        if "/artifacts?" in path: return copy.deepcopy(self.artifacts)
        return copy.deepcopy(self.run)

    def retire(self, current=121):
        with patch.object(superseded, "fetch_public_content_revision", return_value=(current,"time",{})):
            return superseded.retire(self.repo.root,self.revision,self.admission,self.context,
                                     self.source,"123",api=self.api)

    def test_rapid_revisions_during_build_retire_once_and_next_tick_admits_latest(self):
        for current in (119,121,135):
            self.assertEqual("SUPERSEDED",superseded.revision_disposition(118,current,automatic=True,resume=False))
        before = self.repo.journal()
        result = self.retire(135)
        journal = self.repo.journal()
        self.assertIsNone(journal["active"])
        self.assertEqual(before["history"],journal["history"][:-1])
        self.assertEqual("blocked",journal["history"][-1]["state"])
        self.assertEqual({JOURNAL},persistence._commit_paths(self.repo.root,result["remote_head"]))
        self.assertEqual("ADMITTED",self.repo.writer().admit_revision(135,"schedule","124","1")[0])

    def test_all_revision_fence_negative_cases(self):
        for expected,current,automatic,resume in [(118,117,True,False),(118,119,False,False),
                (118,119,True,True),(118,True,True,False),(118,0,True,False),(118,"119",True,False)]:
            with self.subTest(current=current,automatic=automatic,resume=resume),self.assertRaises(ValueError):
                superseded.revision_disposition(expected,current,automatic=automatic,resume=resume)
        self.assertEqual("STABLE",superseded.revision_disposition(118,118,automatic=True,resume=False))

    def test_missing_failed_unknown_or_executed_job_cannot_retire(self):
        before = self.repo.journal()
        for name in superseded.SKIPPED_JOBS:
            row = next(x for x in self.jobs["jobs"] if x["name"] == name)
            for outcome in ("success","failure","cancelled",None):
                row["conclusion"] = outcome
                with self.subTest(name=name,outcome=outcome),self.assertRaises(ValueError): self.retire()
            row["conclusion"] = "skipped"
            row["steps"] = [{"conclusion":"success"}]
            with self.assertRaises(ValueError): self.retire()
            row["steps"] = []
        self.jobs["jobs"].pop()
        with self.assertRaises(ValueError): self.retire()
        self.assertEqual(before,self.repo.journal())

    def test_incomplete_unknown_or_expired_artifact_evidence_cannot_retire(self):
        original = copy.deepcopy(self.artifacts)
        for item in ({"total_count":4,"artifacts":original["artifacts"]},
                     {"total_count":1,"artifacts":[{"name":"a6-upload-direct-result-123","expired":False}]},
                     {"total_count":1,"artifacts":[{"name":"a6-revision-123","expired":True}]}):
            self.artifacts = item
            with self.assertRaises(ValueError): self.retire()

    def test_wrong_run_attempt_source_context_or_tampered_seal_cannot_retire(self):
        original = copy.deepcopy(self.run)
        for key,value in (("run_attempt",2),("status","completed"),("head_sha","0"*40),
                          ("head_repository",{"full_name":"other/repo"})):
            self.run = {**original,key:value}
            with self.subTest(key=key),self.assertRaises(ValueError): self.retire()
        self.run = original
        value = json.loads(self.admission.read_text()); value["payload"]["journal_generation"] += 1
        self.admission.write_text(json.dumps(value))
        with self.assertRaises(ValueError): self.retire()

    def test_concurrent_scheduler_pending_or_coalesced_attempt_cannot_retire(self):
        self.repo.writer().admit_revision(119,"schedule","124","1")
        before = self.repo.journal()
        with self.assertRaises(ValueError): self.retire()
        self.assertEqual(before,self.repo.journal())

    def test_any_mutation_or_unknown_result_invalidates_pristine_boundary(self):
        original = self.repo.journal()["active"]
        for name in original["operations"]:
            for key,value in (("intent_state","RECORDED"),("result_state","APPLIED"),
                              ("result_state","UNKNOWN"),("attempts",[{"attempt_id":"1"}])):
                tx = copy.deepcopy(original); tx["operations"][name][key] = value
                with self.subTest(operation=name,key=key): self.assertFalse(superseded.pristine(tx))

    def test_source_code_drift_cannot_retire(self):
        path = self.repo.root / "tools/publisher/change.py"
        path.parent.mkdir(parents=True)
        path.write_text("# source changed")
        git(self.repo.root,"add","tools")
        git(self.repo.root,"commit","-m","new executable source")
        git(self.repo.root,"push","origin","main")
        with self.assertRaises(ValueError): self.retire()

    def test_lost_push_reply_is_exactly_reconciled_and_retirement_is_not_replayed(self):
        real = persistence._push
        def lost(*args,**kwargs):
            real(*args,**kwargs)
            raise persistence.RepositoryPersistenceError("lost reply")
        with patch.object(persistence,"_push",side_effect=lost): self.retire()
        generation = self.repo.journal()["generation"]
        with self.assertRaises(ValueError): self.retire()
        self.assertEqual(generation,self.repo.journal()["generation"])

    def test_interrupted_retirement_opens_breaker_even_when_remote_commit_exists(self):
        result = self.retire()
        journal = self.repo.journal()
        results = {name:{"result":"skipped"} for name in superseded.SKIPPED_JOBS}
        results.update({"build-validate":{"result":"success","outputs":{"superseded":"true"}},
            "admission":{"result":"success","outputs":{"decision":"ADMITTED"}},
            "superseded-build-retirement":{"result":"success","outputs":{k:str(v) for k,v in result.items()}}})
        path = self.repo.root / JOURNAL
        self.assertIsNone(breaker.a6_failure(results,path))
        for key in ("generation","journal_sha256","retired_transaction_id","status"):
            bad = copy.deepcopy(results); bad["superseded-build-retirement"]["outputs"][key] = "wrong"
            self.assertEqual("superseded-retirement-unproven",breaker.a6_failure(bad,path))
        for outcome in ("failure","cancelled","skipped"):
            bad = copy.deepcopy(results); bad["superseded-build-retirement"]["result"] = outcome
            self.assertIsNotNone(breaker.a6_failure(bad,path))
        self.assertEqual(journal_digest(journal),journal_digest(self.repo.journal()))

    def test_real_pre_and_post_gates_emit_superseded_and_block_build_ready(self):
        from test_scheduled_a6_path import ScheduledA6PathTests
        workflow = yaml.load(WORKFLOW.read_text(encoding="utf8"),Loader=yaml.BaseLoader)
        output = self.root / "outputs"
        env = {"EXECUTION_SHA":self.source,"RESUME_MODE":"false","AUTOMATIC_TICK":"true",
               "GITHUB_OUTPUT":str(output)}
        handoff = self.root / "handoff"; handoff.mkdir()
        (handoff / "revision-resolution.json").write_bytes(self.revision.read_bytes())
        (handoff / "admission.json").write_bytes(self.admission.read_bytes())
        (self.root / "state/publisher-state").mkdir(parents=True)
        (self.root / "state" / JOURNAL).write_bytes((self.repo.root / JOURNAL).read_bytes())
        for step in workflow["jobs"]["build-validate"]["steps"]:
            if step.get("id") in {"pre-revision","post-revision"}:
                result = _run_workflow_script(_python_heredoc(step["run"]),self.root,env,offline_revision=121)
                self.assertEqual(0,result.returncode,result.stderr)
        self.assertEqual(["superseded=true"]*2,output.read_text().splitlines())
        checks = ScheduledA6PathTests(); checks.setUpClass()
        context = checks.context(); context["needs.build-validate.outputs.superseded"] = "true"
        self.assertFalse(checks.enabled("build-ready-write",context))
        self.assertTrue(checks.enabled("superseded-build-retirement",context))
        self.assertFalse(checks.enabled("superseded-build-retirement",context,cancelled=True))


if __name__ == "__main__": unittest.main()
