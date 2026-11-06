import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
const require = createRequire(new URL('../../website/dreary-disk/package.json', import.meta.url));
const { build } = require('esbuild');
const { Miniflare } = require('miniflare');
const compiled = await build({ entryPoints: [fileURLToPath(new URL('../../workers/api/src/index.ts', import.meta.url))], bundle: true, write: false, format: 'esm', platform: 'browser' });
const mf = new Miniflare({ modules: true, script: compiled.outputFiles[0].text, compatibilityDate: '2026-01-01', d1Databases: ['DB'],
  bindings: { ADMIN_TOKEN: 'fixture-admin', BOT_TOKEN: 'fixture-bot', BOT_ADMIN_IDS: '22', TELEGRAM_WEBHOOK_SECRET: 'fixture-secret', TELEGRAM_SOURCE_CHAT_ID: '-1000000000001' },
  outboundService: request => { assert.equal(new URL(request.url).hostname, 'api.telegram.org'); return Response.json({ ok: true, result: true }); } });
const headers = { 'Content-Type': 'application/json', 'X-Admin-Token': 'fixture-admin' };
async function request(path, method = 'GET', body, authenticated = true) {
  const response = await mf.dispatchFetch('https://offline.invalid' + path, { method, headers: authenticated ? headers : { 'Content-Type': 'application/json' }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
  return { status: response.status, body: await response.json() };
}
async function telegram(text, messageId, edited = false) {
  const response = await mf.dispatchFetch('https://offline.invalid/telegram', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Telegram-Bot-Api-Secret-Token': 'fixture-secret' },
    body: JSON.stringify({ [edited ? 'edited_channel_post' : 'channel_post']: { message_id: messageId, chat: { id: -1000000000001, type: 'channel' }, text } }) });
  assert.equal(response.status, 200, await response.clone().text()); return response.json();
}
try {
  const db = await mf.getD1Database('DB');
  for (const migration of ['0001_site_settings.sql', '0003_posts_baseline_and_indexes.sql']) {
    const sql = (await readFile(new URL('../../workers/api/migrations/' + migration, import.meta.url), 'utf8')).replace(/^--.*$/gm, '');
    for (const statement of sql.split(';').filter(part => part.trim())) await db.prepare(statement).run();
  }
  await db.prepare('CREATE TABLE mahoon_post_tags_v1(post_id INTEGER, tag_norm TEXT, PRIMARY KEY(post_id, tag_norm))').run();
  for (const [id, text, published, deleted] of [[1, 'کتاب جدید #کتاب', 1, null], [2, 'شعر جدید #شعر', 1, null], [3, 'حذف شده #کتاب', 0, '2026-01-01'], [4, 'پیش‌نویس #کتاب', 0, null], [5, 'صوت #کتاب_گویا', 1, null], [6, 'بدون برچسب', 1, null], [8, 'حذف شده بدون برچسب', 0, '2026-01-01']]) {
    await db.prepare('INSERT INTO posts (id,text,slug,is_published,deleted_at) VALUES (?,?,?,?,?)').bind(id, text, 'fixture-' + id, published, deleted).run();
  }
  for (const method of ['GET', 'POST', 'PATCH']) assert.equal((await request('/admin/publication-policy', method, method === 'GET' ? undefined : {}, false)).status, 401);
  const initial = await request('/admin/publication-policy');
  assert.equal(initial.status, 200); assert.equal(initial.body.policy.revision, 0); assert.equal(initial.body.channel_deletion.available, false);
  const exported = await request('/posts-full-public-v2?page_size=2');
  assert.equal(exported.status, 200); assert.equal(exported.body.contract, 'posts-full-public-v2');
  assert.equal(exported.body.items.length, 2); assert.equal(exported.body.has_more, true);
  assert.equal(exported.body.snapshot_total_count, 4);
  assert.ok(exported.body.items.every(post => !Object.hasOwn(post, 'admin_note') && !Object.hasOwn(post, 'telegram_message_id')));
  assert.equal((await request('/posts-full-public-v2?cursor=2')).status, 400);
  for (const [text, accepted] of [['بدون هشتگ', false], ['#کتابخانه', false], ['الف#کتاب', false], ['https://example.test/#کتاب', false], ['(#کتاب)،', true], ['#كتاب', true], ['#کتاب‌گویا', true], ['#کتاب_گویا', true], ['#کتابگویا', true]]) {
    const before = (await db.prepare('SELECT COUNT(*) AS n FROM posts').first()).n;
    const result = await telegram(text, 100 + before);
    assert.equal(result.saved, accepted, text);
    assert.equal((await db.prepare('SELECT COUNT(*) AS n FROM posts').first()).n, before + Number(accepted));
  }
  const created = await telegram('آزمایش ویرایش #کتاب', 777);
  assert.equal(created.saved, true);
  const stable = await db.prepare('SELECT id FROM posts WHERE telegram_message_id=777').first();
  assert.equal((await telegram('تکرار #کتاب', 777)).duplicate, true);
  await telegram('هشتگ برداشته شد', 777, true);
  const edited = await db.prepare('SELECT id,is_published,deleted_at FROM posts WHERE telegram_message_id=777').first();
  assert.equal(edited.id, stable.id); assert.equal(edited.is_published, 0); assert.equal(edited.deleted_at, null);
  assert.equal((await request('/admin/posts', 'POST', { text: 'بدون هشتگ', is_published: 1 })).status, 422);
  assert.equal((await request('/admin/posts/1', 'PATCH', { text: 'بدون هشتگ', slug: 'fixture-1', is_published: 1 })).status, 422);
  assert.equal((await request('/admin/posts/8/restore', 'POST', {})).status, 422);
  assert.equal((await request('/admin/posts/3', 'PATCH', { text: '#کتاب', is_published: 1 })).status, 404);
  assert.equal((await request('/admin/posts/bulk', 'POST', { ids: [1, 6], action: 'publish' })).status, 422);
  assert.equal((await request('/admin/posts/bulk', 'POST', { ids: [3], action: 'publish' })).status, 409);
  assert.equal((await db.prepare('SELECT deleted_at FROM posts WHERE id=3').first()).deleted_at, '2026-01-01');
  assert.equal((await request('/admin/posts/3/restore', 'POST', {})).status, 200);
  const policy = { allowed_tags: ['شعر'], auto_publish: false };
  const beforePreview = await db.prepare('SELECT SUM(is_published) AS n FROM posts').first();
  const preview = await request('/admin/publication-policy', 'POST', { policy });
  assert.equal(preview.status, 200); assert.ok(preview.body.affected_count > 0);
  assert.deepEqual(await db.prepare('SELECT SUM(is_published) AS n FROM posts').first(), beforePreview);
  assert.equal((await db.prepare("SELECT value FROM site_settings WHERE key='publication_policy_v1'").first()), null);
  const saved = await request('/admin/publication-policy', 'PATCH', { policy, expected_revision: 0 });
  assert.equal(saved.status, 200); assert.equal(saved.body.policy.revision, 1); assert.equal(saved.body.unpublished_count, preview.body.affected_count);
  assert.equal((await db.prepare('SELECT is_published FROM posts WHERE id=4').first()).is_published, 0);
  assert.equal((await request('/admin/publication-policy', 'PATCH', { policy, expected_revision: 0 })).status, 409);
  assert.equal((await request('/admin/publication-policy', 'PATCH', { policy: { allowed_tags: ['bad tag'], auto_publish: true }, expected_revision: 1 })).status, 400);
  assert.equal((await request('/admin/publication-policy', 'POST', { policy: { allowed_tags: [42], auto_publish: true } })).status, 400);
  const draft = await telegram('بازبینی دستی #شعر', 999);
  assert.equal(draft.saved, true); assert.equal((await db.prepare('SELECT is_published FROM posts WHERE telegram_message_id=999').first()).is_published, 0);
  assert.equal((await telegram('هشتگ دیگر #کتاب', 1000)).saved, false);
  assert.equal((await request('/site-settings')).body.settings.publication_policy_v1, undefined);
  const paused = await request('/admin/publication-policy', 'PATCH', { policy: { allowed_tags: [], auto_publish: false }, expected_revision: 1 });
  assert.equal(paused.status, 200); assert.equal((await telegram('#شعر', 1001)).saved, false);
  console.log('Publication policy integration PASS: exact Unicode tags, all write boundaries, edits, stable IDs, soft-delete/restore, atomic preview/apply, concurrency, private settings, review mode. Production writes: 0.');
} finally { await mf.dispose(); }
