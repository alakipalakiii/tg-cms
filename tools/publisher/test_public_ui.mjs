import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile, writeFile } from 'node:fs/promises';
const require = createRequire(new URL('../../website/dreary-disk/package.json', import.meta.url));
const { chromium } = require('playwright');
const base = 'http://127.0.0.1:4321';
assert.ok(process.env.MAHOON_UI_SNAPSHOT, 'Set MAHOON_UI_SNAPSHOT to an accepted public content snapshot before this integration test.');
const snapshot = JSON.parse(await readFile(process.env.MAHOON_UI_SNAPSHOT));
const posts = snapshot.posts || snapshot.payload.posts;
const templates = ['photo', 'video', 'audio', 'voice', 'text'].map(type => ({ type, post: posts.find(p => type === 'text' ? !p.media_type && !p.photo_file_id : p.media_type === type) })).filter(item => item.post);
const browser = await chromium.launch({ headless: true });
const result = { checks: [], errors: [], analytics_writes: 0 };
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  // Never allow local QA to submit telemetry or modify any remote endpoint.
  await context.route('**/*', route => {
    if (!['GET','HEAD'].includes(route.request().method())) { result.analytics_writes++; return route.abort(); }
    return route.continue();
  });
  const page = await context.newPage(); page.setDefaultTimeout(12000);
  page.on('pageerror', error => result.errors.push(error.message));
  const paths = ['/', '/posts', '/category/' + encodeURIComponent('کتاب'), '/tag/' + encodeURIComponent('کتاب'), '/about', '/contact', ...templates.map(({post}) => '/post/' + encodeURIComponent(post.slug))];
  for (const path of paths) {
    const response = await page.goto(base + path, { waitUntil: 'load' });
    assert.equal(response.status(), 200, path);
    await page.locator('[data-mahoon-r4-theme-toggle]').waitFor();
    await page.locator('main h1').first().waitFor({state:'visible'});
    const headings = await page.locator('main h1:visible').count();
    assert.match(await page.locator('[data-mahoon-r4-theme-toggle]').getAttribute('aria-label'), /تغییر تم/);
    assert.equal(await page.locator('.mahoon-frozen-global-scope #modal').evaluate(el => el.inert), true);
    assert.equal(headings, 1, 'one visible page heading: ' + path);
    assert.equal(await page.locator('link[rel="canonical"]').count(), 1);
    assert.ok((await page.locator('meta[name="description"]').getAttribute('content')).trim());
    const canonical = await page.locator('link[rel="canonical"]').getAttribute('href');
    assert.equal(new URL(canonical).origin, 'https://mahoonartmagazine.ir');
    const schema = await page.locator('script[type="application/ld+json"]').allTextContents();
    schema.forEach(text => JSON.parse(text));
    for (const theme of ['light', 'dark', 'light']) {
      await page.evaluate(theme => window.MahoonTheme.set(theme), theme);
      for (const width of [390, 768, 1440]) {
        await page.setViewportSize({ width, height: 844 });
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, 'no overflow ' + path + ' ' + width);
      }
      if (theme === 'dark') {
        assert.equal(await page.locator('#mainNav a').first().evaluate(el => getComputedStyle(el).color), path === '/' ? 'rgb(255, 201, 189)' : 'rgb(234, 218, 211)');
      }
    }
    result.checks.push({path, headings, canonical, responsive: '390/768/1440', themes: 'light/dark/light'});
  }
  await page.setViewportSize({width:390,height:844});
  await page.goto(base + '/');
  await page.getByRole('button', {name:'باز کردن منو',exact:true}).click();
  assert.equal(await page.locator('.site-menu-toggle').getAttribute('aria-expanded'), 'true');
  await page.getByRole('link',{name:'درباره ما',exact:true}).click();
  await page.waitForURL('**/about');
  await page.getByRole('button', {name:'باز کردن منو',exact:true}).click();
  assert.equal(await page.locator('.site-menu-toggle').getAttribute('aria-expanded'), 'true');
  await page.locator('.site-menu-toggle').press('Escape');
  assert.equal(await page.locator('.site-menu-toggle').getAttribute('aria-expanded'), 'false');
  assert.equal(await page.locator('.site-menu-toggle').evaluate(el => el === document.activeElement), true);
  await page.goto(base + '/nonexistent-ui-audit');
  assert.match(await page.locator('meta[name="robots"]').getAttribute('content'), /noindex/);
  assert.deepEqual(result.errors, []);
  assert.equal(result.analytics_writes, 0);
  result.PASS = true;
  await writeFile(new URL('../../../BACKUP/ui-audit-20261105/public-test.json', import.meta.url), JSON.stringify(result,null,2));
  console.log('Public UI passed: ' + paths.length + ' page types; 3 widths; theme round trip; Astro navigation; metadata; no QA telemetry.');
} finally { await browser.close(); }
