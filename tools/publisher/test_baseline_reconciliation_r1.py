"""Offline safety contracts for the single R1 state reconciliation."""

from collections import deque
from io import BytesIO
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from zipfile import ZipFile
import yaml

import baseline_reconciliation_r1 as r1


ACCOUNT = "773d2dc31655b158d088296a14af5834"
HOST = "mahoonartmagazine.ir"
OLD = r1.OLD_DEPLOYMENT
NEW = r1.ACCEPTED_DEPLOYMENT
VERSION = r1.CURRENT_VERSION
STATE = json.dumps(r1.EXPECTED_STATE, indent=2).encode() + b"\n"


def envelope(result, pages=1):
    return {"success": True, "result": result, "result_info": {"page": 1, "total_pages": pages}}


def make_deployments(active_id=NEW, active_allocation=None, include_old=True, include_new=True):
    active_allocation = active_allocation or {VERSION: 100, r1.ZERO_PERCENT_VERSION: 0}
    rows = []
    if include_new:
        rows.append({"id": NEW, "created_on": "2026-09-30T14:32:38Z", "versions": [
            {"version_id": key, "percentage": value} for key, value in active_allocation.items()]})
    if include_old:
        rows.append({"id": OLD, "created_on": "2026-09-30T13:47:04Z", "versions": [
            {"version_id": VERSION, "percentage": 100}, {"version_id": r1.PREVIOUS_VERSION, "percentage": 0}]})
    if active_id not in {row["id"] for row in rows}:
        rows.insert(0, {"id": active_id, "versions": [{"version_id": VERSION, "percentage": 100}]})
    return rows


def cf_getter(*, account_response=ACCOUNT, worker=True, domain=True, active_sequence=None,
              rows=None, active_records=None, fail_path=None):
    rows = rows if rows is not None else make_deployments()
    active_records = active_records or rows
    active_sequence = deque(active_sequence or [active_records[0], active_records[0]])

    def get(url):
        parsed = urlparse(url)
        path = parsed.path
        if fail_path and fail_path in path:
            raise r1.R1Blocked("CLOUDFLARE_READ", "CLOUDFLARE_READ_FAILED")
        if path == f"/client/v4/accounts/{ACCOUNT}":
            return envelope({"id": account_response})
        if path.endswith("/workers/scripts"):
            return envelope([{"id": r1.WORKER}] if worker else [])
        if path.endswith("/workers/domains"):
            return envelope([{"hostname": HOST, "service": r1.WORKER, "environment": "production"}] if domain else [])
        if path.endswith("/deployments"):
            query = parse_qs(parsed.query)
            if query.get("per_page") == ["1"]:
                active = active_sequence.popleft() if len(active_sequence) > 1 else active_sequence[0]
                return envelope({"deployments": [active]})
            page = int(query.get("page", ["1"])[0])
            return envelope({"deployments": rows if page == 1 else []}, pages=1)
        raise AssertionError(f"unexpected Cloudflare GET: {url}")

    return get


def journal_bytes(**overrides):
    operations = {name: {"operation_id": value, "attempts": [], "intent_state": "NOT_STARTED", "result_state": "NOT_REPORTED"}
                  for name, value in r1.EXPECTED_OPERATIONS.items()}
    item = {"content_revision": 109, "state": "blocked", "logical_transaction_id": r1.EXPECTED_TRANSACTION,
            "worker": r1.WORKER, "recovery_status": "NONE", "operations": operations,
            "execution_attempts": [{"attempt_id": "1", "run_id": "37379469235", "source": "workflow_dispatch",
                                    "timestamp": "2026-10-05T21:59:34.411777+00:00"}]}
    value = {"generation": 2, "active": None, "pending": None, "history": [item]}
    value.update(overrides)
    return json.dumps(value, indent=2).encode()


class R1SafetyTests(unittest.TestCase):
    def test_valid_owner_accepted_allocation_and_complete_history(self):
        result = r1.verify_cloudflare(cf_getter(), ACCOUNT, HOST)
        self.assertEqual("PASS", result["account_identity"])
        self.assertEqual(NEW, result["active_deployment_id"])
        self.assertEqual({VERSION: 100, r1.ZERO_PERCENT_VERSION: 0}, result["active_version_allocation"])
        self.assertTrue(result["deployment_history_proof"]["complete"])
        self.assertTrue(result["deployment_history_proof"]["old_found"])
        self.assertTrue(result["deployment_history_proof"]["accepted_found"])

    def test_deployment_changes_before_persistence_blocks(self):
        before = {"active_deployment_id": NEW, "allocation": {VERSION: 100}}
        after = {"active_deployment_id": "later", "allocation": {VERSION: 100}}
        with self.assertRaisesRegex(r1.R1Blocked, "CLOUDFLARE_SNAPSHOT_CHANGED"):
            r1.verify_snapshots_equal(before, after)

    def test_active_deployment_must_be_the_owner_accepted_id(self):
        rows = make_deployments(active_id="unexpected")
        with self.assertRaises(r1.R1Blocked):
            r1.verify_cloudflare(cf_getter(rows=rows), ACCOUNT, HOST)

    def test_changed_active_version_blocks(self):
        rows = make_deployments()
        changed = {"id": NEW, "versions": [{"version_id": "unexpected-version", "percentage": 100}]}
        with self.assertRaisesRegex(r1.R1Blocked, "ACTIVE_DEPLOYMENT_HISTORY_MISMATCH"):
            r1.verify_cloudflare(cf_getter(rows=rows, active_sequence=[changed, changed]), ACCOUNT, HOST)

    def test_mixed_traffic_blocks(self):
        rows = make_deployments()
        mixed = {"id": NEW, "versions": [{"version_id": VERSION, "percentage": 99}, {"version_id": "unexpected-version", "percentage": 1}]}
        with self.assertRaisesRegex(r1.R1Blocked, "ACTIVE_DEPLOYMENT_HISTORY_MISMATCH"):
            r1.verify_cloudflare(cf_getter(rows=rows, active_sequence=[mixed, mixed]), ACCOUNT, HOST)

    def test_zero_percent_entries_must_be_well_formed_and_total_exact(self):
        rows = make_deployments(active_allocation={VERSION: 100, "bad": True})
        with self.assertRaisesRegex(r1.R1Blocked, "VERSION_ALLOCATION_MALFORMED"):
            r1.verify_cloudflare(cf_getter(rows=rows), ACCOUNT, HOST)

    def test_old_history_identity_is_required(self):
        with self.assertRaises(r1.R1Blocked):
            r1.verify_cloudflare(cf_getter(rows=make_deployments(include_old=False)), ACCOUNT, HOST)

    def test_accepted_history_identity_is_required(self):
        rows = make_deployments(active_id=OLD, include_new=False)
        active = {"id": NEW, "versions": [{"version_id": VERSION, "percentage": 100}]}
        with self.assertRaises(r1.R1Blocked):
            r1.verify_cloudflare(cf_getter(rows=rows, active_records=[active, active]), ACCOUNT, HOST)

    def test_account_worker_and_production_domain_are_verified(self):
        with self.assertRaisesRegex(r1.R1Blocked, "ACCOUNT_IDENTITY_MISMATCH"):
            r1.verify_cloudflare(cf_getter(account_response="other"), ACCOUNT, HOST)
        with self.assertRaisesRegex(r1.R1Blocked, "WORKER_IDENTITY_MISMATCH"):
            r1.verify_cloudflare(cf_getter(worker=False), ACCOUNT, HOST)
        with self.assertRaisesRegex(r1.R1Blocked, "PRODUCTION_DOMAIN_MISMATCH"):
            r1.verify_cloudflare(cf_getter(domain=False), ACCOUNT, HOST)

    def test_start_and_end_cloudflare_snapshots_must_match(self):
        changed = {"id": "changed", "versions": [{"version_id": VERSION, "percentage": 100}]}
        with self.assertRaisesRegex(r1.R1Blocked, "CLOUDFLARE_SNAPSHOT_CHANGED"):
            r1.verify_cloudflare(cf_getter(active_sequence=[make_deployments()[0], changed]), ACCOUNT, HOST)

    def test_cloudflare_read_failure_fails_closed(self):
        with self.assertRaisesRegex(r1.R1Blocked, "CLOUDFLARE_READ_FAILED"):
            r1.verify_cloudflare(cf_getter(fail_path="/accounts/"), ACCOUNT, HOST)

    def test_missing_read_token_blocks_before_any_read(self):
        with tempfile.TemporaryDirectory() as temp:
            def forbidden(_):
                raise AssertionError("Cloudflare read should not run without a token")
            with patch.dict("os.environ", {"GITHUB_SHA": r1.INITIAL_MAIN_SHA}):
                evidence = r1.execute(temp, "YES", ACCOUNT, HOST, "", "gh", "alakipalakiii/tg-cms", temp,
                                      get_cf=forbidden, get_gh=forbidden, download_zip=forbidden)
            self.assertEqual("CREDENTIAL_PREFLIGHT", evidence["failed_stage"])
            self.assertFalse(evidence["cloudflare_mutation"])

    def test_journal_exact_identity_and_generation(self):
        parsed = r1.validate_journal(journal_bytes())
        self.assertEqual(109, parsed["history"][0]["content_revision"])
        for changed in (journal_bytes(generation=3), journal_bytes(active={"id": "new"}),
                        journal_bytes(pending={"id": "new"})):
            with self.assertRaises(r1.R1Blocked):
                r1.validate_journal(changed)

    def test_retained_transaction_identity_must_match(self):
        data = json.loads(journal_bytes())
        data["history"][0]["logical_transaction_id"] = "other"
        with self.assertRaisesRegex(r1.R1Blocked, "RETAINED_TRANSACTION_IDENTITY_MISMATCH"):
            r1.validate_journal(json.dumps(data).encode())

    def test_state_reconciliation_changes_only_deployment_id_and_preserves_bytes(self):
        after = r1.validate_original_state(STATE)
        before_value, after_value = json.loads(STATE), json.loads(after)
        self.assertEqual(NEW, after_value["deployment_id"])
        before_value.pop("deployment_id")
        after_value.pop("deployment_id")
        self.assertEqual(before_value, after_value)
        self.assertEqual(STATE.replace(OLD.encode(), NEW.encode()), after)

    def test_additional_state_field_is_rejected(self):
        value = json.loads(STATE)
        value["new_field"] = "unexpected"
        with self.assertRaisesRegex(r1.R1Blocked, "PERSISTED_STATE_UNEXPECTED"):
            r1.validate_original_state(json.dumps(value).encode())

    def test_state_blob_bytes_must_match_remote_exactly(self):
        raw = STATE + b"\n"
        self.assertNotEqual(r1._sha256(STATE), r1._sha256(raw))
        with self.assertRaises(r1.R1Blocked):
            r1.require_exact_bytes(STATE, raw, "PERSISTED_STATE")

    def test_other_five_state_files_and_journal_must_be_unchanged(self):
        before = {path: {"sha256": "a", "blob_sha": "a"} for path in r1.SIX_STATE_PATHS}
        after = dict(before)
        after[r1.STATE_PATH] = {"sha256": "new", "blob_sha": "new"}
        r1.verify_unchanged_files(before, after, {"sha256": "j"}, {"sha256": "j"})
        changed = dict(after)
        other = next(path for path in r1.SIX_STATE_PATHS if path != r1.STATE_PATH)
        changed[other] = {"sha256": "changed", "blob_sha": "changed"}
        with self.assertRaisesRegex(r1.R1Blocked, "OTHER_PUBLISHED_STATE_CHANGED"):
            r1.verify_unchanged_files(before, changed, {"sha256": "j"}, {"sha256": "j"})
        with self.assertRaisesRegex(r1.R1Blocked, "JOURNAL_CHANGED"):
            r1.verify_unchanged_files(before, after, {"sha256": "j"}, {"sha256": "changed"})

    def test_postcommit_cloudflare_drift_blocks_without_rollback(self):
        before = {"active_deployment_id": NEW, "allocation": {VERSION: 100}}
        after = {"active_deployment_id": NEW, "allocation": {VERSION: 99, "other": 1}}
        with self.assertRaises(r1.R1Blocked):
            r1.verify_snapshots_equal(before, after, "POSTCOMMIT_CLOUDFLARE")

    def test_f1_evidence_is_verified_and_hash_preserved(self):
        archive = BytesIO()
        expected = {"forensic_run_id": r1.F1_RUN_ID, "final_status": "M11_E_BASELINE_FORENSICS_COMPLETE",
                    "root_cause_classification": "SAME_VERSION_NEW_DEPLOYMENT", "root_cause_confidence": "HIGH"}
        with ZipFile(archive, "w") as bundle:
            bundle.writestr("evidence/mahoon-baseline-forensics-evidence.json", json.dumps(expected))
            bundle.writestr("evidence/mahoon-baseline-forensics-timeline.json", "[]")
            bundle.writestr("evidence/mahoon-baseline-forensics-report.txt", "F1 report")
        def get(url):
            if url.endswith(f"/actions/runs/{r1.F1_RUN_ID}"):
                return {"head_sha": r1.F1_SOURCE_SHA, "event": "workflow_dispatch", "conclusion": "success"}
            return {"artifacts": [{"id": 4, "name": r1.F1_ARTIFACT_NAME, "expired": False,
                                    "archive_download_url": "https://artifact.invalid/download"}]}
        proof = r1.verify_f1_evidence(get, lambda _: archive.getvalue(), "alakipalakiii/tg-cms")
        self.assertEqual("UNRESOLVED", proof["attribution_status"])
        self.assertEqual(r1._sha256(archive.getvalue()), proof["archive_sha256"])
        self.assertEqual(3, len(proof["files"]))

    def test_workflow_is_one_confirmed_isolated_read_token_writer(self):
        workflow = Path(__file__).resolve().parents[2] / ".github/workflows/mahoon-baseline-reconciliation-r1.yml"
        data = yaml.load(workflow.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        self.assertEqual({"workflow_dispatch": {"inputs": {"ready": {"description": "Type YES to authorize this single controlled reconciliation run", "required": "true", "type": "choice", "options": ["YES", "NO"]}}}}, data["on"])
        self.assertEqual({"contents": "write", "actions": "read"}, data["permissions"])
        self.assertEqual("mahoon-production-publisher", data["concurrency"]["group"])
        self.assertEqual("false", data["concurrency"]["cancel-in-progress"])
        text = workflow.read_text(encoding="utf-8")
        self.assertIn("secrets.CLOUDFLARE_READ_API_TOKEN", text)
        self.assertNotIn("secrets.CLOUDFLARE_API_TOKEN", text)
        self.assertNotIn("workflow: run", text)
        self.assertNotIn("mahoon-static-publisher", text)
        self.assertNotIn("--force", text)

    def test_h1_dispatch_yes_no_are_yaml_strings_not_booleans(self):
        workflow = Path(__file__).resolve().parents[2] / ".github/workflows/mahoon-baseline-reconciliation-r1.yml"
        raw = workflow.read_text(encoding="utf-8")
        payload = yaml.safe_load(raw)
        # PyYAML YAML 1.1 may interpret the GitHub `on` key as True.
        event_map = payload.get("on", payload.get(True))
        choices = event_map["workflow_dispatch"]["inputs"]["ready"]["options"]
        self.assertEqual(["YES", "NO"], choices)
        self.assertTrue(all(type(value) is str for value in choices))
        self.assertIn('          - "YES"\n          - "NO"\n', raw)
        for bad in ('          - YES\n          - NO\n', '          - true\n          - false\n'):
            wrong = yaml.safe_load(raw.replace('          - "YES"\n          - "NO"\n', bad))
            bad_choices = wrong.get("on", wrong.get(True))["workflow_dispatch"]["inputs"]["ready"]["options"]
            self.assertNotEqual(["YES", "NO"], bad_choices)

    def test_h1_actual_source_guard_exact_parent_grandparent_and_scopes(self):
        expected = "a" * 40
        approved_paths = set(r1.R1_SOURCE_FILES)

        def exercise(*, head=expected, remote=expected, parent=None, grandparent=None,
                     h1_files=None, r1_files=None, api_head=expected):
            parent = r1.R1_IMPLEMENTATION_SHA if parent is None else parent
            grandparent = r1.INITIAL_MAIN_SHA if grandparent is None else grandparent
            h1_files = approved_paths if h1_files is None else h1_files
            r1_files = approved_paths if r1_files is None else r1_files
            values = {
                ("rev-parse", "HEAD"): head,
                ("rev-parse", "refs/remotes/origin/main"): remote,
                ("rev-parse", "HEAD^"): parent,
                ("rev-parse", "HEAD^^"): grandparent,
                ("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"): "\n".join(sorted(h1_files)),
                ("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD^"): "\n".join(sorted(r1_files)),
                ("fetch", "origin", "main"): "",
            }
            def fake_git(_root, *args, **kwargs):
                key = tuple(args)
                if key not in values:
                    raise AssertionError(f"unexpected git command: {key}")
                return subprocess.CompletedProcess(args, 0, stdout=values[key].encode())
            with patch.object(r1, "_git", side_effect=fake_git), patch.object(r1, "_github_get", return_value={"sha": api_head}):
                return r1.check_source_and_remote(Path("."), expected, object(), "https://api.github.invalid", "alakipalakiii/tg-cms")

        self.assertEqual(expected, exercise()["source_commit"])
        cases = (
            {"head": "b" * 40},
            {"remote": "b" * 40},
            {"parent": "b" * 40},
            {"grandparent": "b" * 40},
            {"h1_files": approved_paths | {"unauthorized.txt"}},
            {"r1_files": approved_paths | {"unauthorized.txt"}},
            {"h1_files": approved_paths - {"tools/publisher/test_baseline_reconciliation_r1.py"}},
            {"r1_files": approved_paths - {"tools/publisher/test_baseline_reconciliation_r1.py"}},
            {"api_head": "b" * 40},
        )
        for case in cases:
            with self.subTest(case=case), self.assertRaises(r1.R1Blocked):
                exercise(**case)

    def test_cloudflare_client_is_get_only_and_no_journal_write_path_exists(self):
        source = Path(r1.__file__).read_text(encoding="utf-8")
        self.assertIn('method="GET"', source)
        self.assertNotRegex(source, r"(?i)method\s*=\s*['\"](?:POST|PUT|PATCH|DELETE)")
        self.assertIn('"push", "origin", "HEAD:refs/heads/main"', source)
        self.assertNotIn('"workflow", "run"', source)
        self.assertIn('Path(root, STATE_PATH).write_bytes(after_raw)', source)
        self.assertNotIn('Path(root, JOURNAL_PATH).write_bytes', source)


class GitPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.remote = base / "remote.git"
        self.root = base / "work"
        subprocess.run(["git", "init", "--bare", "--initial-branch=main", str(self.remote)], check=True, capture_output=True)
        self.root.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "R1 test")
        self.git("config", "user.email", "r1@example.invalid")
        state_path = self.root / r1.STATE_PATH
        state_path.parent.mkdir(parents=True)
        state_path.write_bytes(STATE)
        self.git("add", r1.STATE_PATH)
        self.git("commit", "-m", "source")
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "origin", "main")
        self.git("fetch", "origin", "main")
        self.head = self.git("rev-parse", "HEAD").stdout.decode().strip()

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True)

    def persist(self, runner=r1._git):
        after = r1.validate_original_state(STATE)
        return r1._persist_once(self.root, self.head, STATE, after, {}, git_runner=runner)

    def test_local_remote_persists_exactly_one_state_file(self):
        result = self.persist()
        self.assertEqual(result["commit"], result["remote_main"])
        changed = self.git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").stdout.decode().splitlines()
        self.assertEqual([r1.STATE_PATH], changed)
        self.assertEqual(NEW, json.loads((self.root / r1.STATE_PATH).read_bytes())["deployment_id"])

    def test_branch_concurrent_update_blocks_before_state_write(self):
        second = Path(self.temp.name) / "second"
        subprocess.run(["git", "clone", str(self.remote), str(second)], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Racer"], cwd=second, check=True)
        subprocess.run(["git", "config", "user.email", "racer@example.invalid"], cwd=second, check=True)
        (second / "unrelated.txt").write_text("race")
        subprocess.run(["git", "add", "unrelated.txt"], cwd=second, check=True)
        subprocess.run(["git", "commit", "-m", "concurrent"], cwd=second, check=True, capture_output=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=second, check=True, capture_output=True)
        with self.assertRaisesRegex(r1.R1Blocked, "REMOTE_MAIN_MOVED"):
            self.persist()
        self.assertEqual(STATE, (self.root / r1.STATE_PATH).read_bytes())

    def test_rejected_push_is_never_retried(self):
        real_git = r1._git
        calls = []
        def reject_once(root, *args, **kwargs):
            if args and args[0] == "push":
                calls.append(args)
                return subprocess.CompletedProcess(args, 1, b"", b"rejected")
            return real_git(root, *args, **kwargs)
        with self.assertRaisesRegex(r1.R1Blocked, "PUSH_REJECTED_OR_REMOTE_ADVANCED"):
            self.persist(reject_once)
        self.assertEqual(1, len(calls))

    def test_uncertain_push_is_resolved_by_exact_remote_readback(self):
        real_git = r1._git
        calls = []
        def push_then_lose_response(root, *args, **kwargs):
            if args and args[0] == "push":
                calls.append(args)
                real_git(root, *args, **kwargs)
                return subprocess.CompletedProcess(args, 1, b"", b"response lost")
            return real_git(root, *args, **kwargs)
        result = self.persist(push_then_lose_response)
        self.assertTrue(result["uncertain_push_reconciled"])
        self.assertEqual(1, len(calls))

    def test_second_execution_cannot_commit_again(self):
        self.persist()
        with self.assertRaises(r1.R1Blocked):
            self.persist()
        self.assertEqual(1, len(self.git("log", "--oneline").stdout.decode().splitlines()) - 1)


if __name__ == "__main__":
    unittest.main()
