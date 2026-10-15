# MAHOON Platform Audit and Optimization

**Status: IN PROGRESS. No phase PASS claimed.**

Updated 2026-10-15T12:14:03.860627+03:30 Asia/Tehran. This is a new audit phase. The previous revision185 publication remains successfully finalized; its report is historical acceptance, not a substitute for current tests.

## Mission and safety

Preserve existing Telegram hashtag ingestion, official logo/font, static rendering, stable database IDs, admin boundaries and the accepted publication journal. No test channel messages, Telegram edits/deletes, destructive admin tests, secret rotation, manual journal edits or mutation replays. Do not change scheduling solely because the static publisher uses CHECK_ONLY.

## Current readbacks

- origin/main and source at start: e02f70c0cfed72892f25b1e90066395c4cbb440b.
- Website deployment cf817382-242d-4d2e-9b40-969c7a9c1332; version1c92b5b0-0426-4f8f-8328-ee741569149b100%, baselinebc11bf72-e914-498d-8665-b7d98c57ff900%.
- Canonical journal generation139; active/pending null; revision185 completed.
- Fresh CHECK_ONLY38705363433:SUCCESS;2026-10-15T08:24:12.657010Z /11:54:12 Tehran; latest185=published185,UNCHANGED. Receipt9ad175e2dff285f812b6babd5aae76c0d2dbde132c4883d73258baadae7d0e49.
- Fresh unpinned browser38705359244:SUCCESS,16/16; seven actual article IDs1914-1920; native audio/video progress, search/pagination, mobile menu/about, loaded fonts, admin401; JS errors0, forbidden dependencies0. Result rawSHA0bb58ec5ec268fb048f8619c26f808cd4333ed158f3a41368542fe5d5b5918e6.
- Current API Worker tg-cms-api deployment375258db-cb64-4154-a685-ee380f1e87a3, versionea717386-6580-4d39-93a0-6c224deae34e100%, deployed2026-09-12. Live module index.js161176bytes, rawSHAa0d53ba90599742076845aa156e40969590b4ef3180152fc4420e66b1764cbd1, read directly via Cloudflare GET content/v2. Repository source151900bytes is not byte-identical; source authority must be checked before backend changes.

## Existing architecture inventory

| Area | Existing implementation / authority | Verification so far |
|---|---|---|
| Telegram ingestion | API extractTelegramPost; channel/message and edited update variants; media association; D1 posts | Live source read; isolated regression/probe work pending |
| Hashtags/categories | Shared taxonomy:book,dialogue,audio,poetry/text,painting; audiobook overlaps book/audio | Source inspected; no mapping change proposed |
| Automatic display | Existing ingestion and public category APIs; nonlocked Astro runtime fetches current API | Owner-confirmed feature; current content parity holds; distinguish from static publication; no new channel message sent |
| Database | Cloudflare D1 DB binding, posts, site_settings/revision and tag projections | Source inspected; no data mutation |
| Public API | public/home-v1,posts-v1,tag-posts-v1,stats-v1 and safe SEO slug lookup | Runtime/public boundary probes pending hosted audit |
| Homepage | Astro server template, featured/latest/category/search/cards; locked-snapshot branch exists | Fresh mobile screenshot and16-check suite |
| Archives | SSR source and static archive client; stable-ID search/load-more | Fresh20->40 pagination PASS |
| Categories | Shared taxonomy and per-category pages | Fresh search/navigation PASS |
| Articles | DB-ID/slug routes, RTL text/media/meta/related articles | Fresh seven article/image checks PASS |
| Search | Static index contract V2 and public API search in dynamic mode | Numeric-ID PASS; Persian character/empty state tests next |
| Audio/video | Native audio layout plus global audio system, video controls, immutable media | Fresh finite duration and playback progress PASS |
| Images | Original media fields, bootstrap immutable records, historical fallback handling | Fresh seven posts decoded images;19 historical fallback records from previous baseline |
| Admin | Existing admin shell, token client, protected API routes and dedicated restore | Fresh visible login/unauthenticated401 PASS; no destructive tests |
| SEO/indexing | SITE.url, read-only /seo/post/:slug, canonical/JSON-LD, sitemap/RSS/robots | Source inspected; previous full proof distinguished from this phase |
| Website runtime | Current static_version_main serves ASSETS and adds version identity; Astro dynamic worker is separate source path | Actual serving version verified; no assumption that CHECK_ONLY means ingestion absent |
| Cache | Immutable static assets; current API/dynamic fetch policies differ | Header/performance measurements pending |
| Static publication | Revision resolution/admission, sealed build,0% candidate, preproof,promote,production proof,six-file persistence | Canonical state closed; no new publication dispatched |
| Recovery | Journal-derived reconciliation/readback/rollback; no APPLIED replay | Source inspected; previous completed recovery preserved |
| Monitoring/errors | Existing safe diagnostics, retained proof observations, analytics v4/v5 paths, scheduler heartbeat | Duplicate supported versions require caller checks before removal |
| Responsive/a11y | Existing header/footer/menu/RTL/font and player system | Fresh390px and desktop screenshots; tablet/keyboard measurements next |

## Provisional defect register

Confirmed:

- P2 DOC-01:workers/api/README.md still calls index.ts a placeholder although the repository contains a full implementation. Root README also describes an older single dynamic runtime without the accepted static mode. Correct after architecture/source authority is fully documented.

Investigations, not yet claimed as confirmed production vulnerabilities:

- SEC-01:live API generic POST branch reaches Telegram extraction without a visible shared-secret header guard. Local source does not show Telegram IP filtering either. Local public probes are blocked/reset and cannot establish edge protection. Verify with empty updates hosted and isolated live-bundle tests; never insert a forged production post.
- SEARCH-01:static client normalization differs from other Persian normalizers; test Arabic yeh/alef maksura, half-spaces and digits against actual search.
- UI/PERF:tablet, keyboard, empty states, contrast/target sizes and browser timing samples pending; do not invent redesign requirements.

## Method and evidence limits

- In-app browser failed with ERR_CONNECTION_RESET; Chrome integration unavailable. Hosted Playwright is the authorized real-browser fallback. Do not label local connection failure production corruption.
- Chrome DevTools MCP is unavailable. Its trace-based Web Performance skill cannot run; browser PerformanceObserver/lab measurements are planned. Field INP and physical iOS/Android behavior must not be fabricated.
- Graphify analyzed168 source files and19 documents, excluding generated publication pages and large content.2851 graph nodes/6772 post-build edges/113 communities. Graph is navigation assistance, not runtime truth:5 SQL files unparsed (optional parser missing),14 Astro files partially parsed,733 dangling endpoint edges and360 undirected same-endpoint collapses. Direct source and runtime tests remain necessary. Semantic token accounting is an agent-reported estimate, not a billing receipt.
- Current screenshots from38705359244 accepted after opening the exact saved files:mobile menu/home and desktop1920 article. Earlier phase screenshots are not used as new audit evidence.
- All private source, raw metadata and audit artifacts remain outside Git under C:/Users/mehdi karani/AppData/Local/Temp/mahoon-platform-audit-20261015. Do not commit secrets, actual account/D1 IDs or private configuration.

## Next execution checkpoint

1. Complete architecture graph labeling/query; confirm live source differences and safe credential/backup capabilities without exposing values.
2. Add/run focused hosted platform audit mode (tablet/Persian search/keyboard/lab performance/public API boundary and parity).
3. Build isolated tests of the actual live API bundle; identify actual P0/P1 failures and root causes.
4. Implement justified repairs with tests, adjacent checks and website build where applicable.
5. Use the established guarded deployment path; investigate supported code-only deployment before any release because185 is already completed. Never fake a content revision or reopen a completed transaction.
6. Final independent production verification, latest expected counts, canonical consistency, evidence-backed final report/commit/push.

## Repair checkpoint — 2026-10-15, approximately 12:45 Tehran / 09:15 UTC

The earlier provisional register is superseded by these findings:

| ID | Priority | Confirmed evidence | Correction / state |
|---|---|---|---|
| SEC-01 | P0 | Authoritative live bundle, isolated unsigned synthetic update reaches INSERT on two paths; mock stops before execution, outbound calls0. Hosted38708829025 accepts empty unsigned updates on both paths. Live secret-binding names confirm no TELEGRAM_WEBHOOK_SECRET. | Fail-closed constant-time header guard prepared; refresh preserves secret and pending updates; real local workerd regression PASS. Not deployed: coordinated Telegram secret registration requires existing owner Bot API credential. See workers/api/WEBHOOK-SECURITY-ROLLOUT.md. No historical compromise claimed. |
| SEARCH-01 | P2 | Regression fails specifically for alef maksura in دىالوگ:0 vs expected1; Persian/Arabic yeh find the same fixture. | One-line normalization /[يى]/g, same as existing taxonomy; regression PASS. Code a9fce831dfcfa6707fc2a8a5aca11d411cf96d31; production deployment pending. |
| A11Y-01 | P2 | Fresh browser accessibility tree has unnamed homepage searchbox; count live-region attributes absent; Escape leaves mobile menu expanded. | Explicit search names in homepage/archive/category, polite status count and Escape closes/restores focus. Source/real-browser fixture PASS; production deployment pending. |
| DOC-01 | P2 | API README incorrectly calls full source a placeholder; root README points to historical origins and direct deploy instructions. | Document official origins, dynamic/static distinction, guarded production path and live API source authority. |
| VISIBILITY-01 | P1 investigation | Fresh hosted public API shows actual new post1921 absent from immutable search index; CHECK_ONLY38709085039 reports revision188 vs published185. | Ingestion is demonstrably receiving genuine new content. Confirm route visibility and exact freshness before changing any schedule. No competing ingestion or fabricated revision. |

## Fresh browser and performance evidence

Run38708829025, unpinned current version, collected9 cold-context laboratory samples. HTTP200 with matching x-mahoon-worker-version, fonts loaded, no horizontal overflow across1440/768/390px; JS errors0 and forbidden dependencies0. Result SHA256 `5d80ca02751808ef286371dee49162ea999723c3c2003a3a5dce7bd3f1c35fe7`.

| Viewport | Samples | Median TTFB ms | Median observed LCP ms | Maximum CLS |
|---|---:|---:|---:|---:|
| Desktop1440×1000 |3|105.3|324|0.00256|
| Tablet768×1024 |3|88.5|308|0.00209|
| Mobile390×844 |3|89.8|272|0.05316|

These are GitHub runner Chromium measurements with no device/network throttling. They are not field Core Web Vitals or physical-device results. No speed optimization is justified by these samples. Desktop, tablet and mobile screenshots were opened from this exact run; established burgundy/cream identity, official logo/font and RTL layout retained. Offscreen lazy images in a full-page screenshot are not classified as broken without load evidence. Placeholder ads/empty illustration slots are not grounds for redesign.

The run's Persian variant check used a term absent from the index, so its failure did not prove a production search fault. The test now verifies its baseline term exists. Follow-up38710010972 stopped before live observations because the new fixture used350ms against a300ms debounce plus async fetch; replaced with state-based waits and reran locally PASS. These diagnostic failures did not mutate production or justify any release retry.

Hosted public GET health/posts/stats all200. Latest public listings expose none of admin_note/chat_id/chat_title/deleted_at/telegram_message_id. API/stat counts differ from deduplicated static listings by design; do not compare raw totals as corruption evidence.

## Dependency audit, reachability and limits

Fresh npm audit reports16 affected dependency entries (1critical/14high/1low, including transitive effects); this is not16 confirmed production exploits. Primary Astro advisory GHSA-26w7-cxv4-gfx2 requires processing untrusted AVIF through Sharp. This project uses imageService:passthrough; current static_version_main serves ASSETS rather than an Astro request renderer. Dev server/Miniflare are not public production servers. The request-time Astro attack path is therefore absent in the accepted static Worker. Do not blindly apply npm audit fix or claim the dependency findings resolved. Remaining advisory/build-time reachability review is pending.

Sources: [Astro AVIF advisory](https://github.com/withastro/astro/security/advisories/GHSA-26w7-cxv4-gfx2), [Telegram webhook secret](https://core.telegram.org/bots/api#setwebhook), [Workers timingSafeEqual](https://developers.cloudflare.com/workers/runtime-apis/web-crypto/#timingsafeequal).

## Executed repair tests

- Static archive browser regression: red for alef maksura before fix; green after fix, including Persian/Arabic kaf/yeh, numeric IDs, load-more, empty/reset, categories, homepage navigation, invalid-index recovery, real media selectors and keyboard focus.
- npm run build --prefix website/dreary-disk:PASS, Astro6.3.6, adapter13.5.2;6.61seconds.
-85 targeted publisher tests:84PASS/1skip (materializer integration requires explicit opt-in). Separately rerun downstream workflow32PASS after diagnostic integration.
- Telegram boundary test:actual local workerd, missing/invalid configuration503, missing/wrong header401 before mock DB, correct header reaches unchanged processing, authenticated empty update200/saved=false, admin401, safe refresh with no dropped pending updates/no secret in response. No real production writes or Telegram messages.

Production website still revision185 at this checkpoint. Website code pushed through a9fce83; API correction is prepared only. No production secret, content, policy, API code or traffic mutation has occurred in this audit phase yet.

## Continuing execution — 2026-10-15, 09:15 UTC / 12:45 Tehran

- Diagnostic38710415271 reached all live checks after hosted fixture and workerd tests passed. It independently confirmed SEARCH-01:Persian/Arabic yeh260 results, alef maksura0. Raw result SHA256 `3888435d9799bbfcf8f0e741e85c73b97a55d2e7e4370ec8defa362933141f38`.
- VISIBILITY-01 is now confirmed:actual new posts1921 (08:30:17UTC) and1922 (08:54:22UTC) appear in public API but not the static index; /post/1922 returns404 with the expected serving version. This is a demonstrated delivery gap after ingestion, independently of the CHECK_ONLY setting. Owner-confirmed Telegram automation was not rebuilt or disabled by this audit. Current static serving bypasses dynamic Astro/API fetching; a fresh accepted publication is needed for new website routes.
- Scheduled publication policy remains CHECK_ONLY; circuit breaker remains OPEN from incident36727673538. No schedule/policy change has been made. Restore existing scheduled publication only after successful current production proof and safe resolution of the inbound trust boundary; use existing breaker recovery helpers, not manual journal edits.
- A single bounded normal PUBLISH was dispatched as38710568217 on source83905b98a663708e237deb5189b9541b8dcfbade, after fresh no-active journal/production/concurrency checks and passing targeted tests. Admission revision188, generation140, transaction784befea489b1ff145a5c67c590931744971d7e5d3ca5db579869989aa6c18f5. This is genuine new content, not a code-only synthetic revision. At this checkpoint build-validate is running; no success/promotion claim yet.
- Additional P1 INGEST-01:read-only D1 aggregates show10 repeated valid (chat_id,telegram_message_id) groups and911 extra historical rows. Local actual-workerd/D1 test reproduced a second row from sequential redelivery before correction. Prepared atomic INSERT SELECT WHERE NOT EXISTS now passes sequential/concurrent replay tests, edit stable ID/slug/tag projection, soft-delete preservation, all five media types and authorized admin content. Historical posts are not deleted, merged or renumbered.
- Source authorization is part of SEC-01:an authenticated Telegram delivery alone does not authorize an arbitrary bot user to publish. Prepared guard permits the verified configured channel plus existing admins. Recent23 source rows match neither STORAGE_CHAT_ID nor configured admin IDs, so the media storage destination is not substituted as the authoritative channel. Resolve @mahoonartmagazine via authenticated getChat and compare current source privately before activation.
- The API correction was also surgically applied to the exact read-back live module in a private prepared file; all workerd/local D1 tests PASS on that version as well. Base source SHA256 a0d53ba90599742076845aa156e40969590b4ef3180152fc4420e66b1764cbd1; prepared source26a6045550f9245e22fc307a8ca9d4e38af996ed38263a2480b5226bdc43475d. This file remains outside Git and is not deployed; live-only logic is retained.
- Owner credential request is pending. No token was requested in chat, extracted from a Worker, exposed through a migration endpoint, rotated or committed. Independent website work continues while API activation waits on secure Bot API access.

## Restore and adjacent boundary regression — 09:22 UTC / 12:52 Tehran

P1 RESTORE-01:both the live API dedicated restore and bot /restore set is_published=0, contradicting the current explicit AGENTS.md requirement deleted_at=NULL/is_published=1. A local D1 regression reproduced0 vs required1. Prepared correction changes both assignments and the admin confirmation/success copy; no other state transition is changed. The existing live bulk-restore behavior is preserved. No production restore/delete/edit was executed.

Extended regression passes on both compiled repository code and the surgically patched actual live module:read-only SEO returns200 with no admin-only fields and leaves view_count0; public PATCH cannot restore a deleted row; dedicated admin restore uses stable ID and publishes; /delete shows preview without mutation, /delete confirm soft-deletes, /restore publishes without changing ID/slug. Current prepared live-module source SHA256 `64de6dfa0b96c4f4f2059745fcea1f73f380356b9454920b73babda222b64633`, superseding the earlier prepared digest. Website build after admin-copy correction PASS in3.40seconds. The new copy is prepared for coordinated rollout with the API and is not included in the already-running revision188 bundle.

## UI/UX journey evidence and retained design

1. Open homepage at1440/768/390px:official logo/font, RTL header, editorial feature, stable grid/carousels and footer retained; no horizontal page overflow. Current screenshot files are home-desktop.png/home-tablet.png/home-mobile.png in38708829025.
2. Keyboard/mobile navigation:Enter opens the menu; old production Escape does not close it. Prepared script closes it and restores focus; actual script is exercised in the browser fixture. No arbitrary menu redesign.
3. Search from homepage/archive/category:numeric database ID flow passes current smoke; actual Persian variant failure captured in search-persian-variant.png from38710415271. Correction uses existing taxonomy normalization. Empty-state screenshot/search results remain readable; explicit accessible names and polite count updates added without visual changes.
4. Read articles and media:38705359244 opened seven recent actual articles, decoded images and advanced native audio/video. Newer188 content acceptance remains pending the running release. Historical unsupported media fallback is distinguished from working native playback.
5. Administration:current public login shell and unauthenticated401 checked; destructive operations excluded from production. Dedicated restore/PATCH/two-step bot deletion are tested only against local D1. Corrected confirmation discloses publication intent per AGENTS.md.

Visual screenshots alone do not certify contrast, screen-reader speech, touch hardware or codec support on physical iOS/Android. No formal WCAG conformance claim is made. No official brand asset, Persian font, layout identity, content ID or existing channel message has been replaced.

## Rejected changes and optional improvements

- No competing Telegram ingestion, test channel post, forced content revision or artificial publication transaction.
- No speculative redesign, logo/font replacement, new media player or dependency migration. Current lab performance does not justify adding a cache layer or removing established components.
- No blind npm audit fix:runtime reachability and adapter-major compatibility matter; static ASSETS serving and passthrough images are retained. Dependency maintenance is a separately scoped P2/P3 item until an exposed attack path is demonstrated.
- No deletion/renumbering of911 historical duplicate rows. Existing presentation deduplication is preserved; prepared atomic ingestion prevents future replay duplicates.
- No removal of analytics v4/v5 or the dynamic Astro path based only on duplication; callers and operational use still exist.
- Optional P3:physical-device/screen-reader/DevTools trace audit and broader contrast sampling. These are evidence limits, not claims of a specific user-facing defect.

Current phase status remains IN PROGRESS/BLOCKED on coordinated API credential access, with independent website publication still running. Do not return phase PASS from these prepared fixes.
