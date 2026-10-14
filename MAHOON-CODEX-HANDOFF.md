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

The explicit one-continuation allowance has been used. No additional dispatch was made.

## Next step only if the owner authorizes another continuation

Use the existing transaction and all original source IDs; include the existing passing pre-promotion proof source so no zero-percent observer is rerun:

- `mode=POST_PROMOTION_FINALIZE`
- `ready=YES`
- `transaction_id=a180efc687b8bac3039d9ee055735c72ad77163192bf93a2680d5f188344dfac`
- `source_run_id=38569347431`
- `resume_source_run_id=38569347431`
- `resume_source_sha=6a1e76a0ec3a710d77e8e9a26e8b60a9501e5585`
- `preproof_source_run_id=38569347431`

Verify live deployment and journal again first. Do not replay upload, zero-percent or promotion. Continue only through real production proof, retained sanitized evidence, final persistence and reconciliation. Once revision 163 is durable, re-read the latest content revision and use the normal publisher transaction for the latest authorized snapshot. Do not manually edit the journal.

## Remaining acceptance

Final proof/persistence/reconciliation, publication of the latest posts, and complete route/media/navigation/SEO/sitemap/RSS/admin acceptance have not passed. Keep the release blocked.
