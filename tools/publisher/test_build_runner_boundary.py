from __future__ import annotations

import builtins
import base64
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from tools.publisher import artifact_contract


SOURCE_SHA = "4ea871f82c8bbc94016311b3dede83e4b34caa40"
WORKER = "mahoon-art-magazine"
PRIOR_INDEX_RAW = b'{"contract":"IMMUTABLE_MEDIA_INDEX_V1","entries":[]}\n'


def _prior_index_binding() -> dict:
    return {
        "repository": "synthetic-owner/tg-cms",
        "ref": "refs/heads/main",
        "commit_sha": SOURCE_SHA,
        "relative_path": artifact_contract.PRIOR_IMMUTABLE_MEDIA_INDEX_PATH,
        "exists": True,
        "content_sha256": hashlib.sha256(PRIOR_INDEX_RAW).hexdigest(),
        "byte_length": len(PRIOR_INDEX_RAW),
        "transport_base64": base64.b64encode(PRIOR_INDEX_RAW).decode("ascii"),
    }


def _producer(job: str) -> dict:
    return {
        "workflow_run_id": "12345",
        "run_attempt": 1,
        "job": job,
        "source_sha": SOURCE_SHA,
    }


def _transaction(revision: int = 77) -> dict:
    return {
        "worker": WORKER,
        "content_revision": revision,
        "logical_transaction_id": artifact_contract.logical_transaction_id(WORKER, revision),
    }


def _artifact(artifact_type: str, transaction: dict, payload: dict, job: str) -> dict:
    value = {
        "artifact_type": artifact_type,
        "schema_version": "1.0",
        "artifact_id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "producer": _producer(job),
        "transaction": transaction,
        "payload": payload,
    }
    return artifact_contract.validate_artifact(artifact_contract.seal_artifact(value))


def _authorization_pair(revision: int = 77) -> tuple[dict, dict]:
    transaction = _transaction(revision)
    revision_artifact = _artifact(
        "revision_resolution",
        transaction,
        {
            "revision": revision,
            "published_revision": revision - 1,
            "changed_at": datetime.now(timezone.utc).isoformat(),
            "endpoint_id": "mahoon-content-revision-v1",
            "request_count": 1,
            "decision": "CHANGED",
        },
        "revision-resolve",
    )
    admission = _artifact(
        "admission_receipt",
        transaction,
        {
            "decision": "ADMITTED",
            "journal_generation": 2,
            "journal_sha256": "1" * 64,
            "revision_resolution_sha256": revision_artifact["artifact_sha256"],
            "pending_revision": None,
            "active_transaction_id": transaction["logical_transaction_id"],
        },
        "admission-writer",
    )
    return revision_artifact, admission


def _load_runner():
    path = Path(__file__).resolve().parents[1] / "m9" / "publisher_runner.py"
    name = "mahoon_slice2_publisher_runner"
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class BuildRunnerBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = _load_runner()

    def test_import_does_not_load_cloudflare_mutation_module(self):
        sys.modules.pop("publisher.cloudflare_wrangler", None)
        original_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if name == "publisher.cloudflare_wrangler":
                raise AssertionError("build runner import attempted Cloudflare mutation module")
            return original_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=guarded_import):
            module = _load_runner()
        self.assertTrue(hasattr(module, "run_build_validate"))
        self.assertNotIn("publisher.cloudflare_wrangler", sys.modules)

    def test_main_dispatches_build_validate_before_legacy_state_or_mutation(self):
        with mock.patch.dict(os.environ, {"PUBLISHER_MODE": "BUILD_VALIDATE"}, clear=False):
            with mock.patch.object(self.runner, "run_build_validate", return_value=73) as build:
                self.assertEqual(self.runner.main(), 73)
                build.assert_called_once_with()

    def test_build_authorization_requires_admitted_v1_lineage(self):
        revision, admission = _authorization_pair()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            revision_path = root / "revision.json"
            admission_path = root / "admission.json"
            revision_path.write_text(json.dumps(revision), encoding="utf-8")
            admission_path.write_text(json.dumps(admission), encoding="utf-8")
            env = {
                "MAHOON_REVISION_RESOLUTION_ARTIFACT": str(revision_path),
                "MAHOON_ADMISSION_RECEIPT_ARTIFACT": str(admission_path),
            }
            with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(
                self.runner, "execution_source_identity", return_value=(SOURCE_SHA, SOURCE_SHA)
            ):
                loaded_revision, loaded_admission, source = self.runner._build_authorization()
            self.assertEqual(source, SOURCE_SHA)
            self.assertEqual(loaded_revision["artifact_sha256"], revision["artifact_sha256"])
            self.assertEqual(loaded_admission["artifact_sha256"], admission["artifact_sha256"])

            bad = dict(admission)
            bad["payload"] = dict(admission["payload"], decision="DEFERRED")
            bad = artifact_contract.seal_artifact(bad)
            admission_path.write_text(json.dumps(bad), encoding="utf-8")
            with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(
                self.runner, "execution_source_identity", return_value=(SOURCE_SHA, SOURCE_SHA)
            ):
                with self.assertRaises(self.runner.BuildBoundaryError):
                    self.runner._build_authorization()

    def test_build_bundle_is_strict_v1_and_contains_no_cloudflare_identity(self):
        _revision, admission = _authorization_pair()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sealed = root / "site"
            sealed.mkdir()
            (sealed / "index.html").write_text("<html>ok</html>", encoding="utf-8")
            (sealed / "_astro").mkdir()
            (sealed / "_astro" / "app.js").write_text("ok", encoding="utf-8")
            snapshot = root / "snapshot.json"
            route = root / "routes.json"
            media = root / "media.json"
            gates = root / "gates.json"
            for path, content in (
                (snapshot, "{}"), (route, "{}"), (media, "{}"), (gates, "{}"),
            ):
                path.write_text(content, encoding="utf-8")
            with mock.patch.dict(os.environ, {
                "GITHUB_RUN_ID": "12345",
                "GITHUB_RUN_ATTEMPT": "1",
                "GITHUB_JOB": "build-validate",
            }, clear=False):
                artifact = self.runner._create_build_bundle_artifact(
                    transaction=admission["transaction"],
                    source_sha=SOURCE_SHA,
                    admission_digest=admission["artifact_sha256"],
                    sealed_root=sealed,
                    content_fingerprint="a" * 64,
                    snapshot_path=snapshot,
                    route_manifest=route,
                    media_manifest=media,
                    local_gate_evidence=gates,
                    prior_index_binding=_prior_index_binding(),
                )
            artifact_contract.validate_artifact(artifact)
            serialized = json.dumps(artifact, sort_keys=True)
            self.assertNotIn("candidate_version", serialized)
            self.assertNotIn("deployment_id", serialized)
            self.assertEqual([entry["path"] for entry in artifact["payload"]["files"]],
                             ["_astro/app.js", "index.html"])

    def test_scrubbed_environment_removes_credentials_only_during_build(self):
        env = {
            "CLOUDFLARE_API_TOKEN": "cf-secret",
            "CLOUDFLARE_ACCOUNT_ID": "account",
            "GITHUB_TOKEN": "gh-secret",
            "SOME_PASSWORD": "pw",
            "MAHOON_SNAPSHOT_REVISION": "88",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with self.runner._scrubbed_build_environment():
                for key in ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "GITHUB_TOKEN", "SOME_PASSWORD"):
                    self.assertNotIn(key, os.environ)
                self.assertEqual(os.environ["MAHOON_SNAPSHOT_REVISION"], "88")
            for key, value in env.items():
                self.assertEqual(os.environ[key], value)

    def test_synthetic_build_validate_exports_once_seals_bundle_and_never_imports_cloudflare(self):
        revision, admission = _authorization_pair()
        digest = "a" * 64

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            revision_path = root / "revision.json"
            admission_path = root / "admission.json"
            revision_path.write_text(json.dumps(revision), encoding="utf-8")
            admission_path.write_text(json.dumps(admission), encoding="utf-8")
            (root / "publisher-state").mkdir()
            (root / "publisher-state" / "current-accepted-route-manifest.json").write_text(
                json.dumps({"routes": ["/"]}), encoding="utf-8"
            )

            def fake_export(snapshot_path):
                snapshot_path.parent.mkdir(parents=True, exist_ok=True)
                snapshot_path.write_text('{"posts":[]}', encoding="utf-8")
                return {"contract": "PUBLISHED_CONTENT_DELTA_CONTRACT_V2", "count": 0, "posts": []}, digest

            def fake_media(_posts, store, index_path=None):
                self.assertIsNotNone(index_path)
                self.assertEqual(PRIOR_INDEX_RAW, Path(index_path).read_bytes())
                Path(store).mkdir(parents=True, exist_ok=True)
                manifest = Path("runner-build/current-media-manifest.json")
                index = Path("runner-build/immutable-media-index.json")
                manifest.parent.mkdir(parents=True, exist_ok=True)
                manifest.write_text('{"records":[]}', encoding="utf-8")
                index.write_text('{"entries":[]}', encoding="utf-8")
                return {"manifest": str(manifest), "index": str(index), "store": str(store)}

            def fake_routes(_posts, _source, output):
                Path(output).parent.mkdir(parents=True, exist_ok=True)
                Path(output).write_text(json.dumps({"routes": ["/"], "route_count": 1}), encoding="utf-8")
                return {"routes": ["/"]}

            def fake_build(out, _snapshot):
                # These must never reach build subprocesses.
                self.assertNotIn("CLOUDFLARE_API_TOKEN", os.environ)
                self.assertNotIn("GITHUB_TOKEN", os.environ)
                Path(out).mkdir(parents=True, exist_ok=True)
                (Path(out) / "index.html").write_text("<html>sealed</html>", encoding="utf-8")
                media_manifest = Path("runner-build/production-media-manifest.json")
                media_manifest.parent.mkdir(parents=True, exist_ok=True)
                media_manifest.write_text('{"records":[]}', encoding="utf-8")
                return {"output": str(out), "files": 1}

            env = {
                "MAHOON_REVISION_RESOLUTION_ARTIFACT": str(revision_path),
                "MAHOON_ADMISSION_RECEIPT_ARTIFACT": str(admission_path),
                "MAHOON_PUBLISHED_CONTENT_SNAPSHOT": "runner-evidence/current-v2-snapshot.json",
                "MAHOON_BUILD_OUTPUT": "runner-build/static",
                "MAHOON_BUILD_BUNDLE_OUTPUT": "runner-evidence/v1-build-bundle.json",
                "GITHUB_RUN_ID": "12345",
                "GITHUB_RUN_ATTEMPT": "1",
                "GITHUB_JOB": "build-validate",
                "GITHUB_REPOSITORY": "synthetic-owner/tg-cms",
                "CLOUDFLARE_API_TOKEN": "must-not-inherit",
                "GITHUB_TOKEN": "must-not-inherit",
            }

            old_cwd = os.getcwd()
            try:
                os.chdir(root)
                with mock.patch.dict(os.environ, env, clear=False), \
                     mock.patch.object(self.runner, "execution_source_identity", return_value=(SOURCE_SHA, SOURCE_SHA)), \
                     mock.patch.object(self.runner, "GitRepositoryReader") as index_reader, \
                     mock.patch.object(self.runner, "export_content", side_effect=fake_export) as export_call, \
                     mock.patch.object(self.runner, "bootstrap_media", side_effect=fake_media), \
                     mock.patch.object(self.runner, "build_candidate_route_manifest", side_effect=fake_routes), \
                     mock.patch.object(self.runner.static_build_adapter, "build", side_effect=fake_build), \
                     mock.patch.object(self.runner.static_build_adapter, "validate", return_value={"PASS": True}), \
                     mock.patch.object(self.runner, "evaluate_local_candidate", return_value={"measured": True, "PASS": True, "gates": {}}):
                    index_reader.return_value.read_immutable_media_index.return_value = {
                        **_prior_index_binding(), "content_bytes": PRIOR_INDEX_RAW,
                    }
                    original_import = builtins.__import__

                    def guarded_import(name, *args, **kwargs):
                        if name == "publisher.cloudflare_wrangler":
                            raise AssertionError("BUILD_VALIDATE attempted Cloudflare mutation import")
                        if name == "publisher.transaction_journal":
                            raise AssertionError("BUILD_VALIDATE attempted journal import")
                        return original_import(name, *args, **kwargs)

                    with mock.patch("builtins.__import__", side_effect=guarded_import):
                        self.assertEqual(self.runner.run_build_validate(), 0)

                export_call.assert_called_once()
                bundle_path = root / "runner-evidence/v1-build-bundle.json"
                bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
                artifact_contract.validate_artifact(
                    bundle,
                    expected_transaction=admission["transaction"],
                    expected_source_sha=SOURCE_SHA,
                    expected_parents={"admission_receipt_sha256": admission["artifact_sha256"]},
                )
                self.assertEqual(bundle["payload"]["content_fingerprint"], digest)
                self.assertTrue((root / "runner-evidence/publisher-sealed" / digest / "artifact-seal.json").is_file())
            finally:
                os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()
