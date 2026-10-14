# MAHOON finalization handoff

## Current checkpoint: sealed media lineage repair

Run38632770381 physically validated the sealed artifact, retained proof5eabba and materialized all six files successfully. Final persistence rejected before journal writes with JournalUnavailable caused by FileNotFoundError: its CLI resolves a relative journal path against --repository state, but the workflow supplied state/publisher-state/... (thus state/state/...). The workflow now passes the accepted repository-relative publisher-state path. The workflow regression failed before this one-line correction;112 focused workflow/executor tests pass afterward. An isolated end-to-end replay using the real proof, references, six staged files and an unmodified copy of canonical generation117 in a temporary local bare Git repository reached COMPLETED/generation119/revision163 with exact remote readback. No production completion is inferred from this fixture. Next continuation still uses the original eight verified inputs; actual production/journal must be read again first.

Continuation 38614748331 retained the real PASS proof 5eabba732b07a9a1594f72127c3855cd13a432b507ccee7bccc7ab7c2aa39194 and passed physical seal/inventory validation, then rejected the stale media record list. No final persistence or repeated mutation occurred. Read-only metadata diagnostics 38617333828 and 38620206582 prove the original manifest mixed 580 prior records with 596 current rendered-path entries; the snapshot requires 621 identities. Forty missing identities have exact bound rendered-path/hash/size evidence. The remaining photo alias (DB ID1874) shares the unique media identity with1873, and its hash-verified sealed article renders the identical immutable image.

The producer now refreshes current bootstrap records before writing the media manifest. Legacy finalization reads only bound rendered metadata and hash-verified alias HTML; incomplete, conflicting, changed or ambiguous evidence remains rejected. Original sealed manifest/proof bytes remain unchanged. Real remaining-data-contract preflight produced the exact six files and602 immutable index entries, preserving historical entries and adding41 successes. This local preflight does not claim physical seal validation; the hosted continuation must repeat it. Focused168 tests passed (one existing Linux-only skip), including negative lineage/hash/page tests. Current authoritative readback remains generation117, active163, candidate100% on deployment54325ccc, with no proof/state commit yet.

Next: push this evidence-backed repair; run the same eight-input POST_PROMOTION_FINALIZE continuation including source_proof_run_id38599823193. It must finish persistence/reconciliation before any new content transaction. Then re-read and normally publish the latest authorized snapshot, including the static archive repair, and execute final functionality acceptance using baseline_run_id38605324686.

**Status: `MAHOON_PROJECT_FINALIZED_AND_LIVE: BLOCKED`**

## Current production state

- Cloudflare read-only readback: deployment `54325ccc-494e-448f-bfcd-c07e74564928`, candidate `b3aa78ef-7b15-4d36-a87e-90dec308eb00` at 100%, baseline `cefbdeec-a3a7-4963-a4e9-19937f7829f9` at 0%.
- Canonical journal: generation 117, active revision 163, transaction `a180efc687b8bac3039d9ee055735c72ad77163192bf93a2680d5f188344dfac`, state `operation_reported`, pending null.
- Upload / zero-percent / promotion remain APPLIED. Proof SHA and final state commit SHA are null.
- Last successful check-only reading: run 38590971385 found revision 177 and published revision 81. Recheck after revision 163 is finalized.

## Root cause and code fix

Run 38582922041 logged only `ProductionProofRejected`, without a traceback. The code-level cause is the missing backend context value: `create_production_proof()` validated the build bundle but omitted it from the context, while `RuntimeObservationBackend.collect()` immediately reads `context["build_bundle"]`. If lineage validation reaches the backend, this deterministically raises `KeyError` before sealed-file verification, Cloudflare readback, crawler or browser work; the then-current wrapper reduced it to the exception name. The small sealed artifacts agree on the revision, bundle digest and promotion lineage.

Commit `9ff3b9e7ab28a7b3271b545ddb81e3afb2b0a98c` passes the validated bundle. Regression tests require the backend to receive it. Verification: 54 `test_a53_executors` tests and 62 `test_proof_observation_runner` tests passed.

## Continuation status

The one `POST_PROMOTION_FINALIZE` run dispatched was `38594845230`. It passed resume/journal verification, revision resolution, admission reuse and build lineage validation. Upload, zero-percent and promotion jobs were skipped.

The dispatch omitted `preproof_source_run_id`. As a result, `resume-preproof-carryforward` was skipped and the workflow reran pre-promotion proof against the live promoted state. The browser self-test passed; the observer correctly rejected the zero-percent expectation (`ObservationRejected — zero-percent deployment readback does not match sealed result`) before crawling. Production proof and final persistence were skipped. Canonical journal remains unchanged at generation 117/revision 163/operation_reported.

The owner's 2026-10-14 finalization mission supersedes the prior single-run cap and authorizes evidence-based controlled continuations. Controlled continuation run `38599823193` was dispatched at 2026-10-14T16:38:40Z from `1ccca7e39c66e1f9883e1197361e3dc3df955221`, with all seven verified inputs below. It is active; do not dispatch a duplicate. Journal/revision/admission/build-lineage/build-ready/upload/zero/preproof carryforward stages passed. The passing preproof was revalidated without running the zero-percent observer; promotion carryforward passed; production proof is active since 2026-10-14T16:48:50Z; pinned Chromium installation and the hosted self-test passed. All three Cloudflare mutation jobs are skipped. A further 23 normal publication boundary/revision/gate tests passed (one existing skip).

## Active execution checkpoint

Integrated review completed: carry admission/build/upload/zero/preproof/promotion; skip every upload, zero-percent and promotion mutation and the pre-promotion observer. Run production proof, six-file final-state materialization, CAS persistence and exact remote readback. Persistence/contract modules match the sealed source version. New changes fail fast on a missing preproof input, emit structured BLOCKED proof status, and preserve sanitized failed crawl/browser evidence and public screenshots. Focused validation passed: 235 tests across workflow contracts, downstream DAG, CLI, observations, final-state materialization and executors (one existing skip), plus git diff --check.

Use the existing transaction and all original source IDs:

- `mode=POST_PROMOTION_FINALIZE`
- `ready=YES`
- `transaction_id=a180efc687b8bac3039d9ee055735c72ad77163192bf93a2680d5f188344dfac`
- `source_run_id=38569347431`
- `resume_source_run_id=38569347431`
- `resume_source_sha=6a1e76a0ec3a710d77e8e9a26e8b60a9501e5585`
- `preproof_source_run_id=38569347431`

Verify live deployment and journal again first. Do not replay upload, zero-percent or promotion. Continue only through real production proof, retained sanitized evidence, final persistence and reconciliation. Once revision 163 is durable, re-read the latest content revision and use the normal publisher transaction for the latest authorized snapshot. Do not manually edit the journal.

No mutation or journal edit was performed in this review. Pre-dispatch authoritative readback remains deployment `54325ccc-494e-448f-bfcd-c07e74564928`, candidate 100%, baseline 0%; journal generation 117. The source small-artifact seal digests, passing preproof bundle binding, promotion intent/result and deployment identity were independently checked. Full referenced contracts are revalidated in the hosted carryforward jobs. Local body transfers timed out (HTTP 200 partial /posts/); external public rendering returned pages. No production corruption was established; hosted proof is the authority.

## Remaining acceptance

Final proof/persistence/reconciliation, publication of the latest posts, and complete route/media/navigation/SEO/sitemap/RSS/admin acceptance have not passed. Keep the release blocked.

## Live functionality repair during the active proof

Read-only hosted diagnostic run 38602783467 from e6e512d251b432af3d7bcc0bfd770e540265d219 confirmed archive load-more and database-ID search timeouts, while latest article navigation (ID 1910) and native video playback (ID 292) passed, with zero forbidden dependencies and JS errors. Audio navigation timed out waiting for networkidle, so the diagnostic now waits for DOMContentLoaded and still requires decoded duration and advancing playback.

Proven root cause: astro_static_materializer._strip_runtime_api_scripts removed the archive config/API inline script together with its search/load-more bindings. The repair retains only public archive configuration and injects public/mahoon-static-archive.js. That client uses the existing static index and copies rendered cards from static pagination pages (preserving original media); it never calls the API. It handles database IDs, exact-tag category memberships (including audio books), query reset, pagination, errors/retry and homepage Enter-to-search navigation. Category cards come from the corresponding static category pages. Changes are intended for the later normal latest-content transaction, not the already-promoted revision 163.

Validation: Node browser fixtures passed (pagination/media cards/Persian IDs/no-match/reset/category/home navigation/invalid index and retry); 61 focused Python tests passed (two existing Windows/Linux skips); npm run build passed. The read-only diagnostic now also saves live index post identities and checks home/category search. It should be rerun against the final verified version. Current continuation 38599823193 remains active; no duplicate mutation or new content transaction was started.

Final repair validation: static browser fixtures passed again including audio-book overlap and category card presentation; 50 materializer/promotion/DAG tests passed (two existing platform skips); the final npm run build and git diff --check passed. Production proof is still active (started 16:48:50Z).

Repair is pushed as 11da38f3dee2d149daad7460f538cb6a43deca7c. Read-only follow-up 38605324686 completed: archive/home/category search still inert in the deployed old artifact; article navigation, decoded audio (ID 782, 60.584479s, playback advanced 0.77053s) and video (ID 292, 7.105215s, advanced 0.119739s) passed. Zero forbidden dependencies/JS errors. Saved live index: 933 identities, maximum DB ID 1910. Local retained baseline identities: C:/Users/mehdi karani/AppData/Local/Temp/mahoon-live-functionality-38605324686/runner-evidence/live-functionality/index-post-identities.json. Compare this with the final diagnostic index and accepted full crawl after latest publication. No need to rerun the old-version diagnostic again. Production proof 38599823193 remains active.

## Current checkpoint after production PASS (supersedes active-run notes above)

38599823193 completed with production-proof SUCCESS and final-state-materialization FAILURE; final persistence skipped. Real proof SHA: 5eabba732b07a9a1594f72127c3855cd13a432b507ccee7bccc7ab7c2aa39194. Full proof: 4,221/4,221 routes, 557 media objects, 8/8 browser pages, all production gates true, correct deployment/100% candidate, no forbidden runtime requests. Sanitized 10 MB proof/screenshots downloaded to C:/Users/mehdi karani/AppData/Local/Temp/mahoon-passing-production-38599823193. Canonical journal proof field is still null until persistence.

Exact materialization defect reproduced with the real six small mutation references: ArtifactContractError: promote authority referenced artifact is unavailable. Both finalization reference arrays omitted preproof/build authorities. Also proven staging mismatch: _stage_materialized_state returns <temp>/mahoon-final-state/<tx>, containing publisher-state/*; persistence workflow incorrectly chose handoff/<tx>/publisher-state instead of handoff/<tx>.

Uncommitted fixes add complete build/admission/preproof references/downloads to both finalization stages, correct persistence root, use current diagnostic CLI to preserve safe failure reasons/status, and add production-proof-carryforward. This explicitly reuses the real PASS proof only for POST_PROMOTION_FINALIZE with source_proof_run_id set. The CLI validates sealed proof/bundle/operation lineage, exact three persisted observation hashes, current authoritative deployment/100%-0% allocation, and fresh full public GETs with version attribution and NO override; original proof SHA remains unchanged. Source proof artifact and observations are retained, with a fresh readback artifact. Browser/crawl/install stages are skipped only in this explicit validated carry path. Carry regression tests (valid/failed proof/hash drift/live drift/public attribution failure) passed; full 240-test suite passed (one existing skip), with raw hashing delegated to contracts.sha256_bytes and non-artifact readback JSON written with json.dumps.

Next continuation inputs: original seven verified inputs plus source_proof_run_id=38599823193. Do not recrawl or repeat any APPLIED mutation. First finish tests, inspect diff, commit/fast-forward push, and reverify journal/live/concurrency/artifacts. No new continuation dispatched yet.

Additional uncommitted final diagnostic enhancement uses optional baseline_run_id=38605324686 to compare current vs final post identities and check every new article/images/native audio or video, with progress saved before/after each check. Audio now uses the visible native player button. Workflow only reads the same repository tiny diagnostic artifact with contents/actions read permissions. 29 diagnostic workflow tests and Node syntax check passed. After latest publication, run final diagnostic with expected_version=<independently verified final version> and baseline_run_id=38605324686.

Pre-dispatch validation complete: 240 focused tests passed, YAML loaded successfully (56 jobs), account variable matches the previously verified configuration, and git diff --check passed. Browser/npm/cache/observer steps are excluded only for explicit POST_PROMOTION_FINALIZE source_proof_run_id carryforward. Normal publication still performs the complete accepted proofs. Ready to commit/push the repair, then reverify live/journal before the bounded persistence continuation.

Persistence continuation dispatched from c5c449c7d965e023efe32674efa69dbe0a3b9b98 with original seven inputs PLUS source_proof_run_id=38599823193. Check current GitHub run ID before any further dispatch. Fresh preflight: canonical generation117/revision163/operation_reported/proof-null/state-commit-null, mutations unchanged, candidate100/baseline0 on deployment54325ccc, no active/queued/waiting runs, PASS source artifact unexpired. No full crawler will run in this carry path.

## Latest checkpoint: inventory ordering fix

Continuation 38612179372 from c5c449c succeeded in proof carryforward: original PASS proof5eabba retained, all observation hashes and fresh CF/public identity probes validated; no crawler/browser/install or APPLIED mutation ran. Materialization then blocked with preserved status: MaterializationRejected: sealed site inventory differs from build bundle. Canonical persistence did not run.

Exact producer/consumer discrepancy proved from retained real route-state data: 4,218 HTML artifact paths; exactly two list positions differ under relative-path lexical sorting vs Path-component sorting: post/50/index.html and post/50-روش-سالم-1783487267747/index.html. Producer _sealed_file_entries sorts relative POSIX strings, while materializer _site_inventory used Path ordering. New golden prefix-route test failed before the fix and passed afterward. One-line fix makes inventory sorting match the producer, preserving all exact size/hash checks and existing artifact seal verification. All16 final-state materializer tests passed.

Current extra read-only diagnostic38613088632 (c5c449c) checks actual visible audio play controls; it is active/awaiting result and should be inspected. Latest content transaction has NOT started. Next: commit/ff-push one-line ordering fix+regression and checkpoint; reverify live/journal; use the same eight continuation inputs including source_proof_run_id38599823193. Do not recrawl or repeat mutations.

One-line sorting repair pushed: b8551b25d64870afc209bb2069e8a35508d90470. Fresh preflight still generation117/active163/operation_reported/no pending/no proof-or-state SHA, unchanged APPLIED counts, same deployment54325ccc and candidate100/baseline0, no competing runs. A new eight-input POST_PROMOTION_FINALIZE continuation was just dispatched; obtain run ID from GitHub before dispatching anything else. 38613088632 finished: visible audio UI playback PASS, video PASS, latest article PASS, no forbidden dependencies/JS errors; all old archive/home/category controls still fail as expected before the new static client is published. Do not rerun the old-version functionality diagnostic again.
