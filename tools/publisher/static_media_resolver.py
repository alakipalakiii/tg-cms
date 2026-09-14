"""Resolve already-approved media from the immutable local media store."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[2]


class StaticMediaResolutionError(RuntimeError):
    pass


class PublishedMediaResolver:
    def __init__(self) -> None:
        manifest = ROOT / os.environ.get(
            "MAHOON_CURRENT_MEDIA_MANIFEST", "runner-evidence/current-media-manifest.json"
        )
        index_path = ROOT / os.environ.get(
            "MAHOON_IMMUTABLE_MEDIA_INDEX", "runner-evidence/immutable-media-index.json"
        )
        store = ROOT / os.environ.get(
            "MAHOON_IMMUTABLE_MEDIA_STORE", "runner-evidence/immutable-media-store"
        )
        self.store = store
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        self.records = {
            str(record["source_identifier"]): record
            for record in payload.get("records", [])
            if record.get("source_identifier")
        }
        self.index = json.loads(index_path.read_text(encoding="utf-8"))
        self.stats = {"total": 0, "immutable": 0, "fallback": 0, "unresolved": 0}

    @staticmethod
    def source_identifier(source_reference: str) -> str:
        path = urlsplit(source_reference).path.rstrip("/")
        if "/media/" not in path:
            raise StaticMediaResolutionError("STATIC_MEDIA_REFERENCE_INVALID")
        return unquote(path.rsplit("/", 1)[-1])

    def resolve_public_media(self, source_reference: str, *, post_id: int | None = None) -> dict:
        self.stats["total"] += 1
        source_id = self.source_identifier(source_reference)
        record = self.records.get(source_id)
        if record is None or not record.get("sha256"):
            self.stats["unresolved"] += 1
            suffix = f":POST_{post_id}" if post_id is not None else ""
            raise StaticMediaResolutionError(f"STATIC_MEDIA_UNRESOLVED:{source_id}{suffix}")
        immutable_path = record.get("immutable_path") or self.index.get(source_id, {}).get("immutable_path")
        expected_sha = str(record.get("sha256") or self.index.get(source_id, {}).get("sha256") or "")
        if not immutable_path or len(expected_sha) != 64:
            self.stats["unresolved"] += 1
            raise StaticMediaResolutionError(f"STATIC_MEDIA_MAPPING_INVALID:{source_id}")
        blob = self.store / str(immutable_path).lstrip("/").split("/", 1)[-1]
        if not blob.is_file() or hashlib.sha256(blob.read_bytes()).hexdigest() != expected_sha:
            self.stats["unresolved"] += 1
            raise StaticMediaResolutionError(f"STATIC_MEDIA_STORE_INVALID:{source_id}")
        self.stats["immutable"] += 1
        return {
            "status": "IMMUTABLE",
            "public_path": str(immutable_path),
            "sha256": expected_sha,
            "mime": record.get("detected_mime"),
            "media_type": record.get("expected_media_type"),
            "fallback_reason": None,
            "source_identifier": source_id,
            "post_ids": record.get("post_ids", []),
            "blob": str(blob),
        }
