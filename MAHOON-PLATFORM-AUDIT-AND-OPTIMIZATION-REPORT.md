# MAHOON Platform Audit and Optimization

**Status: BLOCKED — coordinated API security activation is held; latest detected content192 is newer than durably completed190. Website190 passed its full acceptance. No platform-phase PASS or latest-content-completion claim.**

Updated 2026-10-15, 15:10 Asia/Tehran / 11:40 UTC. This is a new audit phase. The previous revision185 publication remains successfully finalized; its report is historical acceptance, not a substitute for current tests. Later checkpoints supersede the initial observations below.

## Current execution summary

- Hosted safety run38717022249 on source45c4d3f39cbcbf7ad7198602fde359e12edcc2d1:905 tests in67.449s, no failures/errors, one skip; locked website build PASS5.82s. Node22.23.3/Playwright1.63.0/Chromium153.0.8010.12. The skip requires two optional immutable historical artifact inputs; Linux materializer and browser fixtures executed.
- Read-only platform run38717057790:health/posts/stats200; protected webhook-info401; unsigned empty updates still200/saved=false. Exact raw result SHA256 e72d7119999c0a645c649d7818ca88cac1c03d7c3c1dbe7664e4d4c294e4695e. No secret values, real channel messages or production writes. Its failure is the already-confirmed old-production Persian search variant defect, not a new browser/runtime failure. Current production also retains the old missing accessible status/Escape behavior.
- Pre-release public API included actual posts1921,1922,1923; all were absent from the old static index. Numeric article1923 returns404 with expected version1c92b5b0-0426-4f8f-8328-ee741569149b. New audio1923 created09:24:26UTC; live revision190 changed09:24:47UTC. Ingestion remains active; the static delivery gap is independently demonstrated.
- Normal publication38717369912 completed SUCCESS. Executable source45c4d3f39cbcbf7ad7198602fde359e12edcc2d1; revision190; transaction533326ce77323b7bdb19c03aa3d43a6129fa979ff1006eda0034cf62321d06f8. Journal151, active=null/pending=null. Serving5413751a-cf7e-4f90-aa55-562c520f0054100%, deployment449be33f-3cc1-4312-890f-f3df67718c1f, baseline1c92b5b0-0426-4f8f-8328-ee741569149b0%. All11 production gates and final persistence PASS. No APPLIED operation repeated.
- API security/source/replay/restore correction remains prepared and NOT DEPLOYED under the owner's explicit uninterrupted-ingestion/access instruction. No BOT_TOKEN was supplied, rotated or exposed; no webhook setting was changed. Website/admin copy is compatible with the current API response.

| Finding | Current disposition |
|---|---|
| SEC-01 P0 | Confirmed inbound authentication/source weakness; real workerd/D1 correction passes; coordinated activation held because matching Bot API registration/channel verification cannot be performed with opaque existing bindings. |
| INGEST-01 P1 | Atomic replay suppression prepared/tested; no historical duplicate deletion or ID changes; API rollout held with the verified live-module correction. |
| RESTORE-01 P1 | Dedicated API/bot publication semantics prepared/tested; current API unchanged; website success message reports returned state. |
| VISIBILITY-01 P1 | Posts1921–1923 now present; revision190 durably completed. Future unattended publication remains held until the inbound trust boundary is safely resolved. Schedule/hashtag ingestion unchanged. |
| SEARCH-01 / A11Y-01 P2 | Independently verified live in38726004896:all three character variants260 results, status/polite count, Escape closes, no unnamed sampled controls. |
| PERSIST-01 P1 | Shared Git UTF-8 decoding repair, real Persian-path/red-green regression and exact retirement readback completed. |
| BUILD-PERF-01 P2 | Repeated verified-media hashing eliminated; identical fixture outputs and measured component improvement; final seal/gates retained. |
| DOC-01 P2 | Actual architecture/source authority and safe deployment documentation corrected; exact33-file review recorded below. |

### Independent post-promotion observations

Run38726004896 on the unpinned serving version:PASS; result SHA25633e9675a3252a4c58d351ac9f79561f003efeedf6d76f7f10c2b6948046a3f94. Three cold-context samples per viewport, fonts loaded, no overflow/JS errors/forbidden content dependencies. Latest API IDs1921–1923 all present in static index; protected webhook-info401, public reads200. Telegram empty-update200 remains the explicitly held SEC-01 issue, not a repaired security claim.

| Viewport | Before median TTFB/LCP ms; max CLS | After median TTFB/LCP ms; max CLS |
|---|---|---|
| Desktop1440 |105.3 /324;0.00256|92.2 /276;0.00108|
| Tablet768 |88.5 /308;0.00209|80.8 /244;0.00209|
| Mobile390 |89.8 /272;0.05316|66.2 /216;0.00216|

These laboratory samples use different runner/cache/network circumstances; they do not establish a causal frontend speed improvement or field INP. The controlled media-hashing fixture below is the measured optimization claim. Opened the exact preproof new audio1923 and mobile homepage screenshots; established logo/font/RTL/native-player layout retained.

Run38725998368 independently passed archive/load-more, numeric-ID/home/category search/navigation, old OGG and MP4 playback, admin401/mobile navigation and new photo1921/1922 decoding. New audio1923 failed at image_decode:the diagnostic attempted scrollIntoViewIfNeeded on hidden modal/sticky player covers before playback. Its actual MP3 returned206, finite228.858776s/readyState4/no media error. A local real-Chromium fixture reproduced that exact hidden-image timeout; the diagnostic now scrolls only visible images while still decoding/checking dimensions of **every** image. Deliberately broken hidden image still rejects. This is a diagnostic correction, not a site/player change; corrected hosted new-audio playback subsequently passed in38727489912. No full publication retry is required for this test correction.

### Durable revision190 completion — 11:25 UTC / 14:55 Tehran

Run38717369912 concluded SUCCESS. Production proof completed11:24:21UTC with all11 authoritative gates PASS, matching deployment449be33f-3cc1-4312-890f-f3df67718c1f/version5413751a-cf7e-4f90-aa55-562c520f0054100%/baseline1c92b5b0-0426-4f8f-8328-ee741569149b0%. Proof artifact d58ad376c576469dd4aa08f496837a4375d1c363e69c38bc8cd254ed6a57bdab; raw proof file SHA256757973067f21c0b8af9c6f504931d375f64249f21c7c56f613644c495aab06ea. Zero-origin counts all0 across7 public pages; visual/font/version checks pass.

Final persistence reports COMPLETED, artifactda54593107f0ca4f9cb83b16d0a17694c63fa8e5f761a14c8665ef76ddd45551. Six state files committed ate3abee4dab87410eecd064e48ae0965e8f295141; canonical completion88a9cd68795c357c2cc29d8cd88a916e2c6dfd09, journal generation151, active=null/pending=null, revision190 completed/recoveryNONE. Post-run reconciler38727286924 was correctly skipped by its successful-run condition; no orphan mutation exists. Corrected independent browser38727489912 and sanitized GET-only reconciliation38727878134 subsequently passed.

Expected snapshot1852 posts,943 deduplicated search records,4245 routes,606 unique immutable media objects. Required media identities632:609 previously published,4 new identities,19 historical fallbacks,0 unresolved/hash mismatches/invalid payloads. Latest public revision was independently re-read190 after persistence; no fabricated revision or new publication is needed. Small metadata, proof/screenshots and persistence artifacts retained privately; the651MB build artifact was not downloaded locally.

## Dependency reachability conclusion

The16 npm audit entries remain affected dependencies, not16 established public exploits or a clean dependency bill. Actual public dispatcher imports only asset/media-proof/version handling. Build-time source review found no untrusted HTML attribute-name spreads, custom transition animation input or request-derived persist directive; the existing audio persist name is constant. ClientRouter alone does not meet those injection preconditions. Astro root base lacks the non-root-base authorization prerequisite. The Cloudflare adapter is explicitly excluded from the cited prerendered-error Host SSRF advisory. Passthrough media plus verified JPEG/PNG/GIF/WebP/OGG/MP3/MP4 signatures provides no untrusted AVIF/Sharp or SVG-sanitizer route.

Wrangler/Miniflare/vite-plugin/undici/ws/http-cache-semantics are local build/deployment tooling, with no exposed Node development/WebSocket/proxy service. YAML/TOML/CSS/source-map inputs are checked-in configuration; no public parser/negative-size input path was identified for js-yaml/smol-toml/postcss/source-map-js/nanoid. Devalue is not invoked by the static public request dispatcher. This is reachability triage, not exhaustive third-party fuzzing. Keep dependency maintenance P2; no blind update or major adapter migration during the active transaction.

Primary sources: [spread props](https://github.com/withastro/astro/security/advisories/GHSA-jrpj-wcv7-9fh9), [Host SSRF](https://github.com/withastro/astro/security/advisories/GHSA-2pvr-wf23-7pc7), [transition animation](https://github.com/withastro/astro/security/advisories/GHSA-4g3v-8h47-v7g6), [island transition directives](https://github.com/withastro/astro/security/advisories/GHSA-7pw4-f3q4-r2p2), [base-path authorization](https://github.com/withastro/astro/security/advisories/GHSA-376h-93r7-7g6f).

## Mission and safety

Preserve existing Telegram hashtag ingestion, official logo/font, static rendering, stable database IDs, admin boundaries and the accepted publication journal. No test channel messages, Telegram edits/deletes, destructive admin tests, secret rotation, manual journal edits or mutation replays. Do not change scheduling solely because the static publisher uses CHECK_ONLY.

## Initial readbacks (historical checkpoints)

- origin/main and source at start: e02f70c0cfed72892f25b1e90066395c4cbb440b.
- Website deployment cf817382-242d-4d2e-9b40-969c7a9c1332; version1c92b5b0-0426-4f8f-8328-ee741569149b100%, baselinebc11bf72-e914-498d-8665-b7d98c57ff900%.
- Canonical journal generation139; active/pending null; revision185 completed.
- Fresh CHECK_ONLY38705363433:SUCCESS;2026-10-15T08:24:12.657010Z /11:54:12 Tehran; latest185=published185,UNCHANGED. Receipt9ad175e2dff285f812b6babd5aae76c0d2dbde132c4883d73258baadae7d0e49.
- Fresh unpinned browser38705359244:SUCCESS,16/16; seven actual article IDs1914-1920; native audio/video progress, search/pagination, mobile menu/about, loaded fonts, admin401; JS errors0, forbidden dependencies0. Result rawSHA0bb58ec5ec268fb048f8619c26f808cd4333ed158f3a41368542fe5d5b5918e6.
- Current API Worker tg-cms-api deployment375258db-cb64-4154-a685-ee380f1e87a3, versionea717386-6580-4d39-93a0-6c224deae34e100%, deployed2026-09-12. Live module index.js161176bytes, rawSHAa0d53ba90599742076845aa156e40969590b4ef3180152fc4420e66b1764cbd1, read directly via Cloudflare GET content/v2. Repository source151900bytes is not byte-identical; source authority must be checked before backend changes.

## Existing architecture inventory

| Area | Existing implementation / authority | Verification so far |
|---|---|---|
| Telegram ingestion | API extractTelegramPost; channel/message and edited update variants; media association; D1 posts | Live source/read-only D1/actual new posts verified; local workerd regression passes; SEC-01 activation held |
| Hashtags/categories | Shared taxonomy:book,dialogue,audio,poetry/text,painting; audiobook overlaps book/audio | Source inspected; no mapping change proposed |
| Automatic display | Existing ingestion and public category APIs; nonlocked Astro runtime fetches current API | Ingestion verified by real posts1921–1923; static gap repaired by completed190; future unattended freshness held with SEC-01; no test channel message |
| Database | Cloudflare D1 DB binding, posts, site_settings/revision and tag projections | Source inspected; no data mutation |
| Public API | public/home-v1,posts-v1,tag-posts-v1,stats-v1 and safe SEO slug lookup | Fresh hosted public200/admin401/private-field exclusion; actual local SEO read-only regression |
| Homepage | Astro server template, featured/latest/category/search/cards; locked-snapshot branch exists | Fresh mobile screenshot and16-check suite |
| Archives | SSR source and static archive client; stable-ID search/load-more | Fresh20->40 pagination PASS |
| Categories | Shared taxonomy and per-category pages | Fresh search/navigation PASS |
| Articles | DB-ID/slug routes, RTL text/media/meta/related articles | Fresh seven article/image checks PASS |
| Search | Static index contract V2 and public API search in dynamic mode | Live numeric-ID/Persian variants/empty state/pagination PASS after repair |
| Audio/video | Native audio layout plus global audio system, video controls, immutable media | Fresh finite duration and playback progress PASS |
| Images | Original media fields, bootstrap immutable records, historical fallback handling | Fresh seven posts decoded images;19 historical fallback records from previous baseline |
| Admin | Existing admin shell, token client, protected API routes and dedicated restore | Fresh visible login/unauthenticated401 PASS; no destructive tests |
| SEO/indexing | SITE.url, read-only /seo/post/:slug, canonical/JSON-LD, sitemap/RSS/robots | Fresh190 all11 gates,4245 routes; canonical/JSON-LD/sitemap failures0 |
| Website runtime | Current static_version_main serves ASSETS and adds version identity; Astro dynamic worker is separate source path | Actual serving version verified; no assumption that CHECK_ONLY means ingestion absent |
| Cache | Immutable static assets; current API/dynamic fetch policies differ | Fresh version attribution and9-sample lab observations; immutable media verified |
| Static publication | Revision resolution/admission, sealed build,0% candidate, preproof,promote,production proof,six-file persistence | 190 completed at journal151; state/proof/live identity match |
| Recovery | Journal-derived reconciliation/readback/rollback; no APPLIED replay | Source inspected; previous completed recovery preserved |
| Monitoring/errors | Existing safe diagnostics, retained proof observations, analytics v4/v5 paths, scheduler heartbeat | Duplicate supported versions require caller checks before removal |
| Responsive/a11y | Existing header/footer/menu/RTL/font and player system | Fresh1440/768/390 screenshots; names/status/Escape verified live |

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

## Initial execution plan (completed or superseded by final checkpoints)

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

Fresh npm audit reports16 affected dependency entries (1critical/14high/1low, including transitive effects); this is not16 confirmed production exploits. Primary Astro advisory GHSA-26w7-cxv4-gfx2 requires processing untrusted AVIF through Sharp. This project uses imageService:passthrough; current static_version_main serves ASSETS rather than an Astro request renderer. Dev server/Miniflare are not public production servers. The request-time Astro attack path is therefore absent in the accepted static Worker. Do not blindly apply npm audit fix or claim the dependency findings resolved. Scope-specific runtime/build-input reachability triage is completed above; the affected dependency versions remain maintenance work.

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
- Owner subsequently declined providing a local credential; API activation is held under that explicit instruction. No token was requested in chat, extracted from a Worker, exposed through a migration endpoint, rotated or committed. Independent website work continues while API activation waits on secure Bot API access.

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

Historical checkpoint only: the revision188 build later stopped at the revision fence, before any Cloudflare operation. The current checkpoint below supersedes its running status.


## Owner safety decision and reviewed deployment checkpoint — 2026-10-15, 09:52 UTC / 13:22 Tehran

The owner declined supplying BOT_TOKEN and explicitly requires uninterrupted Telegram ingestion. Authoritative binding names, settings, current live module and public request boundaries have been inspected without exposing secret values. BOT_TOKEN/ADMIN_TOKEN are present as Worker secrets, but neither is locally available; there is no webhook-secret binding. No supported authenticated getWebhookInfo/getChat/setWebhook call can be made from this environment with those opaque bindings. The prepared API auth/source/replay/restore changes remain **NOT DEPLOYED**. Do not rotate a token, alter the active webhook, export a secret, add an authentication bypass or request the same credential again. These are the precise remaining activation/access limits; independent website work continues.

### Exact 33-file review

The owner's 33 files are the complete diff from b29f04b4f2db29ae8ca8ced16696fc3a3e989cf8 to e02f70c0cfed72892f25b1e90066395c4cbb440b. They are reviewed separately from the current audit's additions. Workflow/source/test diffs, caller contracts and generated-state structure/digests were inspected. Review does not certify every historical content record by eye.

| File | Reviewed contract / result |
|---|---|
| `.github/workflows/mahoon-finalization-preflight.yml` | Triggers, executable SHA, read/write credential separation, artifact lineage, fail-closed job conditions and retained diagnostics checked. |
| `.github/workflows/mahoon-live-functionality.yml` | Triggers, executable SHA, read/write credential separation, artifact lineage, fail-closed job conditions and retained diagnostics checked. |
| `.github/workflows/mahoon-post-run-reconciler.yml` | Triggers, executable SHA, read/write credential separation, artifact lineage, fail-closed job conditions and retained diagnostics checked. |
| `.github/workflows/mahoon-static-publisher.yml` | Triggers, executable SHA, read/write credential separation, artifact lineage, fail-closed job conditions and retained diagnostics checked. |
| `MAHOON-CODEX-HANDOFF.md` | Historical claims checked against accepted revision185 evidence; not substituted for fresh production checks. |
| `MAHOON-FINAL-REPORT.txt` | Historical claims checked against accepted revision185 evidence; not substituted for fresh production checks. |
| `publisher-state/current-accepted-route-manifest.json` | Generated evidence: parsed structure, lineage/counts and accepted-state digest; current journal separately revalidated. |
| `publisher-state/immutable-media-index.json` | Generated evidence: parsed structure, lineage/counts and accepted-state digest; current journal separately revalidated. |
| `publisher-state/production-content-fingerprint.json` | Generated evidence: parsed structure, lineage/counts and accepted-state digest; current journal separately revalidated. |
| `publisher-state/production-media-manifest.json` | Generated evidence: parsed structure, lineage/counts and accepted-state digest; current journal separately revalidated. |
| `publisher-state/production-transaction-journal.json` | Generated evidence: parsed structure, lineage/counts and accepted-state digest; current journal separately revalidated. |
| `publisher-state/published-route-manifest.json` | Generated evidence: parsed structure, lineage/counts and accepted-state digest; current journal separately revalidated. |
| `publisher-state/published-static-state.json` | Generated evidence: parsed structure, lineage/counts and accepted-state digest; current journal separately revalidated. |
| `tools/publisher/astro_static_materializer.py` | Static scripts/config preserve search/pagination/category semantics and remove public content-origin dependencies; admin path retained. |
| `tools/publisher/audio_runtime_diagnostic.mjs` | Read-only browser selectors, playback/transport, request version attribution and saved observations; no production content writes. |
| `tools/publisher/final_state_materializer.py` | Deterministic relative-path inventory; photo aliases require sealed bytes, unique peer and matching rendered article. Negative tests retain rejection. |
| `tools/publisher/live_functionality_smoke.mjs` | Read-only browser selectors, playback/transport, request version attribution and saved observations; no production content writes. |
| `tools/publisher/prepromotion_browser_gate.mjs` | Chromium runtime/self-test, launch versus page/visual failure attribution, fonts/screenshots/version and zero-origin checks retained. |
| `tools/publisher/production_proof_runner.py` | Sealed build/lineage preflight, backend collection, per-page failure evidence and unchanged acceptance gates checked. |
| `tools/publisher/proof_observation_runner.py` | Sealed build/lineage preflight, backend collection, per-page failure evidence and unchanged acceptance gates checked. |
| `tools/publisher/test_a53_executors.py` | Regression/negative cases checked against corresponding runtime contract; full-suite results below. |
| `tools/publisher/test_a6_workflow_contract.py` | Regression/negative cases checked against corresponding runtime contract; full-suite results below. |
| `tools/publisher/test_a7_synthetic_acceptance.py` | Regression/negative cases checked against corresponding runtime contract; full-suite results below. |
| `tools/publisher/test_astro_static_materializer.py` | Regression/negative cases checked against corresponding runtime contract; full-suite results below. |
| `tools/publisher/test_downstream_dag_hardening.py` | Regression/negative cases checked against corresponding runtime contract; full-suite results below. |
| `tools/publisher/test_final_state_materializer.py` | Regression/negative cases checked against corresponding runtime contract; full-suite results below. |
| `tools/publisher/test_proof_observation_runner.py` | Regression/negative cases checked against corresponding runtime contract; full-suite results below. |
| `tools/publisher/test_static_archive.mjs` | Regression/negative cases checked against corresponding runtime contract; full-suite results below. |
| `tools/publisher/test_static_version_control.py` | Regression/negative cases checked against corresponding runtime contract; full-suite results below. |
| `tools/publisher/test_workflow_stage_cli.py` | Regression/negative cases checked against corresponding runtime contract; full-suite results below. |
| `tools/publisher/workflow_stage_cli.py` | Existing guarded journal transitions, exact artifact references and diagnostic failure handling; no mutation replay path added. |
| `website/dreary-disk/public/mahoon-static-archive.js` | Immutable same-origin index, database IDs, category/pagination/media/search and failure recovery; real Chromium fixture passed. |
| `website/dreary-disk/src/pages/post/[slug].astro` | SSR meta uses read-only slug SEO endpoint; locked numeric ID routes preserved. Dynamic numeric-only fallback is outside current static-serving acceptance. |


Findings from the review/current execution: (1) two stale test contracts were repaired without removing DAG success/identity/ADMITTED guards; workflow hashing normalizes Git LF/Windows CRLF. (2) nine hardcoded account assignments now use the **existing** repository variable; its exact equality was checked privately before replacement. Frozen reviewed workflow SHA256 is f673623186de878fc92f2f937976c30c99a4f25a5438abba8548ba6d5f3b073d. (3) admin restore success now reports the actual returned publication state, compatible with the held backend rollout. No change to ID/delete/restore endpoints, journal safety or traffic acceptance requirements.

### Failed publication and canonical retirement, without replay

Run38710568217 admitted real revision188 and built until09:25:23UTC. The post-build fence rejected PUBLIC_REVISION_CHANGED_DURING_BUILD:190 (revision changed09:24:47UTC). No build handoff, upload, zero-percent or promotion occurred. The existing generic retire-stale-admitted protocol was used with exact transaction, revision, generation140 and journal digest; it pushed canonical commit9ebbb339c59f793306635bbd2cec1931c576d3b0. Its Windows post-push readback raised UnicodeDecodeError on an unquoted Persian filename. The transition was **not repeated**. Independent raw-byte and corrected-client reads confirm generation141, active=null, pending=null, the188 history entry blocked, and every mutation NOT_STARTED with no attempts. Journal digest f91a4c6b1dd63772986ba8908e2e92db5432fdd4c2c5e70824ffee70eafdccca. Production remains accepted revision185/version1c92b5b0-0426-4f8f-8328-ee741569149b100%, deploymentcf817382-242d-4d2e-9b40-969c7a9c1332.

The root Windows persistence defect is corrected once in the shared Git subprocess with explicit UTF-8. A real local Git bare-remote/Persian-path regression reproduced the failure before correction and verifies successful retirement post-push readback afterward. This changes decoding, not journal transitions or retry policy.

### Measured materializer repair

Repeated references unnecessarily re-read/re-hashed a blob already SHA-verified by the existing immutable resolver. Reuse the verified SHA and file size; initial resolver verification and final sealed inventory remain. A regression failed at11 reads versus1 before correction and passes with1. A separate100-reference/2,097,144-byte fixture, three samples, reduced101 reads to1 and median component time0.1915624s to0.0381758s. HTML SHA7f1130ed77cdff175ca413d9b7e51b71ef116ac0c057c8b0140140a7ebfc14b6 and manifest SHAfbae04b7d271af71c4200bf6fe4f7752f9d24955d9e04972414cbac5b43f05db are identical. This is a local component benchmark, not a claim to have eliminated the17-minute hosted build.

### Regression receipts at this checkpoint

- Full local publisher discovery:904 tests in493.038s; two failures (stale frozen workflow hash/CRLF and old RESUME-only expectation), three skips. Both failing contracts were corrected and rerun in a79-test batch:78PASS/1skip. Further workflow-variable regression and hosted full-suite result pending below; do not call the earlier full run green.
- Website build after compatible admin copy:PASS4.41s. Static archive real Chromium fixture, platform probe safety self-check and actual local workerd/D1 auth/source/replay/edit/restore/SEO regression:PASS. No real channel post or production admin mutation.
- Failed publication artifacts and exact retirement readback retained privately under publication-38710568217. No645MB build download or expensive remote crawl was used to investigate the fence/encoding errors.

Current status: **IN PROGRESS; final PASS withheld**. API security activation remains held by the owner's explicit access/safety decision. Next independent step: isolated Ubuntu/Node22 pinned-Chromium safety suite, then a fresh normal transaction only after current journal/live/revision/concurrency checks. Never weaken the moving-revision fence or repeat APPLIED operations.


## Hosted safety-suite correction — run38716243022

Source30400efba14fd07dd3206d47ddc0ca1035226ac2; Ubuntu/Node22, pinned Chromium installation successful. Full discovery905 tests in60.297s, failures2/errors9/skips1. Exact causes: WorkflowStageCliTests created intents under the real inherited GITHUB_RUN_ID/ATTEMPT, then executed them under its fixed synthetic identity; the existing production identity guard correctly rejected them (nine errors plus one composed acceptance failure). The test setUp now consistently pins only the fixture's local-synthetic/1 identity and restores the caller environment afterward. Cross-run rejection tests remain. The concurrent-bootstrap fixture could create byte-identical commits in the same second on Linux; the competing fixture now has deterministic distinct Git author/committer dates, exercising an actual non-fast-forward race. No runtime validation, journal transition or production guard was relaxed. Reproduction with inherited run38716243022/attempt7 and the affected modules is recorded separately after execution.

This workflow also executes the existing no-op journal bootstrap and read-only public revision resolution; its safety-tests-only job has no Cloudflare credentials or mutation path. The job's printed LIVE_REVISION_LOOKUPS=0 describes its own local tests, not the whole workflow. Canonical generation141 remains unchanged. No new production publication was dispatched from this failed safety run.

Affected hosted-identity/bootstrap/acceptance modules rerun locally with inherited run38716243022/attempt7:119/119PASS in142.786s. The synthetic fixture still rejects an intentionally different executing run. Prepared exact-live-module workerd/D1 regression also rerun PASS; production API remains unchanged.


## Final independent browser acceptance and diagnostic privacy

Corrected read-only run38727489912:12/12PASS on unpinned serving5413751a-cf7e-4f90-aa55-562c520f0054; result rawSHA2562e3e45339ee70d9ebe27409487dadaeca340d2f23ab39a2727fee20c972302cd. Actual new audio1923 decoded8 images (including hidden covers), duration228.858776s and playback advanced0.111942s through its visible native control. New photo1921/1922 decoded6 images each. Archive20→40, stable-ID search/home/category navigation, old OGG/video playback, admin401 and mobile/about navigation pass; JS errors0/forbidden dependencies0. No site/player change or full release rerun was used for the diagnostic repair.

GET-only reconciliation38727494130 independently reports baseline/Worker/domain/deployment/allocation PASS against the completed state. Its legacy helper unnecessarily included the account identifier in the output artifact, contrary to repository metadata rules. P2 DIAG-PRIVACY:removed the output field, kept account validation and internal GET paths intact, and replaced a real identifier in its test fixture with a synthetic value. A new assertion reproduced the exposure before correction; all19 baseline/negative/workflow tests pass after correction. A clean hosted reconciliation receipt will replace this optional raw receipt; required publication/journal/proof artifacts are preserved.

Independent canonical verification:all six Git state blobs exactly match final-persistence SHA256 and byte lengths;613 indexed media identities; journal151 digestad1eb9bb352718ca644a8dcc9edaf0e4330892ded422e6e7781102a74c2d0e3e, revision190completed, active/pendingnull, upload/zero/promotion each one APPLIED attempt, rollback0. At that readback latest content was190; it later advanced to192 as recorded below. This completes the190 website transaction; the overall platform phase remains blocked on the explicitly held API trust-boundary activation.


## Final checkpoint — 2026-10-15, 15:04 Tehran / 11:34 UTC

**Website publication190: completed. Platform audit: BLOCKED on safe API activation and recurring freshness; newest192 has not been published.**

- Sanitized authoritative GET-only reconciliation38727878134:PASS (Worker, official domain mapping, deployment,100/0allocation and persisted state); rawSHA25640b240807519704a23919a83c7dcc170586479b12c06d9707cab3ba7a66cc3c6. Verified it contains neither an account_id field nor the configured account value. Superseded optional raw receipt from38727494130 was removed after private retention and clean replacement. Required publication/journal/proof artifacts were not removed or modified. No history rewrite.
- Production190 has4245/4245 final200 routes,4242 HTML,3704 ID/slug article routes,943 unique search IDs,606 verified immutable media objects,613 index identities. Canonical/SEO/JSON-LD/sitemap omissions, orphan posts, pagination overlap, media HTTP/MIME/version failures and version-attribution failures all0. Sitemap/RSS/robots and admin shell are included in the current crawler/11-gate proof.19 historical unavailable-source fallbacks remain explicit accepted maintenance,0 unresolved media; no such fallback for the three new posts.
- Fresh independent browser38727489912:12/12PASS, including actual new posts1921–1923 and native MP3/OGG/MP4 playback progress. Fresh platform38726004896:all search/keyboard/status/responsive checks PASS,0 JS/forbidden dependencies. Exact final tablet homepage and new audio1923 screenshots were opened after download. Full905-test safety run38717022249 has0failures/errors,1 optional historical-artifact skip; later diagnostic changes have focused real-Chromium regressions, actual hosted acceptance and19/19 baseline tests. Overlapping suites are not summed.
- Final API deployment independently remains375258db-cb64-4154-a685-ee380f1e87a3/versionea717386-6580-4d39-93a0-6c224deae34e100%. No API code/binding/secret/webhook/token/channel content was changed. The connection was preserved by withholding the coordinated backend correction; no uninterrupted-service uptime claim beyond observed evidence is made.
- Source/mutation journal safety remains intact:one APPLIED attempt each for upload/zero/promotion,rollback0; journal151 completed190,active/pendingnull,proof and six persisted Git blobs match exactly. Revision190 equaled persisted190 immediately after completion; the final readback below subsequently detected192. Normal publication38717369912 SUCCESS; post-run reconciler38727286924 correctly skipped a closed successful run. No resume/replay or journal repair is pending for190. Newer192 is separate outstanding content; no192 transaction has been admitted.

### Exact remaining blocker and safe continuation

SEC-01 remains a confirmed P0:the active generic POST handler lacks authenticated Telegram delivery and verified source authorization. Header/source/replay/restore repairs are prepared against both repository and exact live module and pass real local workerd/D1 tests; they are not production fixes yet. Existing BOT_TOKEN/ADMIN_TOKEN bindings are opaque to this environment. No supported authenticated getWebhookInfo/getChat/setWebhook operation can register/verify the matching secret and official channel with the current access. The owner explicitly declined supplying the credential and requires this particular change held if extra access is necessary.

Minimum future owner-enabled step is supported authenticated Bot API registration/verification, either performed by the owner or through an authorized secure credential path; it does **not** require token rotation. Use the documented existing URL, matching secret, actual channel verification and drop_pending_updates=false. Before the coordinated live-module rollout, refresh source/settings/deployment and take the required private D1 backup. Preserve all current bindings/live-only logic, stage/test and verify before activation. Do not deploy the fail-closed guard now, expose Worker secrets, create a public migration endpoint, send a real test post or repeat the declined credential request. See workers/api/WEBHOOK-SECURITY-ROLLOUT.md.

INGEST-01 replay and RESTORE-01 backend semantics remain prepared within that held live-module rollout. Current UI accurately describes the returned restore state. Historical duplicate rows remain untouched. Unattended static publication remains at the existing CHECK_ONLY/open-breaker policy:it was not disabled by this audit and is not reopened while the inbound trust boundary remains unresolved. Genuine current posts are published through190; automatic freshness of future posts is not claimed. This is the remaining production-safety limit, not a request for routine approval.

### Commit and evidence index

| Purpose | Commit |
|---|---|
| Responsive/public-boundary diagnostic |fa4c3995fe146dfa2ab1898a1ae896422dd23db6|
| Deployed Persian search/a11y repair |a9fce831dfcfa6707fc2a8a5aca11d411cf96d31|
| Prepared inbound guard (held) |83905b98a663708e237deb5189b9541b8dcfbade|
| Prepared replay/source authorization (held) |415e99a78d06c5112afd0d42352a2314a9afedd0|
| Prepared backend restore; compatible UI |38acff3267ae21617b633d6e624da7e776250db4|
| Windows readback/media-hash reuse/33-file review |30400efba14fd07dd3206d47ddc0ca1035226ac2|
| Hosted fixture identity/race; deployed executable source |45c4d3f39cbcbf7ad7198602fde359e12edcc2d1|
| Final six-file production state |e3abee4dab87410eecd064e48ae0965e8f295141|
| Canonical190 completion |88a9cd68795c357c2cc29d8cd88a916e2c6dfd09|
| Hidden-cover diagnostic regression |92fe37405297a8c5b4ec0ca5bd80951e61ed1093|
| Final diagnostic code / sanitized receipt repair |61a33bef65183f2eabe696a9ef9fa8b768a07a62|

Final report/handoff-only commit is supplied with the delivery; it changes no runtime or journal state. Durable evidence is in the named GitHub runs and canonical state. Private small artifacts/checkpoints are under C:/Users/mehdi karani/AppData/Local/Temp/mahoon-platform-audit-20261015. No large build download, fake proof, manual journal edit, forced push or improvised rollback.

Remaining optional work:P2 planned dependency maintenance with adapter compatibility;P3 physical iOS/Android codecs, screen-reader/contrast sampling, field INP and DevTools traces. These were not certified. No speculative redesign, brand/font replacement, new ingestion pipeline or destructive production test was introduced.


## Final freshness correction — newer content after completed190

At the last readback, latest public revision is **192**, changed2026-10-15T11:30:18+00:00 /15:00:18 Tehran, after the190 production proof/persistence completed. Scheduled detection38727921763 started11:31:17UTC and emitted sealed revision-resolution artifacteaf4a38b60fe4412b954407ee92da24c8b65fec90cd8c9c58948a6d42115d60c:CHANGED,latest192,published190. Its nonzero CHECK_ONLY result records the difference; it did not admit/upload/promote anything. Fresh final read confirms journal151,active/pendingnull and the same healthy190 deployment100%. This supersedes earlier point-in-time statements that190 was latest.

The independent190 acceptance covers snapshot1852posts and actual new IDs1921–1923, not changes introduced by192. Do not infer192's exact post/edited-record identities from the revision number alone. Current platform freshness is therefore **not PASS**. The finite code-repair publication190 completed; the continuing feed exposes the existing CHECK_ONLY/open-breaker delivery limitation again. No additional full release was dispatched just to chase a moving cutoff during report writing. API trust-boundary activation remains held under the owner instruction; unattended publishing is not reopened on unverified incoming updates. This outstanding192 content and the prepared backend rollout are explicitly retained as unresolved work, not silently marked complete.

Next continuation must start from current canonical/live/revision readbacks. Never resume or replay190. Any future publication uses a genuinely fresh normal transaction with all unchanged acceptance gates, and any schedule/API security change follows the documented production-safety rules. No background continuation is scheduled or claimed.
