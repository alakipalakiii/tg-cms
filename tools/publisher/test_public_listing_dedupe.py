from __future__ import annotations

from public_listing_dedupe import dedupe_public_listing_posts


def _post(post_id: int, created_at: str, text: str = "معنای زندگی چیست؟", media: str = "AQADzw9rG8djMFF-") -> dict:
    return {"id": post_id, "created_at": created_at, "text": text, "media_unique_id": media}


def test_exact_adjacent_source_duplicates_collapse_to_one_listing_record() -> None:
    posts = [
        _post(101, "2026-09-12 12:02:00"),
        _post(100, "2026-09-12 12:00:00"),
        _post(99, "2026-09-12 11:58:00"),
    ]
    result = dedupe_public_listing_posts(posts)
    assert [post["id"] for post in result] == [101]


def test_same_content_outside_window_is_preserved() -> None:
    posts = [
        _post(101, "2026-09-12 12:30:00"),
        _post(100, "2026-09-12 12:00:00"),
    ]
    result = dedupe_public_listing_posts(posts)
    assert [post["id"] for post in result] == [101, 100]


def test_different_media_is_not_collapsed() -> None:
    posts = [
        _post(101, "2026-09-12 12:02:00", media="media-a"),
        _post(100, "2026-09-12 12:00:00", media="media-b"),
    ]
    assert len(dedupe_public_listing_posts(posts)) == 2
