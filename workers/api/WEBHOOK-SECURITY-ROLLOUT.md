# Telegram security rollout: prepared, NOT DEPLOYED

## Current boundary and owner decision — 2026-10-15

SEC-01 remains confirmed and unmitigated. Preserve working ingestion. Never request, extract, export, rotate or replace BOT_TOKEN; never create a public migration endpoint or a real test channel post. Do not deploy repository API wholesale. INGEST-01/replay and RESTORE-01 backend corrections remain held with this surgical API patch.

Fresh Cloudflare GET source still hashes to `a0d53ba90599742076845aa156e40969590b4ef3180152fc4420e66b1764cbd1` (161176 bytes). API deployment `375258db-cb64-4154-a685-ee380f1e87a3`, version `ea717386-6580-4d39-93a0-6c224deae34e` serves100%. It differs from repository source. BOT_TOKEN and ADMIN_TOKEN are opaque secret bindings; TELEGRAM_WEBHOOK_SECRET and TELEGRAM_SOURCE_CHAT_ID are absent. Existing bindings, webhook and API traffic have not changed.

The generic live POST branch accepts unsigned channel updates. Isolated copies reached INSERT with a throwing mock DB and no outbound access; hosted empty-update probes returned200/saved=false. This establishes a missing trust boundary, not a historical-compromise finding. Never authenticate new content solely from these API rows. The revision192 addition was separately matched against the official public Telegram message1689; that corroboration does not repair SEC-01 or authenticate a numeric source-chat ID.

## Prepared correction and tests

- `src/telegramWebhook.ts`: official secret header checked with timing-safe comparison before JSON parsing, management, DB or Telegram operations. Missing/invalid configuration503; missing/wrong header401.
- Source allowlist: configured source channel or existing configured admins. Resolve the numeric channel using authenticated Bot API getChat, not STORAGE_CHAT_ID or untrusted inbound rows.
- Atomic INSERT SELECT WHERE NOT EXISTS blocks sequential/concurrent replays by (telegram_message_id,chat_id), preserves deleted rows, stable database IDs/slugs and edits. No schema migration or historical-row deletion.
- Dedicated API/bot restore sets deleted_at=NULL/is_published=1. Generic PATCH cannot restore. Bot delete remains preview then confirm. Admin copy remains compatible with old/new API results.
- Existing protected GET `/admin/telegram/webhook-info` adds `MAHOON_WEBHOOK_READINESS_V1`; POST `/admin/telegram/webhook-refresh` uses the opaque server-side BOT_TOKEN. No token export is needed. Both require existing ADMIN_TOKEN.
- Readiness verifies configured secret/source, exact existing HTTPS same-origin URL, known settings and authenticated getChat of @mahoonartmagazine (numeric ID, channel type, username). Foreign/missing/credential-bearing/fragment URLs and custom certificates require review; no URL rewrite or fallback. Invoke on the provider-verified existing webhook origin, including its original alias if applicable.
- Refresh preserves the byte-exact URL, existing allowed_updates (including empty arrays) and max_connections. If allowed_updates is absent, omit it so Telegram retains its previous setting. Always drop_pending_updates=false. Secret is passed only to Telegram, never returned. Require acknowledgement and unchanged readback; ambiguous results return502 and must be reconciled, never automatically retried.
- Tests run in real local workerd with fake Bot API/local D1: authentication, wrong/missing config, wrong channel, URL/settings rejection, omitted/empty update types, readback drift, failed acknowledgement, sanitized Bot API errors, sequential/concurrent replay, edits, delete/restore, SEO read-only/private-field exclusions and photo/audio/voice/video/document identities. No production writes or Telegram requests.
- Both repository entry and the surgical prepared copy of the authoritative live module pass `node tools/publisher/test_telegram_boundary.mjs [private-prepared-entry]`. Prepared private entry SHA256 `89661089584e5687e178d4f4ba99db54ba22a5df48a99d22253aedce123128e4`; includes an absolute local helper import, so this is a preparation receipt, not a deployable bundle identity. The standalone prepared bundle also passes the same suite, SHA256 `60709158493e7841e9a28a33c85aa5f3ff9e3d9897b2fdb7c652f2e44c2c8d82`. An additional isolated workerd smoke test uses the actual live compatibility date/flags with fake credentials and outbound Bot API: timing-safe guard on both POST paths and protected inspection/registration PASS. Recheck the final staged module and settings before activation.

## Exact remaining owner action

An existing protected administrative interface genuinely exists in the API; the current website admin screen has no webhook control. This environment has neither an authenticated ADMIN session nor an authenticated Cloudflare browser session (provider displays sign-in); no supported current authenticated registration was performed. Public channel access is not administrative authorization. Read-only GitHub repository secret-name inventory also confirms only the two Cloudflare credential entries, with no ADMIN/BOT/Telegram credential binding available to a workflow; no secret value was read.

The minimal owner action is to authenticate to the existing protected helper with the **existing ADMIN_TOKEN**, through a trusted local terminal or approved authenticated admin client, after a reviewed zero-percent candidate is ready. BOT_TOKEN remains inside Cloudflare. Do not send either token in chat or put it in a plaintext temporary file. A trusted PowerShell terminal can collect ADMIN_TOKEN using Read-Host -AsSecureString and construct the X-Admin-Token header only in process memory; never log headers, full webhook responses or transcripts. No credential is requested by this document.

Use an explicit version override for the zero-percent candidate on the provider-verified existing origin. First GET webhook-info and require readiness.contract=MAHOON_WEBHOOK_READINESS_V1, ready=true and source_verified=true. **If the marker is absent, stop before POST**: Cloudflare can ignore an override and route to the old helper, which rewrites URLs. Review the private existing URL/update settings. Then make exactly one authenticated POST webhook-refresh with the same override, require refreshed=true/acknowledgement and reconcile readback. Do not use the old deployed helper to register security settings.

Example for a trusted local PowerShell session, **only after staging/backup review below**. Replace the two public identity placeholders from independently verified Cloudflare evidence before entering ADMIN_TOKEN. Do not run with transcription/debug logging. This performs one registration POST and never prints its private response:

```powershell
$webhookOrigin = 'https://<provider-verified-current-webhook-origin>'
$candidateVersion = '<reviewed-zero-percent-api-version-uuid>'
$parsedVersion = [guid]::Empty
if ($webhookOrigin.Contains('<') -or
    -not [guid]::TryParse($candidateVersion, [ref]$parsedVersion)) { throw 'Fill verified identities first' }
$originUri = [uri]$webhookOrigin
if ($originUri.Scheme -ne 'https' -or $originUri.UserInfo -or
    $originUri.Query -or $originUri.Fragment -or $originUri.AbsolutePath -ne '/') { throw 'Invalid origin' }
$secureAdmin = Read-Host 'Existing ADMIN_TOKEN (local only)' -AsSecureString
$headers = @{}
try {
  $headers['X-Admin-Token'] = [System.Net.NetworkCredential]::new('', $secureAdmin).Password
  $headers['Cloudflare-Workers-Version-Overrides'] = 'tg-cms-api="' + $candidateVersion + '"'
  $info = Invoke-RestMethod ($webhookOrigin.TrimEnd('/') + '/admin/telegram/webhook-info') -Headers $headers
  if (-not $info.ok -or $info.readiness.contract -ne 'MAHOON_WEBHOOK_READINESS_V1' -or
      $info.readiness.ready -ne $true -or $info.readiness.source_verified -ne $true) { throw 'Readiness rejected; no registration' }
  $registered = Invoke-RestMethod ($webhookOrigin.TrimEnd('/') + '/admin/telegram/webhook-refresh') -Method Post -Headers $headers
  if ($registered.ok -ne $true -or $registered.refreshed -ne $true -or
      $registered.telegram_set_result -ne $true) { throw 'Reconcile; do not retry' }
  Write-Output 'Registration acknowledged; operator must reconcile live delivery before activation.'
} finally {
  $headers.Clear()
  Remove-Variable secureAdmin, info, registered -ErrorAction SilentlyContinue
}
```

The recipe was parsed and executed only against offline stubs in six scenarios: old helper/ignored override, not ready, source mismatch, failed inspection, failed acknowledgement and success. Rejected inspections made zero POSTs; acknowledgement failure made exactly one POST with no retry. No real credential or network was used. The assistant has not run this production operation. An HTTP/network error after POST is ambiguous; do not rerun the recipe until the operator reconciles it.

If the owner cannot use existing ADMIN authentication, activation stays held. A new public bridge, credential export or speculative replacement credential is not an alternative. The assistant can finish independent website work meanwhile.

## Backup, staging, activation and rollback preparation

1. Immediately before rollout, re-read authoritative API deployment, source and binding names; abort on source drift. Preserve private original module/settings/traffic and their digests. Apply only the reviewed patch to that module, preserving live-only behavior and all bindings.
2. Read-only D1 Time Travel inspection confirmed storage version production and an available native bookmark. Private receipt SHA256 `4c51a8e584f025c8c702ea171f5e304c49ef7c6ac573afbc15906abb526b4a13`. Time Travel is provider-native automatic backup; refresh the bookmark and verify recovery access immediately before any major Worker/D1 change. No restore was executed. Full D1 export can block other requests; it was not run during active ingestion. If an offline export is required, coordinate an accepted safe window first; never delete virtual tables to make an export work.
3. Resolve the official channel through authenticated getChat using server-side BOT_TOKEN. A syntactically valid source ID from private D1 records can be provisioned on the zero-percent candidate only as an **untrusted provisional value**. The protected readiness call then resolves the official username using server-side getChat. Its verified_channel_id is returned only after authenticated channel type/username validation. If it differs from the provisional binding, readiness stays false and POST cannot register; correct only the staged source binding from that authenticated evidence and repeat the read-only GET. Never infer numeric-source authenticity from D1 alone. Create a strong new webhook secret with secure provider/local handling. Configure TELEGRAM_SOURCE_CHAT_ID and TELEGRAM_WEBHOOK_SECRET only on the staged version; preserve opaque existing BOT_TOKEN/ADMIN_TOKEN and all other bindings. `wrangler secret put` deploys immediately: do not use it for this staging step. Use reviewed version-scoped settings/secrets and inspect the final sealed staged version.
4. Add the tested candidate to the API deployment at0%, retaining the current version at100%; do not activate fail-closed ingestion yet. Verify version attribution and the protected read-only readiness marker before the owner performs the one registration above. Test candidate missing/wrong-header rejection without any fabricated channel content. The old API accepts the newly added Telegram header while serving100%.
5. Only after matching registration is acknowledged and reconciled, activate the reviewed API candidate through a bounded deployment with recorded rollback identity. Verify actual traffic, public reads/admin401, unsigned empty-update401, authenticated read-only readiness/pending/error state and naturally arriving authorized delivery. Do not generate a real test post. Do not call security PASS before actual live enforcement and delivery evidence.
6. Preserve sanitized evidence. If registration outcome is ambiguous, inspect readback and delivery before any retry. If candidate activation harms ingestion, use the recorded baseline API version and reviewed Cloudflare deployment procedure: the old API tolerates the extra secret header and keeps the same URL/update types. Do not delete the webhook, drop pending updates or rotate credentials. A rollback reopens SEC-01 and must be reported explicitly. Never restore an older D1 snapshot as routine code rollback; that could erase legitimate incoming posts. No rollback was executed during readiness work.

## Primary references

[Telegram setWebhook](https://core.telegram.org/bots/api#setwebhook), [Cloudflare timingSafeEqual](https://developers.cloudflare.com/workers/runtime-apis/web-crypto/#timingsafeequal), [version overrides and fallback behavior](https://developers.cloudflare.com/workers/versions-and-deployments/version-overrides/), [secrets and version-scoped changes](https://developers.cloudflare.com/workers/configuration/secrets/), [D1 Time Travel](https://developers.cloudflare.com/d1/reference/time-travel/), [D1 export blocking/limitations](https://developers.cloudflare.com/d1/best-practices/import-export-data/).
