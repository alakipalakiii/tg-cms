"""Single entry point for the MAHOON publisher modes.

The network/build/upload adapters are deliberately fail-closed until every
candidate artifact is produced by this same runner.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
import urllib.request
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from publisher.core import fingerprint
from publisher import static_build_adapter
from publisher import deployment
from publisher.rollback import automatic_rollback
from publisher.post_deploy_validator import capture_zero_origin, validate_public, validate_zero_origin

API = os.environ.get("MAHOON_PUBLIC_CONTENT_API", "https://api.mahoonartmagazine.ir/posts-full-public-v1?limit=2000")
STATE = Path(os.environ.get("MAHOON_PUBLISHER_STATE", "publisher-state/production-content-fingerprint.json"))


class PublisherStageError(RuntimeError):
    def __init__(self, stage: str, code: str, message: str, **details):
        super().__init__(message)
        self.stage, self.code, self.details = stage, code, details


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sanitize(message: str) -> str:
    message = re.sub(r"(?i)(authorization|token|jwt|cookie|secret)\s*[:=]\s*[^\s,;]+", r"\1=[REDACTED]", str(message))
    return message.replace("CLOUDFLARE_API_TOKEN", "[REDACTED_SECRET]")[:500]


def write_safe_error(stage: str, code: str, exc: Exception, candidate: str | None,
                     deployment_id: str | None, **details) -> dict:
    record = {"timestamp": now(), "failing_stage": stage, "failure_code": code,
              "exception_class": type(exc).__name__, "sanitized_message": sanitize(str(exc)),
              "candidate_version": candidate, "deployment_id": deployment_id,
              "validation_artifact_id": "runner-evidence/candidate-validation.json",
              "retry_count": details.pop("retry_count", 0), **details}
    Path("runner-evidence").mkdir(parents=True, exist_ok=True)
    Path("runner-evidence/publisher-safe-error-contract.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"failure_code": code, "failing_stage": stage, "message": record["sanitized_message"]}, ensure_ascii=False), file=sys.stderr)
    return record


def public_path(route: str) -> str:
    route = "/" + route.lstrip("/")
    if route == "/index.html":
        return "/"
    if route.endswith("index.html"):
        logical = "/" + route.removeprefix("/").removesuffix("index.html").rstrip("/") + "/"
    else:
        logical = route
    return quote(logical, safe="/%:@!$&'()*+,;=-._~")


def export_content() -> tuple[dict, str]:
    request = urllib.request.Request(API, headers={"Accept": "application/json", "User-Agent": "MAHOON-M9-PUBLISHER/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    posts = payload.get("posts", payload if isinstance(payload, list) else [])
    stable = [{key: value for key, value in post.items() if key not in {"view_count", "last_viewed_at"}}
              for post in sorted(posts, key=lambda item: int(item.get("id", 0)))]
    exported = {"contract": "PUBLISHED_CONTENT_DELTA_CONTRACT_V2", "count": len(stable), "posts": stable}
    return exported, fingerprint(exported)


def main() -> int:
    mode = os.environ.get("PUBLISHER_MODE", "CHECK_ONLY").upper()
    if mode not in {"CHECK_ONLY", "PROOF_ZERO_PERCENT", "PUBLISH"}:
        print("PUBLISHER_MODE_INVALID", file=sys.stderr)
        return 2
    exported, digest = export_content()
    state_fingerprint = json.loads(STATE.read_text(encoding="utf-8")).get("fingerprint") if STATE.exists() else None
    previous = (os.environ.get("PUBLISHER_EXPECTED_FINGERPRINT") or state_fingerprint) if mode == "CHECK_ONLY" else state_fingerprint
    unchanged = previous == digest
    print(json.dumps({"mode": mode, "count": exported["count"], "fingerprint": digest,
                      "unchanged": unchanged, "state_present": STATE.exists()}, ensure_ascii=False))
    if mode == "CHECK_ONLY":
        return 0 if unchanged else 3
    out = Path(os.environ.get("MAHOON_BUILD_OUTPUT", "runner-build/static"))
    build = static_build_adapter.build(out)
    media_manifest = Path("runner-build/production-media-manifest.json")
    route_manifest = Path("runner-build/published-route-manifest.json")
    media_manifest.parent.mkdir(parents=True, exist_ok=True)
    media_manifest.write_text(Path("publisher-state/production-media-manifest.json").read_text(encoding="utf-8"), encoding="utf-8")
    route_manifest.write_text(Path("publisher-state/published-route-manifest.json").read_text(encoding="utf-8"), encoding="utf-8")
    if not unchanged:
        delta = subprocess.run([sys.executable, "tools/publisher/delta_build_adapter.py", "--output", str(out), "--media-manifest", str(media_manifest), "--route-manifest", str(route_manifest)], text=True, capture_output=True)
        if delta.returncode != 0:
            print("PUBLISHER_DELTA_BUILD_FAILED", file=sys.stderr)
            return 11
    os.environ["MAHOON_MEDIA_MANIFEST"] = str(media_manifest)
    os.environ["MAHOON_ROUTE_MANIFEST"] = str(route_manifest)
    gate = static_build_adapter.validate(out)
    if not gate["PASS"]:
        print("PUBLISHER_LOCAL_GATE_FAILED", file=sys.stderr)
        return 12
    os.environ["MAHOON_ASSETS_DIRECTORY"] = str(out)
    os.environ["MAHOON_MEDIA_MANIFEST"] = str(media_manifest)
    os.environ["MAHOON_M9C_EVIDENCE"] = "runner-evidence"
    os.environ["MAHOON_CRAWL_OUTPUT"] = "runner-evidence/override-crawl"
    os.environ["MAHOON_WORKER"] = "mahoon-art-magazine"
    os.environ["MAHOON_CREATE_VERSION_ONLY"] = "1"
    proc = subprocess.run([sys.executable, "tools/publisher/cloudflare_direct_api.py"], text=True, capture_output=True)
    if proc.returncode != 0:
        safe_error = " ".join(line for line in proc.stderr.splitlines() if "TOKEN" not in line.upper() and "JWT" not in line.upper())[-1200:]
        print("PUBLISHER_DIRECT_API_ERROR: " + safe_error, file=sys.stderr)
        print("PUBLISHER_DIRECT_API_FAILED", file=sys.stderr)
        return 13
    version_id = None
    for line in reversed(proc.stdout.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        version_id = value.get("version_id") or version_id
    if not version_id:
        print("PUBLISHER_VERSION_ID_MISSING", file=sys.stderr)
        return 14
    pre_promotion = deployment.active_deployment()
    zero_percent_response = deployment.deployment(version_id, os.environ.get("MAHOON_SSR_VERSION", "b660c7ff-9042-4b4e-ab14-63211aa9c1f1"), 0, 100)
    zero_percent_deployment_id = (zero_percent_response.get("result") or {}).get("id") if isinstance(zero_percent_response, dict) else None
    os.environ["MAHOON_CANDIDATE_VERSION"] = version_id
    os.environ["MAHOON_ASSETS_DIRECTORY"] = str(out)
    crawl = subprocess.run([sys.executable, "tools/publisher/candidate_override_crawl.py"], text=True, capture_output=True)
    if crawl.returncode != 0:
        print("PUBLISHER_OVERRIDE_CRAWL_FAILED", file=sys.stderr)
        return 15
    summary_path = Path("runner-evidence/override-crawl/production-override-crawl-summary.json")
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    route_data = json.loads(route_manifest.read_text(encoding="utf-8"))
    expected_post_routes = sum(route.startswith("/post/") for route in route_data.get("routes", []))
    route_binding = (route_data.get("route_count") == len(route_data.get("routes", [])) and expected_post_routes == exported["count"])
    validated = route_binding and summary.get("html_final_200") == summary.get("html_routes") and summary.get("post_final_200") == summary.get("post_routes") and not any(summary.get(key, 0) for key in ("broken_critical_links", "orphan_posts", "duplicate_canonicals", "redirect_loops", "remote_reader_media_dependencies", "workers_dev_leaks", "preview_url_leaks", "post_seo_failures"))
    Path("runner-evidence/candidate-validation.json").parent.mkdir(parents=True, exist_ok=True)
    Path("runner-evidence/candidate-validation.json").write_text(json.dumps({"candidate_version": version_id, "fingerprint": digest, "build": build, "local_gate": gate, "override": summary, "route_binding": {"route_count": route_data.get("route_count"), "post_routes": expected_post_routes, "content_posts": exported["count"], "PASS": route_binding}, "PASS": validated}, ensure_ascii=False, indent=2), encoding="utf-8")
    if not validated:
        print("PUBLISHER_CANDIDATE_VALIDATION_FAILED", file=sys.stderr)
        return 16
    if mode == "PROOF_ZERO_PERCENT":
        proof_routes = [public_path(route) for route in json.loads(Path("publisher-state/published-route-manifest.json").read_text(encoding="utf-8")).get("routes", [])]
        override_public = validate_public(os.environ.get("MAHOON_PRODUCTION_ORIGIN", "https://mahoonartmagazine.ir"), proof_routes, version_id)
        override_zero = capture_zero_origin(os.environ.get("MAHOON_PRODUCTION_ORIGIN", "https://mahoonartmagazine.ir"), proof_routes, version_id)
        Path("runner-evidence/post-validator-override.json").write_text(json.dumps({"public": override_public, "zero_origin": override_zero, "route_count": len(proof_routes), "post_count": sum(p.startswith('/post/') for p in proof_routes), "PASS": override_public.get("PASS") and override_zero.get("PASS")}, ensure_ascii=False, indent=2), encoding="utf-8")
        if not (override_public.get("PASS") and override_zero.get("PASS")):
            details = (override_public.get("failure_details") or [{}])[0]
            error = PublisherStageError("POST_PROMOTION_ROUTE_CRAWL", "ERR_ROUTE_HTTP", "override validator failed", **details)
            write_safe_error(error.stage, error.code, error, version_id, zero_percent_deployment_id, expected="all canonical routes HTTP 200", observed=details)
            print("PUBLISHER_OVERRIDE_VALIDATOR_FAILED", file=sys.stderr)
            return 17
        print(json.dumps({"mode": mode, "candidate_version": version_id, "zero_percent": "PASS", "post_validator_override": "PASS"}))
        return 0
    if os.environ.get("MAHOON_PUBLISH_READY") != "YES":
        print("PUBLISHER_PROMOTION_BLOCKED: MAHOON_PUBLISH_READY=YES required", file=sys.stderr)
        return 18
    current_before = deployment.active_deployment()
    if current_before.get("id") != pre_promotion.get("id"):
        error = PublisherStageError("DEPLOYMENT_STATE_VERIFICATION", "ERR_DEPLOYMENT_STATE_DRIFT", "active deployment changed before promotion", expected=pre_promotion.get("id"), observed=current_before.get("id"))
        write_safe_error(error.stage, error.code, error, version_id, current_before.get("id"), expected=pre_promotion.get("id"), observed=current_before.get("id"))
        return 18
    previous = pre_promotion
    transaction = {"previous_deployment": previous, "candidate_version": version_id,
                   "fingerprint": digest, "validated_candidate": version_id}
    Path("runner-evidence/promotion-transaction.json").write_text(json.dumps(transaction, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        promoted_response = deployment.deployment(version_id, os.environ.get("MAHOON_SSR_VERSION", "b660c7ff-9042-4b4e-ab14-63211aa9c1f1"), 100, 0)
        promoted_deployment_id = (promoted_response.get("result") or {}).get("id") if isinstance(promoted_response, dict) else None
        try:
            promoted = deployment.wait_for_active(version_id, 100, 0)
        except Exception as exc:
            raise PublisherStageError("DEPLOYMENT_STATE_VERIFICATION", "ERR_DEPLOYMENT_PROPAGATION_TIMEOUT", str(exc), expected={version_id: 100}, observed=None) from exc
        promoted_deployment_id = promoted.get("id") or promoted_deployment_id
        route_data = json.loads(Path("publisher-state/published-route-manifest.json").read_text(encoding="utf-8"))
        routes = [public_path(route) for route in route_data.get("routes", [])]
        public = validate_public(os.environ.get("MAHOON_PRODUCTION_ORIGIN", "https://mahoonartmagazine.ir"), routes)
        zero_evidence = capture_zero_origin(os.environ.get("MAHOON_PRODUCTION_ORIGIN", "https://mahoonartmagazine.ir"), routes)
        zero_path = Path("runner-evidence/zero-origin-production.json")
        zero_path.write_text(json.dumps(zero_evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        zero = validate_zero_origin(str(zero_path))
        production_pass = public.get("PASS") and zero.get("PASS")
        Path("runner-evidence/production-validation.json").write_text(json.dumps({"public": public, "zero_origin": zero, "PASS": production_pass}, ensure_ascii=False, indent=2), encoding="utf-8")
        if not public.get("PASS"):
            detail = (public.get("failure_details") or [{}])[0]
            raise PublisherStageError("POST_PROMOTION_ROUTE_CRAWL", "ERR_ROUTE_HTTP", "public validator failed", **detail)
        if not zero.get("PASS"):
            raise PublisherStageError("POST_PROMOTION_ZERO_ORIGIN", "ERR_ZERO_ORIGIN", "zero-origin validator failed", expected=0, observed=zero)
        production_env = os.environ.copy()
        production_env["MAHOON_DISABLE_VERSION_OVERRIDE"] = "1"
        production_env["MAHOON_CRAWL_OUTPUT"] = "runner-evidence/production-crawl"
        production_crawl = subprocess.run([sys.executable, "tools/publisher/candidate_override_crawl.py"], text=True, capture_output=True, env=production_env)
        production_summary_path = Path("runner-evidence/production-crawl/production-override-crawl-summary.json")
        production_summary = json.loads(production_summary_path.read_text(encoding="utf-8")) if production_summary_path.exists() else {}
        production_crawl_pass = production_crawl.returncode == 0 and production_summary.get("html_final_200") == production_summary.get("html_routes") and production_summary.get("post_final_200") == production_summary.get("post_routes") and not any(production_summary.get(key, 0) for key in ("broken_critical_links", "orphan_posts", "duplicate_canonicals", "redirect_loops", "remote_reader_media_dependencies", "workers_dev_leaks", "preview_url_leaks", "post_seo_failures"))
        if not production_crawl_pass:
            raise PublisherStageError("POST_PROMOTION_ROUTE_CRAWL", "ERR_PRODUCTION_CRAWL", "production crawl failed", expected="all canonical routes and posts PASS", observed=production_summary)
        Path("runner-evidence/production-validation.json").write_text(json.dumps({"public": public, "zero_origin": zero, "production_crawl": production_summary, "PASS": True}, ensure_ascii=False, indent=2), encoding="utf-8")
        published_state = Path("runner-evidence/published-state")
        published_state.mkdir(parents=True, exist_ok=True)
        (published_state / "production-content-fingerprint.json").write_text(
            json.dumps({"fingerprint": digest, "count": exported["count"]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for name in ("production-media-manifest.json", "published-route-manifest.json"):
            source = Path("runner-build") / name
            (published_state / name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        print(json.dumps({"mode": mode, "promotion": "PASS", "candidate_version": version_id,
                          "validated_version": version_id, "fingerprint": digest,
                          "validated_fingerprint": digest, "production_validation": "PASS",
                          "zero_origin": "PASS"}))
        return 0
    except Exception as exc:
        stage = exc.stage if isinstance(exc, PublisherStageError) else "UNEXPECTED_RUNNER_BUG"
        code = exc.code if isinstance(exc, PublisherStageError) else "ERR_VALIDATOR_INTERNAL"
        write_safe_error(stage, code, exc, version_id, locals().get("promoted_deployment_id"), **getattr(exc, "details", {}))
        try:
            automatic_rollback(previous)
        except Exception:
            print("AUTOMATIC_ROLLBACK_FAILED", file=sys.stderr)
            return 20
        print("AUTOMATIC_ROLLBACK_COMPLETED: " + type(exc).__name__, file=sys.stderr)
        return 19


if __name__ == "__main__":
    raise SystemExit(main())
