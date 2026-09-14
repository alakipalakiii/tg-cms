"""Canonical exact-tag taxonomy used by the immutable publisher snapshot."""
from __future__ import annotations

import re


AUDIO_BOOK_TAGS = (
    "کتاب_گویا", "کتاب‌گویا", "کتابگویا",
    "کتاب_صوتی", "کتاب‌صوتی", "کتابصوتی",
)
CATEGORY_DEFINITIONS = (
    ("کتاب", ("کتاب", *AUDIO_BOOK_TAGS)),
    ("دیالوگ ها", ("دیالوگ", "دیالوگ‌ها", "دیالوگ_ها", "دیالوگها")),
    ("صوتی", ("صوتی", "صدا", "موسیقی", *AUDIO_BOOK_TAGS)),
    ("شعر و متن", ("متن", "متن‌ها", "متن_ها", "متنها", "شعر", "اشعار", "شعرها", "شعر_ها")),
    ("نقاشی", ("نقاشی",)),
)


def normalize_tag(value: object) -> str:
    return re.sub(
        r"\s+",
        " ",
        str(value or "")
        .lstrip("#")
        .replace("ي", "ی").replace("ى", "ی").replace("ك", "ک")
        .replace("\u200c", "").replace("\u200f", "").replace("_", " "),
    ).strip().lower()


def exact_hashtags(text: object) -> set[str]:
    return {
        normalize_tag(item)
        for item in re.findall(r"(?:^|\s)#([^\s#@]+)", str(text or ""), flags=re.UNICODE)
        if item
    }


def canonical_category(post: dict) -> str | None:
    tags = exact_hashtags(post.get("text", ""))
    for label, variants in CATEGORY_DEFINITIONS:
        if any(normalize_tag(variant) in tags for variant in variants):
            return label
    return None
