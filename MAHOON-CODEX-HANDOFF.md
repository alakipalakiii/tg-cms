# MAHOON finalization handoff

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
