"""Contract tests for the independent Cloudflare GET-only baseline gate."""

import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import production_baseline_readonly as baseline
from production_baseline_readonly import WORKER_NAME, reconcile
import yaml


ACCOUNT = "773d2dc31655b158d088296a14af5834"
HOST = "mahoonartmagazine.ir"
TOKEN = "read-only-test-token"
STATE = {"current_version_type": "STATIC", "current_version": "v-current", "deployment_id": "d-current"}
WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/mahoon-production-baseline-readonly.yml"


def responses(state=STATE):
    return {
        "scripts": [{"id": WORKER_NAME}],
        "domains": [{"hostname": HOST, "service": WORKER_NAME, "environment": "production"}],
        "deployments": {"deployments": [{"id": state["deployment_id"], "versions": [{"version_id": state["current_version"], "percentage": 100}]}]},
    }


class BaselineTests(unittest.TestCase):
    def run_gate(self, state=STATE, account=ACCOUNT, hostname=HOST, token=TOKEN, mutate=None):
        data = responses(state)
        calls = []

        def getter(path, supplied_token):
            calls.append((path, supplied_token))
            key = "scripts" if path.endswith("/scripts") else "domains" if "/domains?" in path else "deployments"
            value = data[key]
            if mutate:
                mutate(key, value)
            return copy.deepcopy(value)

        before = json.dumps(state, sort_keys=True) if isinstance(state, dict) else None
        result = reconcile(state, account, hostname, token, getter)
        after = json.dumps(state, sort_keys=True) if isinstance(state, dict) else None
        self.assertEqual(before, after)
        self.assertTrue(all("Bearer " not in path and supplied == token for path, supplied in calls))
        self.assertTrue(all(not path.startswith(("POST ", "PUT ", "PATCH ", "DELETE ")) for path, _ in calls))
        self.assertFalse(any("CLOUDFLARE_API_TOKEN" in str(v) or "Authorization" in str(v) for v in result.values()))
        return result, calls

    def test_exact_production_baseline_passes(self):
        result, calls = self.run_gate()
        self.assertEqual("PASS", result["baseline_status"])
        self.assertTrue(result["publish_authorized"])
        self.assertEqual(6, len(calls))

    def test_wrong_account_blocks(self):
        result, _ = self.run_gate(account="0" * 32, mutate=lambda key, value: value.__setitem__(0, {"id": "other"}) if key == "scripts" else None)
        self.assertEqual("BLOCKED", result["baseline_status"])

    def test_wrong_worker_blocks(self):
        result, _ = self.run_gate(mutate=lambda key, value: value.__setitem__(0, {"id": "other"}) if key == "scripts" else None)
        self.assertEqual("PRODUCTION_BASELINE_DRIFT", result["safe_error_class"])

    def test_wrong_hostname_blocks(self):
        result, _ = self.run_gate(hostname="wrong.example")
        self.assertEqual("BLOCKED", result["baseline_status"])

    def test_wrong_environment_blocks(self):
        result, _ = self.run_gate(mutate=lambda key, value: value[0].update(environment="preview") if key == "domains" else None)
        self.assertEqual("PRODUCTION_BASELINE_DRIFT", result["safe_error_class"])

    def test_deployment_identity_mismatch_blocks(self):
        result, _ = self.run_gate(mutate=lambda key, value: value["deployments"][0].update(id="other") if key == "deployments" else None)
        self.assertEqual("PRODUCTION_BASELINE_DRIFT", result["safe_error_class"])

    def test_version_identity_mismatch_blocks(self):
        result, _ = self.run_gate(mutate=lambda key, value: value["deployments"][0]["versions"][0].update(version_id="other") if key == "deployments" else None)
        self.assertEqual("BLOCKED", result["baseline_status"])

    def test_99_percent_and_mixed_allocation_block(self):
        for versions in ([{"version_id": "v-current", "percentage": 99}],
                         [{"version_id": "v-current", "percentage": 99}, {"version_id": "v-old", "percentage": 1}]):
            with self.subTest(versions=versions):
                result, _ = self.run_gate(mutate=lambda key, value, versions=versions: value["deployments"][0].update(versions=versions) if key == "deployments" else None)
                self.assertEqual("BLOCKED", result["baseline_status"])

    def test_malformed_version_allocation_blocks(self):
        result, _ = self.run_gate(mutate=lambda key, value: value["deployments"][0].update(versions=[{"version_id": "v-current", "percentage": True}]) if key == "deployments" else None)
        self.assertEqual("BLOCKED", result["baseline_status"])

    def test_missing_repository_variables_block(self):
        for account, hostname in (("", HOST), (ACCOUNT, "")):
            result, calls = self.run_gate(account=account, hostname=hostname)
            self.assertEqual("BLOCKED", result["baseline_status"])
            self.assertEqual([], calls)

    def test_cloudflare_read_failure_blocks(self):
        def fail(path, token):
            raise RuntimeError("403 or 5xx details are not exposed")
        result = reconcile(STATE, ACCOUNT, HOST, TOKEN, fail)
        self.assertEqual("CLOUDFLARE_READ_FAILED", result["safe_error_class"])
        self.assertFalse(result["publish_authorized"])

    def test_invalid_json_or_api_response_blocks(self):
        result = reconcile(STATE, ACCOUNT, HOST, TOKEN, lambda path, token: None)
        self.assertEqual("BLOCKED", result["baseline_status"])

    def test_http_403_and_5xx_are_safe_read_failures(self):
        for status in (403, 503):
            with self.subTest(status=status), patch.object(baseline, "urlopen", side_effect=HTTPError("url", status, "secret response", {}, None)):
                with self.assertRaises(baseline.BaselineBlocked) as raised:
                    baseline._request("/accounts/x/workers/scripts", TOKEN)
                self.assertEqual("CLOUDFLARE_READ_FAILED", raised.exception.error_class)

    def test_invalid_cloudflare_json_is_safe_response_failure(self):
        class BadJsonResponse:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return b"{"
        with patch.object(baseline, "urlopen", return_value=BadJsonResponse()):
            with self.assertRaises(baseline.BaselineBlocked) as raised:
                baseline._request("/accounts/x/workers/scripts", TOKEN)
            self.assertEqual("CLOUDFLARE_RESPONSE_INVALID", raised.exception.error_class)

    def test_missing_read_only_token_blocks(self):
        result, calls = self.run_gate(token="")
        self.assertEqual("READ_ONLY_TOKEN_MISSING", result["safe_error_class"])
        self.assertEqual([], calls)

    def test_remote_change_between_snapshots_blocks(self):
        count = {"deployments": 0}

        def change(key, value):
            if key == "deployments":
                count[key] += 1
                if count[key] == 2:
                    value["deployments"][0]["id"] = "changed"

        result, _ = self.run_gate(mutate=change)
        self.assertEqual("PRODUCTION_BASELINE_DRIFT", result["safe_error_class"])

    def test_failed_verification_never_authorizes_publish(self):
        result, _ = self.run_gate(mutate=lambda key, value: value["scripts"].clear() if key == "scripts" else None)
        self.assertEqual("BLOCKED", result["baseline_status"])
        self.assertFalse(result["publish_authorized"])


class WorkflowContractTests(unittest.TestCase):
    def test_dispatch_only_read_token_and_production_concurrency(self):
        workflow = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        self.assertEqual({"workflow_dispatch": ""}, workflow["on"])
        self.assertEqual({"contents": "read"}, workflow["permissions"])
        self.assertEqual("mahoon-production-publisher", workflow["concurrency"]["group"])
        self.assertEqual("false", workflow["concurrency"]["cancel-in-progress"])
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("secrets.CLOUDFLARE_READ_API_TOKEN", source)
        self.assertIn("vars.CLOUDFLARE_ACCOUNT_ID", source)
        self.assertIn("vars.CLOUDFLARE_EXPECTED_HOSTNAME", source)
        self.assertNotIn("secrets.CLOUDFLARE_API_TOKEN", source)
        self.assertNotIn("contents: write", source)
        self.assertIn("ref: ${{ github.sha }}", source)
        self.assertIn("ref: main", source)
        self.assertIn("if: always()", source)

    def test_helper_only_issues_get_requests_and_no_state_writes(self):
        source = (Path(__file__).resolve().parent / "production_baseline_readonly.py").read_text(encoding="utf-8")
        self.assertIn('method="GET"', source)
        self.assertNotRegex(source, r"(?i)method\s*=\s*['\"](?:POST|PUT|PATCH|DELETE)")
        self.assertNotIn("write_text(state", source)
        self.assertNotIn("publish-static-state.json\", \"w\")", source)


if __name__ == "__main__":
    unittest.main()
