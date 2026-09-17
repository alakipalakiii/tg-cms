"""Independent remote-proof and production-promotion jobs for M10 publishing."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "publisher"))

from publisher import cloudflare_wrangler as deployment
from publisher.resumable_transaction import (
    split_is_baseline_zero,
    verify_production_result,
    verify_proof_bundle,
    verify_remote_result,
)
from publisher.rollback import automatic_rollback
from publisher.state_machine import live_static_baseline, verify_promoted_static

WORKER = "mahoon-art-magazine"
ORIGIN = "https://mahoonartmagazine.ir"
EVIDENCE = Path("runner-evidence")


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _safe_failure(exc: Exception) -> str:
    message = re.sub(r"(?i)(authorization|token|jwt|cookie|secret)\s*[:=]\s*[^\s,;]+",
                     r"\1=[REDACTED]", str(exc))
    return message.replace("CLOUDFLARE_API_TOKEN", "[REDACTED_SECRET]")[:300]


def _command(command: list[str], timeout: int, env: dict[str, str] | None = None) -> None:
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout, env=env)
    if result.returncode:
        raise RuntimeError(f"{Path(command[0]).name} failed ({result.returncode})")


def _gate(summary: dict, key: str) -> bool:
    value = (summary.get("gates") or {}).get(key) or {}
    return value.get("measured") is True and value.get("PASS") is True


def _active_deployment_with_retry(attempts: int = 5) -> dict:
    last_error = None
    for attempt in range(attempts):
        try:
            return deployment.active_deployment(WORKER)
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(2)
    raise RuntimeError("CLOUDFLARE_LIVE_STATE_UNREADABLE") from last_error


def _browser_gate(bundle_dir: Path, transaction: dict, *, production: bool,
                  timeout: int = 240) -> dict:
    route_path = bundle_dir / "candidate-route-manifest.json"
    expectations_path = bundle_dir / "remote-expectations.json"
    output = EVIDENCE / ("production-visual-runtime.json" if production else "remote-visual-runtime.json")
    command = ["node", "tools/publisher/prepromotion_browser_gate.mjs",
               "--base-url", ORIGIN, "--expectations", str(expectations_path),
               "--routes", str(route_path), "--output", str(output)]
    if not production:
        command.extend(["--candidate-version", transaction["candidate_static_version"]])
    _command(command, timeout)
    return _read(output)


def _crawl(bundle_dir: Path, transaction: dict, *, production: bool,
           timeout: int) -> dict:
    route_path = bundle_dir / "candidate-route-manifest.json"
    expectation_path = bundle_dir / "remote-expectations.json"
    media_path = bundle_dir / "semantic-media-manifest.json"
    crawl_root = EVIDENCE / ("production-crawl" if production else "remote-proof-crawl")
    env = os.environ.copy()
    env.update({
        "MAHOON_REMOTE_EXPECTATIONS": str(expectation_path),
        "MAHOON_ROUTE_MANIFEST": str(route_path),
        "MAHOON_MEDIA_MANIFEST": str(media_path),
        "MAHOON_CRAWL_OUTPUT": str(crawl_root),
        "MAHOON_CRAWL_BASE": ORIGIN,
        "MAHOON_PRODUCTION_ORIGIN": ORIGIN,
        "MAHOON_OVERRIDE_WORKER": WORKER,
        "MAHOON_WORKER": WORKER,
        "MAHOON_CANDIDATE_VERSION": transaction["candidate_static_version"],
        "MAHOON_REMOTE_CRAWL_WORKERS": "8",
    })
    env.pop("MAHOON_PUBLISHED_CONTENT_SNAPSHOT", None)
    if production:
        env["MAHOON_DISABLE_VERSION_OVERRIDE"] = "1"
    else:
        env.pop("MAHOON_DISABLE_VERSION_OVERRIDE", None)
    _command([sys.executable, "tools/publisher/candidate_override_crawl.py"], timeout, env)
    return _read(crawl_root / "production-override-crawl" / "production-override-crawl-summary.json")


def _measured_gates(summary: dict, browser: dict, expected_routes: int) -> dict:
    present = summary.get("present_route_count")
    routes_pass = (
        summary.get("measured") is True
        and summary.get("expected_route_count") == expected_routes
        and present == expected_routes
        and summary.get("missing_routes") == []
        and _gate(summary, "remote_route_parity")
    )
    runtime = (browser.get("zero_origin") or {}).get("requests") or {}
    zero_runtime = (browser.get("zero_origin") or {}).get("PASS") is True and all(
        runtime.get(key, 0) == 0 for key in
        ("content_api", "media_api", "workers_dev_content", "telegram", "search_backend")
    )
    visual = (browser.get("visual") or {}).get("PASS") is True
    post_jsonld_missing = int(summary.get("post_jsonld_missing", 0))
    duplicate_canonicals = int(summary.get("duplicate_canonicals", 0))
    workers_dev = int(summary.get("workers_dev_leaks", 0))
    reader_media = int(summary.get("remote_reader_media_dependencies", 0))
    return {
        "full_route_crawl": routes_pass,
        "content_parity": _gate(summary, "remote_content_parity"),
        "listing_uniqueness": _gate(summary, "remote_listing_uniqueness"),
        "category_parity": _gate(summary, "remote_category_parity"),
        "latest_parity": _gate(summary, "remote_latest_parity"),
        "seo": _gate(summary, "remote_seo") and post_jsonld_missing == 0 and duplicate_canonicals == 0,
        "media": _gate(summary, "remote_media") and reader_media == 0,
        "visual": visual,
        "zero_origin_runtime": zero_runtime and workers_dev == 0,
        "remote_expected_route_count": expected_routes,
        "remote_present_route_count": present,
        "remote_missing_routes": summary.get("missing_routes", []),
        "remote_post_jsonld_missing": post_jsonld_missing,
        "remote_duplicate_canonicals": duplicate_canonicals,
        "remote_workers_dev_leaks": workers_dev,
        "remote_public_runtime_requests": runtime,
        "remote_reader_media_dependencies": reader_media,
    }


def run_remote(bundle_dir: Path, transaction_id: str) -> int:
    transaction, bundle_sha = verify_proof_bundle(bundle_dir, transaction_id, _head_sha())
    if transaction.get("target_worker") != WORKER:
        raise ValueError("proof bundle Worker target is not the approved production Static Worker")
    deployment.WORKER = WORKER
    os.environ["MAHOON_WORKER"] = WORKER
    if not split_is_baseline_zero(_active_deployment_with_retry(), transaction):
        raise RuntimeError("REMOTE_PROOF_LIVE_SPLIT_DRIFT")
    routes = _read(bundle_dir / "candidate-route-manifest.json")
    summary = _crawl(bundle_dir, transaction, production=False, timeout=3300)
    browser = _browser_gate(bundle_dir, transaction, production=False)
    gates = _measured_gates(summary, browser, routes["route_count"])
    passed = all(gates[key] is True for key in (
        "full_route_crawl", "content_parity", "listing_uniqueness", "category_parity",
        "latest_parity", "seo", "media", "visual", "zero_origin_runtime"))
    result = {
        "contract": "MAHOON_REMOTE_PROOF_RESULT_V1",
        "transaction_id": transaction_id,
        "candidate_version": transaction["candidate_static_version"],
        "bundle_sha256": bundle_sha,
        "revision_requests": 0, "full_v2_exports": 0, "builds": 0, "uploads": 0,
        "rerun_reuses_candidate": True,
        "REMOTE_PROOF_PASS": passed,
        "REMOTE_FULL_ROUTE_CRAWL": "PASS" if gates["full_route_crawl"] else "FAIL",
        "REMOTE_CONTENT_PARITY": "PASS" if gates["content_parity"] else "FAIL",
        "REMOTE_LISTING_UNIQUENESS": "PASS" if gates["listing_uniqueness"] else "FAIL",
        "REMOTE_CATEGORY_PARITY": "PASS" if gates["category_parity"] else "FAIL",
        "REMOTE_LATEST_PARITY": "PASS" if gates["latest_parity"] else "FAIL",
        "REMOTE_SEO": "PASS" if gates["seo"] else "FAIL",
        "REMOTE_MEDIA": "PASS" if gates["media"] else "FAIL",
        "REMOTE_VISUAL": "PASS" if gates["visual"] else "FAIL",
        "REMOTE_ZERO_ORIGIN_RUNTIME": "PASS" if gates["zero_origin_runtime"] else "FAIL",
        "metrics": gates,
        "crawler_summary": summary,
        "failed_routes": _failed_routes(EVIDENCE / "remote-proof-crawl", routes["routes"]),
        "browser_summary": browser,
    }
    _write(EVIDENCE / "remote-proof-result.json", result)
    print(json.dumps({key: result[key] for key in (
        "transaction_id", "candidate_version", "REMOTE_PROOF_PASS", "REMOTE_FULL_ROUTE_CRAWL",
        "REMOTE_CONTENT_PARITY", "REMOTE_LISTING_UNIQUENESS", "REMOTE_CATEGORY_PARITY",
        "REMOTE_LATEST_PARITY", "REMOTE_VISUAL", "REMOTE_ZERO_ORIGIN_RUNTIME")}, ensure_ascii=False))
    return 0 if passed else 1


def _production_validation(bundle_dir: Path, transaction: dict, bundle_sha: str,
                           remote_result: dict) -> dict:
    routes = _read(bundle_dir / "candidate-route-manifest.json")
    summary = _crawl(bundle_dir, transaction, production=True, timeout=840)
    browser = _browser_gate(bundle_dir, transaction, production=True, timeout=240)
    gates = _measured_gates(summary, browser, routes["route_count"])
    robots = bool(summary.get("robots_sitemap_directive"))
    rss_route = summary.get("routes", {}).get("/rss.xml", {}) if isinstance(summary.get("routes"), dict) else {}
    # The route crawl state is a separate sidecar; check RSS from that measured state.
    state_path = (EVIDENCE / "production-crawl" / "production-override-crawl"
                  / "production-override-crawl-state.json")
    if state_path.is_file():
        rss_route = _read(state_path).get("routes", {}).get("/rss.xml", {})
    rss_pass = rss_route.get("http_status") == 200 and rss_route.get("content_type") in {
        "application/rss+xml", "application/xml", "text/xml"}
    visual_checks = {item.get("name"): item for item in browser.get("checks", [])}
    production_routes = _read(state_path).get("routes", {}) if state_path.is_file() else {}
    admin_pass = (visual_checks.get("admin-shell", {}).get("visual_pass") is True
                  and production_routes.get("/admin", {}).get("http_status") == 200
                  and production_routes.get("/admin/analytics", {}).get("http_status") == 200)
    requirements = {
        "route_parity": gates["full_route_crawl"],
        "content_parity": gates["content_parity"],
        "listing_uniqueness": gates["listing_uniqueness"],
        "category_parity": gates["category_parity"],
        "latest_parity": gates["latest_parity"],
        "media": gates["media"],
        "visual": gates["visual"],
        "seo": gates["seo"] and robots and rss_pass,
        "zero_origin": gates["zero_origin_runtime"],
        "admin_panel": admin_pass,
    }
    passed = all(requirements.values())
    return {
        "contract": "MAHOON_PRODUCTION_RESULT_V1",
        "transaction_id": transaction["transaction_id"],
        "candidate_version": transaction["candidate_static_version"],
        "bundle_sha256": bundle_sha,
        "remote_proof_pass": remote_result.get("REMOTE_PROOF_PASS") is True,
        "production_gates": requirements,
        "production_crawl_summary": summary,
        "failed_routes": _failed_routes(EVIDENCE / "production-crawl", routes["routes"]),
        "production_browser_summary": browser,
        "production_robots_sitemap": robots,
        "production_rss": rss_pass,
        "PASS": passed,
    }


def run_promotion(bundle_dir: Path, proof_dir: Path, transaction_id: str) -> int:
    transaction, bundle_sha = verify_proof_bundle(bundle_dir, transaction_id, _head_sha())
    proof = _read(proof_dir / "remote-proof-result.json")
    verify_remote_result(proof, transaction, bundle_sha)
    if os.environ.get("MAHOON_PUBLISH_READY") != "YES":
        raise RuntimeError("PROMOTION_REQUIRES_MAHOON_PUBLISH_READY_YES")
    deployment.WORKER = WORKER
    os.environ["MAHOON_WORKER"] = WORKER
    static_state = _read(ROOT / "publisher-state" / "published-static-state.json")
    if static_state.get("current_version_type") != "STATIC" or static_state.get("current_version") != transaction.get("baseline_static_version"):
        raise RuntimeError("PUBLISHED_STATIC_STATE_DRIFT")
    live = _active_deployment_with_retry()
    if not split_is_baseline_zero(live, transaction):
        raise RuntimeError("PRE_PROMOTION_LIVE_DRIFT")
    result_path = EVIDENCE / "production-result.json"
    promoted_id = None
    promotion_confirmed = False
    try:
        response = deployment.deploy_pair(WORKER, transaction["candidate_static_version"], 100,
                                          transaction["baseline_static_version"], 0)
        promoted_id = response.get("id")
        promoted_split = {
            transaction["candidate_static_version"]: 100,
            transaction["baseline_static_version"]: 0,
        }
        promoted = deployment.wait_for_active(WORKER, promoted_split, timeout_seconds=150)
        promotion_confirmed, promotion_readback = verify_promoted_static(
            promoted, transaction["candidate_static_version"], transaction["baseline_static_version"])
        if not promotion_confirmed:
            raise RuntimeError("PROMOTION_READBACK_MISMATCH")
        promoted_id = promoted.get("id") or promoted_id
        result = _production_validation(bundle_dir, transaction, bundle_sha, proof)
        result["promotion_performed"] = True
        result["promotion_deployment_id"] = promoted_id
        result["promotion_readback"] = promotion_readback
        result["rollback_performed"] = False
        if not result["PASS"]:
            raise RuntimeError("PRODUCTION_VALIDATION_FAILED")
        _write(result_path, result)
        state_dir = EVIDENCE / "published-state"
        state_dir.mkdir(parents=True, exist_ok=True)
        for source, target in (
            ("semantic-media-manifest.json", "production-media-manifest.json"),
            ("immutable-media-index.json", "immutable-media-index.json"),
            ("candidate-route-manifest.json", "published-route-manifest.json"),
        ):
            (state_dir / target).write_bytes((bundle_dir / source).read_bytes())
        _write(state_dir / "production-content-fingerprint.json", {
            "fingerprint": transaction["content_fingerprint"],
            "count": _read(bundle_dir / "remote-expectations.json")["source_post_count"],
            "published_content_revision": transaction["source_revision"],
        })
        seal = _read(bundle_dir / "artifact-seal.json")
        _write(state_dir / "published-static-state.json", {
            "current_version": transaction["candidate_static_version"],
            "previous_version": transaction["baseline_static_version"],
            "current_version_type": "STATIC",
            "deployment_id": promoted_id,
            "artifact_seal": seal["artifact_sha256"],
            "content_fingerprint": transaction["content_fingerprint"],
        })
        print(json.dumps({"PROMOTION_PERFORMED": "YES", "PRODUCTION_PASS": True,
                          "candidate_version": transaction["candidate_static_version"]}))
        return 0
    except Exception as exc:
        try:
            current = _active_deployment_with_retry()
        except Exception as read_error:
            failure = {
                **(locals().get("result", {}) if isinstance(locals().get("result"), dict) else {}),
                "contract": "MAHOON_PRODUCTION_RESULT_V1",
                "transaction_id": transaction["transaction_id"],
                "candidate_version": transaction["candidate_static_version"],
                "bundle_sha256": bundle_sha,
                "PASS": False,
                "failure": type(exc).__name__ + ": " + _safe_failure(exc),
                "live_state_read_failure": _safe_failure(read_error),
                "promotion_performed": promoted_id is not None or promotion_confirmed,
                "rollback_performed": False,
                "rollback_verified": False,
            }
            _write(result_path, failure)
            print(json.dumps({"PRODUCTION_PASS": False, "ROLLBACK_PERFORMED": False,
                              "LIVE_STATE_READABLE": False}))
            return 1
        expected_candidate_split = {
            transaction["candidate_static_version"]: 100,
            transaction["baseline_static_version"]: 0,
        }
        observed = {item.get("version_id"): item.get("percentage") for item in current.get("versions", [])}
        rollback_performed = False
        rollback_verified = False
        if observed == expected_candidate_split and current.get("id"):
            try:
                restored = automatic_rollback(WORKER, transaction["baseline_static_version"],
                                              transaction["candidate_static_version"], current["id"])
                rollback_performed = True
                rollback_verified = live_static_baseline(restored, transaction["baseline_static_version"])[0]
            except Exception:
                rollback_performed = True
        failure = {
            **(locals().get("result", {}) if isinstance(locals().get("result"), dict) else {}),
            "contract": "MAHOON_PRODUCTION_RESULT_V1",
            "transaction_id": transaction["transaction_id"],
            "candidate_version": transaction["candidate_static_version"],
            "bundle_sha256": bundle_sha,
            "PASS": False,
            "failure": type(exc).__name__ + ": " + _safe_failure(exc),
            "promotion_performed": promotion_confirmed or observed == expected_candidate_split,
            "rollback_performed": rollback_performed,
            "rollback_verified": rollback_verified,
            "observed_deployment": current,
        }
        _write(result_path, failure)
        print(json.dumps({"PROMOTION_PERFORMED": failure["promotion_performed"],
                          "PRODUCTION_PASS": False, "ROLLBACK_PERFORMED": rollback_performed,
                          "ROLLBACK_VERIFIED": rollback_verified, "failure": failure["failure"]}))
        return 1


def _head_sha() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                          capture_output=True, check=True).stdout.strip()


def _failed_routes(crawl_root: Path, expected_routes: list[str] | None = None) -> list[dict]:
    state_path = crawl_root / "production-override-crawl" / "production-override-crawl-state.json"
    routes = _read(state_path).get("routes", {}) if state_path.is_file() else {}
    for route in expected_routes or []:
        routes.setdefault(route, {"error_class": "NOT_CRAWLED"})
    return [
        {"route": path, "http_status": value.get("http_status"),
         "error_class": value.get("error_class"), "status": value.get("status")}
        for path, value in sorted(routes.items()) if value.get("http_status") != 200
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True, choices=("REMOTE_PROOF", "PROMOTE_AND_VALIDATE"))
    parser.add_argument("--transaction-id", required=True)
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--proof-dir", type=Path)
    args = parser.parse_args()
    try:
        if args.stage == "REMOTE_PROOF":
            return run_remote(args.bundle_dir, args.transaction_id)
        if args.proof_dir is None:
            raise ValueError("remote proof artifact directory is required")
        return run_promotion(args.bundle_dir, args.proof_dir, args.transaction_id)
    except Exception as exc:
        if args.stage == "REMOTE_PROOF":
            try:
                transaction, bundle_sha = verify_proof_bundle(args.bundle_dir, args.transaction_id, _head_sha())
                _write(EVIDENCE / "remote-proof-result.json", {
                    "contract": "MAHOON_REMOTE_PROOF_RESULT_V1",
                    "transaction_id": transaction["transaction_id"],
                    "candidate_version": transaction["candidate_static_version"],
                    "bundle_sha256": bundle_sha,
                    "revision_requests": 0, "full_v2_exports": 0, "builds": 0, "uploads": 0,
                    "rerun_reuses_candidate": True,
                    "REMOTE_PROOF_PASS": False,
                    "failure": type(exc).__name__ + ": " + _safe_failure(exc),
                    "failed_routes": _failed_routes(
                        EVIDENCE / "remote-proof-crawl",
                        _read(args.bundle_dir / "candidate-route-manifest.json").get("routes", [])),
                    "crawler_summary": (_read(EVIDENCE / "remote-proof-crawl" / "production-override-crawl"
                                               / "production-override-crawl-summary.json")
                                        if (EVIDENCE / "remote-proof-crawl" / "production-override-crawl"
                                            / "production-override-crawl-summary.json").is_file() else None),
                })
            except Exception:
                pass
        print(json.dumps({"stage": args.stage, "failure": type(exc).__name__ + ": " + _safe_failure(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
