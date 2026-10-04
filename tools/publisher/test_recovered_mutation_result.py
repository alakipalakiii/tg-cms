from __future__ import annotations

import copy
import hashlib
import inspect
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from publisher import artifact_contract as contracts
from publisher import effective_mutation_result as effective
from publisher import recovery_readback
from publisher import workflow_stage_cli as cli
from publisher.transaction_journal import canonical_result_digest
from publisher import test_proof_recovery_runner as proof_fixtures


class UploadReadback:
    def __init__(self, version_id: str):
        self.version_id = version_id

    def list_versions(self, worker: str) -> list[dict]:
        del worker
        return [{"id": self.version_id,
                 "annotations": {"workers/message": self.marker}}]

    def read_deployment(self, worker: str) -> dict:
        raise AssertionError("upload recovery must not query deployments")


class DeploymentReadback:
    def __init__(self, deployment_id: str, versions: list[dict]):
        self.deployment_id, self.versions = deployment_id, versions

    def list_versions(self, worker: str) -> list[dict]:
        raise AssertionError("deployment recovery must not query versions")

    def read_deployment(self, worker: str) -> dict:
        return {"id": self.deployment_id, "versions": self.versions}


class RecoveredMutationResultTests(unittest.TestCase):
    def setUp(self):
        self.fixture = proof_fixtures.ProofRecoveryRunnerTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.tx = self.fixture.tx
        self.intent = self.fixture.upload_intent
        self.unknown = self.fixture._result(self.intent, "UNKNOWN", None, None)
        self.references = {
            item["artifact_sha256"]: item for item in (
                self.fixture.receipt, self.fixture.bundle, self.intent, self.unknown,
            )
        }
        marker = (f"MAHOON-A3:{self.intent['payload']['operation_id']}:{self.intent['payload']['attempt_id']}")
        backend = UploadReadback("candidate-recovered")
        backend.marker = marker
        observed = datetime.now(timezone.utc) - timedelta(seconds=1)
        self.evidence = recovery_readback.collect_fresh_readback(
            self.intent, self.unknown, references=self.references, backend=backend,
            clock=lambda: observed.isoformat(),
        )
        self.decision = __import__("publisher.proof_recovery_runner", fromlist=["recovery_decision"]).recovery_decision(
            self.intent, self.unknown, self.evidence["readback"],
            self.intent["payload"]["journal_generation"],
            clock=lambda: observed.isoformat(), referenced_artifacts=self.references,
        )
        dp = self.decision["payload"]
        self.result_digest = canonical_result_digest("APPLIED", {
            "type": "recovery_decision", "reference": self.decision["artifact_sha256"],
            "sha256": dp["evidence_sha256"],
        })
        self.journal_readback = {
            "worker": self.tx["worker"],
            "logical_transaction_id": self.tx["logical_transaction_id"],
            "content_revision": self.tx["content_revision"],
            "operation_name": "upload_version",
            "operation_id": self.intent["payload"]["operation_id"],
            "attempt_id": self.intent["payload"]["attempt_id"],
            "outcome": "APPLIED", "recovery_status": "RECONCILED_APPLIED",
            "result_digest": self.result_digest,
            "journal_generation": dp["journal_generation"] + 1,
            "journal_sha256": "e" * 64, "remote_head": "f" * 40,
        }
        self.references.update({self.decision["artifact_sha256"]: self.decision})

    def _create(self, *, evidence=None, decision=None, journal=None, clock=None):
        return effective._create_recovered_mutation_result_from_readback(
            intent=self.intent, original_result=self.unknown,
            recovery_evidence=self.evidence if evidence is None else evidence,
            recovery_decision=self.decision if decision is None else decision,
            journal_readback=self.journal_readback if journal is None else journal,
            referenced_artifacts=self.references,
            clock=clock or (lambda: datetime.now(timezone.utc).isoformat()),
        )

    def test_direct_applied_result_remains_accepted_and_unknown_does_not(self):
        direct = self.fixture._result(self.intent, "APPLIED", "version", "candidate-v1")
        view = effective.validate_effective_applied_result(
            direct, self.intent, referenced_artifacts=self.references,
        )
        self.assertEqual(direct["artifact_sha256"], view["artifact_sha256"])
        with self.assertRaises(effective.EffectiveResultRejected):
            effective.validate_effective_applied_result(
                self.unknown, self.intent, referenced_artifacts=self.references,
            )

    def test_bridge_preserves_unknown_and_validates_as_effective_applied(self):
        original_bytes = contracts.canonical_json_bytes(self.unknown)
        bridge = self._create()
        refs = {**self.references, bridge["artifact_sha256"]: bridge}
        view = effective.validate_effective_applied_result(
            bridge, self.intent, referenced_artifacts=refs,
        )
        self.assertEqual("recovered_mutation_result", bridge["artifact_type"])
        self.assertEqual("APPLIED", view["payload"]["result_state"])
        self.assertEqual(self.unknown["artifact_sha256"], bridge["payload"]["original_result_artifact_sha256"])
        self.assertEqual(original_bytes, contracts.canonical_json_bytes(self.unknown))
        self.assertEqual("UNKNOWN", contracts.validate_artifact(self.unknown)["payload"]["result_state"])

    def test_bridge_requires_exact_applied_decision_and_remote_readback(self):
        for choice in ("RECONCILED_NOT_APPLIED", "BLOCKED_UNKNOWN"):
            bad = copy.deepcopy(self.decision)
            bad["payload"]["decision"] = choice
            bad["payload"]["resume_allowed"] = choice == "RECONCILED_NOT_APPLIED"
            bad = contracts.seal_artifact(bad)
            with self.subTest(decision=choice), self.assertRaises(Exception):
                self._create(decision=bad)
        for field, value in (
            ("journal_generation", self.journal_readback["journal_generation"] + 1),
            ("result_digest", "0" * 64),
            ("recovery_status", "REQUIRED"),
            ("remote_head", "x" * 40),
        ):
            bad = dict(self.journal_readback, **{field: value})
            with self.subTest(field=field), self.assertRaises(Exception):
                self._create(journal=bad)

    def test_bridge_rejects_wrong_result_and_decision_lineage(self):
        altered = copy.deepcopy(self.decision)
        altered["payload"]["result_artifact_sha256"] = "0" * 64
        altered = contracts.seal_artifact(altered)
        with self.assertRaises(Exception):
            self._create(decision=altered)
        direct = self.fixture._result(self.intent, "APPLIED", "version", "candidate-v1")
        with self.assertRaises(Exception):
            effective._create_recovered_mutation_result_from_readback(
                intent=self.intent, original_result=direct, recovery_evidence=self.evidence,
                recovery_decision=self.decision, journal_readback=self.journal_readback,
                referenced_artifacts=self.references,
            )

    def test_bridge_rejects_stale_evidence_and_unknown_source_fields(self):
        created = datetime.fromisoformat(self.evidence["observed_at"])
        stale_clock = (created + timedelta(seconds=recovery_readback.MAX_AGE_SECONDS + 1)).isoformat()
        with self.assertRaises(Exception):
            self._create(clock=lambda: stale_clock)
        bridge = self._create()
        extra = copy.deepcopy(bridge)
        extra["payload"]["unrecognized"] = True
        extra = contracts.seal_artifact(extra)
        with self.assertRaises(contracts.ArtifactContractError):
            contracts.validate_artifact(extra)

    def test_bridge_tampering_is_detected_and_cli_only_orchestrates(self):
        bridge = self._create()
        tampered = copy.deepcopy(bridge)
        tampered["payload"]["readback_reference"]["resource_id"] = "forged"
        with self.assertRaises(contracts.ArtifactContractError):
            contracts.validate_artifact(tampered)
        args = cli._parser().parse_args([
            "create-recovered-result", "--intent", "i", "--result", "r",
            "--readback", "rb", "--decision", "d", "--repository", "repo",
            "--output", "out",
        ])
        self.assertEqual("create-recovered-result", args.command)
        source = inspect.getsource(cli.create_recovered_result)
        self.assertIn("journal_writer=writer", source)
        producer = inspect.getsource(effective.create_recovered_mutation_result)
        self.assertIn("read_reconciled_applied_result", producer)
        self.assertIn("effective_result.create_recovered_mutation_result", source)
        self.assertNotIn("canonical_json_bytes", source)
        self.assertNotIn("canonical_result_digest", source)
        self.assertNotIn("cloudflare", source.lower())

    def test_bridge_producer_has_no_mutation_or_journal_write_path(self):
        source = inspect.getsource(effective.create_recovered_mutation_result).lower()
        for forbidden in ("cloudflare", "wrangler", "dispatch(", "record_intent(", "reconcile(", "push"):
            self.assertNotIn(forbidden, source)
        writer = inspect.getsource(__import__("publisher.repository_persistence", fromlist=["GitJournalWriter"]).GitJournalWriter.read_reconciled_applied_result)
        for forbidden in ("_commit_journal", "_push", "cloudflare", "wrangler", "record_result("):
            self.assertNotIn(forbidden, writer)

    def test_recovered_upload_is_an_eligible_zero_percent_prerequisite(self):
        from publisher import cloudflare_operation_adapter as adapter
        bridge = self._create()
        refs = {**self.references, bridge["artifact_sha256"]: bridge}
        deploy_intent = self.fixture._intent("deploy_zero_percent", bridge, {
            "worker": self.tx["worker"], "candidate_version_id": "candidate-recovered",
            "baseline_version_id": "baseline-v1", "expected_current_deployment_id": "dep-before",
            "candidate_percentage": 0, "baseline_percentage": 100,
        })
        refs[deploy_intent["artifact_sha256"]] = deploy_intent
        result = adapter._validate_prerequisite(
            deploy_intent, bridge, self.intent, refs,
        )
        self.assertEqual(bridge["artifact_sha256"], result["artifact_sha256"])

    def test_git_writer_readback_requires_the_exact_durable_reconciliation(self):
        import tempfile
        from publisher import repository_persistence as repository
        from publisher.proof_recovery_runner import recovery_decision
        from publisher.test_a54_remote_lifecycle_bridge import LocalBare, REVISION, SOURCE_SHA, WORKER

        source_tx = {"worker": WORKER, "content_revision": REVISION,
                     "logical_transaction_id": contracts.logical_transaction_id(WORKER, REVISION)}

        def sealed(kind, payload):
            return contracts.seal_artifact({
                "artifact_type": kind, "schema_version": contracts.SCHEMA_VERSION,
                "artifact_id": str(uuid.uuid4()), "created_at": datetime.now(timezone.utc).isoformat(),
                "producer": {"workflow_run_id": "synthetic", "run_attempt": 1,
                             "job": "synthetic", "source_sha": SOURCE_SHA},
                "transaction": dict(source_tx), "payload": payload,
            })

        with tempfile.TemporaryDirectory(prefix="mahoon-bridge-journal-") as temp:
            local = LocalBare(Path(temp))
            writer = local.writer()
            status, txid, generation, _ = writer.admit_revision(
                REVISION, "synthetic", "run", str(uuid.uuid4()),
            )
            self.assertEqual("ADMITTED", status)
            receipt = sealed("admission_receipt", {
                "decision": "ADMITTED", "journal_generation": generation,
                "journal_sha256": "1" * 64, "revision_resolution_sha256": "2" * 64,
                "pending_revision": None, "active_transaction_id": txid,
            })
            bundle = sealed("build_bundle", {
                "admission_receipt_sha256": receipt["artifact_sha256"],
                "files": [{"path": "index.html", "size_bytes": 1, "sha256": "3" * 64}],
                "content_fingerprint": "4" * 64, "snapshot_sha256": "5" * 64,
                "route_manifest_sha256": "6" * 64, "media_manifest_sha256": "7" * 64,
                "local_gate_evidence_sha256": "8" * 64,
            })
            writer.record_build_ready(txid, bundle["artifact_sha256"])
            _state, generation, _ = local.journal().snapshot()
            attempt_id = str(uuid.uuid4())
            intent = sealed("mutation_intent", {
                "operation_id": contracts.operation_id_for(txid, "upload_version"),
                "operation_name": "upload_version", "attempt_id": attempt_id,
                "intent_state": "RECORDED", "build_bundle_sha256": bundle["artifact_sha256"],
                "prerequisite_artifact_sha256": receipt["artifact_sha256"],
                "journal_generation": generation + 1,
                "desired_state": {"worker": WORKER, "build_bundle_sha256": bundle["artifact_sha256"]},
            })
            writer.record_intent(txid, "upload_version", attempt_id,
                                 intent["artifact_sha256"], intent["payload"]["journal_generation"])
            unknown = sealed("mutation_result", {
                "operation_id": intent["payload"]["operation_id"], "attempt_id": attempt_id,
                "result_state": "UNKNOWN", "evidence_sha256": None,
                "intent_artifact_sha256": intent["artifact_sha256"],
                "build_bundle_sha256": bundle["artifact_sha256"], "readback_reference": None,
            })
            writer.record_result(txid, intent["payload"]["operation_id"], attempt_id,
                                 "UNKNOWN", None, intent["artifact_sha256"], unknown["artifact_sha256"])
            refs = {a["artifact_sha256"]: a for a in (receipt, bundle, intent, unknown)}
            marker = f"MAHOON-A3:{intent['payload']['operation_id']}:{attempt_id}"
            backend = UploadReadback("candidate-from-remote")
            backend.marker = marker
            observed_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            evidence = recovery_readback.collect_fresh_readback(
                intent, unknown, references=refs, backend=backend,
                clock=lambda: observed_at.isoformat(),
            )
            _state, recovery_generation, _digest = local.journal().snapshot()
            decision = recovery_decision(
                intent, unknown, evidence["readback"], recovery_generation,
                clock=lambda: observed_at.isoformat(), referenced_artifacts=refs,
            )
            writer.reconcile_recovery_decision(decision)
            refs[decision["artifact_sha256"]] = decision
            bridge = effective.create_recovered_mutation_result(
                intent=intent, original_result=unknown, recovery_evidence=evidence,
                recovery_decision=decision, journal_writer=writer,
                referenced_artifacts=refs,
            )
            readback = writer.read_reconciled_applied_result(
                decision, intent, unknown, referenced_artifacts=refs,
            )
            self.assertEqual("RECONCILED_APPLIED", readback["recovery_status"])
            self.assertEqual("APPLIED", bridge["payload"]["result_state"])
            self.assertEqual(readback["journal_sha256"], bridge["payload"]["journal_sha256"])

    def test_three_recovered_results_complete_proof_and_exact_six_materialization(self):
        import tempfile
        from publisher import final_state_materializer as materializer
        from publisher import proof_recovery_runner as proof_recovery
        from test_final_state_materializer import _fixture

        with tempfile.TemporaryDirectory(prefix="mahoon-recovered-e2e-") as temp:
            f = _fixture(Path(temp))

            def bridge_for(intent, unknown, refs, backend):
                if isinstance(backend, UploadReadback):
                    backend.marker = (f"MAHOON-A3:{intent['payload']['operation_id']}"
                                      f":{intent['payload']['attempt_id']}")
                observed = datetime.now(timezone.utc) - timedelta(seconds=1)
                evidence = recovery_readback.collect_fresh_readback(
                    intent, unknown, references=refs, backend=backend,
                    clock=lambda: observed.isoformat(),
                )
                from publisher.proof_recovery_runner import recovery_decision
                decision = recovery_decision(
                    intent, unknown, evidence["readback"], intent["payload"]["journal_generation"],
                    clock=lambda: observed.isoformat(), referenced_artifacts=refs,
                )
                dp = decision["payload"]
                digest = canonical_result_digest("APPLIED", {
                    "type": "recovery_decision", "reference": decision["artifact_sha256"],
                    "sha256": dp["evidence_sha256"],
                })
                journal = {
                    "worker": intent["transaction"]["worker"],
                    "logical_transaction_id": intent["transaction"]["logical_transaction_id"],
                    "content_revision": intent["transaction"]["content_revision"],
                    "operation_name": intent["payload"]["operation_name"],
                    "operation_id": intent["payload"]["operation_id"],
                    "attempt_id": intent["payload"]["attempt_id"], "outcome": "APPLIED",
                    "recovery_status": "RECONCILED_APPLIED", "result_digest": digest,
                    "journal_generation": dp["journal_generation"] + 1,
                    "journal_sha256": "a" * 64, "remote_head": "b" * 40,
                }
                refs = {**refs, decision["artifact_sha256"]: decision}
                result = effective._create_recovered_mutation_result_from_readback(
                    intent=intent, original_result=unknown, recovery_evidence=evidence,
                    recovery_decision=decision, journal_readback=journal,
                    referenced_artifacts=refs,
                )
                refs[result["artifact_sha256"]] = result
                return result, refs

            upload_unknown = f._result(f.upload_intent, "UNKNOWN", None, None)
            refs = {**f.references, upload_unknown["artifact_sha256"]: upload_unknown}
            upload_bridge, refs = bridge_for(
                f.upload_intent, upload_unknown, refs,
                UploadReadback("candidate-v1"),
            )
            deploy_intent = f._intent("deploy_zero_percent", upload_bridge, {
                "worker": f.tx["worker"], "candidate_version_id": "candidate-v1",
                "baseline_version_id": "baseline-v1", "expected_current_deployment_id": "dep-before",
                "candidate_percentage": 0, "baseline_percentage": 100,
            })
            refs[deploy_intent["artifact_sha256"]] = deploy_intent
            deploy_unknown = f._result(deploy_intent, "UNKNOWN", None, None)
            refs[deploy_unknown["artifact_sha256"]] = deploy_unknown
            deploy_bridge, refs = bridge_for(
                deploy_intent, deploy_unknown, refs,
                DeploymentReadback("dep-zero", [
                    {"version_id": "baseline-v1", "percentage": 100},
                    {"version_id": "candidate-v1", "percentage": 0},
                ]),
            )
            pre_payload = copy.deepcopy(f.prepromotion_proof["payload"])
            pre_payload["deploy_zero_percent_result_artifact_sha256"] = deploy_bridge["artifact_sha256"]
            preproof = self.fixture_artifact("pre_promotion_proof_evidence", pre_payload, f.tx)
            refs[preproof["artifact_sha256"]] = preproof
            promote_intent = f._intent("promote", preproof, {
                "worker": f.tx["worker"], "candidate_version_id": "candidate-v1",
                "baseline_version_id": "baseline-v1", "expected_current_deployment_id": "dep-zero",
                "candidate_percentage": 100, "baseline_percentage": 0,
            })
            refs[promote_intent["artifact_sha256"]] = promote_intent
            promote_unknown = f._result(promote_intent, "UNKNOWN", None, None)
            refs[promote_unknown["artifact_sha256"]] = promote_unknown
            promote_bridge, refs = bridge_for(
                promote_intent, promote_unknown, refs,
                DeploymentReadback("dep-promoted", [
                    {"version_id": "candidate-v1", "percentage": 100},
                    {"version_id": "baseline-v1", "percentage": 0},
                ]),
            )
            results = {
                "upload_version": upload_bridge,
                "deploy_zero_percent": deploy_bridge,
                "promote": promote_bridge,
            }
            def proof_for(values):
                payload = copy.deepcopy(f.proof["payload"])
                payload["operation_result_sha256s"].update({
                    name: result["artifact_sha256"] for name, result in values.items()
                })
                return self.fixture_artifact("proof_evidence", payload, f.tx)

            proof = proof_for(results)
            refs[proof["artifact_sha256"]] = proof
            proof_recovery.validate_proof(proof, f.bundle, results, referenced_artifacts=refs)
            direct_results = {
                "upload_version": f._result(f.upload_intent, "APPLIED", "version", "candidate-v1"),
                "deploy_zero_percent": f._result(deploy_intent, "APPLIED", "deployment", "dep-zero"),
                "promote": f._result(promote_intent, "APPLIED", "deployment", "dep-promoted"),
            }
            combos = (
                {**direct_results, "upload_version": upload_bridge},
                {**direct_results, "deploy_zero_percent": deploy_bridge},
                {**direct_results, "promote": promote_bridge},
                {**direct_results, "upload_version": upload_bridge,
                 "deploy_zero_percent": deploy_bridge},
                {**direct_results, "upload_version": upload_bridge,
                 "promote": promote_bridge},
                {**direct_results, "deploy_zero_percent": deploy_bridge,
                 "promote": promote_bridge},
            )
            for combo in combos:
                mixed_proof = proof_for(combo)
                proof_recovery.validate_proof(
                    mixed_proof, f.bundle, combo, referenced_artifacts=refs,
                )

            failed_payload = copy.deepcopy(f._proof(failed_production=True)["payload"])
            failed_payload["operation_result_sha256s"].update({
                name: result["artifact_sha256"] for name, result in results.items()
            })
            failed_proof = self.fixture_artifact("proof_evidence", failed_payload, f.tx)
            refs[failed_proof["artifact_sha256"]] = failed_proof
            rollback_intent = f._intent("rollback", failed_proof, {
                "worker": f.tx["worker"], "baseline_version_id": "baseline-v1",
                "failed_candidate_version_id": "candidate-v1",
                "expected_current_deployment_id": "dep-promoted",
                "candidate_percentage": 0, "baseline_percentage": 100,
            })
            refs[rollback_intent["artifact_sha256"]] = rollback_intent
            proof_recovery.authorize_rollback(
                failed_proof, promote_intent, promote_bridge, rollback_intent,
                referenced_artifacts=refs,
            )
            cli_inputs = {"proof": failed_proof, "promote": promote_intent,
                          "result": promote_bridge, "rollback": rollback_intent}
            with patch.object(cli, "_many", return_value=list(refs.values())), \
                    patch.object(cli, "_read", side_effect=lambda path, *args, **kwargs: cli_inputs[path]):
                authorized = cli.authorize_rollback(
                    "proof", "promote", "result", "rollback", ["synthetic-refs"],
                )
            self.assertEqual("rollback", authorized["payload"]["operation_name"])
            intent_source = inspect.getsource(cli.create_mutation_intent)
            self.assertIn("_read(promotion_result_path, refs=promotion_refs)", intent_source)
            rollback_unknown = f._result(rollback_intent, "UNKNOWN", None, None)
            refs[rollback_unknown["artifact_sha256"]] = rollback_unknown
            rollback_bridge, rollback_refs = bridge_for(
                rollback_intent, rollback_unknown, refs,
                DeploymentReadback("dep-rollback", [
                    {"version_id": "baseline-v1", "percentage": 100},
                    {"version_id": "candidate-v1", "percentage": 0},
                ]),
            )
            with self.assertRaises(Exception):
                proof_recovery.validate_proof(
                    failed_proof, f.bundle,
                    {**results, "rollback": rollback_bridge},
                    referenced_artifacts=rollback_refs,
                )
            files = materializer.materialize_final_state(
                proof=proof, build_bundle=f.bundle,
                operation_intents={"upload_version": f.upload_intent,
                                   "deploy_zero_percent": deploy_intent,
                                   "promote": promote_intent},
                operation_results=results, snapshot_bytes=f.snapshot_bytes,
                media_manifest_bytes=f.media_bytes, route_manifest_bytes=f.route_bytes,
                sealed_root=f.site, artifact_seal=f.seal,
                referenced_artifacts=refs,
            )
            self.assertEqual(set(contracts.STATE_FILE_PATHS), set(files))

    def fixture_artifact(self, kind, payload, transaction):
        return contracts.seal_artifact({
            "artifact_type": kind, "schema_version": contracts.SCHEMA_VERSION,
            "artifact_id": str(uuid.uuid4()), "created_at": datetime.now(timezone.utc).isoformat(),
            "producer": {"workflow_run_id": "synthetic-run", "run_attempt": 1,
                         "job": "synthetic", "source_sha": self.fixture.upload_intent["producer"]["source_sha"]},
            "transaction": copy.deepcopy(transaction), "payload": payload,
        })


if __name__ == "__main__":
    unittest.main()
