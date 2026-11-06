import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { writeFile, mkdir } from 'node:fs/promises';
const require = createRequire(new URL('../../website/dreary-disk/package.json', import.meta.url));
const { chromium } = require('playwright');
const origin = 'http://127.0.0.1:4328';
const source = 'http://127.0.0.1:4321';
const output = new URL('../../../BACKUP/admin-redesign-20261106/ui/', import.meta.url);
await mkdir(output, { recursive: true });
const mutations = [];
let settingsFailure = false;
let holdSettingsRead = false;
let releaseSettingsRead;
let policy = { revision: 0, allowed_tags: ['هنر', 'کتاب', 'شعر'], auto_publish: true };
let channelSyncAvailable = false;
const post = { id: 24, slug: 'editor-fixture', text: 'روایت آزمایشی هنر\nمتن بلند برای بررسی ویرایش و سئوی خودکار ماهون. #هنر', created_at: '2026-11-05T10:00:00Z', is_published: 1, seo_title: '', seo_description: '', admin_note: '' };
const mediaPost = { ...post, id: 25, slug: 'media-fixture', text: 'روایت تصویر و هنر\nشرح تصویر نمونه برای بررسی کتابخانه رسانه. #کتاب', media_type: 'photo', media_file_id: 'fixture-photo', media_url: origin + '/sources/mahoon-logo.jpg' };
const deletedPost = { ...post, id: 31, slug: 'deleted-fixture', text: 'مطلب حذف‌شده قابل بازگردانی #شعر', deleted_at: '2026-11-05T12:00:00Z', is_published: 0 };
const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url, origin);
    if (url.pathname.startsWith('/fixture-api/')) {
      res.setHeader('Content-Type', 'application/json; charset=utf-8');
      if (req.headers.authorization !== 'Bearer local-fixture') { res.statusCode = 401; res.end(JSON.stringify({ error: 'Unauthorized' })); return; }
      if (settingsFailure && url.pathname.endsWith('/admin/site-settings')) { res.statusCode = 503; res.end(JSON.stringify({ error: 'Fixture settings unavailable' })); return; }
      if (holdSettingsRead && req.method === 'GET' && url.pathname.endsWith('/admin/site-settings')) {
        holdSettingsRead = false;
        await new Promise(resolve => { releaseSettingsRead = resolve; });
        res.end(JSON.stringify({ ok: true, settings: { site_name: 'پاسخ قدیمی' } })); return;
      }
      let body = ''; for await (const part of req) body += part;
      if (req.method !== 'GET') { mutations.push({ path: url.pathname, method: req.method, body: JSON.parse(body || '{}') }); }
      if (url.pathname.endsWith('/admin/publication-policy')) {
        if (req.method === 'PATCH') policy = { ...JSON.parse(body).policy, revision: policy.revision + 1 };
        res.end(JSON.stringify({ ok: true, policy, affected_count: 1, unpublished_count: 1, channel_deletion: { available: channelSyncAvailable, checked_at: channelSyncAvailable ? new Date().toISOString() : null } })); return;
      }
      if (url.pathname.endsWith('/admin/telegram/webhook-info')) { res.end(JSON.stringify({ ok: true, readiness: { ready: true } })); return; }
      if (url.pathname.endsWith('/analytics/report-v5')) {
        res.end(JSON.stringify({ ok: true, totals: { pageviews: 1240, unique_visitors: 780, sessions: 904, today: 66, yesterday: 52 },
          byDay: [{ day: '2026-11-04', views: 31 }, { day: '2026-11-05', views: 52 }, { day: '2026-11-06', views: 66 }],
          topPages: [{ path: '/posts', title: 'همه مطالب', views: 240 }], referrers: [{ referrer_host: 'google.com', views: 110 }],
          devices: [{ device: 'mobile', views: 840 }], countries: [{ country: 'IR', views: 900 }], recent: [] })); return;
      }
      if (req.method === 'POST' && url.pathname.endsWith('/posts/31/restore')) { deletedPost.deleted_at = null; deletedPost.is_published = 1; }
      if (req.method === 'PATCH' && url.pathname.endsWith('/posts/24')) Object.assign(post, JSON.parse(body));
      const selected = /\/posts\/25$/.test(url.pathname) ? mediaPost : /\/posts\/31(?:\/restore)?$/.test(url.pathname) ? deletedPost : post;
      const rows = url.pathname.includes('deleted') ? deletedPost.deleted_at ? [deletedPost] : [] : url.searchParams.get('media') === 'media' ? [mediaPost] : [post, mediaPost, ...(!deletedPost.deleted_at ? [deletedPost] : [])];
      res.end(JSON.stringify({ ok: true, id: selected.id, slug: selected.slug, post: selected, posts: rows, total: rows.length,
        stats: { total: 2 + Number(!deletedPost.deleted_at), published: 1 + Number(post.is_published) + Number(!deletedPost.deleted_at), draft: Number(!post.is_published), deleted: Number(Boolean(deletedPost.deleted_at)) }, settings: {} })); return;
    }
    const upstream = await fetch(source + req.url);
    res.statusCode = upstream.status;
    res.setHeader('Content-Type', upstream.headers.get('content-type') || 'application/octet-stream');
    const body = Buffer.from(await upstream.arrayBuffer());
    res.end(upstream.headers.get('content-type')?.includes('text/html')
      ? body.toString().replaceAll('https://api.mahoonartmagazine.ir', origin + '/fixture-api') : body);
  } catch { res.statusCode = 502; res.end('Local fixture upstream unavailable'); }
});
await new Promise(resolve => server.listen(4328, '127.0.0.1', resolve));
if (process.argv.includes('--serve')) { console.log('Local editor fixture at ' + origin + '/admin (token: local-fixture; no production writes).'); }
else {
  const browser = await chromium.launch({ headless: true });
  const errors = [];
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    await context.route('**/*', route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
    const page = await context.newPage();
    page.setDefaultTimeout(10000);
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(origin + '/admin');
    await page.locator('#tokenInput').fill('wrong-fixture');
    await page.locator('#tokenInput').press('Enter');
    await page.waitForFunction(() => document.querySelector('#loginMessage').textContent.includes('اشتباه'));
    await page.locator('#tokenInput').fill('local-fixture');
    await page.locator('#loginBtn').click();
    await page.locator('#dashboardView.active').waitFor();
    assert.equal(await page.locator('.toast.error').count(), 0);
    await page.waitForFunction(() => document.fonts.status === 'loaded');
    await page.screenshot({ animations: 'disabled', path: fileURLToPath(new URL('admin-desktop-after.png', output)) });
    await page.locator('[data-section-link="posts"]').click();
    await page.locator('[data-edit-id="24"]').first().click();
    await page.locator('#postText').waitFor({ state: 'visible' });
    assert.match(await page.locator('#editorTitle').textContent(), /24/);
    await page.locator('#postText').fill('روایت تازه\nتوضیح تازه برای سئوی خودکار #هنر');
    await page.locator('[data-editor-tab="seo"]').click();
    assert.match(await page.locator('#editorSeoTitle').textContent(), /روایت تازه/);
    await page.locator('#seoTitle').fill('عنوان اختصاصی');
    assert.equal(await page.locator('#editorSeoTitle').textContent(), 'عنوان اختصاصی');
    await page.locator('[data-editor-tab="seo"]').press('ArrowLeft');
    assert.equal(await page.locator('[data-editor-tab="note"]').getAttribute('aria-selected'), 'true');
    await page.locator('#clearBtn').click();
    await page.locator('#confirmDialog[open]').waitFor();
    await page.getByRole('button', { name: 'لغو', exact: true }).click();
    assert.match(await page.locator('#postText').inputValue(), /روایت تازه/);
    await page.locator('[data-sidebar-logout]').click();
    await page.locator('#confirmDialog[open]').waitFor();
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#dashboardView').getAttribute('class'), 'dashboard active');
    await page.locator('[data-section-link="posts"]').click();
    await page.locator('[data-edit-id="24"]').first().click();
    await page.locator('#confirmDialog[open]').waitFor();
    await page.keyboard.press('Escape');
    assert.match(await page.locator('#postText').inputValue(), /روایت تازه/);
    // Saving the fixture checks stable database ID, private note handling, and manual SEO priority.
    await page.locator('[data-section-link="create"]').click();
    assert.match(await page.locator('#postText').inputValue(), /روایت تازه/);
    await page.locator('#saveBtn').click();
    await page.waitForFunction(() => document.querySelector('#editorMessage').textContent.includes('موفقیت'));
    assert.equal(mutations.length, 1);
    assert.equal(mutations[0].path, '/fixture-api/admin/posts/24');
    assert.equal(mutations[0].body.seo_title, 'عنوان اختصاصی');
    assert.equal(mutations[0].body.seo_description, ''); // blank remains automatically derived by public SEO
    for (const section of ['dashboard','posts','media','seo','site-copy','deleted','analytics','export','settings','automation']) {
      await page.locator(`[data-section-link="${section}"]`).click();
      await page.locator(`[data-admin-section="${section}"]`).waitFor({ state: 'visible' });
    }
    await page.locator('[data-section-link="site-copy"]').click();
    await page.waitForFunction(() => !document.querySelector('#saveSiteCopyBtn').disabled);
    await page.locator('[data-section-link="dashboard"]').click();
    holdSettingsRead = true;
    await page.locator('[data-section-link="site-copy"]').click();
    assert.equal(await page.locator('#siteNameInput').isDisabled(), true);
    await page.locator('[data-section-link="dashboard"]').click();
    await page.locator('[data-section-link="site-copy"]').click();
    await page.waitForFunction(() => !document.querySelector('#siteNameInput').disabled);
    await page.locator('#siteNameInput').fill('پیش‌نویس تنظیمات');
    releaseSettingsRead();
    await page.waitForLoadState('networkidle');
    assert.equal(await page.locator('#siteNameInput').inputValue(), 'پیش‌نویس تنظیمات');
    await page.locator('[data-section-link="dashboard"]').click();
    await page.locator('[data-section-link="site-copy"]').click();
    assert.equal(await page.locator('#siteNameInput').inputValue(), 'پیش‌نویس تنظیمات');
    await page.locator('#reloadSiteCopyBtn').click();
    await page.locator('#confirmDialog[open]').waitFor();
    await page.getByRole('button', { name: 'لغو', exact: true }).click();
    assert.equal(await page.locator('#siteNameInput').inputValue(), 'پیش‌نویس تنظیمات');
    settingsFailure = true;
    await page.locator('#reloadSiteCopyBtn').click();
    await page.locator('#confirmDialog[open]').waitFor();
    await page.getByRole('button', { name: 'دریافت دوباره', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('#siteCopyState').textContent.includes('ناموفق'));
    assert.equal(await page.locator('#saveSiteCopyBtn').isDisabled(), true);
    settingsFailure = false;
    await page.locator('#reloadSiteCopyBtn').click();
    await page.waitForFunction(() => !document.querySelector('#saveSiteCopyBtn').disabled);
    assert.equal(mutations.length, 1);
    for (const width of [390, 768, 1440]) {
      await page.setViewportSize({ width, height: 844 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      if (width <= 900) {
        await page.waitForFunction(() => document.querySelector('#adminSidebar').inert);
        assert.equal(await page.locator('#adminSidebar').evaluate(el => el.inert), true);
        await page.locator('#sidebarToggle').click();
        assert.equal(await page.locator('#adminSidebar').evaluate(el => el.inert), false);
        await page.keyboard.press('Escape');
        assert.equal(await page.locator('#sidebarToggle').getAttribute('aria-expanded'), 'false');
      }
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.locator('[data-section-link="automation"]').click();
    await page.locator('#policyFields').waitFor({ state: 'visible' });
    await page.locator('#policyTestText').fill('https://example.test/#کتاب');
    assert.match(await page.locator('#policyTestResult').textContent(), /متوقف/);
    await page.locator('#policyTestText').fill('این یک مطلب نمونه است. (#کتاب)،');
    assert.match(await page.locator('#policyTestResult').textContent(), /مجاز/);
    await page.locator('#publicationTags').fill('#شعر');
    assert.match(await page.locator('#policyTestResult').textContent(), /متوقف/);
    await page.locator('#savePolicy').click();
    await page.locator('#confirmDialog[open]').waitFor();
    await page.keyboard.press('Escape');
    assert.equal(mutations.filter(m => m.method === 'PATCH' && m.path.endsWith('/publication-policy')).length, 0);
    await page.locator('#savePolicy').click();
    await page.locator('#confirmDialog[open]').waitFor();
    await page.locator('#confirmOkBtn').click();
    await page.waitForFunction(() => document.querySelector('#policyState').textContent === 'ذخیره شد');
    assert.equal(policy.revision, 1); assert.deepEqual(policy.allowed_tags, ['شعر']);
    await page.locator('#checkTelegramConnection').click();
    await page.waitForFunction(() => document.querySelector('#telegramConnectionState').textContent.includes('تأیید شد'));
    assert.match(await page.locator('#channelDeleteState').textContent(), /نیازمند/);
    channelSyncAvailable = true;
    await page.locator('#checkTelegramConnection').click();
    await page.waitForFunction(() => document.querySelector('#channelDeleteState').textContent.includes('همگام‌سازی فعال'));
    channelSyncAvailable = false;
    await page.locator('#checkTelegramConnection').click();
    await page.waitForFunction(() => document.querySelector('#channelDeleteState').textContent.includes('نیازمند'));
    await page.screenshot({ animations: 'disabled', path: fileURLToPath(new URL('automation-light.png', output)) });
    await page.locator('#themeToggle').click();
    assert.equal(await page.locator('html').getAttribute('data-admin-theme'), 'dark');
    await page.screenshot({ animations: 'disabled', path: fileURLToPath(new URL('automation-dark.png', output)) });
    await page.locator('#themeToggle').click();
    await page.locator('[data-section-link="posts"]').click();
    await page.locator('[data-edit-id="24"]').first().click();
    await page.locator('#postText').fill('پیش‌نویس قابل بازیابی #شعر');
    await page.waitForFunction(() => JSON.parse(sessionStorage.getItem('mahoon_editor_draft_v1')).payload.text.includes('قابل بازیابی'));
    await page.reload();
    await page.locator('#dashboardView.active').waitFor();
    await page.locator('#draftRecovery').waitFor({ state: 'visible' });
    await page.locator('#restoreLocalDraft').click();
    await page.waitForFunction(() => document.querySelector('#editorMessage').textContent.includes('نسخه موقت بازیابی شد'));
    assert.equal(await page.locator('#postText').inputValue(), 'پیش‌نویس قابل بازیابی #شعر');
    assert.equal(await page.locator('#postId').inputValue(), '24');
    await page.locator('#postText').fill('این مطلب هشتگ مجاز ندارد');
    const savesBefore = mutations.filter(m => m.path.endsWith('/posts/24')).length;
    await page.locator('#saveBtn').click();
    await page.waitForFunction(() => document.querySelector('#editorMessage').textContent.includes('هشتگ مجاز'));
    assert.equal(mutations.filter(m => m.path.endsWith('/posts/24')).length, savesBefore);
    await page.locator('#isPublished').uncheck();
    await page.locator('#saveBtn').click();
    await page.waitForFunction(() => document.querySelector('#localDraftState').textContent.includes('ذخیره نهایی'));
    assert.equal(await page.evaluate(() => sessionStorage.getItem('mahoon_editor_draft_v1')), null);
    await page.locator('[data-section-link="dashboard"]').click();
    await page.locator('[data-start-new]').click();
    await page.waitForFunction(() => document.querySelector('#postId').value === '' && !document.querySelector('#createSection').hidden);
    await page.locator('#postText').fill('کتاب صوتی نمونه #کتاب‌گویا');
    await page.locator('[data-editor-tab="preview"]').click();
    assert.equal(await page.locator('#previewTags .badge').first().textContent(), '#کتاب‌گویا');
    await page.locator('#clearBtn').click();
    await page.locator('#confirmDialog[open]').waitFor();
    await page.locator('#confirmOkBtn').click();
    await page.waitForFunction(() => document.querySelector('#postText').value === '');
    for (const [section, screenshot] of [['dashboard','dashboard'],['posts','posts'],['create','editor'],['automation','automation'],['seo','seo'],['analytics','analytics']]) {
      await page.locator(`[data-section-link="${section}"]`).click();
      await page.locator(`[data-admin-section="${section}"]`).waitFor({ state: 'visible' });
      if (section === 'seo') await page.waitForFunction(() => !document.querySelector('#seoChecklist').textContent.includes('در حال دریافت'));
      if (section === 'analytics') {
        await page.waitForFunction(() => document.querySelector('#analyticsStatus').textContent.includes('بروزرسانی شد'));
        assert.equal(await page.locator('#analyticsPageviews').textContent(), (1240).toLocaleString('fa-IR'));
        assert.equal(await page.locator('.analytics-bar-row').count(), 3);
        assert.ok((await page.locator('.analytics-bar-track').first().boundingBox()).height >= 8);
      }
      await page.screenshot({ animations: 'disabled', path: fileURLToPath(new URL(`${screenshot}-desktop.png`, output)) });
    }
    for (const width of [390, 768]) {
      await page.setViewportSize({ width, height: 844 });
      await page.waitForFunction(() => document.querySelector('#adminSidebar').inert);
      for (const section of ['dashboard','posts','create','automation','media','seo','site-copy','deleted','analytics','export','settings']) {
        await page.locator('#sidebarToggle').click();
        await page.locator(`[data-section-link="${section}"]`).click();
        await page.locator(`[data-admin-section="${section}"]`).waitFor({ state: 'visible' });
        await page.waitForFunction(() => document.querySelector('#sidebarToggle').getAttribute('aria-expanded') === 'false' && !document.querySelector('.admin-workspace').inert);
        await page.locator('#adminSidebar').evaluate(el => Promise.all(el.getAnimations().map(animation => animation.finished)));
        if (section === 'media') await page.locator('#mediaLibrary .admin-data-row').waitFor();
        if (section === 'seo') await page.waitForFunction(() => !document.querySelector('#seoChecklist').textContent.includes('در حال دریافت'));
        if (await page.locator(`[data-admin-section="${section}"] .admin-row-meta`).count()) assert.ok((await page.locator(`[data-admin-section="${section}"] .admin-row-meta`).first().boundingBox()).width >= 200, `${section} metadata ${width}`);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `${section} ${width}`);
        await page.screenshot({ animations: 'disabled', path: fileURLToPath(new URL(`${section}-${width}.png`, output)) });
      }
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.locator('[data-section-link="deleted"]').click();
    await page.locator('[data-restore-id="31"]').click();
    await page.locator('#confirmDialog[open]').waitFor();
    if (await page.locator('#confirmInput').isVisible()) await page.locator('#confirmInput').fill('31');
    await page.locator('#confirmOkBtn').click();
    await page.waitForFunction(() => !document.querySelector('[data-restore-id="31"]'));
    assert.equal(deletedPost.id, 31); assert.equal(deletedPost.deleted_at, null); assert.equal(deletedPost.is_published, 1);
    assert.deepEqual(errors, []);
    await writeFile(new URL('editor-test.json', output), JSON.stringify({ PASS: true, checks: ['login failure and recovery','stable-ID editing and restore','automatic/manual SEO preview','RTL keyboard tabs','clear/logout/replace cancel preserves unsaved content','fixture-only save','all 11 sections','settings draft preserved, out-of-order reads ignored, failed read cannot overwrite production','policy preview, cancel and confirmed apply','literal Unicode hashtags including ZWNJ, URLs excluded','theme toggle','reload and recover draft with stable ID','untagged publication rejected, draft allowed','dashboard new-post action resets stable ID','populated analytics KPI and visible bar tracks','media/SEO/deleted metadata usable width on mobile','390/768/1440 overflow and drawer keyboard'], production_mutations: 0, page_errors: errors }, null, 2));
    console.log('Editor UI regression tests passed; production writes: 0.');
  } finally { await browser.close(); server.close(); }
}
