"""Read-only proof observations for the sealed publisher V1 lifecycle."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Protocol
from urllib.parse import urlsplit

from publisher import artifact_contract as contracts
from publisher import artifact_transport as transport
from publisher import effective_mutation_result as effective_result


class ObservationRejected(ValueError):
    """A read-only observation is absent, malformed, or inconsistent."""


_SECRET_FIELD = re.compile(r"(?:token|secret|password|authorization|credential|api[_-]?key)", re.I)


def _reject_secret_fields(value: object) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if isinstance(key, str) and _SECRET_FIELD.search(key):
                raise ObservationRejected("observation contains a secret-like field")
            _reject_secret_fields(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _reject_secret_fields(child)


class ReadOnlyObservationBackend(Protocol):
    def collect(self, context: Mapping[str, Any]) -> Mapping[str, Any]: ...


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _persist_evidence(root: Path, files: Mapping[str, object]) -> dict[str, str]:
    hashes = {}
    for name, value in files.items():
        if Path(name).name != name or not name.endswith(".json"):
            raise ObservationRejected("evidence filename is unsafe")
        raw = _canonical(value)
        target = root / name
        with target.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        stored = target.read_bytes()
        if stored != raw:
            raise ObservationRejected("stored observation evidence changed")
        hashes[name] = _sha(stored)
    return hashes


def _bool_gate(summary: Mapping[str, Any], key: str) -> bool:
    gates = summary.get("gates")
    item = gates.get(key) if isinstance(gates, Mapping) else None
    return isinstance(item, Mapping) and item.get("measured") is True and item.get("PASS") is True


def _remote_gates(crawler: Mapping[str, Any], browser: Mapping[str, Any], expected_routes: int) -> dict[str, bool]:
    present = crawler.get("present_route_count")
    zero = browser.get("zero_origin")
    requests = zero.get("requests") if isinstance(zero, Mapping) else None
    counts_ok = isinstance(requests, Mapping) and set(requests) == {
        "content_api", "media_api", "workers_dev_content", "telegram", "search_backend",
    } and all(type(value) is int and value == 0 for value in requests.values())
    return {
        "full_route_crawl": crawler.get("measured") is True
            and crawler.get("expected_route_count") == expected_routes
            and present == expected_routes and crawler.get("missing_routes") == []
            and _bool_gate(crawler, "remote_route_parity"),
        "content_parity": _bool_gate(crawler, "remote_content_parity"),
        "listing_uniqueness": _bool_gate(crawler, "remote_listing_uniqueness"),
        "category_parity": _bool_gate(crawler, "remote_category_parity"),
        "latest_parity": _bool_gate(crawler, "remote_latest_parity"),
        "seo": _bool_gate(crawler, "remote_seo")
            and crawler.get("post_jsonld_missing") == 0
            and crawler.get("duplicate_canonicals") == 0,
        "media": _bool_gate(crawler, "remote_media")
            and crawler.get("remote_reader_media_dependencies") == 0,
        "visual": isinstance(browser.get("visual"), Mapping)
            and browser["visual"].get("PASS") is True,
        "zero_origin_runtime": isinstance(zero, Mapping) and zero.get("PASS") is True
            and counts_ok and crawler.get("workers_dev_leaks") == 0,
    }


def _zero_origin(browser: Mapping[str, Any]) -> dict:
    source = browser.get("zero_origin")
    if not isinstance(source, Mapping) or not isinstance(source.get("requests"), Mapping):
        raise ObservationRejected("zero-origin runtime observation is missing")
    counts = source["requests"]
    expected = {"content_api", "media_api", "workers_dev_content", "telegram", "search_backend"}
    if set(counts) != expected or any(type(v) is not int or v < 0 for v in counts.values()):
        raise ObservationRejected("zero-origin request counters are malformed")
    pages = source.get("public_pages_checked")
    if type(pages) is not int or pages < 1:
        raise ObservationRejected("zero-origin public page count is invalid")
    passed = source.get("PASS") is True and all(value == 0 for value in counts.values())
    if not passed:
        raise ObservationRejected("zero-origin gate failed; authoritative proof is not emitted")
    return {"public_pages_checked": pages, "requests": dict(counts), "PASS": True}


def _read_inputs(paths: Mapping[str, str | Path], kinds: Mapping[str, str | None],
                 reference_paths: list[str | Path] | None = None) -> dict[str, dict]:
    raw = {}
    for name, kind in kinds.items():
        try:
            value = json.loads(Path(paths[name]).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ObservationRejected("sealed proof input is unreadable") from exc
        raw[name] = value
    extras = transport.read_references(reference_paths or [])
    refs = transport.references(*raw.values(), *extras.values())
    checked = {name: contracts.validate_artifact(value, referenced_artifacts=refs)
               for name, value in raw.items()}
    if any(kind is not None and checked[name]["artifact_type"] != kind
           for name, kind in kinds.items()):
        raise ObservationRejected("proof input artifact type mismatch")
    return checked


def _check_pair(intent: dict, result: dict, operation: str, bundle: dict,
                referenced_artifacts: Mapping[str, Any] | None = None) -> None:
    refs = transport.references(*(referenced_artifacts or {}).values(), bundle, intent, result)
    applied = effective_result.validate_effective_applied_result(
        result, intent, referenced_artifacts=refs,
    )
    if (intent["payload"]["operation_name"] != operation
            or intent["payload"]["build_bundle_sha256"] != bundle["artifact_sha256"]
            or applied["payload"]["build_bundle_sha256"] != bundle["artifact_sha256"]
            or applied["payload"]["result_state"] != "APPLIED"):
        raise ObservationRejected(f"{operation} must have an APPLIED result for this build")


def _input_files_match(bundle: Mapping[str, Any], *, sealed_root: str | Path,
                       snapshot: str | Path, routes: str | Path, media: str | Path,
                       local_gates: str | Path | None = None) -> None:
    payload = bundle["payload"]
    unresolved_root = Path(sealed_root)
    if unresolved_root.is_symlink():
        raise ObservationRejected("sealed build root is invalid")
    root = unresolved_root.resolve(strict=True)
    if not root.is_dir():
        raise ObservationRejected("sealed build root is invalid")
    expected = {item["path"]: (item["size_bytes"], item["sha256"])
                for item in payload["files"]}
    actual = {}
    for item in root.rglob("*"):
        if item.is_symlink():
            raise ObservationRejected("sealed build contains a symlink")
        if item.is_file():
            rel = item.relative_to(root).as_posix()
            raw = item.read_bytes()
            actual[rel] = (len(raw), _sha(raw))
    if actual != expected:
        raise ObservationRejected("sealed build files differ from build bundle")
    checks = ((snapshot, "snapshot_sha256"), (routes, "route_manifest_sha256"),
              (media, "media_manifest_sha256"))
    for path, field in checks:
        if _sha(Path(path).read_bytes()) != payload[field]:
            raise ObservationRejected(f"build input {field} digest mismatch")
    if local_gates is not None and _sha(Path(local_gates).read_bytes()) != payload["local_gate_evidence_sha256"]:
        raise ObservationRejected("local gate evidence digest mismatch")


class RuntimeObservationBackend:
    """Run the existing GET-only crawler/browser against the sealed build lineage."""

    def __init__(self, *, stage: str, base_url: str, evidence_root: str | Path,
                 sealed_root: str | Path, snapshot: str | Path, routes: str | Path,
                 media: str | Path, local_gates: str | Path | None = None):
        if stage not in {"pre-promotion", "production"}:
            raise ValueError("observation stage is invalid")
        parts = urlsplit(base_url)
        if ((parts.scheme, (parts.hostname or "").lower(), parts.path, parts.query, parts.fragment) not in {
                ("https", "mahoonartmagazine.ir", "", "", ""),
                ("https", "mahoonartmagazine.ir", "/", "", ""),
            } or parts.port is not None or parts.username or parts.password):
            raise ValueError("observation origin is not the approved public site")
        self.stage, self.base_url, self.evidence_root = stage, base_url.rstrip("/"), Path(evidence_root)
        self.sealed_root, self.snapshot = Path(sealed_root), Path(snapshot)
        self.routes, self.media, self.local_gates = Path(routes), Path(media), local_gates

    def collect(self, context: Mapping[str, Any]) -> Mapping[str, Any]:
        bundle = context["build_bundle"]
        _input_files_match(bundle, sealed_root=self.sealed_root, snapshot=self.snapshot,
                           routes=self.routes, media=self.media, local_gates=self.local_gates)
        self.evidence_root.parent.mkdir(parents=True, exist_ok=True)
        stage_root = Path(tempfile.mkdtemp(prefix=f".{self.evidence_root.name}.stage-",
                                           dir=self.evidence_root.parent))
        try:
            from publisher import cloudflare_wrangler
            worker = context["transaction"]["worker"]
            live = cloudflare_wrangler.active_deployment(worker)
            versions = live.get("versions")
            if not isinstance(versions, list) or not all(
                    isinstance(item, Mapping) and isinstance(item.get("version_id"), str)
                    and type(item.get("percentage")) is int
                    and 0 <= item["percentage"] <= 100 for item in versions):
                raise ObservationRejected("read-only deployment state is malformed")
            split = {item["version_id"]: item["percentage"] for item in versions}
            if len(split) != len(versions) or sum(split.values()) != 100:
                raise ObservationRejected("read-only deployment split is ambiguous")
            candidate = context["candidate_identity"]
            candidate_id, baseline_id = candidate["candidate_version_id"], candidate["baseline_version_id"]
            promotion_id = (context.get("promotion_deployment_id")
                            or candidate.get("zero_percent_deployment_id"))
            expected_id = (context.get("expected_deployment_id")
                           or (candidate.get("zero_percent_deployment_id") if self.stage == "pre-promotion"
                               else context.get("promotion_deployment_id")))
            percentages = ((0, 100) if self.stage == "pre-promotion" else (100, 0))
            deployment_id = live.get("id")
            identity_pass = (
                isinstance(deployment_id, str) and deployment_id == expected_id
                and split.get(candidate_id, 0) == percentages[0]
                and split.get(baseline_id, 0) == percentages[1]
                and set(split) <= {candidate_id, baseline_id}
            )
            identity = {"candidate_version_id": candidate_id,
                        "baseline_version_id": baseline_id,
                        "promotion_deployment_id": deployment_id or "unavailable",
                        "candidate_percentage": split.get(candidate_id, 0),
                        "baseline_percentage": split.get(baseline_id, 0),
                        "PASS": identity_pass}
            if self.stage == "pre-promotion" and not identity_pass:
                raise ObservationRejected("zero-percent deployment readback does not match sealed result")
            crawl_root = stage_root / "crawl"
            env = {}
            for key, value in os.environ.items():
                upper = key.upper()
                if (upper.startswith("CLOUDFLARE_") or upper in {"GITHUB_TOKEN", "GH_TOKEN"}
                        or any(marker in upper for marker in ("TOKEN", "SECRET", "PASSWORD",
                                                              "CREDENTIAL", "AUTHORIZATION"))):
                    continue
                env[key] = value
            env.update({
                "PYTHONDONTWRITEBYTECODE": "1",
                "MAHOON_CRAWL_OUTPUT": str(crawl_root), "MAHOON_CRAWL_BASE": self.base_url,
                "MAHOON_PRODUCTION_ORIGIN": self.base_url,
                "MAHOON_OVERRIDE_WORKER": context["transaction"]["worker"],
                "MAHOON_WORKER": context["transaction"]["worker"],
                "MAHOON_CANDIDATE_VERSION": context["candidate_identity"]["candidate_version_id"],
                "MAHOON_REMOTE_CRAWL_WORKERS": "8",
                "MAHOON_ASSETS_DIRECTORY": str(self.sealed_root),
                "MAHOON_ROUTE_MANIFEST": str(self.routes),
                "MAHOON_PUBLISHED_CONTENT_SNAPSHOT": str(self.snapshot),
                "MAHOON_MEDIA_MANIFEST": str(self.media),
            })
            if self.stage == "production":
                env["MAHOON_DISABLE_VERSION_OVERRIDE"] = "1"
            crawler_path = Path(__file__).with_name("candidate_override_crawl.py")
            crawler = subprocess.run([sys.executable, str(crawler_path)], cwd=Path(__file__).parents[2],
                                     env=env, capture_output=True, timeout=3600, check=False)
            if crawler.returncode:
                raise ObservationRejected("read-only crawler did not complete")
            crawl_out = crawl_root / "production-override-crawl"
            summary = json.loads((crawl_out / "production-override-crawl-summary.json").read_text(encoding="utf-8"))
            state = json.loads((crawl_out / "production-override-crawl-state.json").read_text(encoding="utf-8"))
            browser_path = stage_root / "browser.json"
            command = ["node", str(Path(__file__).with_name("prepromotion_browser_gate.mjs")),
                       "--base-url", self.base_url, "--snapshot", str(self.snapshot),
                       "--routes", str(self.routes), "--output", str(browser_path)]
            if self.stage == "pre-promotion":
                command.extend(["--candidate-version", context["candidate_identity"]["candidate_version_id"]])
            browser_proc = subprocess.run(command, cwd=Path(__file__).parents[2], env=env,
                                          capture_output=True, timeout=600, check=False)
            if browser_proc.returncode:
                raise ObservationRejected("read-only browser observation did not complete")
            browser = json.loads(browser_path.read_text(encoding="utf-8"))
            return {"crawler": summary, "route_state": state, "browser": browser,
                    "identity_confirmation": identity,
                    "directory": stage_root}
        except Exception:
            shutil.rmtree(stage_root, ignore_errors=True)
            raise


def _observation_parts(raw: object, expected_routes: int, evidence_root: Path) -> tuple[dict, dict, dict, dict]:
    if not isinstance(raw, Mapping) or set(raw) != {
        "crawler", "route_state", "browser", "identity_confirmation", "directory",
    }:
        raise ObservationRejected("read-only observation result is incomplete")
    crawler, state, browser = raw["crawler"], raw["route_state"], raw["browser"]
    if not all(isinstance(value, Mapping) for value in (crawler, state, browser)):
        raise ObservationRejected("read-only observation evidence must be objects")
    _reject_secret_fields(raw)
    gates = _remote_gates(crawler, browser, expected_routes)
    zero = _zero_origin(browser)
    return dict(crawler), dict(state), dict(browser), {"gates": gates, "zero": zero}


def _evidence(root: Path, crawler: dict, state: dict, browser: dict,
              identity: Mapping[str, Any]) -> tuple[dict, Path]:
    hashes = _persist_evidence(root, {"crawler-summary.json": {
                                          "summary": crawler,
                                          "deployment_readback": dict(identity),
                                      },
                                      "crawler-route-state.json": state,
                                      "browser-observations.json": browser})
    return hashes, root


def execute_pre_promotion_observation(*, build_path: str | Path, deploy_intent_path: str | Path,
                                      deploy_result_path: str | Path, sealed_root: str | Path,
                                      snapshot_path: str | Path, route_manifest_path: str | Path,
                                      media_manifest_path: str | Path, evidence_dir: str | Path,
                                      output_path: str | Path, backend: ReadOnlyObservationBackend,
                                      reference_paths: list[str | Path] | None = None) -> dict:
    values = _read_inputs({"build": build_path, "intent": deploy_intent_path,
                           "result": deploy_result_path}, {"build": "build_bundle",
                           "intent": "mutation_intent", "result": None},
                          reference_paths)
    build, intent, result = values["build"], values["intent"], values["result"]
    _check_pair(intent, result, "deploy_zero_percent", build,
                transport.references(*values.values(), *transport.read_references(reference_paths or []).values()))
    refs = transport.read_references(reference_paths or [])
    full_refs = transport.references(*values.values(), *refs.values())
    candidate = {
        "worker": build["transaction"]["worker"],
        "candidate_version_id": intent["payload"]["desired_state"]["candidate_version_id"],
        "baseline_version_id": intent["payload"]["desired_state"]["baseline_version_id"],
        "zero_percent_deployment_id": result["payload"]["readback_reference"]["resource_id"],
        "content_fingerprint": build["payload"]["content_fingerprint"],
    }
    if intent["transaction"] != build["transaction"] or result["transaction"] != build["transaction"]:
        raise ObservationRejected("deploy transaction does not match build")
    _input_files_match(build, sealed_root=sealed_root, snapshot=snapshot_path,
                       routes=route_manifest_path, media=media_manifest_path)
    target = Path(evidence_dir)
    if target.exists():
        raise FileExistsError("evidence destination already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.stage-", dir=target.parent))
    completed = False
    try:
        context = {"stage": "pre-promotion", "transaction": build["transaction"],
                   "source_sha": build["producer"]["source_sha"], "build_bundle": build,
                   "candidate_identity": candidate, "deploy_intent": intent,
                   "deploy_result": result, "sealed_root": str(Path(sealed_root).resolve()),
                   "snapshot_path": str(Path(snapshot_path).resolve()),
                   "route_manifest_path": str(Path(route_manifest_path).resolve()),
                   "media_manifest_path": str(Path(media_manifest_path).resolve()),
                   "expected_deployment_id": candidate["zero_percent_deployment_id"]}
        raw = backend.collect(context)
        expected_routes = json.loads(Path(route_manifest_path).read_text(encoding="utf-8")).get("route_count")
        if type(expected_routes) is not int or expected_routes < 1:
            raise ObservationRejected("sealed route manifest is invalid")
        crawler, state, browser, derived = _observation_parts(raw, expected_routes, staging)
        identity = raw.get("identity_confirmation") if isinstance(raw, Mapping) else None
        if not isinstance(identity, Mapping):
            raise ObservationRejected("zero-percent deployment readback is unavailable")
        evidence, _runtime_dir = _evidence(staging, crawler, state, browser, identity)
        remote = {"crawler_evidence_sha256": evidence["crawler-summary.json"],
                  "browser_evidence_sha256": evidence["browser-observations.json"],
                  "gates": derived["gates"], "PASS": all(derived["gates"].values())}
        zero = derived["zero"]
        remote_path, zero_path = staging / "remote-contract.json", staging / "zero-origin-contract.json"
        remote_path.write_bytes(_canonical(remote)); zero_path.write_bytes(_canonical(zero))
        # Delegate authoritative sealing and lineage checks to the accepted A5.1 producer.
        from publisher.workflow_stage_cli import create_pre_promotion_proof
        proof = create_pre_promotion_proof(build_path, deploy_intent_path, deploy_result_path,
                                           remote_path, zero_path, [*map(str, reference_paths or [])])
        proof = contracts.validate_artifact(proof, referenced_artifacts=full_refs)
        if proof["artifact_type"] != "pre_promotion_proof_evidence":
            raise ObservationRejected("accepted pre-promotion proof type mismatch")
        identity = raw.get("identity_confirmation")
        if not isinstance(identity, Mapping) or set(identity) != {
            "candidate_version_id", "baseline_version_id", "promotion_deployment_id",
            "candidate_percentage", "baseline_percentage", "PASS",
        } or (identity["candidate_version_id"] != candidate["candidate_version_id"]
              or identity["baseline_version_id"] != candidate["baseline_version_id"]
              or identity["promotion_deployment_id"] != candidate["zero_percent_deployment_id"]
              or identity["candidate_percentage"] != 0 or identity["baseline_percentage"] != 100
              or identity["PASS"] is not True):
            raise ObservationRejected("zero-percent deployment identity readback mismatch")
        generated = raw.get("directory") if isinstance(raw, Mapping) else None
        if isinstance(generated, Path) and generated.is_dir():
            shutil.rmtree(generated, ignore_errors=True)
        if target.exists():
            raise FileExistsError("evidence destination appeared during observation")
        staging.rename(target)
        try:
            transport.write_artifact(output_path, proof,
                                     expected_type="pre_promotion_proof_evidence",
                                     referenced_artifacts=full_refs)
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise
        completed = True
        return {"status": "PASS" if proof["payload"]["PASS"] else "FAIL",
                "artifact_sha256": proof["artifact_sha256"], "evidence_dir": str(target),
                "crawler_evidence_sha256": evidence["crawler-summary.json"],
                "browser_evidence_sha256": evidence["browser-observations.json"],
                "gates": derived["gates"]}
    finally:
        if not completed:
            shutil.rmtree(staging, ignore_errors=True)


class _ProductionAdapter:
    def __init__(self, backend: ReadOnlyObservationBackend, evidence_dir: Path,
                 expected_routes: int, local: Mapping[str, Any]):
        self.backend, self.evidence_dir, self.expected_routes = backend, evidence_dir, expected_routes
        self.local = dict(local)

    def collect(self, context: Mapping[str, Any]) -> Mapping[str, Any]:
        raw = self.backend.collect({**context, "stage": "production"})
        crawler, state, browser, derived = _observation_parts(raw, self.expected_routes, self.evidence_dir)
        identity = raw.get("identity_confirmation") if isinstance(raw, Mapping) else None
        if not isinstance(identity, Mapping):
            raise ObservationRejected("production deployment readback is unavailable")
        hashes, _ = _evidence(self.evidence_dir, crawler, state, browser, identity)
        generated = raw.get("directory")
        if isinstance(generated, Path) and generated.is_dir():
            shutil.rmtree(generated, ignore_errors=True)
        gates = dict(derived["gates"])
        pinning = crawler.get("remote_crawler_version_pinning")
        gates["route_parity"] = gates["full_route_crawl"]
        gates["page_attribution"] = isinstance(pinning, Mapping) and pinning.get("PASS") is True \
            and pinning.get("override_sent") == "NO" and pinning.get("attribution_required") == "YES"
        gates.pop("full_route_crawl")
        gates.pop("zero_origin_runtime")
        rss = state.get("routes", {}).get("/rss.xml", {}) if isinstance(state.get("routes"), Mapping) else {}
        robots = state.get("routes", {}).get("/robots.txt", {}) if isinstance(state.get("routes"), Mapping) else {}
        gates["seo"] = gates.pop("seo") and robots.get("robots_sitemap") is True \
            and rss.get("http_status") == 200 and rss.get("content_type") in {
                "application/rss+xml", "application/xml", "text/xml"}
        gates["zero_origin"] = derived["gates"]["zero_origin_runtime"]
        checks = {item.get("name"): item for item in browser.get("checks", []) if isinstance(item, Mapping)}
        routes = state.get("routes", {})
        gates["admin_panel"] = checks.get("admin-shell", {}).get("visual_pass") is True \
            and routes.get("/admin", {}).get("http_status") == 200 \
            and routes.get("/admin/analytics", {}).get("http_status") == 200
        if not isinstance(identity, Mapping) or set(identity) != {
            "candidate_version_id", "baseline_version_id", "promotion_deployment_id",
            "candidate_percentage", "baseline_percentage", "PASS",
        }:
            raise ObservationRejected("production deployment readback is missing or malformed")
        if identity.get("PASS") is not True:
            # All production gates remain explicit, but a failed identity cannot masquerade as PASS.
            identity = dict(identity, PASS=False)
        return {
            "local": self.local,
            "identity_confirmation": dict(identity),
            "production": {"crawler_evidence_sha256": hashes["crawler-summary.json"],
                           "browser_evidence_sha256": hashes["browser-observations.json"],
                           "route_state_evidence_sha256": hashes["crawler-route-state.json"],
                           "gates": {name: gates[name] for name in contracts.PRODUCTION_GATES}},
        }


def execute_production_observation(*, artifact_paths: Mapping[str, str | Path],
                                   sealed_root: str | Path, snapshot_path: str | Path,
                                   route_manifest_path: str | Path, media_manifest_path: str | Path,
                                   local_gates_path: str | Path, evidence_dir: str | Path,
                                   output_path: str | Path, backend: ReadOnlyObservationBackend,
                                   reference_paths: list[str | Path] | None = None) -> dict:
    kinds = {"build": "build_bundle", "upload_intent": "mutation_intent",
             "upload_result": None, "deploy_intent": "mutation_intent",
             "deploy_result": None, "preproof": "pre_promotion_proof_evidence",
             "promote_intent": "mutation_intent", "promote_result": None}
    values = _read_inputs(artifact_paths, kinds, reference_paths)
    all_refs = transport.references(*values.values(),
                                    *transport.read_references(reference_paths or []).values())
    build = values["build"]
    for operation in ("upload_version", "deploy_zero_percent", "promote"):
        intent, result = values[f"{operation.split('_')[0]}_intent"], values[f"{operation.split('_')[0]}_result"]
        if operation == "deploy_zero_percent":
            intent, result = values["deploy_intent"], values["deploy_result"]
        elif operation == "upload_version":
            intent, result = values["upload_intent"], values["upload_result"]
        else:
            intent, result = values["promote_intent"], values["promote_result"]
        _check_pair(intent, result, operation, build, all_refs)
    refs = all_refs
    _input_files_match(build, sealed_root=sealed_root, snapshot=snapshot_path,
                       routes=route_manifest_path, media=media_manifest_path,
                       local_gates=local_gates_path)
    route_count = json.loads(Path(route_manifest_path).read_text(encoding="utf-8")).get("route_count")
    if type(route_count) is not int or route_count < 1:
        raise ObservationRejected("sealed route manifest is invalid")
    target = Path(evidence_dir)
    if target.exists():
        raise FileExistsError("evidence destination already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.stage-", dir=target.parent))
    completed = False
    try:
        local_data = json.loads(Path(local_gates_path).read_text(encoding="utf-8"))
        local_gates = local_data.get("gates")
        if not isinstance(local_gates, Mapping) or set(local_gates) != set(contracts.LOCAL_GATES) \
                or any(type(value) is not bool for value in local_gates.values()):
            raise ObservationRejected("sealed local gate map is invalid")
        local = {"evidence_sha256": build["payload"]["local_gate_evidence_sha256"],
                 "gates": dict(local_gates)}
        class RuntimeWithIdentity:
            def collect(self, context):
                raw = backend.collect(context)
                if not isinstance(raw, Mapping):
                    raise ObservationRejected("production observation is malformed")
                return raw
        adapter = _ProductionAdapter(RuntimeWithIdentity(), staging, route_count, local)
        # Existing A5.3 executor validates all lineage, gates, and emits the authoritative proof.
        from publisher.production_proof_runner import create_production_proof
        proof = create_production_proof(
            build_bundle=values["build"], upload_intent=values["upload_intent"],
            upload_result=values["upload_result"], deploy_intent=values["deploy_intent"],
            deploy_result=values["deploy_result"], pre_promotion_proof=values["preproof"],
            promote_intent=values["promote_intent"], promote_result=values["promote_result"],
            backend=adapter,
            referenced_artifacts=refs,
        )
        proof = contracts.validate_artifact(proof, referenced_artifacts=refs)
        if proof["artifact_type"] != "proof_evidence":
            raise ObservationRejected("accepted production proof type mismatch")
        # Runtime backend evidence has already been staged; only its private working dir is discarded.
        if target.exists():
            raise FileExistsError("evidence destination appeared during observation")
        staging.rename(target)
        try:
            transport.write_artifact(output_path, proof, expected_type="proof_evidence",
                                     referenced_artifacts=refs)
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise
        completed = True
        return {"status": proof["payload"]["proof_state"],
                "artifact_sha256": proof["artifact_sha256"], "evidence_dir": str(target)}
    finally:
        if not completed:
            shutil.rmtree(staging, ignore_errors=True)
