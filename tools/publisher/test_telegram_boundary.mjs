import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
const require = createRequire(new URL('../../website/dreary-disk/package.json', import.meta.url));
const { build } = require('esbuild');
const { Miniflare } = require('miniflare');
const compiled = await build({ entryPoints: [fileURLToPath(new URL('../../workers/api/src/index.ts', import.meta.url))],
  bundle: true, write: false, format: 'esm', platform: 'browser' });
// The binding throws before any database operation; no production database or network is used.
const fixture = compiled.outputFiles[0].text.replace('async fetch(request, env) {',
  'async fetch(request, env) { env.DB = { prepare() { throw new Error("OFFLINE_DB_BLOCKED"); } };');
assert.notEqual(fixture, compiled.outputFiles[0].text);
const update = { channel_post: { message_id: 1, chat: { id: -1000000000001, type: 'channel' }, text: 'Offline fixture #کتاب' } };
for (const secret of [undefined, '', 'invalid secret', 'fixture-secret']) {
  const mf = new Miniflare({ modules: true, script: fixture, compatibilityDate: '2026-01-01',
    bindings: secret === undefined ? {} : { TELEGRAM_WEBHOOK_SECRET: secret },
    outboundService: () => { throw new Error('OFFLINE_NETWORK_BLOCKED'); } });
  try {
    for (const supplied of [undefined, 'wrong-secret', 'fixture-secret']) {
      const request = (body) => ({ method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(supplied ? { 'X-Telegram-Bot-Api-Secret-Token': supplied } : {}) },
        body: JSON.stringify(body) });
      const response = await mf.dispatchFetch('https://offline.invalid/telegram', request(update));
      const body = await response.json();
      if (!secret || secret === 'invalid secret') assert.equal(response.status, 503);
      else if (supplied !== secret) assert.equal(response.status, 401);
      else { assert.equal(response.status, 500); assert.equal(body.error, 'OFFLINE_DB_BLOCKED'); }
      const empty = await mf.dispatchFetch('https://offline.invalid/telegram', request({}));
      if (secret === 'fixture-secret' && supplied === secret) {
        assert.equal(empty.status, 200); assert.equal((await empty.json()).saved, false);
      } else assert.equal(empty.status, response.status);
    }
    assert.equal((await mf.dispatchFetch('https://offline.invalid/admin/health')).status, 401);
  } finally { await mf.dispose(); }
}
let webhookPayload;
const refresh = new Miniflare({ modules: true, script: fixture, compatibilityDate: '2026-01-01',
  bindings: { TELEGRAM_WEBHOOK_SECRET: 'fixture-secret', ADMIN_TOKEN: 'fixture-admin', BOT_TOKEN: 'fixture-token' },
  outboundService: async (request) => {
    if (new URL(request.url).pathname.endsWith('/setWebhook')) {
      webhookPayload = await request.json();
      return Response.json({ ok: true, result: true });
    }
    assert.ok(new URL(request.url).pathname.endsWith('/getWebhookInfo'));
    return Response.json({ ok: true, result: { url: 'https://offline.invalid/telegram' } });
  } });
try {
  const response = await refresh.dispatchFetch('https://offline.invalid/admin/telegram/webhook-refresh',
    { method: 'POST', headers: { 'X-Admin-Token': 'fixture-admin' } });
  assert.equal(response.status, 200);
  assert.equal(webhookPayload.secret_token, 'fixture-secret');
  assert.equal(webhookPayload.drop_pending_updates, false);
  assert.deepEqual(webhookPayload.allowed_updates, ['message', 'edited_message', 'channel_post', 'edited_channel_post']);
  assert.ok(!(await response.text()).includes('fixture-secret'));
} finally { await refresh.dispose(); }
const source = await readFile(new URL('../../workers/api/src/index.ts', import.meta.url), 'utf8');
assert.ok(source.indexOf('telegramWebhookRejection(request, env.TELEGRAM_WEBHOOK_SECRET)')
  < source.indexOf('const update = await request.json();'));
console.log('Telegram boundary: actual workerd runtime, missing/invalid configuration, unsigned/wrong/correct token, empty update, admin boundary; no real writes/network.');
