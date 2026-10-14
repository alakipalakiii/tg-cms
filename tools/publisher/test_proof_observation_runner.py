from __future__ import annotations

import copy
import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import test_proof_recovery_runner as fixtures
from publisher import artifact_contract as contracts
from publisher import artifact_transport as transport
from publisher import proof_observation_runner as runner
from publisher.workflow_stage_cli import (
    execute_observed_pre_promotion_proof,
    execute_observed_production_proof,
)
from test_a53_executors import fresh_proof_fixture


def _crawler(*, failed=None, attribution=True):
    remote_names = {
        "remote_route_parity", "remote_content_parity", "remote_listing_uniqueness",
        "remote_category_parity", "remote_latest_parity", "remote_seo", "remote_media",
    }
    gates = {name: {"measured": True, "PASS": name != failed} for name in remote_names}
    return {
        "measured": True, "expected_route_count": 3, "present_route_count": 3,
        "missing_routes": [], "gates": gates, "post_jsonld_missing": 0,
        "duplicate_canonicals": 0, "remote_reader_media_dependencies": 0,
        "workers_dev_leaks": 0,
        "remote_crawler_version_pinning": {"PASS": attribution, "override_sent": "NO",
                                            "attribution_required": "YES"},
    }


def _browser(*, visual=True, zero=True, admin=True):
    counts = {name: 0 for name in ("content_api", "media_api", "workers_dev_content",
                                   "telegram", "search_backend")}
    if not zero:
        counts["content_api"] = 1
    return {
        "visual": {"pages_checked": 2, "PASS": visual},
        "zero_origin": {"public_pages_checked": 2, "requests": counts, "PASS": zero},
        "checks": [{"name": "admin-shell", "visual_pass": admin}],
    }


class FakeBackend:
    def __init__(self, *, failed_gate=None, visual=True, zero=True, admin=True,
                 attribution=True, secret_field=False, identity_pass=True):
        self.failed_gate = failed_gate
        self.visual, self.zero, self.admin = visual, zero, admin
        self.attribution, self.secret_field, self.identity_pass = attribution, secret_field, identity_pass
        self.calls = 0
        self.mutation_calls = 0

    def collect(self, context):
        self.calls += 1
        deployment = "dep-zero" if context["stage"] == "pre-promotion" else "dep-promoted"
        candidate_pct = 0 if context["stage"] == "pre-promotion" else 100
        value = {
            "crawler": _crawler(failed=self.failed_gate, attribution=self.attribution),
            "route_state": {"routes": {
                "/admin": {"http_status": 200}, "/admin/analytics": {"http_status": 200},
                "/robots.txt": {"robots_sitemap": True},
                "/rss.xml": {"http_status": 200, "content_type": "application/rss+xml"},
            }},
            "browser": _browser(visual=self.visual, zero=self.zero, admin=self.admin),
            "identity_confirmation": {
                "candidate_version_id": "candidate-v1", "baseline_version_id": "baseline-v1",
                "promotion_deployment_id": deployment, "candidate_percentage": candidate_pct,
                "baseline_percentage": 100 - candidate_pct, "PASS": self.identity_pass,
            },
            "directory": None,
        }
        if self.secret_field:
            value["crawler"]["api_token"] = "synthetic-secret-marker"
        return value

    def mutate(self, *_args):
        self.mutation_calls += 1


class ProofObservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.f = fresh_proof_fixture()
        self.artifacts = {
            "receipt": self.f.receipt, "build": self.f.bundle,
            "upload_intent": self.f.upload_intent, "upload_result": self.f.upload_result,
            "deploy_intent": self.f.deploy_intent, "deploy_result": self.f.deploy_result,
            "preproof": self.f.prepromotion_proof, "promote_intent": self.f.promote_intent,
            "promote_result": self.f.promote_result,
        }
        self.refs = transport.references(*self.artifacts.values())
        self.paths = {}
        for name, value in self.artifacts.items():
            path = self.root / f"{name}.json"
            transport.write_artifact(path, value, referenced_artifacts=self.refs)
            self.paths[name] = path
        self.sealed = self.root / "sealed"
        self.sealed.mkdir()
        self.snapshot = self.root / "snapshot.json"
        self.snapshot.write_text("{}", encoding="utf-8")
        self.routes = self.root / "routes.json"
        self.routes.write_text(json.dumps({"routes": ["/", "/posts", "/admin"], "route_count": 3}), encoding="utf-8")
        self.media = self.root / "media.json"
        self.media.write_text("{}", encoding="utf-8")
        self.local = self.root / "local.json"
        self.local.write_text(json.dumps({"measured": True, "PASS": True, "gates": {
            name: {"measured": True, "PASS": True} for name in contracts.LOCAL_GATES
        }}), encoding="utf-8")
        self.common_patch = patch.object(runner, "_input_files_match")
        self.common_patch.start()
        self.addCleanup(self.common_patch.stop)

    def tearDown(self):
        self.temp.cleanup()

    def pre(self, backend=None, *, intent=None, result=None, evidence=None, output=None):
        backend = backend or FakeBackend()
        intent_path = self.paths["deploy_intent"]
        result_path = self.paths["deploy_result"]
        if intent is not None:
            intent_path = self.root / "custom-intent.json"
            transport.write_artifact(intent_path, intent, referenced_artifacts=self.refs)
        if result is not None:
            result_path = self.root / "custom-result.json"
            transport.write_artifact(result_path, result, referenced_artifacts=self.refs)
        evidence = evidence or self.root / "pre-evidence"
        output = output or self.root / "preproof-output.json"
        references = [str(self.paths[name]) for name in ("receipt", "upload_intent", "upload_result")]
        return runner.execute_pre_promotion_observation(
            build_path=self.paths["build"], deploy_intent_path=intent_path,
            deploy_result_path=result_path, sealed_root=self.sealed, snapshot_path=self.snapshot,
            route_manifest_path=self.routes, media_manifest_path=self.media,
            evidence_dir=evidence, output_path=output, backend=backend,
            reference_paths=references,
        )

    def production(self, backend=None, *, artifacts=None, evidence=None, output=None):
        backend = backend or FakeBackend()
        paths = artifacts or {
            "build": self.paths["build"], "upload_intent": self.paths["upload_intent"],
            "upload_result": self.paths["upload_result"], "deploy_intent": self.paths["deploy_intent"],
            "deploy_result": self.paths["deploy_result"], "preproof": self.paths["preproof"],
            "promote_intent": self.paths["promote_intent"], "promote_result": self.paths["promote_result"],
        }
        return runner.execute_production_observation(
            artifact_paths=paths, sealed_root=self.sealed, snapshot_path=self.snapshot,
            route_manifest_path=self.routes, media_manifest_path=self.media,
            local_gates_path=self.local, evidence_dir=evidence or self.root / "prod-evidence",
            output_path=output or self.root / "proof-output.json", backend=backend,
        )

    def test_01_valid_applied_zero_percent_lineage_enters_observation(self):
        fake = FakeBackend(); self.assertEqual("PASS", self.pre(fake)["status"]); self.assertEqual(1, fake.calls)

    def test_02_not_applied_deployment_rejected(self):
        bad = copy.deepcopy(self.f.deploy_result); bad["payload"]["result_state"] = "NOT_APPLIED"
        bad = contracts.seal_artifact(bad)
        with self.assertRaises(Exception): self.pre(result=bad)

    def test_03_unknown_deployment_rejected(self):
        bad = copy.deepcopy(self.f.deploy_result); bad["payload"]["result_state"] = "UNKNOWN"
        bad = contracts.seal_artifact(bad)
        with self.assertRaises(Exception): self.pre(result=bad)

    def test_04_transaction_mismatch_rejected_before_backend(self):
        fake = FakeBackend(); bad = copy.deepcopy(self.f.deploy_result)
        bad["transaction"]["content_revision"] += 1; bad = contracts.seal_artifact(bad)
        with self.assertRaises(Exception): self.pre(fake, result=bad)
        self.assertEqual(0, fake.calls)

    def test_05_candidate_mismatch_rejected_before_backend(self):
        bad = copy.deepcopy(self.f.deploy_intent); bad["payload"]["desired_state"]["candidate_version_id"] = "other"
        bad = contracts.seal_artifact(bad); fake = FakeBackend()
        with self.assertRaises(Exception): self.pre(fake, intent=bad)
        self.assertEqual(0, fake.calls)

    def test_06_deployment_identity_mismatch_rejected(self):
        bad = copy.deepcopy(self.f.deploy_result); bad["payload"]["readback_reference"]["resource_id"] = "wrong"
        bad = contracts.seal_artifact(bad); fake = FakeBackend()
        with self.assertRaises(Exception): self.pre(fake, result=bad)
        self.assertEqual(1, fake.calls)

    def test_07_all_remote_gates_create_pass_contract(self):
        self.pre(); proof = transport.read_artifact(self.root / "preproof-output.json", expected_type="pre_promotion_proof_evidence", referenced_artifacts=self.refs)
        self.assertTrue(proof["payload"]["PASS"]); self.assertEqual(set(contracts.REMOTE_GATES), set(proof["payload"]["remote"]["gates"]))

    def test_08_each_remote_gate_independently_prevents_pass(self):
        names = {"full_route_crawl": "remote_route_parity", "content_parity": "remote_content_parity",
                 "listing_uniqueness": "remote_listing_uniqueness", "category_parity": "remote_category_parity",
                 "latest_parity": "remote_latest_parity", "seo": "remote_seo", "media": "remote_media"}
        for index, (gate, source) in enumerate(names.items()):
            with self.subTest(gate=gate):
                result = self.pre(FakeBackend(failed_gate=source), evidence=self.root / f"gate-{index}-evidence",
                                  output=self.root / f"gate-{index}.json")
                self.assertEqual("FAIL", result["status"])
                proof = transport.read_artifact(self.root / f"gate-{index}.json", expected_type="pre_promotion_proof_evidence", referenced_artifacts=self.refs)
                self.assertFalse(proof["payload"]["remote"]["gates"][gate])
        result = self.pre(FakeBackend(visual=False), evidence=self.root / "browser-0-evidence",
                          output=self.root / "browser-0.json")
        self.assertEqual("FAIL", result["status"])
        with self.assertRaises(runner.ObservationRejected): self.pre(FakeBackend(zero=False))

    def test_09_zero_origin_failure_prevents_authoritative_pass(self):
        with self.assertRaises(runner.ObservationRejected): self.pre(FakeBackend(zero=False))
        self.assertFalse((self.root / "preproof-output.json").exists())

    def test_10_zero_origin_request_counts_are_preserved(self):
        self.pre(); proof = transport.read_artifact(self.root / "preproof-output.json", expected_type="pre_promotion_proof_evidence", referenced_artifacts=self.refs)
        self.assertEqual({name: 0 for name in ("content_api", "media_api", "workers_dev_content", "telegram", "search_backend")}, proof["payload"]["zero_origin_validation"]["requests"])

    def test_11_crawler_digest_matches_persisted_evidence(self):
        result = self.pre(); raw = (Path(result["evidence_dir"]) / "crawler-summary.json").read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), result["crawler_evidence_sha256"])

    def test_12_browser_digest_matches_persisted_evidence(self):
        result = self.pre(); raw = (Path(result["evidence_dir"]) / "browser-observations.json").read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), result["browser_evidence_sha256"])

    def test_13_crawler_evidence_tampering_is_detectable(self):
        result = self.pre(); path = Path(result["evidence_dir"]) / "crawler-summary.json"
        path.write_text("tampered", encoding="utf-8")
        self.assertNotEqual(result["crawler_evidence_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())

    def test_14_browser_evidence_tampering_is_detectable(self):
        result = self.pre(); path = Path(result["evidence_dir"]) / "browser-observations.json"
        path.write_text("tampered", encoding="utf-8")
        self.assertNotEqual(result["browser_evidence_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())

    def test_15_legacy_remote_result_cannot_authorize_output(self):
        fake = FakeBackend(); legacy = self.root / "remote-proof-result.json"
        legacy.write_text(json.dumps({"REMOTE_PROOF_PASS": True}), encoding="utf-8")
        with self.assertRaises(AttributeError): self.pre(legacy)  # filename is never a backend/authority
        self.assertEqual(0, fake.calls)

    def test_16_legacy_bundle_not_required_for_new_path(self):
        self.assertEqual("PASS", self.pre()["status"])
        self.assertFalse((self.root / "transaction.json").exists())

    def test_17_mutation_backend_is_never_called(self):
        fake = FakeBackend(); self.pre(fake)
        self.assertEqual(1, fake.calls); self.assertEqual(0, fake.mutation_calls)

    def test_18_no_journal_write_dependency(self):
        source = Path(runner.__file__).read_text(encoding="utf-8")
        self.assertNotIn("TransactionJournal", source); self.assertNotIn("record_intent", source)

    def test_19_no_repository_persistence_dependency(self):
        source = Path(runner.__file__).read_text(encoding="utf-8")
        self.assertNotIn("GitRepositoryWriter", source); self.assertNotIn("final_persistence", source)

    def test_20_preproof_is_valid_under_frozen_contract(self):
        self.pre(); self.assertEqual("pre_promotion_proof_evidence", transport.read_artifact(
            self.root / "preproof-output.json", expected_type="pre_promotion_proof_evidence",
            referenced_artifacts=self.refs)["artifact_type"])

    def test_21_applied_promotion_enters_production_observation(self):
        fake = FakeBackend(); self.assertEqual("PASS", self.production(fake)["status"]); self.assertEqual(1, fake.calls)

    def test_21a_measured_local_gates_are_normalized_without_losing_acceptance(self):
        self.production()
        proof = transport.read_artifact(self.root / "proof-output.json", expected_type="proof_evidence",
                                        referenced_artifacts=self.refs)
        local = proof["payload"]["gate_results"]["local"]
        self.assertTrue(local["PASS"])
        self.assertEqual({name: True for name in contracts.LOCAL_GATES}, local["gates"])

    def test_21b_failed_local_gate_is_rejected_before_production_observation(self):
        local_data = json.loads(self.local.read_text(encoding="utf-8"))
        local_data["gates"][contracts.LOCAL_GATES[0]]["PASS"] = False
        local_data["PASS"] = False
        self.local.write_text(json.dumps(local_data), encoding="utf-8")
        fake = FakeBackend()
        with self.assertRaises(runner.ObservationRejected):
            self.production(fake)
        self.assertEqual(0, fake.calls)

    def test_22_not_applied_promotion_rejected(self):
        bad = copy.deepcopy(self.f.promote_result); bad["payload"]["result_state"] = "NOT_APPLIED"
        bad = contracts.seal_artifact(bad); paths = dict(self.production_paths()); paths["promote_result"] = self._write_custom("na-promote.json", bad)
        fake = FakeBackend()
        with self.assertRaises(Exception): self.production(fake, artifacts=paths)
        self.assertEqual(0, fake.calls)

    def production_paths(self):
        return {"build": self.paths["build"], "upload_intent": self.paths["upload_intent"],
                "upload_result": self.paths["upload_result"], "deploy_intent": self.paths["deploy_intent"],
                "deploy_result": self.paths["deploy_result"], "preproof": self.paths["preproof"],
                "promote_intent": self.paths["promote_intent"], "promote_result": self.paths["promote_result"]}

    def _write_custom(self, name, value):
        path = self.root / name; transport.write_artifact(path, value, referenced_artifacts=self.refs); return path

    def test_23_unknown_promotion_rejected(self):
        bad = copy.deepcopy(self.f.promote_result); bad["payload"]["result_state"] = "UNKNOWN"
        bad = contracts.seal_artifact(bad); paths = self.production_paths(); paths["promote_result"] = self._write_custom("unknown.json", bad)
        with self.assertRaises(Exception): self.production(FakeBackend(), artifacts=paths)

    def test_24_transaction_mismatch_rejected(self):
        bad = copy.deepcopy(self.f.promote_result); bad["transaction"]["content_revision"] += 1
        bad = contracts.seal_artifact(bad); paths = self.production_paths()
        with self.assertRaises(Exception):
            paths["promote_result"] = self._write_custom("tx-mismatch.json", bad)
            self.production(FakeBackend(), artifacts=paths)

    def test_25_candidate_mismatch_rejected(self):
        bad = copy.deepcopy(self.f.promote_intent); bad["payload"]["desired_state"]["candidate_version_id"] = "other"
        bad = contracts.seal_artifact(bad); paths = self.production_paths()
        with self.assertRaises(Exception):
            paths["promote_intent"] = self._write_custom("candidate-mismatch.json", bad)
            self.production(FakeBackend(), artifacts=paths)

    def test_26_promotion_deployment_mismatch_is_fail_closed(self):
        result = self.production(FakeBackend(identity_pass=False), evidence=self.root / "identity-evidence",
                                 output=self.root / "identity-proof.json")
        self.assertEqual("FAIL", result["status"])

    def test_27_all_production_gates_true_emits_pass(self):
        self.assertEqual("PASS", self.production()["status"])

    def test_28_each_production_gate_independently_prevents_pass(self):
        crawler_sources = {
            "route_parity": "remote_route_parity", "content_parity": "remote_content_parity",
            "listing_uniqueness": "remote_listing_uniqueness", "category_parity": "remote_category_parity",
            "latest_parity": "remote_latest_parity", "media": "remote_media", "seo": "remote_seo",
        }
        index = 0
        for gate, source in crawler_sources.items():
            with self.subTest(gate=gate):
                result = self.production(FakeBackend(failed_gate=source), evidence=self.root / f"prod-gate-{index}", output=self.root / f"prod-proof-{index}.json")
                self.assertEqual("FAIL", result["status"]); index += 1
        for gate, kw in (("visual", {"visual": False}), ("admin_panel", {"admin": False}),
                         ("page_attribution", {"attribution": False})):
            with self.subTest(gate=gate):
                result = self.production(FakeBackend(**kw), evidence=self.root / f"prod-gate-{index}", output=self.root / f"prod-proof-{index}.json")
                self.assertEqual("FAIL", result["status"]); index += 1

    def test_29_page_attribution_failure_prevents_pass(self):
        self.assertEqual("FAIL", self.production(FakeBackend(attribution=False), evidence=self.root / "attr-evidence", output=self.root / "attr-proof.json")["status"])

    def test_30_admin_panel_failure_prevents_pass(self):
        self.assertEqual("FAIL", self.production(FakeBackend(admin=False), evidence=self.root / "admin-evidence", output=self.root / "admin-proof.json")["status"])

    def test_31_production_zero_origin_failure_blocks_artifact(self):
        with self.assertRaises(Exception): self.production(FakeBackend(zero=False))
        self.assertFalse((self.root / "proof-output.json").exists())

    def test_32_observation_contract_has_no_mutation_authority(self):
        observed = self.production(); proof = transport.read_artifact(self.root / "proof-output.json", expected_type="proof_evidence", referenced_artifacts=self.refs)
        self.assertNotIn("mutation_authority", proof["payload"]); self.assertEqual("PASS", observed["status"])

    def test_33_production_runner_invokes_no_mutation_method(self):
        fake = FakeBackend(); self.production(fake); self.assertEqual(1, fake.calls)

    def test_34_legacy_combined_stage_not_imported_or_called(self):
        source = Path(runner.__file__).read_text(encoding="utf-8")
        self.assertNotIn("run_promotion", source); self.assertNotIn("automatic_rollback", source)

    def test_35_production_proof_validates_existing_contract(self):
        self.production(); self.assertEqual("proof_evidence", transport.read_artifact(
            self.root / "proof-output.json", expected_type="proof_evidence", referenced_artifacts=self.refs)["artifact_type"])

    def test_36_proof_failure_cannot_authorize_rollback(self):
        failed = self.production(FakeBackend(admin=False), evidence=self.root / "rollback-evidence", output=self.root / "rollback-proof.json")
        self.assertEqual("FAIL", failed["status"])
        proof = transport.read_artifact(self.root / "rollback-proof.json", expected_type="proof_evidence", referenced_artifacts=self.refs)
        self.assertEqual("FAIL", proof["payload"]["proof_state"])
        self.assertNotIn("authorize_rollback", Path(runner.__file__).read_text(encoding="utf-8"))

    def test_37_breaker_alone_is_not_an_observation_input(self):
        source = Path(runner.__file__).read_text(encoding="utf-8")
        self.assertNotIn("breaker", source.lower())

    def test_38_pre_cli_revalidates_sealed_inputs(self):
        from publisher.workflow_stage_cli import validate_artifact_file
        self.assertEqual("build_bundle", validate_artifact_file(self.paths["build"], "build_bundle")["artifact_type"])

    def test_39_pre_cli_rejects_tampered_input(self):
        build = self.paths["build"]
        original = build.read_bytes()
        try:
            build.write_text("{}", encoding="utf-8")
            with self.assertRaises(Exception): self.pre()
        finally:
            build.write_bytes(original)

    def test_40_pre_cli_atomic_authoritative_artifact_output(self):
        self.pre(); self.assertEqual("pre_promotion_proof_evidence", transport.read_artifact(
            self.root / "preproof-output.json", expected_type="pre_promotion_proof_evidence", referenced_artifacts=self.refs)["artifact_type"])

    def test_41_production_cli_revalidates_promote_result(self):
        self.production(); self.assertEqual("proof_evidence", transport.read_artifact(
            self.root / "proof-output.json", expected_type="proof_evidence", referenced_artifacts=self.refs)["artifact_type"])

    def test_42_production_cli_rejects_tampered_promote_result(self):
        bad = self.root / "tampered-promote.json"; bad.write_text("{}", encoding="utf-8")
        paths = self.production_paths(); paths["promote_result"] = bad
        with self.assertRaises(Exception): self.production(artifacts=paths)

    def test_43_production_cli_atomically_writes_proof(self):
        self.production(); self.assertTrue((self.root / "proof-output.json").is_file())
        self.assertFalse(list(self.root.glob(".proof-output.json.*.tmp")))

    def test_44_failed_validation_leaves_no_partial_evidence(self):
        evidence = self.root / "failed-evidence"
        with self.assertRaises(runner.ObservationRejected): self.pre(FakeBackend(zero=False), evidence=evidence)
        self.assertFalse(evidence.exists()); self.assertFalse(list(self.root.glob(".failed-evidence.stage-*")))

    def test_45_existing_output_is_not_overwritten(self):
        output = self.root / "existing.json"; output.write_text("keep", encoding="utf-8")
        with self.assertRaises(FileExistsError): self.pre(output=output)
        self.assertEqual("keep", output.read_text(encoding="utf-8"))

    def test_46_secret_like_fields_are_rejected_and_not_persisted(self):
        evidence = self.root / "secret-evidence"
        with self.assertRaises(runner.ObservationRejected): self.pre(FakeBackend(secret_field=True), evidence=evidence)
        self.assertFalse(evidence.exists())
        self.assertFalse(any(b"synthetic-secret-marker" in path.read_bytes() for path in self.root.rglob("*.json") if path != self.paths["build"]))

    def test_47_raw_evidence_filename_never_substitutes_for_sealed_authority(self):
        legacy = self.root / "remote-proof-result.json"; legacy.write_text('{"PASS":true}', encoding="utf-8")
        self.assertEqual("PASS", self.pre()["status"])

    def test_48_evidence_hashes_are_deterministic(self):
        first = self.pre(evidence=self.root / "det-a", output=self.root / "det-a-proof.json")
        second = self.pre(evidence=self.root / "det-b", output=self.root / "det-b-proof.json")
        self.assertEqual(first["crawler_evidence_sha256"], second["crawler_evidence_sha256"])
        self.assertEqual(first["browser_evidence_sha256"], second["browser_evidence_sha256"])

    def test_49_focused_execution_uses_only_fake_backend(self):
        fake = FakeBackend(); self.pre(fake)
        self.assertEqual(1, fake.calls)
        self.assertFalse(runner.RuntimeObservationBackend is FakeBackend)

    def test_50_read_only_commands_do_not_require_mutation_credentials(self):
        source = Path(runner.__file__).read_text(encoding="utf-8")
        self.assertNotIn("CLOUDFLARE_API_TOKEN", source); self.assertNotIn("CloudflareOperationAdapter", source)

    def test_cli_entrypoints_are_explicit_and_separate(self):
        from publisher.workflow_stage_cli import _parser
        choices = _parser()._subparsers._group_actions[0].choices
        self.assertIn("pre-promotion-proof-observe", choices)
        self.assertIn("production-proof-observe", choices)

    def test_pre_and_production_cli_wrappers_accept_injected_backend(self):
        pre = execute_observed_pre_promotion_proof
        prod = execute_observed_production_proof
        self.assertTrue(callable(pre)); self.assertTrue(callable(prod))

    def test_cli_pre_observation_command_uses_injected_fake_backend(self):
        from publisher import workflow_stage_cli as cli
        fake = FakeBackend(); out = io.StringIO()
        argv = ["pre-promotion-proof-observe", "--build-bundle", str(self.paths["build"]),
                "--deploy-intent", str(self.paths["deploy_intent"]),
                "--deploy-result", str(self.paths["deploy_result"]),
                "--sealed-root", str(self.sealed), "--snapshot", str(self.snapshot),
                "--route-manifest", str(self.routes), "--media-manifest", str(self.media),
                "--base-url", "https://mahoonartmagazine.ir",
                "--evidence-dir", str(self.root / "cli-pre-evidence"),
                "--output", str(self.root / "cli-preproof.json")]
        for name in ("receipt", "upload_intent", "upload_result"):
            argv.extend(["--reference", str(self.paths[name])])
        with patch.object(runner, "RuntimeObservationBackend", return_value=fake), contextlib.redirect_stdout(out):
            code = cli.main(argv)
        self.assertEqual(0, code); self.assertEqual(1, fake.calls)
        self.assertEqual("pre_promotion_proof_evidence", transport.read_artifact(
            self.root / "cli-preproof.json", expected_type="pre_promotion_proof_evidence",
            referenced_artifacts=self.refs)["artifact_type"])

    def test_cli_production_observation_command_uses_injected_fake_backend(self):
        from publisher import workflow_stage_cli as cli
        fake = FakeBackend(); out = io.StringIO()
        argv = ["production-proof-observe"]
        flag_map = {
            "build-bundle": "build", "upload-intent": "upload_intent", "upload-result": "upload_result",
            "deploy-intent": "deploy_intent", "deploy-result": "deploy_result",
            "pre-promotion-proof": "preproof", "promote-intent": "promote_intent",
            "promote-result": "promote_result",
        }
        for flag, name in flag_map.items(): argv.extend(["--" + flag, str(self.paths[name])])
        argv.extend(["--sealed-root", str(self.sealed), "--snapshot", str(self.snapshot),
                     "--route-manifest", str(self.routes), "--media-manifest", str(self.media),
                     "--local-gates", str(self.local), "--base-url", "https://mahoonartmagazine.ir",
                     "--evidence-dir", str(self.root / "cli-prod-evidence"),
                     "--output", str(self.root / "cli-proof.json")])
        with patch.object(runner, "RuntimeObservationBackend", return_value=fake), contextlib.redirect_stdout(out):
            code = cli.main(argv)
        self.assertEqual(0, code); self.assertEqual(1, fake.calls)
        self.assertEqual("proof_evidence", transport.read_artifact(
            self.root / "cli-proof.json", expected_type="proof_evidence", referenced_artifacts=self.refs)["artifact_type"])

    def test_runtime_backend_rejects_unapproved_origin_before_io(self):
        with self.assertRaises(ValueError):
            runner.RuntimeObservationBackend(stage="pre-promotion", base_url="https://example.invalid",
                evidence_root=self.root / "runtime", sealed_root=self.sealed,
                snapshot=self.snapshot, routes=self.routes, media=self.media)

    def test_runtime_crawler_rejection_surfaces_redacted_stderr_tail(self):
        from subprocess import CompletedProcess
        from publisher import cloudflare_wrangler

        backend = runner.RuntimeObservationBackend(
            stage="pre-promotion", base_url="https://mahoonartmagazine.ir",
            evidence_root=self.root / "runtime-evidence", sealed_root=self.sealed,
            snapshot=self.snapshot, routes=self.routes, media=self.media,
        )
        context = {
            "build_bundle": {}, "transaction": {"worker": "mahoon-art-magazine"},
            "candidate_identity": {
                "candidate_version_id": "candidate-v1", "baseline_version_id": "baseline-v1",
                "zero_percent_deployment_id": "dep-zero",
            },
        }
        completed = CompletedProcess(
            args=[], returncode=1, stdout=b"",
            stderr=b"RuntimeError: API_TOKEN=synthetic-secret-marker\n",
        )
        with patch.object(runner, "_input_files_match"), \
             patch.object(cloudflare_wrangler, "active_deployment", return_value={
                 "id": "dep-zero", "versions": [
                     {"version_id": "candidate-v1", "percentage": 0},
                     {"version_id": "baseline-v1", "percentage": 100},
                 ],
             }), patch.object(runner.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(runner.ObservationRejected, "RuntimeError: API_TOKEN=\\[redacted\\]") as error:
                backend.collect(context)
        self.assertNotIn("synthetic-secret-marker", str(error.exception))

    def test_runtime_browser_rejection_surfaces_redacted_stderr_tail(self):
        from subprocess import CompletedProcess
        from publisher import cloudflare_wrangler

        backend = runner.RuntimeObservationBackend(
            stage="pre-promotion", base_url="https://mahoonartmagazine.ir",
            evidence_root=self.root / "runtime-browser-evidence", sealed_root=self.sealed,
            snapshot=self.snapshot, routes=self.routes, media=self.media,
        )
        context = {
            "build_bundle": {}, "transaction": {"worker": "mahoon-art-magazine"},
            "candidate_identity": {
                "candidate_version_id": "candidate-v1", "baseline_version_id": "baseline-v1",
                "zero_percent_deployment_id": "dep-zero",
            },
        }

        def run(command, **kwargs):
            if command[0] == "node":
                return CompletedProcess(
                    command, 1, stdout=b"",
                    stderr=b"Error: API_TOKEN=synthetic-secret-marker\n    at run (gate.mjs:1:2)\nNode.js v22.23.3\n",
                )
            crawl_out = Path(kwargs["env"]["MAHOON_CRAWL_OUTPUT"]) / "production-override-crawl"
            crawl_out.mkdir(parents=True)
            (crawl_out / "production-override-crawl-summary.json").write_text("{}", encoding="utf-8")
            (crawl_out / "production-override-crawl-state.json").write_text("{}", encoding="utf-8")
            return CompletedProcess(command, 0, stdout=b"", stderr=b"")

        with patch.object(runner, "_input_files_match"), \
             patch.object(cloudflare_wrangler, "active_deployment", return_value={
                 "id": "dep-zero", "versions": [
                     {"version_id": "candidate-v1", "percentage": 0},
                     {"version_id": "baseline-v1", "percentage": 100},
                 ],
             }), patch.object(runner.subprocess, "run", side_effect=run):
            with self.assertRaisesRegex(
                runner.ObservationRejected,
                "read-only browser observation did not complete.*Error: API_TOKEN=\\[redacted\\]",
            ) as error:
                backend.collect(context)
        self.assertNotIn("synthetic-secret-marker", str(error.exception))

    def test_runtime_browser_visual_failure_preserves_sanitized_page_evidence(self):
        from subprocess import CompletedProcess
        from publisher import cloudflare_wrangler

        evidence_root = self.root / "runtime-visual-evidence"
        backend = runner.RuntimeObservationBackend(
            stage="pre-promotion", base_url="https://mahoonartmagazine.ir",
            evidence_root=evidence_root, sealed_root=self.sealed, snapshot=self.snapshot,
            routes=self.routes, media=self.media,
        )
        context = {
            "build_bundle": {}, "transaction": {"worker": "mahoon-art-magazine"},
            "candidate_identity": {
                "candidate_version_id": "candidate-v1", "baseline_version_id": "baseline-v1",
                "zero_percent_deployment_id": "dep-zero",
            },
        }
        browser = {
            "measured": True, "candidate_version": "candidate-v1",
            "runtime": {"node_version": "v22.23.3", "playwright_version": "1.63.0",
                        "chromium_version": "Chromium 140"},
            "checks": [{"name": "posts", "route": "/posts/?token=private-value", "status": 200,
                        "navigation_error": None, "screenshot_error": "screenshot timeout",
                        "font_loading": {"status": "loading", "ready": False},
                        "pageErrors": ["API_TOKEN=synthetic-secret-marker"],
                        "actual_version": "candidate-v1", "version_attribution_pass": True,
                        "visual_pass": False, "zero_origin_pass": True},
                       {"name": "old-post", "route": "/post/old?preview=private-value", "status": 0,
                        "navigation_error": "TimeoutError: navigation timed out", "screenshot_error": None,
                        "font_loading": None, "actual_version": None,
                        "version_attribution_pass": False, "visual_pass": False,
                        "zero_origin_pass": True}],
            "visual": {"pages_checked": 1, "PASS": False},
            "zero_origin": {"public_pages_checked": 1, "PASS": True}, "PASS": False,
        }

        def run(command, **kwargs):
            if command[0] == "node":
                Path(command[command.index("--output") + 1]).write_text(json.dumps(browser), encoding="utf-8")
                return CompletedProcess(command, 1, stdout=b"", stderr=b"visual gate failed\n")
            crawl_out = Path(kwargs["env"]["MAHOON_CRAWL_OUTPUT"]) / "production-override-crawl"
            crawl_out.mkdir(parents=True)
            (crawl_out / "production-override-crawl-summary.json").write_text("{}", encoding="utf-8")
            (crawl_out / "production-override-crawl-state.json").write_text("{}", encoding="utf-8")
            return CompletedProcess(command, 0, stdout=b"", stderr=b"")

        with patch.object(runner, "_input_files_match"), \
             patch.object(cloudflare_wrangler, "active_deployment", return_value={
                 "id": "dep-zero", "versions": [
                     {"version_id": "candidate-v1", "percentage": 0},
                     {"version_id": "baseline-v1", "percentage": 100},
                 ],
             }), patch.object(runner.subprocess, "run", side_effect=run):
            result = backend.collect(context)
        evidence = self.root / "runtime-visual-evidence-browser-diagnostic.json"
        diagnostic = json.loads(evidence.read_text(encoding="utf-8"))
        self.assertFalse(result["browser"]["PASS"])
        self.assertEqual(1, diagnostic["process_exit_code"])
        page = diagnostic["browser"]["checks"][0]
        self.assertEqual("/posts/", page["route"])
        self.assertEqual(200, page["status"])
        self.assertEqual("screenshot timeout", page["screenshot_error"])
        self.assertFalse(page["font_loading"]["ready"])
        self.assertTrue(page["version_attribution_pass"])
        self.assertEqual("navigation timed out", diagnostic["browser"]["checks"][1]["navigation_error"].split(": ", 1)[1])
        self.assertEqual(0, diagnostic["browser"]["checks"][1]["status"])
        self.assertNotIn("synthetic-secret-marker", evidence.read_text(encoding="utf-8"))
        self.assertNotIn("private-value", evidence.read_text(encoding="utf-8"))
        import shutil
        shutil.rmtree(result["directory"])

    def test_runtime_browser_launch_and_javascript_errors_are_distinguished(self):
        from subprocess import CompletedProcess
        from publisher import cloudflare_wrangler

        context = {
            "build_bundle": {}, "transaction": {"worker": "mahoon-art-magazine"},
            "candidate_identity": {
                "candidate_version_id": "candidate-v1", "baseline_version_id": "baseline-v1",
                "zero_percent_deployment_id": "dep-zero",
            },
        }
        for kind, expected in (("browser_launch_error", "browser launch failed"),
                               ("javascript_exception", "browser JavaScript exception")):
            with self.subTest(kind=kind):
                evidence_root = self.root / f"runtime-{kind}"
                backend = runner.RuntimeObservationBackend(
                    stage="pre-promotion", base_url="https://mahoonartmagazine.ir",
                    evidence_root=evidence_root, sealed_root=self.sealed, snapshot=self.snapshot,
                    routes=self.routes, media=self.media,
                )

                def run(command, **kwargs):
                    if command[0] == "node":
                        Path(command[command.index("--output") + 1]).write_text(json.dumps({
                            "measured": False, "browser_error_kind": kind,
                            "failure": "Error: API_TOKEN=synthetic-secret-marker",
                        }), encoding="utf-8")
                        return CompletedProcess(command, 2, stdout=b"", stderr=b"runtime failure\n")
                    crawl_out = Path(kwargs["env"]["MAHOON_CRAWL_OUTPUT"]) / "production-override-crawl"
                    crawl_out.mkdir(parents=True)
                    (crawl_out / "production-override-crawl-summary.json").write_text("{}", encoding="utf-8")
                    (crawl_out / "production-override-crawl-state.json").write_text("{}", encoding="utf-8")
                    return CompletedProcess(command, 0, stdout=b"", stderr=b"")

                with patch.object(runner, "_input_files_match"), \
                     patch.object(cloudflare_wrangler, "active_deployment", return_value={
                         "id": "dep-zero", "versions": [
                             {"version_id": "candidate-v1", "percentage": 0},
                             {"version_id": "baseline-v1", "percentage": 100},
                         ],
                     }), patch.object(runner.subprocess, "run", side_effect=run):
                    with self.assertRaisesRegex(runner.ObservationRejected, expected):
                        backend.collect(context)
                evidence = self.root / f"runtime-{kind}-browser-diagnostic.json"
                saved = json.loads(evidence.read_text(encoding="utf-8"))
                self.assertEqual(kind, saved["browser"]["browser_error_kind"])
                self.assertNotIn("synthetic-secret-marker", evidence.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
