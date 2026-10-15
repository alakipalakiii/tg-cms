import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
const require = createRequire(new URL('../../website/dreary-disk/package.json', import.meta.url));
const { build } = require('esbuild');
const { Miniflare } = require('miniflare');
const entry = process.argv[2] ? resolve(process.argv[2]) : fileURLToPath(new URL('../../workers/api/src/index.ts', import.meta.url));
const compiled = await build({ entryPoints: [entry],
  bundle: true, write: false, format: 'esm', platform: 'browser' });
// The binding throws before any database operation; no production database or network is used.
const fixture = compiled.outputFiles[0].text.replace('async fetch(request, env) {',
  'async fetch(request, env) { env.DB = { prepare() { throw new Error("OFFLINE_DB_BLOCKED"); } };');
assert.notEqual(fixture, compiled.outputFiles[0].text);
const update = { channel_post: { message_id: 1, chat: { id: -1000000000001, type: 'channel' }, text: 'Offline fixture #کتاب' } };
for (const secret of [undefined, '', 'invalid secret', 'fixture-secret']) {
  const mf = new Miniflare({ modules: true, script: fixture, compatibilityDate: '2026-01-01',
    bindings: { ...(secret === undefined ? {} : { TELEGRAM_WEBHOOK_SECRET: secret }), TELEGRAM_SOURCE_CHAT_ID: '-1000000000001' },
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
const source = await readFile(entry, 'utf8');
assert.ok(source.indexOf('telegramWebhookRejection(request, env.TELEGRAM_WEBHOOK_SECRET)')
  < source.indexOf('const update = await request.json();'));
const ingestion = new Miniflare({ modules: true, script: compiled.outputFiles[0].text, compatibilityDate: '2026-01-01',
  bindings: { TELEGRAM_WEBHOOK_SECRET: 'fixture-secret', TELEGRAM_SOURCE_CHAT_ID: '-1000000000001', BOT_ADMIN_IDS: '123', ADMIN_TOKEN: 'fixture-admin' }, d1Databases: ['DB'],
  outboundService: () => { throw new Error('OFFLINE_NETWORK_BLOCKED'); } });
try {
  const db = await ingestion.getD1Database('DB');
  const schema = await readFile(new URL('../../workers/api/migrations/0003_posts_baseline_and_indexes.sql', import.meta.url), 'utf8');
  await db.batch(schema.split(';').filter((sql) => sql.trim()).map((sql) => db.prepare(sql)));
  await db.prepare('CREATE TABLE mahoon_post_tags_v1(post_id INTEGER, tag_norm TEXT, PRIMARY KEY(post_id,tag_norm))').run();
  const deliver = async (body) => {
    const response = await ingestion.dispatchFetch('https://offline.invalid/telegram', { method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Telegram-Bot-Api-Secret-Token': 'fixture-secret' }, body: JSON.stringify(body) });
    assert.equal(response.status, 200); return response.json();
  };
  const photo = { message_id: 11, date: 1700000000, chat: { id: -1000000000001, type: 'channel' },
    caption: 'Fixture #کتاب', photo: [{ file_id: 'fixture-file', file_unique_id: 'fixture-media', width: 640, height: 480 }] };
  assert.equal((await deliver({ channel_post: photo })).saved, true);
  let row = await db.prepare('SELECT * FROM posts').first();
  const stableId = row.id, stableSlug = row.slug;
  assert.equal(row.photo_file_id, 'fixture-file'); assert.equal(row.created_at, '2023-11-14 22:13:20');
  const seo = await ingestion.dispatchFetch('https://offline.invalid/seo/post/' + encodeURIComponent(stableSlug));
  assert.equal(seo.status, 200);
  for (const key of ['admin_note', 'chat_id', 'chat_title', 'deleted_at', 'telegram_message_id']) assert.ok(!(key in (await seo.clone().json()).post));
  assert.equal((await db.prepare('SELECT view_count FROM posts WHERE id=?').bind(stableId).first()).view_count, 0);
  await new Promise((resolve) => setTimeout(resolve, 15));
  assert.equal((await deliver({ channel_post: photo })).duplicate, true);
  assert.equal((await db.prepare('SELECT COUNT(*) AS n FROM posts').first()).n, 1, 'Telegram replay must not insert another row');
  await Promise.all([deliver({ channel_post: photo }), deliver({ channel_post: photo })]);
  assert.equal((await db.prepare('SELECT COUNT(*) AS n FROM posts').first()).n, 1);
  for (const envelope of [{ channel_post: { ...photo, chat: { id: -1000000000002, type: 'channel' } } },
    { message: { ...photo, chat: { id: 999, type: 'private' }, from: { id: 999 } } }]) {
    assert.equal((await deliver(envelope)).reason, 'Unapproved source');
    assert.equal((await db.prepare('SELECT COUNT(*) AS n FROM posts').first()).n, 1);
  }
  assert.equal((await deliver({ edited_channel_post: { ...photo, caption: 'Edited fixture #صوتی' } })).edited, true);
  row = await db.prepare('SELECT * FROM posts').first();
  assert.equal(row.id, stableId); assert.equal(row.slug, stableSlug); assert.equal(row.text, 'Edited fixture #صوتی');
  assert.equal((await db.prepare('SELECT tag_norm FROM mahoon_post_tags_v1 WHERE post_id=?').bind(stableId).first()).tag_norm, 'صوتی');
  await db.prepare("UPDATE posts SET deleted_at='2026-01-01',is_published=0 WHERE id=?").bind(stableId).run();
  await deliver({ channel_post: photo });
  await deliver({ edited_channel_post: photo });
  assert.equal((await db.prepare('SELECT COUNT(*) AS n FROM posts').first()).n, 1);
  row = await db.prepare('SELECT * FROM posts').first();
  assert.equal(row.deleted_at, '2026-01-01'); assert.equal(row.is_published, 0);
  assert.equal((await ingestion.dispatchFetch('https://offline.invalid/admin/posts/' + stableId, { method: 'PATCH',
    headers: { 'Content-Type': 'application/json', 'X-Admin-Token': 'fixture-admin' }, body: JSON.stringify({ deleted_at: null, is_published: 1, text: 'Cannot restore via PATCH' }) })).status, 404);
  assert.equal((await ingestion.dispatchFetch('https://offline.invalid/admin/posts/' + stableId + '/restore',
    { method: 'POST', headers: { 'X-Admin-Token': 'fixture-admin' } })).status, 200);
  row = await db.prepare('SELECT * FROM posts WHERE id=?').bind(stableId).first();
  assert.equal(row.deleted_at, null); assert.equal(row.is_published, 1, 'Dedicated restore must publish, per AGENTS.md');
  const command = (text) => deliver({ message: { message_id: 100, chat: { id: 123, type: 'private' }, from: { id: 123 }, text } });
  assert.equal((await command('/delete ' + stableId)).action, 'delete_preview');
  assert.equal((await db.prepare('SELECT deleted_at FROM posts WHERE id=?').bind(stableId).first()).deleted_at, null);
  await command('/delete confirm ' + stableId);
  assert.ok((await db.prepare('SELECT deleted_at FROM posts WHERE id=?').bind(stableId).first()).deleted_at);
  await command('/restore ' + stableId);
  row = await db.prepare('SELECT * FROM posts WHERE id=?').bind(stableId).first();
  assert.equal(row.deleted_at, null); assert.equal(row.is_published, 1); assert.equal(row.id, stableId); assert.equal(row.slug, stableSlug);
  for (const [position, kind] of ['audio', 'voice', 'video', 'document'].entries()) {
    assert.equal((await deliver({ channel_post: { message_id: 20 + position, date: 1700000000 + position,
      chat: photo.chat, caption: 'Fixture #صوتی', [kind]: { file_id: 'fixture-' + kind, file_unique_id: 'unique-' + kind, duration: 10 } } })).saved, true);
    const media = await db.prepare('SELECT media_type,media_file_id FROM posts WHERE telegram_message_id=?').bind(20 + position).first();
    assert.equal(media.media_type, kind); assert.equal(media.media_file_id, 'fixture-' + kind);
  }
  const adminPost = { ...photo, message_id: 50, chat: { id: 123, type: 'private' }, from: { id: 123 } };
  assert.equal((await deliver({ message: adminPost })).saved, true);
} finally { await ingestion.dispose(); }
const missingSource = new Miniflare({ modules: true, script: fixture, compatibilityDate: '2026-01-01',
  bindings: { TELEGRAM_WEBHOOK_SECRET: 'fixture-secret' }, outboundService: () => { throw new Error('OFFLINE_NETWORK_BLOCKED'); } });
try {
  assert.equal((await missingSource.dispatchFetch('https://offline.invalid/telegram', { method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Telegram-Bot-Api-Secret-Token': 'fixture-secret' },
    body: JSON.stringify(update) })).status, 503);
} finally { await missingSource.dispose(); }
const admin = await readFile(new URL('../../website/dreary-disk/src/pages/admin.astro', import.meta.url), 'utf8');
const restoreCopy = admin.slice(admin.indexOf('async function restoreDeletedPost'), admin.indexOf('function formatAdminNumber'));
assert.ok(restoreCopy.includes('برای انتشار'));
assert.ok(!restoreCopy.includes('پیش‌نویس خصوصی'));
console.log('Telegram boundary and local D1: authentication, source authorization, refresh, sequential/concurrent replay, edits, stable IDs/slugs, deleted-post preservation, photo/audio/voice/video/document; no production writes/network.');
