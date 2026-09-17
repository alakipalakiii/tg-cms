import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.publisher import cloudflare_wrangler as wrangler
from tools.publisher import rollback
from tools.publisher.seal_artifact import create_seal, verify_seal
from tools.publisher.state_machine import live_static_baseline, static_deployment_plan, verify_promoted_static
from tools.publisher.resumable_transaction import split_is_baseline_zero


class StaticVersionControlTests(unittest.TestCase):
    def test_static_version_worker_is_tracked_and_uses_asset_binding(self):
        worker = Path("tools/publisher/static_version_main.js")
        runner = Path("tools/m9/publisher_runner.py").read_text(encoding="utf-8")
        self.assertTrue(worker.is_file())
        source = worker.read_text(encoding="utf-8")
        self.assertIn("env.ASSETS.fetch(request)", source)
        self.assertIn('"binding": "ASSETS"', runner)
        self.assertIn('tools/publisher/static_version_main.js', runner)
        self.assertNotIn('runner-evidence/static-version-main.js', runner)

    def test_initial_rollback_anchor_is_captured_before_upload(self):
        runner = Path("tools/m9/publisher_runner.py").read_text(encoding="utf-8")
        anchor = runner.index('rollback_state = {"deployment_id": pre_promotion["id"]')
        record = runner.index('"phase": "PRE_CANDIDATE_UPLOAD"', anchor)
        upload = runner.index('deployment.upload_version(', record)
        self.assertLess(anchor, record)
        self.assertLess(record, upload)

    def test_publish_captures_transaction_baseline_before_revision_and_upload(self):
        runner = Path("tools/m9/publisher_runner.py").read_text(encoding="utf-8")
        capture = runner.index('transaction_start_deployment = deployment.active_deployment(target_worker)')
        revision_lookup = runner.index('current_revision, changed_at, revision_meta = fetch_public_content_revision()')
        upload_guard = runner.index('live_before_upload = deployment.active_deployment(target_worker)')
        upload = runner.index('deployment.upload_version(')
        self.assertLess(capture, revision_lookup)
        self.assertLess(upload_guard, upload)
        self.assertIn('"captured_before_revision_lookup": True', runner)

    def test_static_deployment_plan_contains_only_static_pairs(self):
        plan = static_deployment_plan("mahoon-art-magazine", "known-static", "candidate-static")
        self.assertEqual({"known-static": 100}, plan["baseline"])
        self.assertEqual({"known-static": 100, "candidate-static": 0}, plan["candidate_zero_percent"])
        self.assertEqual({"candidate-static": 100, "known-static": 0}, plan["promotion"])
        self.assertEqual({"known-static": 100, "candidate-static": 0}, plan["rollback"])
        self.assertFalse(plan["contains_ssr_version"])
        self.assertNotIn("SSR", str(plan))

    def test_existing_zero_percent_candidate_is_preserved_without_allowing_traffic(self):
        state = {"id": "d", "versions": [
            {"version_id": "7c6570b4-dbf5-42d3-84d6-acdb0da63092", "percentage": 100},
            {"version_id": "33df7584-c670-432f-8078-a94f11ee4837", "percentage": 0},
        ]}
        self.assertTrue(live_static_baseline(state, "7c6570b4-dbf5-42d3-84d6-acdb0da63092")[0])
        tx = {"baseline_static_version": "7c6570b4-dbf5-42d3-84d6-acdb0da63092",
              "candidate_static_version": "candidate-new",
              "preexisting_zero_versions": ["33df7584-c670-432f-8078-a94f11ee4837"]}
        zero = {"versions": [*state["versions"], {"version_id": "candidate-new", "percentage": 0}]}
        self.assertTrue(split_is_baseline_zero(zero, tx))
        unsafe = {"versions": [
            {"version_id": "7c6570b4-dbf5-42d3-84d6-acdb0da63092", "percentage": 99},
            {"version_id": "33df7584-c670-432f-8078-a94f11ee4837", "percentage": 1},
        ]}
        self.assertFalse(live_static_baseline(unsafe, "7c6570b4-dbf5-42d3-84d6-acdb0da63092")[0])
        promoted = {"id": "p", "versions": [
            {"version_id": "candidate-new", "percentage": 100},
            {"version_id": "7c6570b4-dbf5-42d3-84d6-acdb0da63092", "percentage": 0},
            {"version_id": "33df7584-c670-432f-8078-a94f11ee4837", "percentage": 0},
        ]}
        self.assertTrue(verify_promoted_static(promoted, "candidate-new", tx["baseline_static_version"])[0])

    def test_failed_transaction_rolls_back_to_pre_promotion_live_not_old_history(self):
        pre_promotion_version = "7c6570b4-dbf5-42d3-84d6-acdb0da63092"
        stale_historical_version = "d25d1131-ec90-4efb-90c8-a62f9721fe6c"
        candidate_version = "candidate-static-not-uploaded"
        pre_promotion = {
            "id": "pre-promotion-deployment",
            "versions": [{"version_id": pre_promotion_version, "percentage": 100}],
        }
        promoted = {
            "id": "promoted-deployment",
            "versions": [
                {"version_id": candidate_version, "percentage": 100},
                {"version_id": pre_promotion_version, "percentage": 0},
            ],
        }
        self.assertTrue(live_static_baseline(pre_promotion, pre_promotion_version)[0])

        runner = Path("tools/m9/publisher_runner.py").read_text(encoding="utf-8")
        self.assertIn('active = [item.get("version_id") for item in pre_promotion.get("versions", []) if item.get("percentage") == 100]', runner)
        self.assertIn('"previous_static_version": current_static_version', runner)
        self.assertIn('automatic_rollback(target_worker, current_static_version, version_id', runner)

        with patch.object(rollback.deployment, "active_deployment", return_value=promoted), \
             patch.object(rollback.deployment, "rollback_to_previous_static") as restore, \
             patch.object(rollback.deployment, "wait_for_active", return_value={"id": "rollback-deployment"}):
            rollback.automatic_rollback(
                "mahoon-art-magazine", pre_promotion_version, candidate_version,
                "promoted-deployment",
            )

        restore.assert_called_once_with(
            "mahoon-art-magazine", pre_promotion_version, candidate_version,
        )
        self.assertNotEqual(stale_historical_version, restore.call_args.args[1])

    def test_wrangler_uses_newest_deployment_not_oldest_history_entry(self):
        history = [
            {"id": "old", "created_on": "2026-09-11T00:00:00Z", "versions": []},
            {"id": "latest", "created_on": "2026-09-14T12:41:59Z", "versions": [{"version_id": "static", "percentage": 100}]},
        ]
        with patch.object(wrangler, "_json", return_value=history):
            self.assertEqual("latest", wrangler.read_deployment("worker")["id"])

    def test_deploy_pair_emits_only_static_pair_and_rejects_bad_traffic(self):
        with patch.object(wrangler, "_run", return_value="[]") as run, patch.object(
            wrangler, "read_deployment", return_value={"id": "d", "versions": []}
        ):
            wrangler.deploy_pair("worker", "candidate", 0, "verified-static", 100)
        self.assertIn("candidate@0", run.call_args.args[0])
        self.assertIn("verified-static@100", run.call_args.args[0])
        self.assertNotIn("SSR", str(run.call_args.args[0]))
        with patch.object(wrangler, "_run", return_value="[]") as run, patch.object(
            wrangler, "read_deployment", return_value={"id": "d", "versions": []}
        ):
            wrangler.deploy_pair("worker", "candidate", 0, "verified-static", 100,
                                 ("33df7584-c670-432f-8078-a94f11ee4837",))
        self.assertIn("33df7584-c670-432f-8078-a94f11ee4837@0", run.call_args.args[0])
        with patch.object(wrangler, "_run") as run:
            with self.assertRaises(wrangler.WranglerError):
                wrangler.deploy_pair("worker", "candidate", 0, "verified-static", 90)
            run.assert_not_called()

    def test_artifact_seal_is_measured_and_detects_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "site"
            (root / "_astro").mkdir(parents=True)
            (root / "media").mkdir()
            (root / "index.html").write_text("sealed candidate", encoding="utf-8")
            (root / "_astro/app.js").write_text("console.log('ok')", encoding="utf-8")
            (root / "media/item.jpg").write_bytes(b"\xff\xd8\xffmedia")
            seal = create_seal(root, content_fingerprint="content-digest", route_hash="route-digest")
            self.assertEqual(3, seal["artifact_file_count"])
            self.assertEqual(1, seal["media_file_count"])
            self.assertEqual(1, seal["asset_file_count"])
            self.assertTrue(verify_seal(root, seal))
            (root / "index.html").write_text("changed after seal", encoding="utf-8")
            self.assertFalse(verify_seal(root, seal))


if __name__ == "__main__":
    unittest.main()
