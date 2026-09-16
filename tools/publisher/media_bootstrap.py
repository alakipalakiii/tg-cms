"""Build-time, fail-closed hydration of immutable media for static publishing."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_BASE = "https://mahoonartmagazine.ir"
SOURCE_BASE = "https://api.mahoonartmagazine.ir"


class MediaBootstrapError(RuntimeError):
    pass


def source_identifier(post: dict) -> str | None:
    values = source_identifiers(post)
    return values[0][0] if values else None


def source_identifiers(post: dict) -> list[tuple[str, str]]:
    """Return every public media identity the locked Astro snapshot may render."""
    values: list[tuple[str, str]] = []
    seen: set[str] = set()
    for key, kind in (("media_file_id", media_type(post)), ("photo_file_id", "photo"),
                      ("thumbnail_file_id", "photo"), ("thumb_file_id", "photo"),
                      ("file_id", media_type(post)), ("telegram_file_id", media_type(post))):
        value = str(post.get(key) or "").strip()
        if value and value not in seen:
            seen.add(value)
            values.append((value, kind))
    return values


def media_type(post: dict) -> str:
    return str(post.get("media_type") or ("photo" if post.get("photo_file_id") else "")).lower()


def signature_mime(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"OggS"):
        return "audio/ogg"
    if data.startswith(b"ID3") or data[:2] in {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"}:
        return "audio/mpeg"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "video/mp4"
    return None


def _extension(mime: str) -> str:
    return {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp", "audio/ogg": ".ogg", "audio/mpeg": ".mp3", "video/mp4": ".mp4"}.get(mime, "")


def _read_json(path: Path, fallback: object) -> object:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else fallback


def load_index(path: Path) -> dict[str, dict]:
    payload = _read_json(path, {"entries": []})
    entries = payload.get("entries", []) if isinstance(payload, dict) else []
    return {str(item["source_identifier"]): dict(item) for item in entries if isinstance(item, dict) and item.get("source_identifier")}


def write_index(path: Path, records: dict[str, dict]) -> None:
    entries = [records[key] for key in sorted(records)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"contract": "IMMUTABLE_MEDIA_INDEX_V1", "entries": entries}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _fetch(url: str) -> tuple[bytes, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "MAHOON-Immutable-Media-Bootstrap/1.0", "Accept": "image/*,audio/*,video/*"})
    with urllib.request.urlopen(request, timeout=90) as response:
        if response.status != 200:
            raise MediaBootstrapError(f"MEDIA_HTTP_{response.status}")
        return response.read(), str(response.headers.get_content_type() or "")


def _verify(data: bytes, expected_sha: str | None, expected_mime: str | None) -> tuple[str, str]:
    if not data:
        raise MediaBootstrapError("MEDIA_EMPTY_PAYLOAD")
    detected = signature_mime(data)
    if not detected:
        raise MediaBootstrapError("MEDIA_INVALID_SIGNATURE")
    if expected_mime and detected != expected_mime:
        raise MediaBootstrapError("MEDIA_MIME_MISMATCH")
    digest = hashlib.sha256(data).hexdigest()
    if expected_sha and digest != expected_sha:
        raise MediaBootstrapError("MEDIA_SHA256_MISMATCH")
    return digest, detected


def bootstrap(posts: list[dict], *, index_path: Path | None = None, store: Path | None = None,
              output_manifest: Path | None = None, output_index: Path | None = None,
              production_base: str | None = None, source_base: str | None = None) -> dict:
    index_path = index_path or ROOT / "publisher-state/immutable-media-index.json"
    store = store or ROOT / "runner-evidence/immutable-media-store"
    output_manifest = output_manifest or ROOT / "runner-build/current-media-manifest.json"
    output_index = output_index or ROOT / "runner-build/immutable-media-index.json"
    production_base = (production_base or os.environ.get("MAHOON_PRODUCTION_MEDIA_BASE") or PRODUCTION_BASE).rstrip("/")
    source_base = (source_base or os.environ.get("MAHOON_MEDIA_SOURCE_BASE") or SOURCE_BASE).rstrip("/")
    known = load_index(index_path)
    required: dict[str, dict] = {}
    for post in posts:
        for identity, kind in source_identifiers(post):
            record = required.setdefault(identity, {"source_identifier": identity, "post_ids": [], "media_type": kind})
            record["post_ids"].append(int(post["id"]))
    stats = {"mode": "REQUIRED_SET_ONLY", "required_distinct": len(required), "published": 0, "new": 0, "fallback": 0, "unresolved": 0, "source_redownloads": 0, "hash_mismatches": 0, "invalid_payloads": 0}
    records: list[dict] = []
    store.mkdir(parents=True, exist_ok=True)
    for identity in sorted(required):
        item = dict(known.get(identity, {}))
        try:
            if item:
                stats["published"] += 1
                data, _header_mime = _fetch(production_base + str(item["immutable_path"]))
                digest, detected = _verify(data, str(item.get("sha256") or ""), str(item.get("mime") or "") or None)
            else:
                encoded = urllib.parse.quote(identity, safe="")
                try:
                    data, _header_mime = _fetch(source_base + "/media/" + encoded)
                except urllib.error.HTTPError as exc:
                    if exc.code not in {404, 410}:
                        raise
                    records.append({"source_identifier": identity, "post_ids": required[identity]["post_ids"], "fallback": True, "fallback_reason": f"SOURCE_HTTP_{exc.code}"})
                    stats["fallback"] += 1
                    continue
                digest, detected = _verify(data, None, None)
                item = {"source_identifier": identity, "immutable_path": f"/media/{digest[:2]}/{digest}{_extension(detected)}", "sha256": digest, "mime": detected, "media_type": required[identity]["media_type"], "fallback": False}
                known[identity] = item
                stats["new"] += 1
            target = store / Path(str(item["immutable_path"])).name
            if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                target.write_bytes(data)
            records.append({**item, "post_ids": required[identity]["post_ids"], "detected_mime": detected, "fallback": False})
        except MediaBootstrapError as exc:
            if "MISMATCH" in str(exc):
                stats["hash_mismatches"] += 1
            if "SIGNATURE" in str(exc) or "EMPTY" in str(exc):
                stats["invalid_payloads"] += 1
            stats["unresolved"] += 1
            raise
    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    output_manifest.write_text(json.dumps({"contract": "CURRENT_MEDIA_RESOLUTION_V1", "records": records, "stats": stats}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_index(output_index, known)
    return {"manifest": str(output_manifest), "index": str(output_index), "store": str(store), **stats}
