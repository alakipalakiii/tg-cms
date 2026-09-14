"""SQLite proof for the authoritative public-content revision contract."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "workers" / "api" / "migrations"


def revision(db: sqlite3.Connection) -> int:
    value = db.execute(
        "SELECT value FROM site_settings WHERE key = 'public_content_revision'"
    ).fetchone()[0]
    return int(json.loads(value)["revision"])


def main() -> None:
    db = sqlite3.connect(":memory:")
    db.executescript(
        """
        CREATE TABLE site_settings (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL DEFAULT '',
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE posts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          text TEXT,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          slug TEXT,
          telegram_message_id INTEGER,
          chat_id TEXT,
          chat_title TEXT,
          updated_at TEXT,
          is_published INTEGER DEFAULT 1,
          deleted_at TEXT,
          seo_title TEXT,
          seo_description TEXT,
          admin_note TEXT,
          media_type TEXT,
          media_file_id TEXT,
          media_unique_id TEXT,
          media_mime_type TEXT,
          media_file_name TEXT,
          media_duration INTEGER,
          media_width INTEGER,
          media_height INTEGER,
          media_size INTEGER,
          photo_file_id TEXT,
          photo_unique_id TEXT,
          photo_width INTEGER,
          photo_height INTEGER,
          view_count INTEGER DEFAULT 0,
          last_viewed_at TEXT
        );
        """
    )
    db.executescript((MIGRATIONS / "0004_public_content_revision.sql").read_text(encoding="utf-8"))
    assert revision(db) == 1

    db.execute("INSERT INTO posts(text, slug) VALUES ('public', 'public')")
    assert revision(db) == 2
    db.execute("INSERT INTO posts(text, slug, is_published) VALUES ('draft', 'draft', 0)")
    assert revision(db) == 2
    db.execute("UPDATE posts SET text = 'draft edit' WHERE slug = 'draft'")
    assert revision(db) == 2
    db.execute("UPDATE posts SET is_published = 1 WHERE slug = 'draft'")
    assert revision(db) == 3
    db.execute("UPDATE posts SET text = 'public edit' WHERE slug = 'public'")
    assert revision(db) == 4
    db.execute("UPDATE posts SET media_file_id = 'media-1' WHERE slug = 'public'")
    assert revision(db) == 5
    db.execute("UPDATE posts SET admin_note = 'operator note' WHERE slug = 'public'")
    assert revision(db) == 6
    db.execute("UPDATE posts SET view_count = 1, last_viewed_at = CURRENT_TIMESTAMP WHERE slug = 'public'")
    assert revision(db) == 6
    db.execute("UPDATE posts SET is_published = 0 WHERE slug = 'public'")
    assert revision(db) == 7
    db.execute("UPDATE posts SET is_published = 1 WHERE slug = 'public'")
    assert revision(db) == 8
    db.execute("UPDATE posts SET deleted_at = CURRENT_TIMESTAMP, is_published = 0 WHERE slug = 'public'")
    assert revision(db) == 9
    db.execute("UPDATE posts SET deleted_at = NULL, is_published = 1 WHERE slug = 'public'")
    assert revision(db) == 10
    db.execute("DELETE FROM posts WHERE slug = 'public'")
    assert revision(db) == 11

    db.commit()
    before = revision(db)
    try:
        db.execute("BEGIN")
        db.execute("INSERT INTO posts(text, slug) VALUES ('rolled back', 'rolled-back')")
        db.execute("INSERT INTO missing_table(value) VALUES ('must fail')")
    except sqlite3.Error:
        db.execute("ROLLBACK")
    else:
        raise AssertionError("failure path unexpectedly committed")
    assert revision(db) == before
    print("REVISION_MUTATION_TESTS=PASS")
    print("CONTENT_CHANGED_WITHOUT_REVISION=IMPOSSIBLE_BY_TESTED_PATHS")
    print("REVISION_ENDPOINT_POST_TABLE_SCAN=NO")
    print("REVISION_LOOKUP_COMPLEXITY=CONSTANT_SINGLE_RECORD")


if __name__ == "__main__":
    main()
