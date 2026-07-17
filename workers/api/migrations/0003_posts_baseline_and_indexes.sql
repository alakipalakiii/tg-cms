-- Mahoon posts schema baseline and integrity indexes v1.
-- CREATE TABLE IF NOT EXISTS is a no-op on the existing production table.
CREATE TABLE IF NOT EXISTS posts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  text TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  slug TEXT,
  telegram_message_id INTEGER,
  chat_id TEXT,
  chat_title TEXT,
  updated_at DATETIME,
  media_type TEXT,
  photo_file_id TEXT,
  photo_unique_id TEXT,
  photo_width INTEGER,
  photo_height INTEGER,
  is_published INTEGER DEFAULT 1,
  deleted_at DATETIME,
  seo_title TEXT,
  seo_description TEXT,
  admin_note TEXT,
  view_count INTEGER DEFAULT 0,
  last_viewed_at DATETIME,
  media_file_id TEXT,
  media_unique_id TEXT,
  media_mime_type TEXT,
  media_file_name TEXT,
  media_duration INTEGER,
  media_width INTEGER,
  media_height INTEGER,
  media_size INTEGER
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_posts_slug_unique_nonempty
  ON posts(slug)
  WHERE slug IS NOT NULL AND slug != '';

CREATE INDEX IF NOT EXISTS idx_posts_public_created_id
  ON posts(created_at DESC, id DESC)
  WHERE slug IS NOT NULL
    AND slug != ''
    AND (deleted_at IS NULL OR deleted_at = '')
    AND (is_published = 1 OR is_published IS NULL);

CREATE INDEX IF NOT EXISTS idx_posts_active_created_id
  ON posts(created_at DESC, id DESC)
  WHERE deleted_at IS NULL OR deleted_at = '';

CREATE INDEX IF NOT EXISTS idx_posts_deleted_at_id
  ON posts(deleted_at DESC, id DESC)
  WHERE deleted_at IS NOT NULL AND deleted_at != '';

CREATE INDEX IF NOT EXISTS idx_posts_telegram_message_id
  ON posts(telegram_message_id)
  WHERE telegram_message_id IS NOT NULL;
