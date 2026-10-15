import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir, writeFile } from 'node:fs/promises';
import { classifyPublicRequest } from './prepromotion_browser_gate.mjs';

const base = 'https://mahoonartmagazine.ir';
const api = 'https://api.mahoonartmagazine.ir';
const output = 'runner-evidence/platform-audit';
const require = createRequire(new URL('../../website/dreary-disk/package.json', import.meta.url));
const { chromium, request } = require('playwright');

function validateProbe(path, method, data) {
  const url = new URL(path, api);
  assert.equal(url.origin, api);
  const read = method === 'GET' && ['/health', '/public/posts-v1', '/public/stats-v1', '/admin/telegram/webhook-info'].includes(url.pathname);
  const emptyUpdate = method === 'POST' && ['/telegram', '/__mahoon_audit_invalid_route'].includes(url.pathname)
    && data && Object.keys(data).length === 0;
  assert.ok(read || emptyUpdate, 'Audit probe must be a public read or an empty update');
  return url.href;
}

function cls(entries) {
  let maximum = 0, value = 0, start = 0, previous = -Infinity;
  for (const entry of entries.filter((item) => !item.hadRecentInput)) {
    if (entry.startTime - previous < 1000 && entry.startTime - start < 5000) value += entry.value;
    else { start = entry.startTime; value = entry.value; }
    previous = entry.startTime;
    maximum = Math.max(maximum, value);
  }
  return maximum;
}

if (process.argv.includes('--self-test')) {
  assert.equal(validateProbe('/health', 'GET'), api + '/health');
  assert.equal(validateProbe('/telegram', 'POST', {}), api + '/telegram');
  for (const args of [['/telegram', 'POST', { channel_post: {} }], ['/admin/posts', 'POST', {}],
    ['https://unapproved.example/health', 'GET'], ['/health', 'DELETE']]) {
    assert.throws(() => validateProbe(...args));
  }
  assert.equal(cls([{ startTime: 0, value: 0.1 }, { startTime: 500, value: 0.2 },
    { startTime: 7000, value: 0.15 }, { startTime: 7100, value: 0.9, hadRecentInput: true }]), 0.1 + 0.2);
  console.log('Platform audit self-check passed: read-only probes and CLS session windows.');
} else {
  const expected = process.env.MAHOON_EXPECTED_VERSION;
  assert.match(expected || '', /^[0-9a-f-]{36}$/);
  const pinned = process.env.MAHOON_PIN_CANDIDATE === 'YES';
  const extraHTTPHeaders = pinned ? { 'cloudflare-workers-version-overrides': `mahoon-art-magazine="${expected}"` } : {};
  const result = { expected_version: expected, candidate_pinned: pinned, measured: false,
    checks: [], performance: [], api_probes: [], page_errors: [], public_dependencies: [] };
  await mkdir(output, { recursive: true });
  const save = () => writeFile(`${output}/result.json`, JSON.stringify(result, null, 2) + '\n');
  async function check(name, action) {
    result.active_check = name; await save();
    try { result.checks.push({ name, PASS: true, evidence: await action() }); }
    catch (error) { result.checks.push({ name, PASS: false, error_type: error.name,
      reason: String(error.message).replace(/https?:\/\/\S+/g, '[public URL]').slice(0, 300) }); }
    result.active_check = null; await save();
  }
  let browser, page, boundary;
  async function navigate(target, path) {
    const response = await target.goto(base + path, { waitUntil: 'load', timeout: 45000 });
    assert.equal(response.status(), 200);
    assert.equal(response.headers()['x-mahoon-worker-version'], expected);
    await target.waitForFunction(() => document.fonts.status === 'loaded'
      && document.fonts.check('12px MahoonFont'), null, { timeout: 30000 });
  }
  try {
    browser = await chromium.launch({ headless: true });
    result.runtime = { node: process.version, playwright: require('playwright/package.json').version,
      chromium: browser.version(), source_sha: process.env.GITHUB_SHA || null };
    boundary = await request.newContext({ timeout: 20000 });
    result.measured = true;
    for (const [label, width, height] of [['desktop', 1440, 1000], ['tablet', 768, 1024], ['mobile', 390, 844]]) {
      await check(`viewport_${label}`, async () => {
        for (let sample = 0; sample < 3; sample++) {
          const context = await browser.newContext({ viewport: { width, height }, extraHTTPHeaders });
          try {
            const target = await context.newPage();
            target.on('pageerror', (error) => result.page_errors.push({ page: label, type: error.name }));
            target.on('request', (req) => {
              const classification = classifyPublicRequest(req.url());
              if (classification) result.public_dependencies.push({ page: label, classification });
            });
            await target.addInitScript(() => {
              window.__mahoonAudit = { lcp: [], shifts: [], events: [] };
              for (const [type, key] of [['largest-contentful-paint', 'lcp'], ['layout-shift', 'shifts'], ['event', 'events']]) {
                try { new PerformanceObserver((list) => window.__mahoonAudit[key].push(...list.getEntries().map((e) => ({
                  startTime: e.startTime, value: e.value, hadRecentInput: e.hadRecentInput,
                  duration: e.duration, name: e.name, tag: e.element?.tagName,
                })))).observe({ type, buffered: true, ...(type === 'event' ? { durationThreshold: 16 } : {}) }); } catch {}
              }
            });
            await navigate(target, '/');
            await target.waitForTimeout(1200);
            const data = await target.evaluate(() => {
              const nav = performance.getEntriesByType('navigation')[0];
              const visible = (node) => { const r = node.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
              const unnamed = [...document.querySelectorAll('a[href],button,input,select,textarea,[role="button"]')]
                .filter(visible).filter((node) => ![node.getAttribute('aria-label'), node.getAttribute('title'),
                  node.textContent?.trim(), node.querySelector('img')?.alt,
                  ...String(node.getAttribute('aria-labelledby') || '').split(/\s+/).map((id) => document.getElementById(id)?.textContent),
                  ...[...document.querySelectorAll('label')].filter((label) => label.htmlFor === node.id).map((label) => label.textContent)]
                  .some((text) => text?.trim()))
                .map((node) => ({ tag: node.tagName, id: node.id, class: node.className }));
              return { ttfb_ms: nav.responseStart - nav.startTime, dom_content_loaded_ms: nav.domContentLoadedEventEnd,
                load_ms: nav.loadEventEnd, paints: performance.getEntriesByType('paint').map((e) => ({ name: e.name, startTime: e.startTime })),
                observations: window.__mahoonAudit, overflow: document.documentElement.scrollWidth > innerWidth + 1,
                font: document.fonts.status, unnamed_controls: unnamed,
                resources: performance.getEntriesByType('resource').map((e) => ({ origin: new URL(e.name).origin,
                  path: new URL(e.name).pathname, initiator: e.initiatorType, duration_ms: e.duration,
                  transfer_bytes: e.transferSize, decoded_bytes: e.decodedBodySize })) };
            });
            data.cls = cls(data.observations.shifts);
            result.performance.push({ viewport: label, width, height, sample, lab_only: true, ...data });
            assert.equal(data.overflow, false);
            if (sample === 0) {
              await target.screenshot({ path: `${output}/home-${label}.png`, fullPage: true });
              await writeFile(`${output}/home-${label}-accessibility.yml`, await target.locator('body').ariaSnapshot());
            }
          } finally { await context.close(); }
          await save();
        }
        return { samples: 3, width, height };
      });
    }
    page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, extraHTTPHeaders });
    const indexResponse = await page.request.get(base + '/search/search-index.json');
    assert.equal(indexResponse.status(), 200);
    const index = await indexResponse.json();
    assert.equal(index.contract, 'STATIC_SEARCH_CONTRACT_V2');
    result.index_count = index.records.length;
    await check('persian_search_variants', async () => {
      await navigate(page, '/posts/');
      const query = 'دیالوگ';
      assert.ok(index.records.some((record) => record.normalized_search_text.includes(query)), 'Baseline term must exist in sealed index');
      const evidence = [];
      for (const value of [query, query.replace(/ی/g, 'ي'), query.replace(/ی/g, 'ى')]) {
        await page.locator('#archiveSearch').fill(value);
        await page.waitForTimeout(700);
        evidence.push({ query: value, count: await page.locator('#archiveGrid article').count(),
          status: await page.locator('#archiveCount').textContent() });
      }
      result.search_variants = evidence;
      await page.screenshot({ path: `${output}/search-persian-variant.png`, fullPage: true });
      assert.ok(evidence[0].count > 0);
      assert.equal(evidence[1].status, evidence[0].status);
      assert.equal(evidence[2].status, evidence[0].status);
      return evidence;
    });
    await check('search_empty_state', async () => {
      await page.locator('#archiveSearch').fill('mahoon-no-match-8ea05d9');
      await page.waitForFunction(() => document.querySelectorAll('#archiveGrid article').length === 0);
      assert.equal(await page.locator('#archiveEmpty').isVisible(), true);
      const liveRegion = await page.locator('#archiveCount').evaluate((node) => ({ role: node.getAttribute('role'), live: node.getAttribute('aria-live') }));
      await page.screenshot({ path: `${output}/search-empty.png`, fullPage: true });
      return { empty_visible: true, count_live_region: liveRegion };
    });
    await check('mobile_keyboard_menu', async () => {
      await page.setViewportSize({ width: 390, height: 844 }); await navigate(page, '/');
      await page.locator('.site-menu-toggle').focus(); await page.keyboard.press('Enter');
      assert.equal(await page.locator('.site-menu-toggle').getAttribute('aria-expanded'), 'true');
      await page.keyboard.press('Escape');
      return { enter_opens: true, escape_closes: await page.locator('.site-menu-toggle').getAttribute('aria-expanded') === 'false' };
    });
    for (const [path, method, data] of [['/health', 'GET'], ['/public/posts-v1?limit=10&offset=0', 'GET'],
      ['/public/stats-v1', 'GET'], ['/admin/telegram/webhook-info', 'GET'], ['/telegram', 'POST', {}], ['/__mahoon_audit_invalid_route', 'POST', {}]]) {
      await check(`api_${method}_${path.split('?')[0]}`, async () => {
        const response = await boundary.fetch(validateProbe(path, method, data), { method, ...(data ? { data } : {}) });
        const body = await response.json();
        const observation = { path, method, status: response.status(), ok: body.ok, saved: body.saved,
          reason: body.reason, error: body.error, total: body.total, response_keys: Object.keys(body) };
        if (Array.isArray(body.posts)) {
          observation.post_ids = body.posts.map((post) => post.id);
          observation.latest_posts = body.posts.map(({ id, slug, created_at, media_type }) => ({ id, slug, created_at, media_type }));
          observation.private_fields_present = [...new Set(body.posts.flatMap((post) => ['admin_note', 'chat_id', 'chat_title', 'deleted_at', 'telegram_message_id'].filter((key) => key in post)))];
          observation.latest_ids_missing_from_static_index = observation.post_ids.filter((id) => !index.records.some((record) => record.id === id));
          if (observation.latest_ids_missing_from_static_index.length) {
            const latestId = observation.latest_ids_missing_from_static_index[0];
            const article = await page.request.get(base + '/post/' + latestId);
            observation.latest_missing_article = { id: latestId, status: article.status(), version: article.headers()['x-mahoon-worker-version'] };
          }
        }
        result.api_probes.push(observation);
        if (method === 'GET') assert.equal(response.status(), path.startsWith('/admin/') ? 401 : 200);
        else { assert.ok([200, 401, 403, 404, 405].includes(response.status())); if (response.status() === 200) assert.equal(body.saved, false); }
        return observation;
      });
    }
  } finally {
    await boundary?.dispose(); await browser?.close();
    result.active_check = null;
    result.PASS = result.measured && result.checks.every((item) => item.PASS)
      && result.page_errors.length === 0 && result.public_dependencies.length === 0;
    result.metric_limits = 'Laboratory Chromium viewport samples; no field INP, physical device or Chrome DevTools trace claim.';
    await save();
  }
  console.log(JSON.stringify({ PASS: result.PASS, checks: result.checks.map(({ name, PASS }) => ({ name, PASS })) }));
  if (!result.PASS) process.exitCode = 1;
}
