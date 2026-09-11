import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.publisher import cloudflare_wrangler as w


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


if __name__ == "__main__":
    unittest.main()
