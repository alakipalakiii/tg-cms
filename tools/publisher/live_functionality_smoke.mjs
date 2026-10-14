import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile, mkdir, writeFile } from 'node:fs/promises';

const require = createRequire(new URL('../../website/dreary-disk/package.json', import.meta.url));
const { chromium, request } = require('playwright');
const base = 'https://mahoonartmagazine.ir';
const expected = process.env.MAHOON_EXPECTED_VERSION;
assert.match(expected || '', /^[0-9a-f-]{36}$/);
const candidatePinned = process.env.MAHOON_PIN_CANDIDATE === 'YES';
const versionHeaders = candidatePinned ? { 'cloudflare-workers-version-overrides': `mahoon-art-magazine="${expected}"` } : {};
const articleMediaSelectors = {
  "audio": "[data-mahoon-native-player] audio.mahoon-native-player__audio",
  "video": "#postArticle video"
};
const output = 'runner-evidence/live-functionality';
await mkdir(output, { recursive: true });
const checks = [];
const publicDependencies = [];
const pageErrors = [];
const candidateExternalRequests = [];
let newPosts = [];
let browser, page, boundary;
let failureStage = null;
let mediaResponses = [];

async function saveProgress(activeCheck) {
  await writeFile(`${output}/result.json`, JSON.stringify({ status: 'RUNNING', measured: Boolean(browser),
    expected_version: expected, candidate_pinned: candidatePinned, active_check: activeCheck, checks, new_post_ids: newPosts.map((post) => post.id),
    public_dependencies: publicDependencies, page_errors: pageErrors, PASS: false,
    candidate_external_requests: candidateExternalRequests,
  }, null, 2) + '\n');
}

async function check(name, action) {
  failureStage = null;
  mediaResponses = [];
  await saveProgress(name);
  try {
    checks.push({ name, PASS: true, evidence: await action() });
  } catch (error) {
    checks.push({ name, PASS: false, error_type: error.name, failure_stage: failureStage, media_responses: [...mediaResponses],
      page_state: await page.evaluate(() => ({
        path: location.pathname, font_status: document.fonts.status,
        font_available: document.fonts.check('12px MahoonFont'),
        media: [...document.querySelectorAll('audio,video')].map((node) => ({
          tag: node.tagName, native_article: Boolean(node.closest('#postArticle')),
          native_player: Boolean(node.closest('[data-mahoon-native-player]')),
          source_path: node.currentSrc ? new URL(node.currentSrc).pathname : null,
          ready_state: node.readyState, duration: Number.isFinite(node.duration) ? node.duration : null,
          duration_state: String(node.duration),
          current_time: node.currentTime, error_code: node.error?.code || null,
        })),
      })).catch(() => null),
      reason: String(error.message).replace(/https?:\/\/\S+/g, '[public URL]')
        .replace(/\bBearer\s+\S+/gi, 'Bearer [redacted]')
        .replace(/\b([\w-]*(?:TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTHORIZATION|API[_-]?KEY)[\w-]*\s*[=:]\s*)\S+/gi, '$1[redacted]').slice(0, 300) });
  }
  await saveProgress(null);
}

async function navigate(path) {
  failureStage = 'navigation';
  const response = await page.goto(base + path, { waitUntil: 'domcontentloaded', timeout: 60000 });
  assert.equal(response.status(), 200);
  assert.equal(response.headers()['x-mahoon-worker-version'], expected);
  failureStage = 'font_loading';
  await page.waitForFunction(() => document.fonts.status === 'loaded'
    && document.fonts.check('12px MahoonFont')
    && getComputedStyle(document.body).fontFamily.includes('MahoonFont'), null, { timeout: 30000 });
  return path;
}

async function playback(kind) {
  const selector = articleMediaSelectors[kind];
  const element = page.locator(selector).first();
  failureStage = `${kind}_metadata`;
  await element.evaluate((node) => { node.preload = 'auto'; node.load(); });
  await page.waitForFunction((tag) => {
    const node = document.querySelector(tag);
    return node && node.readyState >= 2 && Number.isFinite(node.duration) && node.duration > 0;
  }, selector, { timeout: 30000 });
  failureStage = `${kind}_play_control`;
  if (kind === 'audio') await page.locator('[data-mahoon-native-player] .js-play:visible').first().click();
  else await element.evaluate((node) => node.play());
  failureStage = `${kind}_play_progress`;
  await page.waitForFunction((tag) => document.querySelector(tag).currentTime > 0.1, selector, { timeout: 10000 });
  return element.evaluate((node) => { node.pause(); return {
    duration: node.duration, current_time: node.currentTime, source_path: new URL(node.currentSrc).pathname,
  }; });
}

try {
  browser = await chromium.launch({ headless: true, args: ['--autoplay-policy=no-user-gesture-required'] });
  // Routing disables the browser cache and changes OGG range/metadata behavior.
  page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, extraHTTPHeaders: versionHeaders });
  boundary = await request.newContext();
  page.on('pageerror', (error) => pageErrors.push(error.name));
  page.on('response', (response) => {
    if (response.request().resourceType() === 'media') {
      const headers = response.headers();
      mediaResponses.push({ path: new URL(response.url()).pathname, status: response.status(),
        content_type: headers['content-type'] || null, content_length: headers['content-length'] || null,
        content_range: headers['content-range'] || null, actual_version: headers['x-mahoon-worker-version'] || null });
    }
  });
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (candidatePinned && /^https?:$/.test(url.protocol) && url.origin !== base)
      candidateExternalRequests.push(url.hostname + url.pathname);
    if (url.hostname === 'api.mahoonartmagazine.ir' || url.hostname.endsWith('.workers.dev')
        || /(^|\.)telegram\.org$/.test(url.hostname)) publicDependencies.push(url.hostname + url.pathname);
  });
  const indexResponse = await page.request.get(base + '/search/search-index.json', { headers: versionHeaders });
  assert.equal(indexResponse.status(), 200);
  assert.equal(indexResponse.headers()['x-mahoon-worker-version'], expected);
  const index = await indexResponse.json();
  assert.equal(index.contract, 'STATIC_SEARCH_CONTRACT_V2');
  const records = index.records;
  assert.ok(records.length > 0);
  await writeFile(`${output}/index-post-identities.json`, JSON.stringify(records.map((record) => ({
    id: record.id, path: new URL(record.url).pathname, category: record.category,
  })), null, 2) + '\n');
  const latest = records.reduce((a, b) => Number(a.id) > Number(b.id) ? a : b);
  if (process.env.MAHOON_BASELINE_RUN_ID) {
    const baseline = JSON.parse(await readFile('baseline/runner-evidence/live-functionality/index-post-identities.json', 'utf8'));
    assert.ok(Array.isArray(baseline) && baseline.every((post) => Number.isInteger(post.id)));
    const prior = new Set(baseline.map((post) => post.id));
    newPosts = records.filter((post) => !prior.has(post.id));
  }
  await check('archive_load_more', async () => {
    await navigate('/posts/');
    const before = await page.locator('#archiveGrid article').count();
    await page.locator('#archiveMore').click();
    await page.waitForFunction((count) => document.querySelectorAll('#archiveGrid article').length > count, before, { timeout: 10000 });
    return { before, after: await page.locator('#archiveGrid article').count() };
  });
  await check('archive_search_by_database_id', async () => {
    await page.locator('#archiveSearch').fill(String(latest.id));
    const path = new URL(latest.url).pathname;
    await page.waitForFunction((expectedPath) => {
      const cards = [...document.querySelectorAll('#archiveGrid article')];
      return cards.length === 1 && new URL(cards[0].querySelector('a').href).pathname === expectedPath;
    }, path, { timeout: 10000 });
    await page.screenshot({ path: `${output}/archive-search.png`, fullPage: true });
    return { database_id: latest.id, path };
  });
  await check('latest_article_navigation', async () => {
    const path = new URL(latest.url).pathname;
    await navigate(path);
    assert.ok((await page.locator('main').innerText()).trim().length > 80);
    return { database_id: latest.id, path };
  });
  await check('home_search_navigation', async () => {
    await navigate('/');
    await page.locator('#mSearch').fill(String(latest.id));
    await page.locator('#mSearch').press('Enter');
    await page.waitForURL((url) => url.pathname.replace(/\/$/, '') === '/search'
      && url.searchParams.get('q') === String(latest.id), { timeout: 10000 });
    await page.waitForFunction(() => document.querySelectorAll('#archiveGrid article').length === 1,
      null, { timeout: 10000 });
    return { database_id: latest.id, path: new URL(page.url()).pathname };
  });
  await check('category_search_by_database_id', async () => {
    const post = records.find((record) => record.category);
    const path = '/category/' + encodeURIComponent(post.category);
    await navigate(path);
    await page.locator('#archiveSearch').fill(String(post.id));
    await page.waitForFunction(() => document.querySelectorAll('#archiveGrid article').length === 1,
      null, { timeout: 10000 });
    assert.equal(new URL(await page.locator('#archiveGrid article a').first().getAttribute('href'), base).pathname,
      new URL(post.url).pathname);
    return { database_id: post.id, path };
  });
  const manifest = JSON.parse(await readFile('publisher-state/production-media-manifest.json', 'utf8'));
  for (const kind of ['audio', 'video']) {
    await check(`${kind}_playback`, async () => {
      const media = manifest.records.find((item) => String(item.detected_mime || item.mime).startsWith(kind + '/')
        && item.post_ids.some((id) => records.some((record) => record.id === id)));
      assert.ok(media, `${kind} sample is required`);
      const post = records.find((record) => media.post_ids.includes(record.id));
      const path = new URL(post.url).pathname;
      await navigate(path);
      const evidence = await playback(kind);
      return { database_id: post.id, path, ...evidence };
    });
  }
  await check('admin_authentication_boundary', async () => {
    await navigate('/admin');
    assert.ok(await page.locator('#loginView #tokenInput[type="password"]').isVisible());
    assert.ok(await page.locator('#loginView #loginBtn').isVisible());
    const response = await boundary.get('https://api.mahoonartmagazine.ir/admin/health');
    assert.equal(response.status(), 401);
    const body = await response.json();
    assert.equal(body.ok, false);
    assert.equal(body.error, 'Unauthorized');
    return { login_visible: true, unauthenticated_api_status: response.status() };
  });
  for (const post of newPosts) {
    await check(`new_article_${post.id}`, async () => {
      const path = new URL(post.url).pathname;
      await navigate(path);
      assert.ok((await page.locator('main').innerText()).trim().length > 80);
      const images = page.locator('main img');
      failureStage = 'image_decode';
      for (const image of await images.all()) {
        await image.scrollIntoViewIfNeeded();
        await image.evaluate((node) => node.decode());
        assert.ok(await image.evaluate((node) => node.naturalWidth > 0 && node.naturalHeight > 0));
      }
      const media = {};
      for (const kind of ['audio', 'video']) if (await page.locator(articleMediaSelectors[kind]).count()) media[kind] = await playback(kind);
      await page.screenshot({ path: `${output}/new-post-${post.id}.png`, fullPage: true });
      return { database_id: post.id, path, decoded_images: await images.count(), media };
    });
  }
} catch (error) {
  checks.push({ name: 'preflight', PASS: false, error_type: error.name });
} finally {
  await browser?.close();
  await boundary?.dispose();
  const result = { measured: Boolean(browser), expected_version: expected, candidate_pinned: candidatePinned, checks, public_dependencies: publicDependencies,
    new_post_ids: newPosts.map((post) => post.id), baseline_run_id: process.env.MAHOON_BASELINE_RUN_ID || null,
    page_errors: pageErrors, PASS: checks.length === 8 + newPosts.length && checks.every((item) => item.PASS)
      && publicDependencies.length === 0 && pageErrors.length === 0 && candidateExternalRequests.length === 0,
    candidate_external_requests: candidateExternalRequests };
  await writeFile(`${output}/result.json`, JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify(result));
  process.exitCode = result.PASS ? 0 : 1;
}
