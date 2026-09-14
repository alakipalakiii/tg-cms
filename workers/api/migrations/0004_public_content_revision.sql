-- Authoritative public-content revision control record.
-- The singleton row is the only object read by the Publisher revision endpoint.
INSERT OR IGNORE INTO site_settings (key, value, updated_at)
VALUES (
  'public_content_revision',
  json_object('revision', 1, 'changed_at', CURRENT_TIMESTAMP),
  CURRENT_TIMESTAMP
);

-- New public posts advance the revision atomically with the INSERT.
CREATE TRIGGER IF NOT EXISTS mahoon_public_content_revision_after_insert
AFTER INSERT ON posts
WHEN (NEW.deleted_at IS NULL OR NEW.deleted_at = '')
 AND COALESCE(NEW.is_published, 1) = 1
BEGIN
  UPDATE site_settings
  SET value = json_object(
        'revision', CAST(json_extract(value, '$.revision') AS INTEGER) + 1,
        'changed_at', CURRENT_TIMESTAMP
      ),
      updated_at = CURRENT_TIMESTAMP
  WHERE key = 'public_content_revision';
END;

-- Any public-facing post field change advances the revision atomically with the UPDATE.
-- view_count and last_viewed_at are intentionally excluded: page views are not content changes.
CREATE TRIGGER IF NOT EXISTS mahoon_public_content_revision_after_update
AFTER UPDATE OF
  text,
  created_at,
  slug,
  telegram_message_id,
  chat_id,
  chat_title,
  updated_at,
  is_published,
  deleted_at,
  seo_title,
  seo_description,
  admin_note,
  media_type,
  media_file_id,
  media_unique_id,
  media_mime_type,
  media_file_name,
  media_duration,
  media_width,
  media_height,
  media_size,
  photo_file_id,
  photo_unique_id,
  photo_width,
  photo_height
ON posts
WHEN (
       ((OLD.deleted_at IS NULL OR OLD.deleted_at = '') AND COALESCE(OLD.is_published, 1) = 1)
    OR ((NEW.deleted_at IS NULL OR NEW.deleted_at = '') AND COALESCE(NEW.is_published, 1) = 1)
  )
 AND (
       OLD.text IS NOT NEW.text
    OR OLD.created_at IS NOT NEW.created_at
    OR OLD.slug IS NOT NEW.slug
    OR OLD.telegram_message_id IS NOT NEW.telegram_message_id
    OR OLD.chat_id IS NOT NEW.chat_id
    OR OLD.chat_title IS NOT NEW.chat_title
    OR OLD.updated_at IS NOT NEW.updated_at
    OR OLD.is_published IS NOT NEW.is_published
    OR OLD.deleted_at IS NOT NEW.deleted_at
    OR OLD.seo_title IS NOT NEW.seo_title
    OR OLD.seo_description IS NOT NEW.seo_description
    OR OLD.admin_note IS NOT NEW.admin_note
    OR OLD.media_type IS NOT NEW.media_type
    OR OLD.media_file_id IS NOT NEW.media_file_id
    OR OLD.media_unique_id IS NOT NEW.media_unique_id
    OR OLD.media_mime_type IS NOT NEW.media_mime_type
    OR OLD.media_file_name IS NOT NEW.media_file_name
    OR OLD.media_duration IS NOT NEW.media_duration
    OR OLD.media_width IS NOT NEW.media_width
    OR OLD.media_height IS NOT NEW.media_height
    OR OLD.media_size IS NOT NEW.media_size
    OR OLD.photo_file_id IS NOT NEW.photo_file_id
    OR OLD.photo_unique_id IS NOT NEW.photo_unique_id
    OR OLD.photo_width IS NOT NEW.photo_width
    OR OLD.photo_height IS NOT NEW.photo_height
  )
BEGIN
  UPDATE site_settings
  SET value = json_object(
        'revision', CAST(json_extract(value, '$.revision') AS INTEGER) + 1,
        'changed_at', CURRENT_TIMESTAMP
      ),
      updated_at = CURRENT_TIMESTAMP
  WHERE key = 'public_content_revision';
END;

-- Hard delete is not an approved application operation, but this trigger keeps the
-- invariant true if a future maintenance path removes a row.
CREATE TRIGGER IF NOT EXISTS mahoon_public_content_revision_after_delete
AFTER DELETE ON posts
WHEN (OLD.deleted_at IS NULL OR OLD.deleted_at = '')
 AND COALESCE(OLD.is_published, 1) = 1
BEGIN
  UPDATE site_settings
  SET value = json_object(
        'revision', CAST(json_extract(value, '$.revision') AS INTEGER) + 1,
        'changed_at', CURRENT_TIMESTAMP
      ),
      updated_at = CURRENT_TIMESTAMP
  WHERE key = 'public_content_revision';
END;
