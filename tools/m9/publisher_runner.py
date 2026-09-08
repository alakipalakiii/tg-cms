"""Single entry point for the MAHOON publisher modes.

The network/build/upload adapters are deliberately fail-closed until every
candidate artifact is produced by this same runner.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from publisher.core import fingerprint

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
    previous = json.loads(STATE.read_text(encoding="utf-8")).get("fingerprint") if STATE.exists() else None
    unchanged = previous == digest
    print(json.dumps({"mode": mode, "count": exported["count"], "fingerprint": digest,
                      "unchanged": unchanged, "state_present": STATE.exists()}, ensure_ascii=False))
    if mode == "CHECK_ONLY":
        return 0 if unchanged else 3
    source = os.environ.get("MAHOON_STATIC_SOURCE", "")
    if not source or not Path(source).is_dir():
        print("PUBLISHER_FULL_PATH_BLOCKED: runner-owned static source/build adapter is not configured", file=sys.stderr)
        return 10
    if not unchanged and not os.environ.get("MAHOON_REVIEWED_DELTA", ""):
        print("PUBLISHER_DELTA_BLOCKED: changed content requires a reviewed delta", file=sys.stderr)
        return 11
    print("PUBLISHER_FULL_PATH_BLOCKED: build/upload/validation adapters are not enabled", file=sys.stderr)
    return 12


if __name__ == "__main__":
    raise SystemExit(main())
