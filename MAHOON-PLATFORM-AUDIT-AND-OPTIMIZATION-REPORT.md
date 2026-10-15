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

No production code, content, publishing policy or secret has been changed in this audit checkpoint.
