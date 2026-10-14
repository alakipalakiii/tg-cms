# MAHOON Codex handoff

**Status: `MAHOON_PROJECT_FINALIZED_AND_LIVE: BLOCKED`**

## Current durable state

Read the canonical journal from `origin/main`, not a stale checkout:

- Generation 117, active revision 163, transaction `a180efc687b8bac3039d9ee055735c72ad77163192bf93a2680d5f188344dfac`.
- State `operation_reported`; upload, zero-percent deployment, and promotion are `APPLIED`; rollback is `NOT_REPORTED`.
- Proof evidence SHA and state commit SHA are null; pending is null.
- Promotion result points to deployment `54325ccc-494e-448f-bfcd-c07e74564928`. Current traffic percentages were not freshly read during the last proof attempt.
- Latest content check-only run 38585147355 reported revision 175 versus published revision 81. Finish or safely reconcile revision 163 before considering revision 175.

## Recent hosted runs

- `38485698374`: pre-promotion browser observation failed. The artifact did not retain `browser.json`.
- `38578178875`: isolated browser runtime diagnostic passed after the pinned Chromium install. The browser self-test passed; both baseline and candidate `/posts/` responses transferred completely with HTTP 200.
- `38580846067`: production proof stopped on the local-gate evidence schema mismatch, before a sealed production proof.
- `38582922041`: local-gate fix passed setup and self-test; proof stopped with `ProductionProofRejected`. No proof hash or page-level evidence artifact was retained. Upload, zero-percent, and promotion jobs were skipped.
- `38585147355`: read-only check-only reported current revision 175 and published revision 81; journal bootstrap was already initialized.

## Pushed fixes

- `5017811` normalizes the build's measured local-gate records while requiring the overall and all six individual gates to be measured and passing.
- `e1b979b` carries sanitized `ObservationRejected` reasons through the proof wrapper and surfaces safe `ProductionProofRejected` messages. This latest diagnostic change has local tests but has not been run in GitHub Actions.

## Next safe action

The exact production-proof rejection from run `38582922041` is unknown because the run used the older wrapper. If the owner continues, use the existing transaction and the already authorized source references in one bounded `POST_PROMOTION_FINALIZE` run on `main` after commit `e1b979b`. Confirm the APPLIED mutation jobs stay skipped. Inspect the newly surfaced safe reason and uploaded page evidence before deciding any further action. Do not replay upload, zero-percent, promotion, or rollback. Do not publish revision 175 until revision 163 has a durable proof and consistent journal state.

## Acceptance still needed

Require a passing production proof and retained sanitized route/browser evidence, fresh live candidate/baseline traffic readback, durable final persistence and revision reconciliation, and full website checks for routes, media/audio, navigation, SEO metadata, and canonical URLs. Until those exist, keep the project blocked.
