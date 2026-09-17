"""Deterministic content seal for immutable Static artifacts."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


class SealError(RuntimeError):
    pass


def tree_digest(root: Path) -> tuple[str, int]:
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise SealError("ARTIFACT_SYMLINK_REFUSED")
        if path.is_file():
            data = path.read_bytes()
            files.append([path.relative_to(root).as_posix(), hashlib.sha256(data).hexdigest(), len(data)])
    canonical = json.dumps(files, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest(), len(files)


def _seal_hash(payload: dict) -> str:
    unsigned = {key: value for key, value in payload.items() if key != "artifact_sha256"}
    canonical = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def create_seal(root: Path, *, content_fingerprint: str, route_hash: str) -> dict:
    root = root.resolve()
    if not root.is_dir() or not content_fingerprint or not route_hash:
        raise SealError("ARTIFACT_SEAL_INPUT_MISSING")
    artifact_hash, file_count = tree_digest(root)
    media_hash, media_count = tree_digest(root / "media") if (root / "media").is_dir() else (hashlib.sha256(b"[]").hexdigest(), 0)
    asset_hash, asset_count = tree_digest(root / "_astro") if (root / "_astro").is_dir() else (hashlib.sha256(b"[]").hexdigest(), 0)
    payload = {
        "contract": "MAHOON_STATIC_ARTIFACT_SEAL_V1",
        "content_fingerprint": content_fingerprint,
        "route_hash": route_hash,
        "artifact_tree_sha256": artifact_hash,
        "artifact_file_count": file_count,
        "media_tree_sha256": media_hash,
        "media_file_count": media_count,
        "asset_tree_sha256": asset_hash,
        "asset_file_count": asset_count,
    }
    payload["artifact_sha256"] = _seal_hash(payload)
    return payload


def verify_seal(root: Path, seal: dict) -> bool:
    if not isinstance(seal, dict) or seal.get("contract") != "MAHOON_STATIC_ARTIFACT_SEAL_V1":
        return False
    try:
        expected = create_seal(root, content_fingerprint=str(seal["content_fingerprint"]),
                               route_hash=str(seal["route_hash"]))
    except (KeyError, OSError, SealError):
        return False
    return expected == seal and seal.get("artifact_sha256") == _seal_hash(seal)


def main() -> int:
    root = Path(os.environ["MAHOON_SEALED_SITE"])
    payload = create_seal(root, content_fingerprint=os.environ.get("MAHOON_CONTENT_FINGERPRINT", ""),
                          route_hash=os.environ.get("MAHOON_ROUTE_HASH", ""))
    target = root.parent / "artifact-seal.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"seal_path": str(target), "artifact_sha256": payload["artifact_sha256"],
                      "file_count": payload["artifact_file_count"], "PASS": True}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
