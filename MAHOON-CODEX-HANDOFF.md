# MAHOON Codex Handoff

**Status: BLOCKED. Do not call the project live or dispatch another resume until the browser/response failure is diagnosed and corrected.**

## Verified state

- Canonical journal on `origin/main`: generation 112, active revision 163, transaction `a180efc687b8bac3039d9ee055735c72ad77163192bf93a2680d5f188344dfac`, state `operation_reported`, recovery `NONE`.
- The transaction already has one `APPLIED` `upload_version` attempt and one `APPLIED` `deploy_zero_percent` attempt. `promote` and `rollback` have no attempts. Do not recreate either successful mutation.
- Current Cloudflare deployment `33ce4d96-1054-48c6-ae21-02690633d7e5` routes 100% to baseline `cefbdeec-a3a7-4963-a4e9-19937f7829f9` and 0% to candidate `b3aa78ef-7b15-4d36-a87e-90dec308eb00`.
- The read-only content-revision endpoint reports revision 166. The last check-only run, `38485373151`, reported persisted published revision 81 and exited 3 because it detected a change; it made no publication mutation.
- Latest code commit on `origin/main`: `dcbe460b312936b6b89fcb30c0431e7e081a0ec2`.

## Last proof attempt

Run `38485698374` used the canonical `RESUME_ADMITTED` flow with the original source run and admission. Journal verification, artifact carry-forward, build-lineage validation, and admission passed. It failed after 34m38s in `pre-promotion-proof` with:

`ObservationRejected — read-only browser observation did not complete (exit 1): Node.js v22.23.3`

All promotion, production-proof, final-persistence, and rollback stages were skipped. Earlier proof run `38480089851` failed at the same stage. The final failure did not preserve the underlying JavaScript exception.

A local read-only reproduction checked 8 representative pages: zero-origin checks passed, but visual proof failed on font-wait screenshots, navigation timeouts, and connection resets. A local `/posts/` transfer probe returned HTTP 200 but did not complete its chunked response for either the baseline or candidate; the captured candidate body ended mid-script at 62,809 bytes. Treat this as a local diagnostic only: the cause is not established, and it does not replace hosted proof.

## Next safe sequence

1. Freshly inspect `origin/main`, `publisher-state/production-transaction-journal.json`, the public revision endpoint, and Cloudflare deployment percentages. The state may change after this handoff.
2. Diagnose the incomplete browser/HTTP response using the existing proof contract. Keep version attribution, full route proof, zero-origin checks, and all promotion gates intact.
3. The code at `dcbe460` improves captured Node.js errors by selecting the exception line rather than the trailing runtime-version line. Focused proof-observation tests passed (57 tests).
4. Only after the cause is fixed and the proof is expected to complete, resume the exact transaction with its original admitted source. Current verified identifiers were source run `38320622522`, source SHA `6a1e76a0ec3a710d77e8e9a26e8b60a9501e5585`, admission digest `3da108417499930d24a7fb72e34e44ce2dbb273ab8b5d3b88505123e171bf8c9`, and transaction ID above. Revalidate all of them first.
5. If revision 163 completes, confirm durable journal and 100% traffic. Then publish revision 166 through a separate normal transaction if it remains the current revision.
6. Run full production acceptance for the main domain, routes, images, media/audio, navigation, SEO metadata, canonical URLs, and pipeline lifecycle before declaring success.

## Validation and known risks

- `python -m unittest discover -s tools/publisher -p test_proof_observation_runner.py`: 57 passed.
- A previous full publisher suite passed 870 tests, 3 skipped. A later repeated full-suite run was stopped after more than 9 minutes without completion.
- Website build passed after the SEO endpoint change. The final diagnostic changes did not modify website or Worker source.
- A prior dependency audit reported 16 advisories, including 1 critical. GitHub Actions also reported Node.js 20 deprecation and the upcoming `ubuntu-latest` migration.
- No D1, Worker source, Cloudflare secret, or environment-variable changes were made.

See [`MAHOON-FINAL-REPORT.txt`](MAHOON-FINAL-REPORT.txt) for the complete evidence-backed status.
