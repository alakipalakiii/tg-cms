import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { createHash } from 'node:crypto';
import { readFile, mkdir, writeFile } from 'node:fs/promises';

const require = createRequire(new URL('../../website/dreary-disk/package.json', import.meta.url));
const { chromium, request } = require('playwright');
const base = 'https://mahoonartmagazine.ir';
const candidate = process.env.MAHOON_EXPECTED_VERSION;
assert.match(candidate || '', /^[0-9a-f-]{36}$/);
const state = JSON.parse(await readFile('publisher-state/published-static-state.json', 'utf8'));
const manifest = JSON.parse(await readFile('publisher-state/production-media-manifest.json', 'utf8'));
const media = manifest.records.find((record) => record.post_ids?.includes(782) && record.mime === 'audio/ogg');
assert.ok(media && media.fallback === false);
const header = (version) => ({ 'cloudflare-workers-version-overrides': `mahoon-art-magazine="${version}"` });
const output = 'runner-evidence/live-functionality/audio-runtime.json';
await mkdir('runner-evidence/live-functionality', { recursive: true });
const report = { baseline: state.current_version, candidate, source_path: media.immutable_path, transfers: [], cases: [] };
const save = () => writeFile(output, JSON.stringify(report, null, 2) + '\n');
const http = await request.newContext({ timeout: 15000 });
let browser;
try {
  for (const version of [state.current_version, candidate]) {
    const response = await http.get(base + media.immutable_path, { headers: header(version) });
    const bytes = await response.body();
    assert.equal(response.status(), 200);
    assert.equal(createHash('sha256').update(bytes).digest('hex'), media.sha256);
    const range = await http.get(base + media.immutable_path, { headers: { ...header(version), Range: 'bytes=0-65535' } });
    const partial = await range.body();
    assert.ok([200, 206].includes(range.status()));
    assert.deepEqual(partial, range.status() === 206 ? bytes.subarray(0, 65536) : bytes);
    report.transfers.push({ version, bytes: bytes.length, sha256: media.sha256, headers: {
      content_type: response.headers()['content-type'], content_length: response.headers()['content-length'],
    }, range_status: range.status(), range_bytes: partial.length, content_range: range.headers()['content-range'] || null });
    await save();
  }
  browser = await chromium.launch({ headless: true, args: ['--autoplay-policy=no-user-gesture-required'] });
  for (const [name, version, method] of [
    ['baseline_unintercepted', state.current_version, 'none'],
    ['baseline_route_headers', state.current_version, 'headers'],
    ['candidate_route_all_headers', candidate, 'allHeaders'],
    ['candidate_context_headers', candidate, 'context'],
  ]) {
    const context = await browser.newContext(method === 'context' ? { extraHTTPHeaders: header(version) } : {});
    const page = await context.newPage();
    const result = { name, version, method, media_responses: [] };
    report.cases.push(result); await save();
    if (method === 'headers' || method === 'allHeaders') await page.route('**/*', async (route) => {
      const headers = method === 'allHeaders' ? await route.request().allHeaders() : route.request().headers();
      await route.continue({ headers: new URL(route.request().url()).origin === base ? { ...headers, ...header(version) } : headers });
    });
    page.on('response', (response) => {
      if (response.request().resourceType() === 'media') result.media_responses.push({
        status: response.status(), range_request: response.request().headers().range || null,
        content_length: response.headers()['content-length'] || null, content_range: response.headers()['content-range'] || null,
      });
    });
    try {
      const response = await page.goto(base + '/post/782/', { waitUntil: 'domcontentloaded', timeout: 45000 });
      assert.equal(response.status(), 200); assert.equal(response.headers()['x-mahoon-worker-version'], version);
      const audio = page.locator('[data-mahoon-native-player] audio.mahoon-native-player__audio');
      await audio.evaluate((node) => { node.preload = 'auto'; node.load(); });
      result.finite_metadata = await page.waitForFunction(() => {
        const node = document.querySelector('[data-mahoon-native-player] audio.mahoon-native-player__audio');
        return node && node.readyState >= 2 && Number.isFinite(node.duration) && node.duration > 0;
      }, null, { timeout: 10000 }).then(() => true).catch(() => false);
      await page.locator('[data-mahoon-native-player] .js-play:visible').first().click();
      result.play_progress = await page.waitForFunction((path) => [...document.querySelectorAll('audio')].some((node) =>
        node.currentSrc && new URL(node.currentSrc).pathname === path && !node.paused && node.currentTime > 0.1),
      media.immutable_path, { timeout: 10000 }).then(() => true).catch(() => false);
      result.players = await page.locator('audio').evaluateAll((nodes) => nodes.map((node) => ({
        native: Boolean(node.closest('[data-mahoon-native-player]')), duration: String(node.duration),
        ready_state: node.readyState, current_time: node.currentTime, paused: node.paused, error_code: node.error?.code || null,
      })));
      result.decoded_duration = await page.evaluate(async (path) => {
        const bytes = await (await fetch(path)).arrayBuffer(); const audioContext = new AudioContext();
        try { return (await audioContext.decodeAudioData(bytes)).duration; } finally { await audioContext.close(); }
      }, media.immutable_path);
    } catch (error) { result.error_type = error.name; }
    finally { await context.close(); await save(); }
  }
  report.diagnostic_completed = true;
} catch (error) { report.error_type = error.name; process.exitCode = 1; }
finally { await browser?.close(); await http.dispose(); await save(); console.log(JSON.stringify(report)); }
