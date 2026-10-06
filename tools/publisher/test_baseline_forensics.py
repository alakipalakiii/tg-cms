"""Offline contracts for the single-run, read-only baseline forensic collector."""

from io import BytesIO
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from zipfile import ZipFile

import yaml
import baseline_forensics as f


ACCOUNT = "773d2dc31655b158d088296a14af5834"
HOST = "mahoonartmagazine.ir"
PERSISTED_DEPLOYMENT = f.PERSISTED_DEPLOYMENT
PERSISTED_VERSION = f.PERSISTED_VERSION
ACTIVE = {"id": PERSISTED_DEPLOYMENT, "created_on": "2026-09-30T15:00:00Z", "versions": [{"version_id": PERSISTED_VERSION, "percentage": 100}]}


def envelope(result, pages=1, page=1):
    return {"success": True, "result": result, "result_info": {"total_pages": pages, "page": page}}


def fixture_responses(active=ACTIVE, deployments=None, versions=None, audit=None):
    deployments = deployments if deployments is not None else [active]
    versions = versions if versions is not None else [{"id": PERSISTED_VERSION, "number": 7, "metadata": {"created_on": "2026-09-30T14:10:00Z", "source": "wrangler", "author_id": "actor-id", "author_email": "private@example.test"}}]
    audit = audit if audit is not None else []

    def get(url):
        if url.endswith(f"/accounts/{ACCOUNT}"):
            return envelope({"id": ACCOUNT})
        if url.endswith("/workers/scripts"):
            return envelope([{"id": f.WORKER}])
        if "/workers/domains?" in url:
            return envelope([{"hostname": HOST, "service": f.WORKER, "environment": "production"}])
        if "/deployments" in url:
            return envelope({"deployments": deployments}, pages=1)
        if "/versions?" in url:
            return envelope({"items": versions}, pages=1)
        if "/audit_logs?" in url:
            return envelope(audit, pages=1)
        raise AssertionError(f"unexpected GET: {url}")
    return get


class BaselineForensicsTests(unittest.TestCase):
    def test_exact_deployment_and_active_version(self):
        result = f._cloudflare_evidence(fixture_responses(), ACCOUNT, HOST, "2026-10-06T00:00:00Z")
        self.assertEqual("PASS", result["account_identity_status"])
        self.assertEqual("PASS", result["active_deployment_status"])
        self.assertEqual({PERSISTED_VERSION: 100}, result["active_allocations"])
        self.assertEqual("FOUND", result["persisted_deployment_history_match"]["status"])

    def test_different_deployment_same_persisted_version_is_classified(self):
        classification = f.classify("new-deployment", {PERSISTED_VERSION: 100}, PERSISTED_DEPLOYMENT,
                                    PERSISTED_VERSION, False, [], [], "UNAVAILABLE")
        self.assertEqual(("SAME_VERSION_NEW_DEPLOYMENT", "HIGH"), classification)

    def test_different_deployment_and_version_is_classified(self):
        classification = f.classify("new-deployment", {"new-version": 100}, PERSISTED_DEPLOYMENT,
                                    PERSISTED_VERSION, False, [], [], "UNAVAILABLE")
        self.assertEqual(("DIFFERENT_ACTIVE_VERSION", "HIGH"), classification)

    def test_mixed_traffic_allocation_is_drift(self):
        self.assertEqual("TRAFFIC_ALLOCATION_DRIFT", f.classify("new", {PERSISTED_VERSION: 99, "old": 1},
                         PERSISTED_DEPLOYMENT, PERSISTED_VERSION, False, [], [], "AVAILABLE")[0])

    def test_persisted_and_observed_deployment_history_matches(self):
        rows = [ACTIVE, {"id": f.PRIOR_OBSERVED_DEPLOYMENT, "versions": [{"version_id": "v", "percentage": 100}]}]
        self.assertEqual("FOUND", f._match(rows, PERSISTED_DEPLOYMENT, True)["status"])
        self.assertEqual("FOUND", f._match(rows, f.PRIOR_OBSERVED_DEPLOYMENT, True)["status"])

    def test_missing_deployment_is_distinguished_by_pagination_coverage(self):
        self.assertEqual("NOT_FOUND_IN_COMPLETE_HISTORY", f._match([], PERSISTED_DEPLOYMENT, True)["status"])
        self.assertEqual("NOT_FOUND_IN_RETRIEVED_WINDOW", f._match([], PERSISTED_DEPLOYMENT, False)["status"])

    def test_missing_pagination_metadata_cannot_claim_complete_history(self):
        result = f._paged_get(lambda _: {"success": True, "result": {"deployments": [ACTIVE]}},
                              f"/accounts/{ACCOUNT}/workers/scripts/{f.WORKER}/deployments", "deployments", 5)
        self.assertFalse(result["complete"])
        self.assertEqual("PAGINATION_METADATA_UNAVAILABLE", result["safe_error_class"])

    def test_malformed_deployment_metadata_and_allocation(self):
        record = f._deployment_record({"id": "d", "versions": [{"version_id": "v", "percentage": True}]})
        self.assertEqual("VERSIONS_MALFORMED", record["allocation_error"])

    def test_unauthorized_audit_read_is_unavailable_not_negative_evidence(self):
        def get(url):
            if "/audit_logs?" in url:
                raise f.ForensicError("HTTP_READ_FAILED", 403)
            return fixture_responses()(url)
        result = f._cloudflare_evidence(get, ACCOUNT, HOST, "2026-10-06T00:00:00Z")
        self.assertEqual("UNAVAILABLE", result["audit_evidence_status"])
        self.assertIn("AUDIT_EVIDENCE_UNAVAILABLE", result["limitations"])

    def test_allocation_change_during_observation_is_flagged(self):
        changed = f.classify("one", {PERSISTED_VERSION: 100}, PERSISTED_DEPLOYMENT,
                             PERSISTED_VERSION, True, [], [], "AVAILABLE")
        self.assertEqual("REMOTE_SNAPSHOT_CHANGED_DURING_FORENSICS", changed[0])

    def test_git_history_records_exact_state_bytes_and_observed_version(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._git_repo(root)
            self._write_state(root, "d-old", "v-old")
            self._commit(root, "old state")
            self._write_state(root, PERSISTED_DEPLOYMENT, PERSISTED_VERSION)
            self._commit(root, "persisted deployment")
            history = f.git_state_history(root)
            self.assertEqual(2, len(history))
            self.assertTrue(all(len(item["file_sha256"]) == 64 for item in history))
            finding = f.git_history_findings(root, history, PERSISTED_DEPLOYMENT, "cloudflare-deployment", [PERSISTED_VERSION])
            self.assertEqual("d-old", finding["first_commit_introducing_persisted_deployment"]["parent_state"]["deployment_id"])
            self.assertEqual("v-old", finding["first_commit_introducing_persisted_deployment"]["parent_state"]["current_version"])
            self.assertFalse(finding["observed_deployment_ever_persisted"])
            self.assertTrue(finding["active_version_ever_persisted"][PERSISTED_VERSION])

    def test_git_history_without_active_version_reports_false(self):
        history = [{"deployment_id": "d", "current_version": "other"}]
        finding = f.git_history_findings(".", history, "d", "unknown", [PERSISTED_VERSION])
        self.assertFalse(finding["active_version_ever_persisted"][PERSISTED_VERSION])

    def test_missing_timestamps_are_not_invented(self):
        started, finished = "2026-10-01T00:00:00Z", "2026-10-01T00:00:01Z"
        timeline = f.build_timeline([], {"runs": [], "artifacts": []}, {"deployment_history": {"items": []}, "audit_evidence": []}, started, finished)
        self.assertEqual([started, finished], [item["timestamp_utc"] for item in timeline])

    def test_no_source_or_actor_attribution_is_guessed(self):
        deployment = f._deployment_record({"id": "d", "versions": [{"version_id": "v", "percentage": 100}]})
        audit = f._compact_audit({"resource": {"id": "d"}, "metadata": {"worker_name": f.WORKER}}, ("d",), f.WORKER)
        self.assertNotIn("source", deployment)
        self.assertEqual({}, audit["actor"])

    def test_sensitive_metadata_is_redacted_or_allowlisted(self):
        deployment = f._deployment_record({"author_email": "secret@example.test", "annotations": {"workers/message": "Bearer abc123 token=secret-value"}, "versions": [{"version_id": "v", "percentage": 100}]})
        self.assertEqual("[REDACTED]", deployment["author_email"])
        self.assertNotIn("abc123", deployment["annotations"]["workers/message"])
        audit = f._compact_audit({"when": "2026-10-01T00:00:00Z", "actor": {"email": "private@example.test", "ip": "192.0.2.1", "id": "actor", "type": "user"}, "resource": {"id": "d"}, "metadata": {"version_id": "v", "secret": "hidden"}}, ("d",), f.WORKER)
        self.assertEqual("[REDACTED]", audit["actor_email"])
        self.assertNotIn("hidden", json.dumps(audit))

    def test_artifact_extraction_keeps_only_uuid_references(self):
        bundle = BytesIO()
        with ZipFile(bundle, "w") as archive:
            archive.writestr("proof.json", json.dumps({"deployment_id": PERSISTED_DEPLOYMENT, "version_id": PERSISTED_VERSION, "token": "do-not-copy"}))
        refs = f._artifact_references(bundle.getvalue(), "proof", 9)
        self.assertEqual({PERSISTED_DEPLOYMENT, PERSISTED_VERSION}, {item["value"] for item in refs})
        self.assertNotIn("token", json.dumps(refs))

    def test_only_get_requests_and_no_mutating_or_publish_workflow(self):
        source = Path(f.__file__).read_text(encoding="utf-8")
        workflow = Path(__file__).resolve().parents[2] / ".github/workflows/mahoon-baseline-forensics.yml"
        raw = workflow.read_text(encoding="utf-8")
        parsed = yaml.load(raw, Loader=yaml.BaseLoader)
        self.assertEqual({"workflow_dispatch": ""}, parsed["on"])
        self.assertEqual("mahoon-production-publisher", parsed["concurrency"]["group"])
        self.assertEqual("false", parsed["concurrency"]["cancel-in-progress"])
        self.assertEqual({"contents": "read", "actions": "read"}, parsed["permissions"])
        self.assertIn('method="GET"', source)
        self.assertNotRegex(source, r"(?i)method\s*=\s*['\"](?:POST|PUT|PATCH|DELETE)")
        self.assertNotIn("mahoon-static-publisher.yml --ref", source + raw)
        self.assertNotIn("secrets.CLOUDFLARE_API_TOKEN", raw)
        self.assertIn("fetch-depth: 0", raw)

    def test_forensics_does_not_write_journal_or_persisted_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._git_repo(root)
            self._write_state(root, PERSISTED_DEPLOYMENT, PERSISTED_VERSION)
            state_path = root / "publisher-state/published-static-state.json"
            journal = root / "publisher-state/production-transaction-journal.json"
            journal.write_text('{"generation":2}', encoding="utf-8")
            self._commit(root, "inputs")
            before = state_path.read_bytes(), journal.read_bytes()
            def get(url):
                return fixture_responses()(url)
            gh = {"status": "AVAILABLE", "runs": [], "artifacts": []}
            evidence, _, _ = f.run_forensics(root, ACCOUNT, HOST, "token", "gh-token", "repo/name", get_json=get, gh_history=gh)
            self.assertEqual(before, (state_path.read_bytes(), journal.read_bytes()))
            self.assertTrue(evidence["journal_unchanged"])
            self.assertTrue(evidence["persisted_state_unchanged"])
            self.assertFalse(evidence["cloudflare_mutation_started"])
            self.assertFalse(evidence["publish_dispatched"])

    def test_remote_deployment_change_during_collection_is_incomplete(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._git_repo(root)
            self._write_state(root, PERSISTED_DEPLOYMENT, PERSISTED_VERSION)
            (root / "publisher-state/production-transaction-journal.json").write_text("{}", encoding="utf-8")
            self._commit(root, "inputs")
            calls = {"snapshot": 0}
            changed_active = {"id": "later", "created_on": "2026-10-01T00:00:00Z", "versions": [{"version_id": PERSISTED_VERSION, "percentage": 100}]}
            base = fixture_responses()
            def get(url):
                if "/deployments" in url:
                    calls["snapshot"] += 1
                    row = ACTIVE if calls["snapshot"] == 1 else changed_active
                    return envelope({"deployments": [row]})
                return base(url)
            evidence, _, _ = f.run_forensics(root, ACCOUNT, HOST, "token", "gh-token", "repo/name", get_json=get, gh_history={"status":"AVAILABLE","runs":[],"artifacts":[]})
            self.assertEqual("REMOTE_SNAPSHOT_CHANGED_DURING_FORENSICS", evidence["root_cause_classification"])
            self.assertEqual("M11_E_BASELINE_FORENSICS_INCOMPLETE", evidence["final_status"])

    @staticmethod
    def _git_repo(root):
        subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Forensics test"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)

    @staticmethod
    def _write_state(root, deployment, version):
        path = root / "publisher-state/published-static-state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"deployment_id": deployment, "current_version": version, "previous_version": "prev", "current_version_type": "STATIC", "artifact_seal": "seal", "content_fingerprint": "fingerprint"}), encoding="utf-8")

    @staticmethod
    def _commit(root, message):
        subprocess.run(["git", "add", "publisher-state"], cwd=root, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", message], cwd=root, check=True, capture_output=True)


if __name__ == "__main__":
    unittest.main()
