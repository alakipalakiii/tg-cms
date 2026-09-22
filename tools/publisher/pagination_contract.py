"""Shared public archive pagination contract."""
from __future__ import annotations

PAGE_SIZE = 20


def page_count(item_count: int) -> int:
    return (max(0, item_count) + PAGE_SIZE - 1) // PAGE_SIZE