import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile, mkdir, writeFile } from 'node:fs/promises';

const require = createRequire(new URL('../../website/dreary-disk/package.json', import.meta.url));
const { chromium } = require('playwright');
const base = 'https://mahoonartmagazine.ir';
const expected = process.env.MAHOON_EXPECTED_VERSION;
assert.match(expected || '', /^[0-9a-f-]{36}$/);
const output = 'runner-evidence/live-functionality';
await mkdir(output, { recursive: true });
const checks = [];
const publicDependencies = [];
const pageErrors = [];
let browser, page;

async function check(name, action) {
  try {
    checks.push({ name, PASS: true, evidence: await action() });
  } catch (error) {
    checks.push({ name, PASS: false, error_type: error.name,
      reason: String(error.message).replace(/https?:\/\/\S+/g, '[public URL]')
        .replace(/\bBearer\s+\S+/gi, 'Bearer [redacted]')
        .replace(/\b([\w-]*(?:TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTHORIZATION|API[_-]?KEY)[\w-]*\s*[=:]\s*)\S+/gi, '$1[redacted]').slice(0, 300) });
  }
}

async function navigate(path) {
  const response = await page.goto(base + path, { waitUntil: 'networkidle', timeout: 60000 });
  assert.equal(response.status(), 200);
  assert.equal(response.headers()['x-mahoon-worker-version'], expected);
  return path;
}

try {
  browser = await chromium.launch({ headless: true, args: ['--autoplay-policy=no-user-gesture-required'] });
  page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.on('pageerror', (error) => pageErrors.push(error.name));
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (url.hostname === 'api.mahoonartmagazine.ir' || url.hostname.endsWith('.workers.dev')
        || /(^|\.)telegram\.org$/.test(url.hostname)) publicDependencies.push(url.hostname + url.pathname);
  });
  const indexResponse = await page.request.get(base + '/search/search-index.json');
  assert.equal(indexResponse.status(), 200);
  assert.equal(indexResponse.headers()['x-mahoon-worker-version'], expected);
  const index = await indexResponse.json();
  assert.equal(index.contract, 'STATIC_SEARCH_CONTRACT_V2');
  const records = index.records;
  assert.ok(records.length > 0);
  const latest = records.reduce((a, b) => Number(a.id) > Number(b.id) ? a : b);
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
  const manifest = JSON.parse(await readFile('publisher-state/production-media-manifest.json', 'utf8'));
  for (const kind of ['audio', 'video']) {
    await check(`${kind}_playback`, async () => {
      const media = manifest.records.find((item) => String(item.detected_mime || item.mime).startsWith(kind + '/')
        && item.post_ids.some((id) => records.some((record) => record.id === id)));
      assert.ok(media, `${kind} sample is required`);
      const post = records.find((record) => media.post_ids.includes(record.id));
      const path = new URL(post.url).pathname;
      await navigate(path);
      const element = page.locator(kind).first();
      await element.evaluate((node) => { node.preload = 'auto'; node.load(); });
      await page.waitForFunction((tag) => {
        const node = document.querySelector(tag);
        return node && node.readyState >= 2 && Number.isFinite(node.duration) && node.duration > 0;
      }, kind, { timeout: 30000 });
      await element.evaluate((node) => node.play());
      await page.waitForFunction((tag) => document.querySelector(tag).currentTime > 0.1, kind, { timeout: 10000 });
      const evidence = await element.evaluate((node) => { node.pause(); return {
        duration: node.duration, current_time: node.currentTime, source_path: new URL(node.currentSrc).pathname,
      }; });
      return { database_id: post.id, path, ...evidence };
    });
  }
} catch (error) {
  checks.push({ name: 'preflight', PASS: false, error_type: error.name });
} finally {
  await browser?.close();
  const result = { measured: Boolean(browser), expected_version: expected, checks, public_dependencies: publicDependencies,
    page_errors: pageErrors, PASS: checks.length === 5 && checks.every((item) => item.PASS)
      && publicDependencies.length === 0 && pageErrors.length === 0 };
  await writeFile(`${output}/result.json`, JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify(result));
  process.exitCode = result.PASS ? 0 : 1;
}
