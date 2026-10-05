"""Fail-closed read-only public-content revision lookup."""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Callable

try:
    from .content_transport import fetch_json
except ImportError:
    from content_transport import fetch_json


DEFAULT_ENDPOINT = "https://mahoon-content-revision.morentoofficial.workers.dev/public/content-revision-v1"


def _normalize_changed_at(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise RuntimeError("PUBLIC_CONTENT_REVISION_CONTRACT_INVALID")
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", value):
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc
            ).isoformat()
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
    except (OverflowError, ValueError):
        raise RuntimeError("PUBLIC_CONTENT_REVISION_CONTRACT_INVALID") from None
    return value


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
    if not isinstance(revision, int) or revision < 1:
        raise RuntimeError("PUBLIC_CONTENT_REVISION_CONTRACT_INVALID")
    return revision, _normalize_changed_at(payload.get("changed_at")), meta
