"""One-time deterministic recovery of published media identities from static HTML."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import urllib.request
from pathlib import Path

from export_v2 import export_complete
from media_bootstrap import ROOT, media_type, source_identifier, write_index

STATIC_PATH = re.compile(r'''(?:src|href)=["'](?P<path>/media/[0-9a-f]{2}/[0-9a-f]{64}\.(?:jpg|png|gif|webp|mp3|ogg|mp4))["']''', re.I)


def fetch_static_path(post_id: int, base: str) -> tuple[int, str | None]:
    request = urllib.request.Request(f"{base.rstrip('/')}/post/{post_id}", headers={"User-Agent": "MAHOON-Immutable-Media-Index/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            match = STATIC_PATH.search(response.read().decode("utf-8", "replace"))
            return post_id, match.group("path") if match else None
    except Exception:
        return post_id, None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="publisher-state/immutable-media-index.json")
    parser.add_argument("--production-base", default="https://mahoonartmagazine.ir")
    args = parser.parse_args()
    manifest = json.loads((ROOT / "publisher-state/production-media-manifest.json").read_text(encoding="utf-8"))
    exported, _proof = export_complete("https://api.mahoonartmagazine.ir/posts-full-public-v2")
    by_id = {int(post["id"]): post for post in exported["posts"] if source_identifier(post)}
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        found = dict(pool.map(lambda post_id: fetch_static_path(post_id, args.production_base), sorted(by_id)))
    index: dict[str, dict] = {}
    for post_id, path in found.items():
        post = by_id[post_id]
        item = manifest.get(path or "")
        identity = source_identifier(post)
        if not item or not identity:
            continue
        sha = str(item.get("mahoon_sha256") or "")
        if len(sha) != 64 or Path(path).stem != sha:
            continue
        index.setdefault(identity, {
            "source_identifier": identity,
            "immutable_path": path,
            "sha256": sha,
            "mime": {".jpg": "image/jpeg", ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp", ".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".mp4": "video/mp4"}[Path(path).suffix.lower()],
            "media_type": media_type(post),
            "fallback": False,
        })
    write_index(ROOT / args.output, index)
    print(json.dumps({"published_mappings": len(index), "manifest_entries": len(manifest), "unmapped": len(by_id) - len(index)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
