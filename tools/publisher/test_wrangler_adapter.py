import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

from tools.publisher import cloudflare_wrangler as w
from tools.publisher.seal_artifact import create_seal


class WranglerAdapterTests(unittest.TestCase):
    def test_deploy_pair_uses_static_pair(self):
        with patch.object(w, "_run", return_value="[]") as run, patch.object(w, "read_deployment", return_value={"versions": []}):
            w.deploy_pair("worker", "new", 100, "old", 0)
        self.assertIn("new@100", run.call_args.args[0])
        self.assertIn("old@0", run.call_args.args[0])

    def test_rollback_never_targets_ssr(self):
        with patch.object(w, "deploy_pair", return_value={}) as deploy:
            w.rollback_to_previous_static("worker", "old-static", "failed-static")
        self.assertEqual(deploy.call_args.args[1:5], ("old-static", 100, "failed-static", 0))

    def test_upload_requires_seal_and_refuses_mutable_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "site"
            root.mkdir()
            with self.assertRaises(w.WranglerError):
                w.upload_version("worker", root, root / "config.json", "test")
            (root.parent / "artifact-seal.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(w.WranglerError):
                w.upload_version("worker", Path(tmp) / "m9-v2-candidate-site", root / "config.json", "test")

    def test_malformed_json_fails_closed(self):
        with patch.object(w, "_run", return_value="not-json"):
            with self.assertRaises(w.WranglerError):
                w.list_versions("worker")

    def test_check_only_contract_is_read_only(self):
        source = Path("tools/m9/publisher_runner.py").read_text(encoding="utf-8")
        check_block = source.split('if mode == "CHECK_ONLY":', 1)[1].split('if mode == "PUBLISH"', 1)[0]
        self.assertNotIn("upload_version", check_block)
        self.assertNotIn("deploy_pair", check_block)
        self.assertNotIn("cloudflare_direct_api", source)

    def test_publisher_wrangler_matches_ci_auth_verified_version(self):
        workflow = Path(".github/workflows/mahoon-static-publisher.yml").read_text(encoding="utf-8")
        self.assertIn("MAHOON_WRANGLER: npx wrangler@4.83.0", workflow)
        self.assertNotIn("npx wrangler@4.83.0 whoami", workflow)
        self.assertNotIn("CLOUDFLARE_API_TOKEN", workflow.split("  check-only:", 1)[0])


class UploadSessionRetryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        project = Path(temporary.name)
        self.root = project / "sealed" / "site"
        self.root.mkdir(parents=True)
        (self.root / "index.html").write_text("sealed test", encoding="utf-8")
        seal = create_seal(self.root, content_fingerprint="f", route_hash="r")
        (self.root.parent / "artifact-seal.json").write_text(json.dumps(seal), encoding="utf-8")
        self.config = project / "website" / "app" / "wrangler.json"
        self.config.parent.mkdir(parents=True)
        self.config.write_text('{"assets":{"directory":"./dist"}}', encoding="utf-8")
        self.marker = "MAHOON-A3:" + "a" * 64 + ":f47ac10b-58cc-4372-a567-0e02b2c3d410"
        self.version = {"id": "version-one", "annotations": {"workers/message": self.marker}}
        self.error = w.AssetUploadSessionRejected("assets upload session rejected (Cloudflare 10013)")

    def upload(self):
        return w.upload_version("worker", self.root, self.config, self.marker)

    def test_early_session_10013_retries_identical_sealed_upload_after_fresh_readback(self):
        diagnostic = ("A request to the Cloudflare API (/accounts/" + "b" * 32
                      + "/workers/scripts/worker/assets-upload-session) failed.\n[code: 10013]")
        events, snapshots = [], iter([[], [], [], [self.version]])
        def versions(worker):
            events.append("read")
            return next(snapshots)
        responses = iter([subprocess.CompletedProcess([], 1, "", diagnostic),
                          subprocess.CompletedProcess([], 0, "uploaded", "")])
        def command(*args, **kwargs):
            events.append("upload")
            return next(responses)
        with patch.object(w, "WRANGLER", ["npx", "wrangler@4.83.0"]), \
             patch.object(w, "ACCOUNT", "b" * 32), patch.object(w, "list_versions", side_effect=versions), \
             patch.object(w.subprocess, "run", side_effect=command) as run, patch.object(w.time, "sleep") as sleep:
            self.assertEqual("version-one", self.upload())
        self.assertEqual(["read", "upload", "read", "read", "upload", "read"], events)
        self.assertEqual(2, run.call_count)
        self.assertEqual(run.call_args_list[0].args, run.call_args_list[1].args)
        self.assertIn(self.marker, run.call_args.args[0])
        sleep.assert_called_once_with(2)

    def test_lost_acknowledgement_reuses_unique_marker_without_another_upload(self):
        with patch.object(w, "list_versions", side_effect=[[], [self.version]]), \
             patch.object(w, "_run", side_effect=w.WranglerError("lost response token=synthetic-secret")) as run, \
             patch.object(w.time, "sleep") as sleep:
            self.assertEqual("version-one", self.upload())
        self.assertEqual(1, run.call_count)
        sleep.assert_not_called()

    def test_existing_exact_attempt_version_is_reused_before_first_upload(self):
        with patch.object(w, "list_versions", return_value=[self.version]), patch.object(w, "_run") as run:
            self.assertEqual("version-one", self.upload())
        run.assert_not_called()

    def test_three_early_session_failures_exhaust_budget_without_claiming_success(self):
        with patch.object(w, "list_versions", return_value=[]), \
             patch.object(w, "_run", side_effect=self.error) as run, patch.object(w.time, "sleep") as sleep:
            with self.assertRaises(w.WranglerError):
                self.upload()
        self.assertEqual(3, run.call_count)
        self.assertEqual([call(2), call(4)], sleep.call_args_list)
        self.assertEqual(1, len({tuple(item.args[0]) for item in run.call_args_list}))

    def test_changed_payload_and_replaced_seal_cannot_change_the_retried_operation(self):
        def change_artifact(_delay):
            (self.root / "index.html").write_text("different payload", encoding="utf-8")
            changed = create_seal(self.root, content_fingerprint="different", route_hash="r")
            (self.root.parent / "artifact-seal.json").write_text(json.dumps(changed), encoding="utf-8")
        with patch.object(w, "list_versions", return_value=[]), \
             patch.object(w, "_run", side_effect=self.error) as run, \
             patch.object(w.time, "sleep", side_effect=change_artifact):
            with self.assertRaises(w.WranglerError):
                self.upload()
        self.assertEqual(1, run.call_count)

    def test_generic_and_version_creation_errors_never_retry_by_marker_absence(self):
        for error in (w.WranglerError("transport lost token=synthetic-secret"),
                      w.WranglerError("request /versions failed [code: 10013]"),
                      subprocess.TimeoutExpired("synthetic-secret-command", 900)):
            with self.subTest(error=type(error).__name__), patch.object(w, "list_versions", return_value=[]), \
                 patch.object(w, "_run", side_effect=error) as run, patch.object(w.time, "sleep") as sleep:
                with self.assertRaises(w.WranglerError) as caught:
                    self.upload()
                self.assertEqual(1, run.call_count)
                sleep.assert_not_called()
                self.assertNotIn("synthetic-secret", str(caught.exception))

    def test_ambiguous_malformed_or_unreadable_readback_prevents_repeat(self):
        for readback in ([self.version, self.version], [{"id": "bad", "annotations": "invalid"}],
                         w.WranglerError("token=synthetic-secret")):
            with self.subTest(readback=type(readback).__name__), \
                 patch.object(w, "list_versions", side_effect=[[], readback]), \
                 patch.object(w, "_run", side_effect=self.error) as run, patch.object(w.time, "sleep") as sleep:
                with self.assertRaises(w.WranglerError) as caught:
                    self.upload()
                self.assertEqual(1, run.call_count)
                sleep.assert_not_called()
                self.assertNotIn("synthetic-secret", str(caught.exception))

    def test_retry_classifier_requires_pinned_version_exact_endpoint_and_single_error(self):
        endpoint = "/accounts/" + "b" * 32 + "/workers/scripts/worker/assets-upload-session"
        for binary, path, code in [(["npx", "wrangler"], endpoint, "10013"),
                                   (["npx", "wrangler@4.83.0"], endpoint.replace("assets-upload-session", "versions"), "10013"),
                                   (["npx", "wrangler@4.83.0"], endpoint, "10000"),
                                   (["npx", "wrangler@4.83.0"], endpoint, "10013] [code: 10000")]:
            diagnostic = f"A request to the Cloudflare API ({path}) failed. [code: {code}]"
            with self.subTest(binary=binary, code=code), patch.object(w, "WRANGLER", binary), \
                 patch.object(w, "ACCOUNT", "b" * 32), patch.object(w.subprocess, "run", return_value=
                    subprocess.CompletedProcess([], 1, "", diagnostic)):
                with self.assertRaises(w.WranglerError) as caught:
                    w._run(["versions", "upload", "--name", "worker"])
                self.assertIs(type(caught.exception), w.WranglerError)


if __name__ == "__main__":
    unittest.main()
