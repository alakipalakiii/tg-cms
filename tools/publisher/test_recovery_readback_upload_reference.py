"""Regression test: recovery readback for an upload_version intent with UNKNOWN
result. The upload_version branch of _validate_inputs proves admission lineage
through the sealed intent itself (create_mutation_intent already checked
bundle.payload.admission_receipt_sha256 == admission.artifact_sha256 at intent
creation), so the readback step needs only the admission receipt in refs — not
the build_bundle. The broken workflow shape passes only --reference
admission.json; this test pins that that shape is accepted.

Sealed artifacts are built with contracts.seal_artifact so digests are valid
(canonical), matching what validate_artifact re-computes.
"""
import hashlib
import unittest
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
import sys
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "tools/publisher"))

from publisher import artifact_contract as contracts
from publisher import recovery_readback


def _H(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class _NoopBackend:
    """Stands in for WranglerReadOnlyBackend: reports no matching version."""
    def list_versions(self, _worker: str) -> list[dict]:
        return []
    def read_deployment(self, _worker: str) -> dict:
        return {"id": "dep-1", "versions": [{"version_id": "base", "percentage": 100}]}


def _envelope(kind: str, payload: dict, source: dict) -> dict:
    value = {
        "artifact_type": kind,
        "schema_version": contracts.SCHEMA_VERSION,
        "artifact_id": str(uuid.uuid4()),
        "created_at": "2026-10-11T19:00:00+00:00",
        "producer": source["producer"],
        "transaction": source["transaction"],
        "payload": payload,
    }
    return contracts.seal_artifact(value)


def _scenario() -> dict:
    worker = "mahoon-art-magazine"
    revision = 159
    tx = {"worker": worker, "content_revision": revision,
          "logical_transaction_id": contracts.logical_transaction_id(worker, revision)}
    source = {"transaction": tx,
              "producer": {"workflow_run_id": "1", "run_attempt": 1, "job": "test",
                           "source_sha": "a" * 40}}

    admission = _envelope("admission_receipt", {
        "decision": "ADMITTED", "journal_generation": 40, "journal_sha256": _H("journal40"),
        "revision_resolution_sha256": _H("revres"), "pending_revision": None,
        "active_transaction_id": None,
    }, source)

    bundle = _envelope("build_bundle", {
        "admission_receipt_sha256": admission["artifact_sha256"],
        "files": [], "content_fingerprint": _H("content"), "snapshot_sha256": _H("snap"),
        "route_manifest_sha256": _H("route"), "media_manifest_sha256": _H("media"),
        "local_gate_evidence_sha256": _H("gate"),
    }, source)

    op_id = contracts.operation_id_for(tx["logical_transaction_id"], "upload_version")
    attempt = str(uuid.uuid4())
    intent = _envelope("mutation_intent", {
        "operation_id": op_id, "operation_name": "upload_version", "attempt_id": attempt,
        "intent_state": "RECORDED", "build_bundle_sha256": bundle["artifact_sha256"],
        "prerequisite_artifact_sha256": admission["artifact_sha256"],
        "journal_generation": 41,
        "desired_state": {"worker": worker, "build_bundle_sha256": bundle["artifact_sha256"]},
    }, source)

    result = _envelope("mutation_result", {
        "operation_id": op_id, "attempt_id": attempt, "result_state": "UNKNOWN",
        "evidence_sha256": None, "intent_artifact_sha256": intent["artifact_sha256"],
        "build_bundle_sha256": bundle["artifact_sha256"], "readback_reference": None,
    }, source)

    return {"intent": intent, "result": result, "admission": admission, "bundle": bundle}


class RecoveryReadbackUploadReferenceTests(unittest.TestCase):
    def test_observe_accepts_admission_only_reference(self):
        # The exact pre-fix broken workflow shape: only admission.json in refs.
        s = _scenario()
        value = recovery_readback.collect_fresh_readback(
            s["intent"], s["result"],
            references={s["admission"]["artifact_sha256"]: s["admission"]},
            backend=_NoopBackend(),
            clock=lambda: "2026-10-11T19:00:30+00:00")
        # UNKNOWN upload with no matching Cloudflare version -> absent resource.
        self.assertIsNone(value["readback"]["resource_id"])
        self.assertIsNone(value["readback"]["resource_type"])

    def test_observe_accepts_admission_and_bundle_reference(self):
        # Adding the build bundle to refs must also be accepted.
        s = _scenario()
        value = recovery_readback.collect_fresh_readback(
            s["intent"], s["result"],
            references={s["admission"]["artifact_sha256"]: s["admission"],
                        s["bundle"]["artifact_sha256"]: s["bundle"]},
            backend=_NoopBackend(),
            clock=lambda: "2026-10-11T19:00:30+00:00")
        self.assertIsNone(value["readback"]["resource_id"])


if __name__ == "__main__":
    unittest.main()
