"""Conservative public-listing dedupe for adjacent identical source emissions."""
from __future__ import annotations

from datetime import datetime, timezone
import re
import unicodedata


DUPLICATE_WINDOW_SECONDS = 10 * 60
_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")


def _timestamp(value: object) -> float:
    raw = str(value or "").strip().replace(" ", "T")
    if not raw:
        return 0.0
    try:
        return datetime.fromisoformat(raw).replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return 0.0


def _normalized_text(value: object) -> str:
    return re.sub(r"\s+", " ", _ZERO_WIDTH.sub("", unicodedata.normalize("NFKC", str(value or "")))).strip()


def public_listing_key(post: dict) -> str:
    media_identity = str(
        post.get("media_unique_id")
        or post.get("photo_unique_id")
        or post.get("media_file_id")
        or post.get("photo_file_id")
        or ""
    ).strip()
    return _normalized_text(post.get("text")) + "\0" + media_identity


def dedupe_public_listing_posts(posts: list[dict]) -> list[dict]:
    ordered = sorted(posts, key=lambda post: (_timestamp(post.get("created_at")), int(post.get("id") or 0)), reverse=True)
    last_seen: dict[str, float] = {}
    result: list[dict] = []
    for post in ordered:
        key = public_listing_key(post)
        current = _timestamp(post.get("created_at"))
        previous = last_seen.get(key, 0.0)
        adjacent_duplicate = current > 0 and previous > 0 and abs(previous - current) <= DUPLICATE_WINDOW_SECONDS
        if not adjacent_duplicate:
            result.append(post)
        if current > 0:
            last_seen[key] = current
    return result
