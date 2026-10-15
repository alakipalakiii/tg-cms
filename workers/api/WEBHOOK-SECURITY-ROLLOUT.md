# Inbound Telegram authentication: pending coordinated production rollout

Status: prepared and tested; **not deployed**. Do not deploy repository API wholesale.

## Evidence

The authoritative live API module SHA256 is `a0d53ba90599742076845aa156e40969590b4ef3180152fc4420e66b1764cbd1`.
Its generic POST branch accepts unsigned channel updates. An isolated copy reached `INSERT INTO posts` on both `/telegram` and an unrelated route; the mock database threw before execution and all outbound network was disabled. Hosted run `38708829025` confirmed both routes accept empty unsigned updates with HTTP200/saved=false. No forged content was submitted to production. This establishes missing inbound authentication; it is not evidence of a historical compromise.

The live Worker has BOT_TOKEN and ADMIN_TOKEN secret bindings, but no TELEGRAM_WEBHOOK_SECRET. Neither existing token is available in the execution environment. The actual API bundle differs from repository source; preserve live-only logic and all bindings during a surgical rollout.

## Prepared correction

- `src/telegramWebhook.ts` validates the official secret-token header with Workers' timing-safe comparison before parsing or handling a Telegram update.
- Missing/invalid configuration returns503; absent/wrong token returns401 before database or Telegram operations.
- Authenticated empty updates remain200/saved=false; existing extraction, stable IDs and management logic are unchanged.
- Content from other Telegram chats is ignored unless it is from an existing configured admin. TELEGRAM_SOURCE_CHAT_ID must be resolved from the official channel through Bot API getChat; STORAGE_CHAT_ID is a separate media destination and must not be assumed to be the source.
- An atomic INSERT SELECT WHERE NOT EXISTS suppresses replays by (telegram_message_id,chat_id), including previously deleted messages. Existing historical rows are preserved. Edits still update by stable database ID and retain the slug.
- The authenticated webhook-refresh helper passes the configured secret to setWebhook and keeps drop_pending_updates=false and all four existing update types. It never returns the secret.
- `node tools/publisher/test_telegram_boundary.mjs` checks the compiled repository API in real local workerd, including refresh with a fake Bot API. No real database, Telegram request or post mutation is used.

## Safe rollout order

1. Refresh actual live API version/source digest, bindings and webhook URL. Export and privately verify a D1 backup before changing the Worker. Save rollback identity privately.
2. Obtain temporary secure access to the owner's existing Bot API credential, or have the owner perform the next registration step. Never send tokens in chat or commit them.
3. Resolve the official @mahoonartmagazine channel with getChat, compare its numeric ID with the recent source rows privately, and prepare TELEGRAM_SOURCE_CHAT_ID. Generate a new random webhook secret. Call getWebhookInfo and setWebhook with the **existing URL**, existing allowed_updates, new secret_token and drop_pending_updates=false. Keep the original API running during this step: it already accepts the added header. Do not rotate BOT_TOKEN or discard pending updates.
4. Apply only the tested guard/refresh correction to the verified current live module, preserving live-only logic, D1 binding and all existing settings. Bind TELEGRAM_WEBHOOK_SECRET to the same value. Test the candidate before traffic change; unknown/missing tokens must not reach any database or network operation.
5. Activate through a reviewed, bounded API deployment with rollback evidence. Verify public reads/admin401 and unsigned empty-update401 from hosted probes. Check real webhook pending/error state without sending a test channel message.
6. Retain sanitized evidence and exact source/deployment hashes; remove any temporary local credential file. A rollback must keep Telegram registration and the API authentication configuration compatible.

Do not deploy a fail-closed guard ahead of Telegram registration. Do not add a public migration endpoint, export existing Worker secrets, overwrite the API from stale repository source, or claim this issue fixed before live enforcement is verified.

Sources: [Telegram setWebhook](https://core.telegram.org/bots/api#setwebhook), [Cloudflare timingSafeEqual](https://developers.cloudflare.com/workers/runtime-apis/web-crypto/#timingsafeequal).
