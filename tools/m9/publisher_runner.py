"""Single entry point for the MAHOON publisher modes.

The network/build/upload adapters are deliberately fail-closed until every
candidate artifact is produced by this same runner.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from publisher.core import fingerprint
from publisher import static_build_adapter
from publisher import deployment

API = os.environ.get("MAHOON_PUBLIC_CONTENT_API", "https://api.mahoonartmagazine.ir/posts-full-public-v1?limit=2000")
STATE = Path(os.environ.get("MAHOON_PUBLISHER_STATE", "publisher-state/production-content-fingerprint.json"))


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
    previous = os.environ.get("PUBLISHER_EXPECTED_FINGERPRINT") or (json.loads(STATE.read_text(encoding="utf-8")).get("fingerprint") if STATE.exists() else None)
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
    deployment.deployment(version_id, os.environ.get("MAHOON_SSR_VERSION", "b660c7ff-9042-4b4e-ab14-63211aa9c1f1"), 0, 100)
    os.environ["MAHOON_CANDIDATE_VERSION"] = version_id
    os.environ["MAHOON_ASSETS_DIRECTORY"] = str(out)
    crawl = subprocess.run([sys.executable, "tools/publisher/candidate_override_crawl.py"], text=True, capture_output=True)
    if crawl.returncode != 0:
        print("PUBLISHER_OVERRIDE_CRAWL_FAILED", file=sys.stderr)
        return 15
    summary_path = Path("runner-evidence/override-crawl/production-override-crawl-summary.json")
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    validated = summary.get("html_final_200") == summary.get("html_routes") and summary.get("post_final_200") == summary.get("post_routes") and not any(summary.get(key, 0) for key in ("broken_critical_links", "orphan_posts", "duplicate_canonicals", "redirect_loops", "remote_reader_media_dependencies", "workers_dev_leaks", "preview_url_leaks", "post_seo_failures"))
    Path("runner-evidence/candidate-validation.json").parent.mkdir(parents=True, exist_ok=True)
    Path("runner-evidence/candidate-validation.json").write_text(json.dumps({"candidate_version": version_id, "fingerprint": digest, "build": build, "local_gate": gate, "override": summary, "PASS": validated}, ensure_ascii=False, indent=2), encoding="utf-8")
    if not validated:
        print("PUBLISHER_CANDIDATE_VALIDATION_FAILED", file=sys.stderr)
        return 16
    if mode == "PROOF_ZERO_PERCENT":
        print(json.dumps({"mode": mode, "candidate_version": version_id, "zero_percent": "PASS"}))
        return 0
    print("PUBLISHER_PROMOTION_BLOCKED: explicit ready marker and rollback transaction are required", file=sys.stderr)
    return 18


if __name__ == "__main__":
    raise SystemExit(main())
