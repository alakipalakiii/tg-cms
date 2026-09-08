"""Minimal, non-secret publisher control-plane proof for the M9 release.

This runner deliberately fails closed when a content change is detected. A
production publishing implementation must be reviewed together with the
static builder and uploader; it must never silently publish a partial build.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request

API = os.environ.get("MAHOON_PUBLIC_CONTENT_API", "https://api.mahoonartmagazine.ir/posts-full-public-v1?limit=2000")


def main() -> int:
    mode = os.environ.get("PUBLISHER_MODE", "proof")
    request = urllib.request.Request(API, headers={"Accept": "application/json", "User-Agent": "MAHOON-M9-PUBLISHER/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    expected = os.environ.get("PUBLISHER_EXPECTED_FINGERPRINT", "")
    print(json.dumps({"mode": mode, "source": urllib.parse.urlsplit(API).hostname, "fingerprint": fingerprint, "items": len(payload.get("posts", payload if isinstance(payload, list) else []))}, ensure_ascii=False))
    if mode == "proof":
        return 0
    if mode != "publish":
        print("publisher mode is invalid", file=sys.stderr)
        return 2
    if not expected or fingerprint != expected:
        print("publisher is fail-closed: reviewed source fingerprint is missing or changed", file=sys.stderr)
        return 3
    print("publisher is fail-closed: no reviewed static artifact is attached to this release", file=sys.stderr)
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
