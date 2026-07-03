# Mahoon API Worker Source

This folder is reserved for keeping the source code of the Mahoon Art Magazine API Worker in GitHub for backup and development.

The live API Worker is currently managed directly in Cloudflare. This repository should not be treated as the active deployment source until that workflow is explicitly changed.

## Secrets

The API Worker uses environment values such as `env.BOT_TOKEN`, `env.ADMIN_TOKEN`, `env.STORAGE_CHAT_ID`, and `env.SITE_PUBLIC_URL`.

Secrets and environment-specific values must only be configured in Cloudflare Variables and Secrets.

Do not write real values for these variables into repository files:

- `BOT_TOKEN`
- `ADMIN_TOKEN`
- `STORAGE_CHAT_ID`
- `SITE_PUBLIC_URL`

Real local files such as `.env`, `.dev.vars`, and `wrangler.toml` must not be committed.

## Source Code

The real Worker source code should be copied from Cloudflare later and saved in:

```text
src/index.ts
```

Until then, `src/index.ts` is only a safe placeholder.

## Admin Endpoints

Admin endpoints must be protected by `ADMIN_TOKEN`.

### `GET /admin/posts/deleted`

- Admin-only.
- Returns only posts where `deleted_at IS NOT NULL`.
- Used by the Deleted tab in the admin panel.
- Does not change any data.

### `POST /admin/posts/:id/restore`

- Admin-only.
- Works only with the database `id` from the `posts` table.
- Restores only a post where `deleted_at IS NOT NULL`.
- Restore means:

  ```sql
  is_published = 1
  deleted_at = NULL
  updated_at = CURRENT_TIMESTAMP
  ```

- The stable post ID does not change after restore.
- This is not hard delete.
