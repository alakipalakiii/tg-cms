from __future__ import annotations

import base64
import hashlib
import http.client
import json
import mimetypes
import os
import sys
import time
import uuid
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

ACCOUNT = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN", "")
WORKER = os.environ.get("MAHOON_WORKER", "mahoon-static-proof")
ROOT = Path(os.environ.get("MAHOON_ASSETS_DIRECTORY", "website/mahoon-static/dist"))
MEDIA_STATE = Path(os.environ.get("MAHOON_MEDIA_MANIFEST", "publisher-state/production-media-manifest.json"))
MEDIA_SOURCE = os.environ.get("MAHOON_MEDIA_SOURCE", "https://mahoon-static-proof.morentoofficial.workers.dev")
OUT = Path(os.environ.get("MAHOON_M9C_EVIDENCE", "artifacts/mahoon-static-publisher/m9c"))
OUT.mkdir(parents=True, exist_ok=True)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def api(method: str, path: str, body: bytes | None, content_type: str, bearer: str | None = TOKEN):
    # Large server-provided buckets can legitimately take several minutes over
    # the direct API; keep the bounded retry policy while allowing the request
    # to finish without changing the manifest or bucket plan.
    conn = http.client.HTTPSConnection("api.cloudflare.com", timeout=600)
    headers = {"Content-Type": content_type, "Accept": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    conn.request(method, path, body=body, headers=headers)
    response = conn.getresponse()
    raw = response.read()
    status = response.status
    conn.close()
    try:
        data = json.loads(raw.decode("utf-8")) if raw else {}
    except Exception:
        data = {"success": False, "raw_length": len(raw)}
    return status, data


def manifest_data():
    items = {}
    byte_hashes = {}
    for p in sorted(x for x in ROOT.rglob("*") if x.is_file()):
        rel = p.relative_to(ROOT).as_posix()
        data = p.read_bytes()
        ext = p.suffix[1:] if p.suffix else ""
        cloud_hash = hashlib.sha256(base64.b64encode(data) + ext.encode()).hexdigest()[:32]
        mahoon_hash = hashlib.sha256(data).hexdigest()
        public = "/" + rel
        items[public] = {"hash": cloud_hash, "size": len(data)}
        byte_hashes[public] = {"mahoon_sha256": mahoon_hash, "cloudflare_hash": cloud_hash, "size": len(data)}
    if MEDIA_STATE.exists():
        persisted = json.loads(MEDIA_STATE.read_text(encoding="utf-8"))
        for public, item in persisted.items():
            if not public.startswith("/media/"):
                continue
            items[public] = {"hash": item["cloudflare_hash"], "size": item["size"]}
            byte_hashes[public] = {**item, "source": MEDIA_SOURCE + public}
    return items, byte_hashes


def asset_bytes(public: str, byte_hashes: dict) -> bytes:
    if public.startswith("/media/"):
        item = byte_hashes[public]
        source = item.get("source") or MEDIA_SOURCE
        request = urllib.request.Request(source if source.endswith(public) else source + public, headers={"User-Agent": "MAHOON-M9-PUBLISHER-MEDIA/1.0"})
        with urllib.request.urlopen(request, timeout=180) as response:
            data = response.read()
        if len(data) != item["size"] or hashlib.sha256(data).hexdigest() != item["mahoon_sha256"]:
            raise RuntimeError("MEDIA_SHA_MISMATCH_FAIL_CLOSED")
        return data
    return (ROOT / public.lstrip("/").replace("/", os.sep)).read_bytes()


def save_manifest(items, byte_hashes):
    (OUT / "cloudflare-asset-manifest.json").write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "mahoon-byte-integrity-manifest.json").write_text(json.dumps(byte_hashes, ensure_ascii=False, indent=2), encoding="utf-8")


def multipart(parts):
    boundary = "----mahoon-m9c-" + uuid.uuid4().hex
    chunks = []
    for name, value, ctype, filename in parts:
        chunks.append(f"--{boundary}\r\n".encode())
        disp = f'form-data; name="{name}"'
        if filename:
            disp += f'; filename="{filename}"'
        chunks.append(f"Content-Disposition: {disp}\r\n".encode())
        if ctype:
            chunks.append(f"Content-Type: {ctype}\r\n".encode())
        chunks.append(b"\r\n")
        chunks.append(value if isinstance(value, bytes) else value.encode())
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def build_bucket_plan(manifest, buckets):
    by_hash = {v["hash"]: (k, v["size"]) for k, v in manifest.items()}
    plan = []
    for i, bucket in enumerate(buckets):
        entries = []
        total = 0
        types = {}
        for h in bucket:
            path, size = by_hash[h]
            ext = Path(path).suffix.lower() or "(none)"
            types[ext] = types.get(ext, 0) + 1
            total += size
            entries.append({"path": path, "hash": h, "size": size})
        plan.append({"bucket": i, "file_count": len(entries), "raw_bytes": total, "content_types": types, "largest_file": max((e["size"] for e in entries), default=0), "files": entries})
    return plan


def session(manifest):
    path = f"/client/v4/accounts/{ACCOUNT}/workers/scripts/{WORKER}/assets-upload-session"
    payload = json.dumps({"manifest": manifest}, separators=(",", ":")).encode()
    status, data = api("POST", path, payload, "application/json")
    if status < 200 or status >= 300 or not data.get("success", True):
        raise RuntimeError(f"upload session failed HTTP {status}")
    result = data.get("result") or {}
    jwt = result.get("jwt")
    buckets = result.get("buckets") or []
    if not jwt:
        raise RuntimeError("upload session returned no JWT")
    return jwt, buckets, status


def upload_bucket(bucket, manifest, upload_jwt, byte_hashes):
    by_hash = {v["hash"]: k for k, v in manifest.items()}
    parts = []
    for h in bucket:
        encoded = base64.b64encode(asset_bytes(by_hash[h], byte_hashes)).decode("ascii")
        parts.append((h, encoded, "text/plain", None))
    body, ctype = multipart(parts)
    return api("POST", f"/client/v4/accounts/{ACCOUNT}/workers/assets/upload?{urlencode({'base64': 'true'})}", body, ctype, upload_jwt)


def recover_bucket_one_asset_at_a_time(items, manifest, byte_hashes, upload_jwt):
    """Seed recovery for a transport-failing bucket; never retries the corpus."""
    completion = None
    for item in items:
        recovered = False
        for attempt in range(1, 4):
            status, data = upload_bucket([item["hash"]], manifest, upload_jwt, byte_hashes)
            if 200 <= status < 300:
                completion = (data.get("result") or {}).get("jwt") or completion
                recovered = True
                break
            time.sleep(2 ** (attempt - 1))
        if not recovered:
            return None
    return completion or upload_jwt


def do_upload(manifest, byte_hashes, buckets, upload_jwt):
    plan = build_bucket_plan(manifest, buckets)
    (OUT / "asset-upload-bucket-plan.json").write_text(json.dumps({"bucket_count": len(plan), "total_files": sum(x["file_count"] for x in plan), "total_bytes": sum(x["raw_bytes"] for x in plan), "buckets": plan}, ensure_ascii=False, indent=2), encoding="utf-8")
    state = {"started_at": now(), "bucket_count": len(plan), "completed": [], "failed": []}
    state_path = OUT / os.environ.get("MAHOON_BUCKET_STATE", "bucket-upload-state.json")
    completion = upload_jwt if not plan else None
    for item in plan:
        record = {"bucket": item["bucket"], "file_count": item["file_count"], "raw_bytes": item["raw_bytes"], "attempts": []}
        ok = False
        for attempt in range(1, 4):
            started = now()
            try:
                status, data = upload_bucket([x["hash"] for x in item["files"]], manifest, upload_jwt, byte_hashes)
                record["attempts"].append({"attempt": attempt, "started_at": started, "ended_at": now(), "http_status": status, "success": 200 <= status < 300})
                if 200 <= status < 300:
                    result = data.get("result") or {}
                    completion = result.get("jwt") or completion
                    ok = True
                    break
            except Exception as exc:
                record["attempts"].append({"attempt": attempt, "started_at": started, "ended_at": now(), "http_status": None, "success": False, "error_type": type(exc).__name__})
            time.sleep(2 ** (attempt - 1))
        if not ok:
            seed_completion = recover_bucket_one_asset_at_a_time(item["files"], manifest, byte_hashes, upload_jwt)
            if not seed_completion:
                state["failed"].append(record)
                state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
                raise RuntimeError(f"bucket {item['bucket']} failed after bounded retries and seed recovery")
            record["seed_recovery"] = "PASS"
            completion = seed_completion
        state["completed"].append(record)
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    state["ended_at"] = now()
    state["completion_token_received"] = bool(completion)
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    if not completion:
        raise RuntimeError("uploads completed without completion token")
    return completion, plan


def deploy(completion):
    version_id = create_version(completion)
    deployment_payload = json.dumps({"strategy": "percentage", "versions": [{"percentage": 100, "version_id": version_id}]}).encode()
    dstatus, ddata = api("POST", f"/client/v4/accounts/{ACCOUNT}/workers/scripts/{WORKER}/deployments", deployment_payload, "application/json")
    if dstatus < 200 or dstatus >= 300 or not ddata.get("success", True):
        raise RuntimeError(f"deployment creation failed HTTP {dstatus}")
    return version_id, dstatus


def create_version(completion):
    metadata = {"main_module": "main.js", "compatibility_date": "2026-09-08", "assets": {"jwt": completion, "config": {"html_handling": "drop-trailing-slash", "not_found_handling": "404-page"}}}
    module = b"export default { async fetch() { return new Response('not found', { status: 404 }); } };\n"
    body, ctype = multipart([("metadata", json.dumps(metadata), "application/json", None), ("main.js", module, "application/javascript+module", "main.js")])
    status, data = api("PUT", f"/client/v4/accounts/{ACCOUNT}/workers/scripts/{WORKER}", body, ctype)
    if status < 200 or status >= 300 or not data.get("success", True):
        raise RuntimeError(f"version creation failed HTTP {status}")
    result = data.get("result") or {}
    version_id = result.get("id") or result.get("version_id")
    if not version_id:
        raise RuntimeError("version created without visible version id")
    if version_id == WORKER:
        vstatus, vdata = api("GET", f"/client/v4/accounts/{ACCOUNT}/workers/scripts/{WORKER}/versions", None, "application/json")
        items = (vdata.get("result") or {}).get("items") or []
        version_id = (items[0].get("id") if items else None)
        if not version_id:
            raise RuntimeError(f"version list returned no version id HTTP {vstatus}")
    return version_id


def finish_upload(completion):
    if os.environ.get("MAHOON_CREATE_VERSION_ONLY") == "1":
        return {"version_id": create_version(completion), "deployment_performed": False}
    version_id, deployment_status = deploy(completion)
    return {"version_id": version_id, "deployment_http_status": deployment_status, "deployment_performed": True}


def run_resume():
    manifest, byte_hashes = manifest_data()
    prior_plan = json.loads((OUT / "asset-upload-bucket-plan.json").read_text(encoding="utf-8"))
    prior_state = json.loads((OUT / "bucket-upload-state.json").read_text(encoding="utf-8"))
    prior_by_index = {b["bucket"]: b for b in prior_plan["buckets"]}
    completed_indexes = {b["bucket"] for b in prior_state.get("completed", [])}
    completed_hashes = {f["hash"] for i in completed_indexes for f in prior_by_index[i]["files"]}
    upload_jwt, buckets, session_status = session(manifest)
    requested = {h for bucket in buckets for h in bucket}
    resume_effective = bool(requested) and not (requested & completed_hashes) and len(requested) < len(manifest)
    evidence = {"resession_http_status": session_status, "previous_completed_buckets": len(completed_indexes), "previous_completed_assets": len(completed_hashes), "new_requested_assets": len(requested), "server_side_resume_effective": resume_effective, "new_bucket_count": len(buckets)}
    (OUT / "resume-evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps({"resession_created": True, **evidence}))
    if not resume_effective:
        raise RuntimeError("server-side resume was not effective; stopping after one controlled re-session")
    os.environ["MAHOON_BUCKET_STATE"] = "bucket-upload-state-resume.json"
    completion, plan = do_upload(manifest, byte_hashes, buckets, upload_jwt)
    if os.environ.get("MAHOON_CREATE_VERSION_ONLY") == "1":
        version_id = create_version(completion)
        print(json.dumps({"completion_token_received": True, "version_id": version_id, "deployment_performed": False}))
    else:
        version_id, deployment_status = deploy(completion)
        print(json.dumps({"completion_token_received": True, "version_id": version_id, "deployment_http_status": deployment_status}))


def run_retry_remaining():
    """Retry the already-proven remaining server request without restarting the full manifest."""
    manifest, byte_hashes = manifest_data()
    upload_jwt, buckets, session_status = session(manifest)
    requested = {h for bucket in buckets for h in bucket}
    if not requested or len(requested) >= len(manifest):
        raise RuntimeError("remaining-only retry was not returned by the server")
    evidence = {"resession_http_status": session_status, "requested_assets": len(requested), "server_side_remaining_only": True, "bucket_count": len(buckets)}
    (OUT / "remaining-retry-evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence))
    os.environ["MAHOON_BUCKET_STATE"] = "bucket-upload-state-resume-retry.json"
    completion, _ = do_upload(manifest, byte_hashes, buckets, upload_jwt)
    print(json.dumps({"completion_token_received": True, **finish_upload(completion)}))


def main():
    if not ACCOUNT or not TOKEN:
        raise SystemExit("missing required secure environment")
    if len(sys.argv) > 1 and sys.argv[1] == "resume":
        run_resume()
        return
    if len(sys.argv) > 1 and sys.argv[1] == "retry-remaining":
        run_retry_remaining()
        return
    manifest, byte_hashes = manifest_data()
    save_manifest(manifest, byte_hashes)
    print(json.dumps({"manifest_assets": len(manifest), "manifest_bytes": sum(v["size"] for v in manifest.values()), "control_files_present": all(x in manifest for x in ("/_headers", "/_redirects"))}))
    upload_jwt, buckets, session_status = session(manifest)
    plan = build_bucket_plan(manifest, buckets)
    print(json.dumps({"upload_session_created": True, "session_http_status": session_status, "bucket_count": len(buckets), "requested_assets": sum(len(x) for x in buckets), "requested_bytes": sum(item["raw_bytes"] for item in plan)}))
    completion, _ = do_upload(manifest, byte_hashes, buckets, upload_jwt)
    print(json.dumps({"completion_token_received": True, **finish_upload(completion)}))


if __name__ == "__main__":
    main()
