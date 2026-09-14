"""Fail-closed read-only public-content revision lookup."""
from __future__ import annotations

import os
from typing import Callable

try:
    from .content_transport import fetch_json
except ImportError:
    from content_transport import fetch_json


DEFAULT_ENDPOINT = "https://mahoon-content-revision.morentoofficial.workers.dev/public/content-revision-v1"


def fetch_public_content_revision(
    endpoint: str | None = None,
    fetcher: Callable = fetch_json,
) -> tuple[int, str, dict]:
    payload, meta = fetcher(endpoint or os.environ.get(
        "MAHOON_PUBLIC_CONTENT_REVISION_API", DEFAULT_ENDPOINT
    ))
    if not isinstance(payload, dict):
        raise RuntimeError("PUBLIC_CONTENT_REVISION_CONTRACT_INVALID")
    revision = payload.get("revision")
    changed_at = payload.get("changed_at")
    if not isinstance(revision, int) or revision < 1 or not isinstance(changed_at, str) or not changed_at.strip():
        raise RuntimeError("PUBLIC_CONTENT_REVISION_CONTRACT_INVALID")
    return revision, changed_at, meta
