import { createRequire } from 'node:module';
import { createServer } from 'node:http';
import { readFile, mkdir } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(new URL('../../website/dreary-disk/package.json', import.meta.url));
const { chromium } = require('playwright');
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../..');

export function classifyPublicRequest(raw) {
  const url = new URL(raw);
  const host = url.hostname.toLowerCase();
  if (host === 'api.mahoonartmagazine.ir') {
    if (url.pathname.startsWith('/media/')) return 'media_api';
    if (/search/i.test(url.pathname)) return 'search_backend';
    return 'content_api';
  }
  if (host.endsWith('.workers.dev')) return 'workers_dev_content';
  if (host === 'api.telegram.org' || host === 'telegram.org' || host.endsWith('.telegram.org')) return 'telegram';
  if (/search|query|posts-full/i.test(url.pathname) && host !== 'mahoonartmagazine.ir') return 'search_backend';
  return null;
}

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === '--self-test') args.selfTest = true;
    else if (argv[i].startsWith('--')) args[argv[i].slice(2)] = argv[++i];
  }
  return args;
}

function sortedPosts(posts) {
  return [...posts].sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')) || Number(b.id) - Number(a.id));
}

export function adminStructurePass(structure) {
  return structure.textLength > 0 && structure.admin && structure.authLogin && structure.loginVisible
    && !structure.overflow && structure.title.length > 0
    && !/^(?:Times New Roman|serif)$/i.test(structure.font.trim());
}

function representatives(snapshot, routes) {
  if (snapshot.contract === 'MAHOON_REMOTE_EXPECTATIONS_V1') {
    return (snapshot.visual_routes || []).map((item) => ({ ...item }));
  }
  const posts = sortedPosts(snapshot.payload.posts || []);
  const byPath = new Set(routes);
  const routeFor = (post) => `/post/${post.slug}`;
  const newest = posts[0];
  const oldest = posts.at(-1);
  const categoryPost = posts.find((post) => /#(کتاب|دیالوگ|صوتی|متن|شعر|نقاشی)/u.test(post.text || ''));
  const audioPost = posts.find((post) => /audio|voice|music|audio_book|کتاب.?صوتی/i.test(`${post.media_type || ''} ${post.text || ''}`));
  const selected = [
    { name: 'home-desktop', route: '/' },
    { name: 'archive', route: '/posts' },
    { name: 'category', route: categoryPost ? `/category/${encodeURIComponent((categoryPost.text.match(/#(کتاب|دیالوگ|صوتی|متن|شعر|نقاشی)/u) || [])[1] || '')}` : '' },
    { name: 'old-post', route: oldest ? routeFor(oldest) : '' },
    { name: 'new-post', route: newest ? routeFor(newest) : '' },
    ...(audioPost ? [{ name: 'audio-post', route: routeFor(audioPost) }] : []),
    { name: 'admin-shell', route: '/admin', admin: true },
  ];
  selected[2].route = selected[2].route.replaceAll('%20', '%20');
  const categoryRoute = routes.find((route) => route.startsWith('/category/') && !route.includes('/page/'));
  if (categoryRoute) selected[2].route = categoryRoute;
  return selected.filter((item) => item.route && (item.route === '/' || byPath.has(item.route) || byPath.has(decodeURIComponent(item.route))));
}

async function checkPage(browser, base, candidateVersion, route, name, viewport, screenshots, publicPage) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const resources = { stylesheets: 0, scripts: 0, failed: [] };
  const runtime = { content_api: 0, media_api: 0, workers_dev_content: 0, telegram: 0, search_backend: 0 };
  const pageErrors = [];
  const pinnedRequests = [];
  let actualVersion = null;
  const baseOrigin = new URL(base).origin;
  await page.route('**/*', async (routeRequest) => {
    const requestUrl = new URL(routeRequest.request().url());
    if (candidateVersion && requestUrl.origin === baseOrigin) {
      const headers = {
        ...routeRequest.request().headers(),
        'cloudflare-workers-version-overrides': `mahoon-art-magazine="${candidateVersion}"`,
      };
      pinnedRequests.push({ url: requestUrl.href, version: candidateVersion });
      await routeRequest.continue({ headers });
    } else {
      await routeRequest.continue();
    }
  });
  if (publicPage) {
    page.on('request', (request) => {
      const kind = classifyPublicRequest(request.url());
      if (kind) runtime[kind] += 1;
    });
  }
  page.on('response', (response) => {
    if (response.request().isNavigationRequest() && response.request().frame() === page.mainFrame()) {
      actualVersion = response.headers()['x-mahoon-worker-version'] || null;
    }
    const kind = response.request().resourceType();
    if (kind === 'stylesheet') {
      if (response.ok()) resources.stylesheets += 1;
      else resources.failed.push({ url: response.url(), status: response.status() });
    }
    if (kind === 'script') {
      if (response.ok()) resources.scripts += 1;
      else resources.failed.push({ url: response.url(), status: response.status() });
    }
  });
  page.on('pageerror', (error) => pageErrors.push(String(error).slice(0, 200)));
  const url = new URL(route, base).href;
  let status = 0;
  try {
    const response = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });
    status = response?.status() || 0;
    await page.waitForTimeout(800);
    const structure = await page.evaluate(() => ({
      textLength: document.body?.innerText?.trim().length || 0,
      main: Boolean(document.querySelector('main')),
      header: Boolean(document.querySelector('header')),
      admin: document.body?.classList.contains('admin-page') && Boolean(document.querySelector('.admin-shell')),
      authLogin: Boolean(document.querySelector('#loginView #tokenInput[type="password"]')
        && document.querySelector('#loginView #loginBtn')),
      loginVisible: (() => {
        const element = document.querySelector('#loginView');
        return Boolean(element && getComputedStyle(element).display !== 'none' && element.getClientRects().length);
      })(),
      font: getComputedStyle(document.body).fontFamily,
      overflow: document.documentElement.scrollWidth > innerWidth + 3,
      title: document.title,
    }));
    const styleOk = resources.stylesheets > 0 && !resources.failed.some((item) => item.url.toLowerCase().endsWith('.css'));
    const jsOk = resources.failed.length === 0;
    const structureOk = name === 'admin-shell'
      ? adminStructurePass(structure)
      : structure.textLength > 80 && structure.main && structure.header && !structure.overflow
        && structure.title.length > 0 && !/^(?:Times New Roman|serif)$/i.test(structure.font.trim());
    const versionAttributionPass = !candidateVersion || actualVersion === candidateVersion;
    const overridePinned = !candidateVersion || pinnedRequests.length > 0
      && pinnedRequests.every((item) => item.version === candidateVersion);
    if (screenshots) {
      await mkdir(screenshots, { recursive: true });
      await page.screenshot({ path: resolve(screenshots, `${name}-${viewport.width}.png`), fullPage: true, timeout: 30000 });
    }
    return { name, route, status, structure, resources, runtime, pageErrors,
      actual_version: actualVersion, version_attribution_pass: versionAttributionPass,
      override_pinned_on_every_same_origin_request: overridePinned,
      visual_pass: status === 200 && styleOk && jsOk && structureOk && versionAttributionPass && overridePinned && pageErrors.length === 0,
      zero_origin_pass: !Object.values(runtime).some(Boolean) };
  } catch (error) {
    return { name, route, status, resources, runtime, pageErrors,
      actual_version: actualVersion, version_attribution_pass: !candidateVersion || actualVersion === candidateVersion,
      override_pinned_on_every_same_origin_request: !candidateVersion || pinnedRequests.length > 0,
      visual_pass: false, zero_origin_pass: !Object.values(runtime).some(Boolean), failure: String(error).slice(0, 300) };
  } finally {
    await context.close();
  }
}

async function runCandidate(args) {
  const sourcePath = args.expectations || args.snapshot;
  if (!sourcePath) throw new Error('--expectations or --snapshot is required');
  const snapshot = JSON.parse(await readFile(sourcePath, 'utf8'));
  const manifest = JSON.parse(await readFile(args.routes, 'utf8'));
  if (args.expectations && snapshot.contract !== 'MAHOON_REMOTE_EXPECTATIONS_V1') {
    throw new Error('remote expectations contract is invalid');
  }
  const selected = representatives(snapshot, manifest.routes);
  const screenshots = args.output ? `${args.output}.screenshots` : null;
  const browser = await chromium.launch({ headless: true });
  try {
    const checks = [];
    for (const item of selected) {
      const desktop = await checkPage(browser, args['base-url'], args['candidate-version'], item.route, item.name,
        { width: 1440, height: 1000 }, screenshots, !item.admin);
      checks.push(desktop);
      if (item.name === 'home-desktop') {
        checks.push(await checkPage(browser, args['base-url'], args['candidate-version'], '/', 'home-mobile',
          { width: 390, height: 844 }, screenshots, true));
      }
    }
    const runtime = Object.fromEntries(['content_api', 'media_api', 'workers_dev_content', 'telegram', 'search_backend']
      .map((key) => [key, checks.reduce((sum, item) => sum + (item.runtime?.[key] || 0), 0)]));
    const visualPass = checks.length >= 6 && checks.every((item) => item.visual_pass);
    const publicChecks = checks.filter((item) => item.name !== 'admin-shell');
    const zeroOriginPass = publicChecks.length > 0 && publicChecks.every((item) => item.zero_origin_pass)
      && Object.values(runtime).every((count) => count === 0);
    return { measured: true, candidate_version: args['candidate-version'], checks,
      visual: { pages_checked: checks.length, PASS: visualPass },
      zero_origin: { public_pages_checked: publicChecks.length, requests: runtime, PASS: zeroOriginPass },
      PASS: visualPass && zeroOriginPass };
  } finally {
    await browser.close();
  }
}

async function selfTest() {
  const server = createServer((req, res) => {
    const path = new URL(req.url, 'http://127.0.0.1').pathname;
    if (path === '/style.css') {
      if (req.url.includes('broken')) { res.writeHead(404); res.end('missing'); return; }
      res.writeHead(200, { 'content-type': 'text/css' });
      res.end('body{font-family:Arial,sans-serif;margin:0}.site-header{display:block}main{min-height:200px}');
      return;
    }
    if (path === '/app.js') {
      res.writeHead(200, { 'content-type': 'text/javascript' });
      res.end("if(location.pathname==='/bad-origin') fetch('https://api.mahoonartmagazine.ir/posts')");
      return;
    }
    res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
    if (path === '/admin' || path === '/admin-broken') {
      const auth = path === '/admin'
        ? '<label for="tokenInput">رمز مدیر</label><input id="tokenInput" type="password"><button id="loginBtn">ورود</button>'
        : '<label>ورود مدیر</label><button>ورود</button>';
      res.end(`<!doctype html><html><head><title>Admin fixture</title><link rel="stylesheet" href="/style.css"><script defer src="/app.js"></script></head><body class="admin-page"><main><section id="loginView" class="login-wrap"><div class="login-card"><h1>مدیریت</h1>${auth}</div></section><section class="dashboard"><div class="admin-shell"></div></section></main></body></html>`);
      return;
    }
    const broken = path === '/bad-visual';
    res.end(`<!doctype html><html><head><title>Fixture</title><link rel="stylesheet" href="/style.css${broken ? '?broken' : ''}"><script defer src="/app.js"></script></head><body><header class="site-header">MAHOON art magazine</header>${broken ? '<div>broken shell</div>' : '<main><h1>Fixture content</h1><p>Visible page content for measured visual gate with enough readable text to rule out a blank error shell.</p></main>'}</body></html>`);
  });
  await new Promise((resolveListen) => server.listen(0, '127.0.0.1', resolveListen));
  const base = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch({ headless: true });
  const intercept = async (page) => page.route('https://api.mahoonartmagazine.ir/**', (route) => route.abort());
  try {
    const healthy = await browser.newPage({ viewport: { width: 1280, height: 800 } });
    await intercept(healthy);
    const good = await checkPage(browser, base, null, '/', 'fixture', { width: 1280, height: 800 }, null, true);
    await healthy.close();
    const shortAdmin = await checkPage(browser, base, null, '/admin', 'admin-shell', { width: 1280, height: 800 }, null, false);
    const structurallyBrokenAdmin = await checkPage(browser, base, null, '/admin-broken', 'admin-shell', { width: 1280, height: 800 }, null, false);
    const brokenVisual = await checkPage(browser, base, null, '/bad-visual', 'fixture', { width: 1280, height: 800 }, null, true);
    const brokenNetworkPage = await browser.newPage({ viewport: { width: 1280, height: 800 } });
    await intercept(brokenNetworkPage);
    let blockedRequests = 0;
    brokenNetworkPage.on('request', (request) => { if (classifyPublicRequest(request.url()) === 'content_api') blockedRequests += 1; });
    await brokenNetworkPage.goto(`${base}/bad-origin`);
    await brokenNetworkPage.waitForTimeout(300);
    await brokenNetworkPage.close();
    const results = {
      visual_healthy_fixture: good.visual_pass,
      visual_healthy_diagnostic: { status: good.status, structure: good.structure, resources: good.resources, pageErrors: good.pageErrors },
      visual_broken_fixture: !brokenVisual.visual_pass,
      admin_structural_short_login_fixture: shortAdmin.visual_pass && shortAdmin.structure.textLength < 80,
      admin_structural_missing_auth_fixture: !structurallyBrokenAdmin.visual_pass,
      zero_origin_healthy_fixture: good.zero_origin_pass,
      zero_origin_broken_fixture: blockedRequests > 0,
      measured_blocked_api_requests: blockedRequests,
    };
    results.PASS = Object.values(results).every((value) => typeof value !== 'boolean' || value === true);
    console.log(JSON.stringify(results));
    return results.PASS ? 0 : 1;
  } finally {
    await browser.close();
    await new Promise((resolveClose) => server.close(resolveClose));
  }
}

const args = parseArgs(process.argv.slice(2));
const exitCode = args.selfTest ? await selfTest() : await runCandidate(args).then(async (result) => {
  if (args.output) {
    const target = resolve(args.output);
    await mkdir(dirname(target), { recursive: true });
    const { writeFile } = await import('node:fs/promises');
    await writeFile(target, `${JSON.stringify(result, null, 2)}\n`, 'utf8');
  }
  console.log(JSON.stringify({ measured: result.measured, visual: result.visual, zero_origin: result.zero_origin, PASS: result.PASS }));
  return result.PASS ? 0 : 1;
});
process.exitCode = exitCode;
