import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { classifyPublicRequest } from './prepromotion_browser_gate.mjs';

assert.equal(classifyPublicRequest('https://static.cloudflareinsights.com/beacon.min.js'), null);
assert.equal(classifyPublicRequest('https://api.mahoonartmagazine.ir/media/example'), 'media_api');
assert.equal(classifyPublicRequest('https://example.workers.dev/posts'), 'workers_dev_content');
assert.equal(classifyPublicRequest('https://api.telegram.org/file/example'), 'telegram');
assert.equal(classifyPublicRequest('https://unapproved.example/search'), 'search_backend');

const require = createRequire(new URL('../../website/dreary-disk/package.json', import.meta.url));
const { chromium } = require('playwright');
const client = await readFile(new URL('../../website/dreary-disk/public/mahoon-static-archive.js', import.meta.url));
const records = Array.from({ length: 22 }, (_, position) => ({ id: position + 1,
  url: '/post/fixture-' + (position + 1), category: position === 0 || position % 2 ? 'book' : 'text',
  tags: [position === 0 ? 'audiobook' : position % 2 ? 'book' : 'text'],
  normalized_search_text: 'fixture title ' + (position + 1) + (position === 0 ? ' دیالوگ کتاب خانه هنر' : '') }));
let invalidIndex = false;
const server = createServer((request, response) => {
  const url = new URL(request.url, 'http://localhost');
  if (url.pathname === '/mahoon-static-archive.js') {
    response.setHeader('Content-Type', 'application/javascript'); response.end(client); return;
  }
  if (url.pathname === '/search/search-index.json') {
    response.setHeader('Content-Type', 'application/json');
    response.end(JSON.stringify({ contract: invalidIndex ? 'INVALID' : 'STATIC_SEARCH_CONTRACT_V2', records })); return;
  }
  if (url.pathname === '/fixture.svg') {
    response.setHeader('Content-Type', 'image/svg+xml');
    response.end('<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"></svg>'); return;
  }
  response.setHeader('Content-Type', 'text/html; charset=utf-8');
  if (url.pathname === '/') {
    response.end('<input id="mSearch"><script src="/mahoon-static-archive.js" defer></script>'); return;
  }
  const category = url.pathname.startsWith('/category/');
  const categoryName = category ? url.pathname.split('/')[2] : '';
  const categoryTags = categoryName === 'audio' ? ['audio', 'audiobook'] : ['book', 'audiobook'];
  const pageNumber = Number(url.pathname.split('/page/')[1] || 1);
  const filtered = category ? records.filter((record) => record.tags.some((tag) => categoryTags.includes(tag))) : records;
  const slice = filtered.slice((pageNumber - 1) * 20, pageNumber * 20);
  const cards = slice.map((record) => `<article data-kind="${categoryName || 'posts'}"><a href="${record.url}"><img src="/fixture.svg" alt="fixture ${record.id}"></a><h2>Fixture ${record.id}</h2></article>`).join('');
  response.end(`<main><input id="archiveSearch"><div id="archiveGrid">${cards}</div>
    <button id="archiveMore" ${filtered.length <= pageNumber * 20 ? 'hidden' : ''}>More</button>
    <span id="archiveCount"></span><span id="archiveTotal"></span><div id="archiveEmpty" hidden></div>
    <script id="archiveConfig" type="application/json">${JSON.stringify({ mode: category ? 'category' : 'posts',
      category: categoryName, category_tags: categoryTags, pageSize: 20, initialNextOffset: pageNumber * 20 })}</script>
    <script src="/mahoon-static-archive.js" defer></script></main>`);
});
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  const errors = [], remoteRequests = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('request', (request) => { if (!request.url().startsWith(origin)) remoteRequests.push(request.url()); });
  await page.goto(origin + '/posts/');
  assert.equal(await page.locator('#archiveGrid article').count(), 20);
  await page.locator('#archiveMore').click();
  await page.waitForFunction(() => document.querySelectorAll('#archiveGrid article').length === 22);
  assert.equal(await page.locator('#archiveGrid a').last().getAttribute('href'), '/post/fixture-22');
  assert.equal(await page.locator('#archiveGrid img').last().getAttribute('src'), '/fixture.svg');
  for (const query of ['دیالوگ', 'ديالوگ', 'دىالوگ', 'کتاب', 'كتاب']) {
    await page.locator('#archiveSearch').fill('not present');
    await page.waitForFunction(() => document.querySelectorAll('#archiveGrid article').length === 0);
    await page.locator('#archiveSearch').fill(query);
    await page.waitForFunction(() => document.querySelectorAll('#archiveGrid article').length === 1, null, { timeout: 3000 });
    assert.equal(await page.locator('#archiveGrid article').count(), 1, query);
    assert.equal(await page.locator('#archiveGrid a').getAttribute('href'), '/post/fixture-1');
  }
  await page.locator('#archiveSearch').fill('۲۲');
  await page.waitForFunction(() => document.querySelector('#archiveGrid a')?.getAttribute('href') === '/post/fixture-22');
  assert.equal(await page.locator('#archiveGrid a').getAttribute('href'), '/post/fixture-22');
  await page.locator('#archiveSearch').fill('not present');
  await page.waitForFunction(() => document.querySelectorAll('#archiveGrid article').length === 0);
  assert.equal(await page.locator('#archiveEmpty').isVisible(), true);
  await page.locator('#archiveSearch').fill('');
  await page.waitForFunction(() => document.querySelectorAll('#archiveGrid article').length === 20);
  await page.goto(origin + '/category/book?q=3');
  await page.waitForFunction(() => document.querySelectorAll('#archiveGrid article').length === 0);
  await page.locator('#archiveSearch').fill('2');
  await page.waitForFunction(() => document.querySelectorAll('#archiveGrid article').length === 1);
  assert.equal(await page.locator('#archiveGrid a').getAttribute('href'), '/post/fixture-2');
  await page.goto(origin + '/category/audio?q=1');
  await page.waitForFunction(() => document.getElementById('archiveCount').textContent.startsWith('نمایش'));
  assert.equal(await page.locator('#archiveGrid a').getAttribute('href'), '/post/fixture-1');
  assert.equal(await page.locator('#archiveGrid article').getAttribute('data-kind'), 'audio');
  await page.goto(origin + '/');
  await page.locator('#mSearch').fill('22');
  await page.locator('#mSearch').press('Enter');
  await page.waitForURL(origin + '/search?q=22');
  await page.waitForFunction(() => document.querySelectorAll('#archiveGrid article').length === 1);
  invalidIndex = true;
  await page.goto(origin + '/posts?q=22');
  await page.waitForFunction(() => document.getElementById('archiveEmpty').hidden === false);
  assert.equal(await page.locator('#archiveGrid article').count(), 20);
  invalidIndex = false;
  await page.locator('#archiveSearch').fill('21');
  await page.waitForFunction(() => document.querySelectorAll('#archiveGrid article').length === 1);
  assert.equal(await page.locator('#archiveGrid a').getAttribute('href'), '/post/fixture-21');
  assert.deepEqual(errors, []);
  assert.deepEqual(remoteRequests, []);
  const diagnostic = await readFile(new URL('./live_functionality_smoke.mjs', import.meta.url), 'utf8');
  const selectors = JSON.parse(diagnostic.match(/const articleMediaSelectors = (\{[\s\S]*?\n\});/)[1]);
  await page.setContent('<audio class="mahoon-r4-global-audio"></audio><article id="postArticle"><p>Photo post</p></article>');
  assert.equal(await page.locator('audio').count(), 1);
  assert.equal(await page.locator(selectors.audio).count(), 0);
  await page.setContent('<audio class="mahoon-r4-global-audio"></audio><article id="postArticle"><section data-mahoon-native-player><audio class="mahoon-native-player__audio" data-fixture="native"></audio></section><video data-fixture="post"></video></article>');
  assert.equal(await page.locator(selectors.audio).count(), 1);
  assert.equal(await page.locator(selectors.audio).getAttribute('data-fixture'), 'native');
  assert.equal(await page.locator(selectors.video).getAttribute('data-fixture'), 'post');
  await page.locator('[data-mahoon-native-player]').evaluate((node) => document.body.append(node));
  assert.equal(await page.locator('#postArticle audio').count(), 0);
  assert.equal(await page.locator(selectors.audio).getAttribute('data-fixture'), 'native');
  const layout = await readFile(new URL('../../website/dreary-disk/src/layouts/BaseLayout.astro', import.meta.url), 'utf8');
  const menuScript = [...layout.matchAll(/<script is:inline>([\s\S]*?)<\/script>/g)]
    .map((match) => match[1]).find((script) => script.includes('document.querySelector(".site-menu-toggle")'));
  assert.ok(menuScript);
  await page.setContent('<button class="site-menu-toggle" aria-expanded="false">Menu</button><nav id="mainNav"><a href="/">Home</a></nav>');
  await page.addScriptTag({ content: menuScript });
  await page.locator('button').focus(); await page.keyboard.press('Enter');
  assert.equal(await page.locator('button').getAttribute('aria-expanded'), 'true');
  await page.locator('a').focus(); await page.keyboard.press('Escape');
  assert.equal(await page.locator('button').getAttribute('aria-expanded'), 'false');
  assert.equal(await page.locator('nav').evaluate((node) => node.classList.contains('is-open')), false);
  assert.equal(await page.locator('button').evaluate((node) => node === document.activeElement), true);
  for (const source of ['index.astro', 'posts.astro', 'category/[category].astro']) {
    const html = await readFile(new URL('../../website/dreary-disk/src/pages/' + source, import.meta.url), 'utf8');
    assert.match(html, /<input[^>]+type="search"[^>]+aria-label="[^"]+"/);
    if (source !== 'index.astro') assert.match(html, /id="archiveCount" role="status" aria-live="polite"/);
  }
  console.log('Static archive browser fixtures passed: pagination, media cards, database IDs, no-match/reset, category, home navigation, invalid index.');
} finally {
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
