# Mahoon API Worker Source

This folder is reserved for keeping the source code of the Mahoon Art Magazine API Worker in GitHub for backup and development.

The live API Worker is currently managed directly in Cloudflare. This repository should not be treated as the active deployment source until that workflow is explicitly changed.

## Secrets

Secrets and environment-specific values must only be configured in Cloudflare Variables and Secrets.

Do not write real values for these variables into repository files:

- `BOT_TOKEN`
- `ADMIN_TOKEN`
- `STORAGE_CHAT_ID`
- `SITE_PUBLIC_URL`

## Source Code

The real Worker source code should be copied from Cloudflare later and saved in:

```text
src/index.ts
```

Until then, `src/index.ts` is only a safe placeholder.
