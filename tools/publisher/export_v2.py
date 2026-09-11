"""Complete, fail-closed keyset export for the publisher control plane."""
from __future__ import annotations

from urllib.parse import urlencode

try:
    from .content_transport import fetch_json
except ImportError:
    from content_transport import fetch_json

CONTRACT = "posts-full-public-v2"
DEFAULT_PAGE_SIZE = 250
MAX_PAGES = 100_000


def export_complete(endpoint: str, page_size: int = DEFAULT_PAGE_SIZE) -> tuple[dict, dict]:
    if not isinstance(page_size, int) or not 1 <= page_size <= 500:
        raise RuntimeError("invalid V2 page size")

    cursor = 0
    snapshot_max_id = None
    snapshot_total_count = None
    items: list[dict] = []
    seen: set[int] = set()
    page_count = 0
    request_url = endpoint

    while True:
        query = {"page_size": page_size, "cursor": cursor}
        if snapshot_max_id is not None:
            query["snapshot_max_id"] = snapshot_max_id
            query["snapshot_total_count"] = snapshot_total_count
        separator = "&" if "?" in request_url else "?"
        payload, _meta = fetch_json(request_url + separator + urlencode(query))
        if not isinstance(payload, dict) or payload.get("contract") != CONTRACT or payload.get("ok") is not True:
            raise RuntimeError("V2 export contract mismatch")
        page_max = payload.get("snapshot_max_id")
        page_total = payload.get("snapshot_total_count")
        page_items = payload.get("items")
        if not isinstance(page_max, int) or not isinstance(page_total, int) or not isinstance(page_items, list):
            raise RuntimeError("V2 export page shape invalid")
        if snapshot_max_id is None:
            snapshot_max_id = page_max
            snapshot_total_count = page_total
        elif page_max != snapshot_max_id or page_total != snapshot_total_count:
            raise RuntimeError("V2 snapshot metadata changed")

        last_id = cursor
        for item in page_items:
            if not isinstance(item, dict) or not isinstance(item.get("id"), int):
                raise RuntimeError("V2 item shape invalid")
            item_id = item["id"]
            if item_id <= last_id or item_id > snapshot_max_id:
                raise RuntimeError("V2 cursor ordering or snapshot bound failed")
            if item_id in seen:
                raise RuntimeError("V2 duplicate id")
            seen.add(item_id)
            items.append(item)
            last_id = item_id

        page_count += 1
        has_more = payload.get("has_more")
        next_cursor = payload.get("next_cursor")
        if not isinstance(has_more, bool):
            raise RuntimeError("V2 has_more is invalid")
        if not has_more:
            if next_cursor is not None:
                raise RuntimeError("V2 terminal page has a cursor")
            break
        if not isinstance(next_cursor, int) or next_cursor <= cursor:
            raise RuntimeError("V2 cursor did not progress")
        cursor = next_cursor
        request_url = endpoint
        if page_count >= MAX_PAGES:
            raise RuntimeError("V2 export exceeded page bound")

    if len(items) != snapshot_total_count:
        raise RuntimeError("V2 export cardinality mismatch")
    return {
        "contract": "PUBLISHED_CONTENT_DELTA_CONTRACT_V2",
        "count": len(items),
        "posts": items,
    }, {
        "contract": CONTRACT,
        "page_count": page_count,
        "collected_posts": len(items),
        "snapshot_max_id": snapshot_max_id,
        "snapshot_total_count": snapshot_total_count,
        "duplicate_ids": 0,
        "status": "PASS",
    }
