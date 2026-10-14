"""M11-E Part A regression tests: explicit fail-closed gates on the downstream DAG.

Covers the 8 required invariants:
(1) Fresh PUBLISH with resume-admission=skipped traverses the full chain.
(2) Every Cloudflare mutation job blocks if its exact intent-write predecessor
    fails/skips (explicit ``!cancelled() && needs.<p>.result == 'success'``).
(3) Failure/cancellation blocks mutation.
(4) Irrelevant skipped branches don't poison the selected path.
(5) Direct successful mutation op permits result-write.
(6) Recovery branches only run for their intended UNKNOWN state.
(7) Normal APPLIED result does not enter recovery.
(8) Rollback only eligible after explicit failed production proof + successful
    promotion evidence.
"""
import re
import unittest

import yaml


class DownstreamDagHardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pathlib
        cls.WORKFLOW = yaml.load(
            (pathlib.Path(__file__).resolve().parents[2]
             / ".github/workflows/mahoon-static-publisher.yml").read_text(encoding="utf-8"),
            Loader=yaml.BaseLoader,
        )
        cls.RECONCILER = yaml.load(
            (pathlib.Path(__file__).resolve().parents[2]
             / ".github/workflows/mahoon-post-run-reconciler.yml").read_text(encoding="utf-8"),
            Loader=yaml.BaseLoader,
        )

    def job(self, name):
        return self.WORKFLOW["jobs"][name]

    def gate(self, name):
        return str(self.job(name).get("if", ""))

    def needs(self, name):
        n = self.job(name).get("needs", [])
        return [n] if isinstance(n, str) else list(n)

    # (2) every Cloudflare mutation job has an explicit success gate on its
    # exact direct predecessor.
    _CF_MUTATION = {
        "cloudflare-upload-operation": "upload-intent-write",
        "cloudflare-zero-percent-operation": "zero-percent-intent-write",
        "cloudflare-promote-operation": "promote-intent-write",
        "cloudflare-rollback-operation": "rollback-intent-write",
    }

    def test_cf_mutation_jobs_have_explicit_direct_success_gate(self):
        for job_name, predecessor in self._CF_MUTATION.items():
            gate = self.gate(job_name)
            self.assertIn(f"needs.{predecessor}.result == 'success'", gate,
                          f"{job_name} must gate on its exact predecessor success")
            self.assertIn("!cancelled()", gate,
                          f"{job_name} must not run after cancellation")
            self.assertNotIn("always()", gate,
                             f"{job_name} must not use unconditional always()")

    # result-writes are explicit success gates on their direct mutation op.
    _RESULT_WRITE = {
        "upload-result-write": "cloudflare-upload-operation",
        "zero-percent-result-write": "cloudflare-zero-percent-operation",
        "promote-result-write": "cloudflare-promote-operation",
        "rollback-result-write": "cloudflare-rollback-operation",
    }

    def test_result_writes_gate_on_direct_mutation_op(self):
        for job_name, predecessor in self._RESULT_WRITE.items():
            gate = self.gate(job_name)
            self.assertIn(f"needs.{predecessor}.result == 'success'", gate,
                          f"{job_name} must gate on its direct mutation op")
            self.assertIn("!cancelled()", gate)

    # (5) a direct successful mutation op permits the result-write to run.
    def test_result_write_permits_when_mutation_succeeds(self):
        for job_name, predecessor in self._RESULT_WRITE.items():
            gate = self.gate(job_name)
            # The gate's only blocking conjuncts are !cancelled() and the
            # direct predecessor success; no extra outputs poison it.
            self.assertNotIn("outputs.result_state", gate,
                             f"{job_name} must not gate on an output that is "
                             f"empty for a successful but UNKNOWN op")

    # (3) cancellation blocks mutation.
    def test_cancellation_blocks_mutation(self):
        for job_name in (*self._CF_MUTATION, *self._RESULT_WRITE):
            self.assertIn("!cancelled()", self.gate(job_name),
                          f"{job_name} must not run when workflow is cancelled")

    # (6) recovery observe jobs gate on exactly the UNKNOWN result state.
    _RECOVERY_OBSERVE = {
        "upload-recovery-readback-observe": "upload-result-write",
        "zero-recovery-readback-observe": "zero-percent-result-write",
        "promote-recovery-readback-observe": "promote-result-write",
        "rollback-recovery-readback-observe": "rollback-result-write",
    }

    def test_recovery_observe_runs_only_for_unknown(self):
        for job_name, result_write in self._RECOVERY_OBSERVE.items():
            gate = self.gate(job_name)
            self.assertIn(f"needs.{result_write}.outputs.result_state == 'UNKNOWN'", gate,
                          f"{job_name} must run only when the result is UNKNOWN")
            self.assertIn("always()", gate,
                          f"{job_name} must observe even a failed result-write")

    # (7) a normal APPLIED result must NOT enter recovery: the recovery-decision
    # job is only reached through the UNKNOWN-gated observe job.
    def test_applied_result_does_not_enter_recovery(self):
        for job_name, result_write in self._RECOVERY_OBSERVE.items():
            gate = self.gate(job_name)
            self.assertNotIn("'APPLIED'", gate,
                             f"{job_name} must not fire for an APPLIED result")

    # create-recovered-result jobs gate on RECONCILED_APPLIED + reconcile success.
    def test_create_recovered_result_gates_on_reconciled_applied(self):
        for job_name in ("upload-create-recovered-result",
                         "zero-create-recovered-result",
                         "promote-create-recovered-result",
                         "rollback-create-recovered-result"):
            gate = self.gate(job_name)
            self.assertIn("RECONCILED_APPLIED", gate,
                          f"{job_name} must require a reconciled-applied decision")

    # (8) rollback only eligible after failed production proof + successful
    # promotion evidence.
    def test_rollback_eligibility_requires_failed_proof_and_promotion(self):
        gate = self.gate("rollback-intent-write")
        self.assertIn("needs.production-proof.outputs.proof_state == 'FAIL'", gate,
                       "rollback must require an explicit failed production proof")
        self.assertIn("needs.promote-result-write.outputs.result_state == 'APPLIED'", gate)
        self.assertIn("needs.promote-create-recovered-result.outputs.recovered == 'true'", gate)

    # (1) a fresh PUBLISH chain: admission success + build-validate success
    # propagates to every mutation job without touching the skipped resume
    # branch.
    def test_fresh_publish_chain_is_gated_back_to_build_validate(self):
        jobs = self.WORKFLOW["jobs"]
        mutation_jobs = [
            "build-ready-write", "production-baseline-reconciliation",
            "upload-intent-write", "cloudflare-upload-operation",
            "upload-result-write", "zero-percent-intent-write",
            "cloudflare-zero-percent-operation", "zero-percent-result-write",
            "pre-promotion-proof", "promote-intent-write",
            "cloudflare-promote-operation", "promote-result-write",
            "production-proof", "final-state-materialization", "final-persistence",
        ]

        def needs_list(name):
            n = jobs[name].get("needs", [])
            return [n] if isinstance(n, str) else list(n)

        def blocks_on_build_validate(name, depth=0):
            if depth > 60:
                return False
            gate = str(jobs[name].get("if", ""))
            if "needs.build-validate.result == 'success'" in gate:
                return True
            if not gate:
                nn = needs_list(name)
                if not nn:
                    return False
                return all(blocks_on_build_validate(n, depth + 1) for n in nn)
            refs = re.findall(r"needs\.([\w-]+)", gate)
            if not refs:
                return False
            for ref in refs:
                if ref not in jobs:
                    continue
                if f"needs.{ref}.result == 'success'" in gate:
                    if not blocks_on_build_validate(ref, depth + 1):
                        return False
                    continue
                m = re.search(
                    rf"needs\.{re.escape(ref)}\.outputs\.[\w-]+\s*==\s*'([^']*)'", gate)
                if m is not None:
                    if m.group(1) == "":
                        return False
                    if not blocks_on_build_validate(ref, depth + 1):
                        return False
                else:
                    return False
            return True

        for name in mutation_jobs:
            self.assertIn(name, jobs, f"missing job: {name}")
            self.assertTrue(blocks_on_build_validate(name),
                            f"{name} can run when build-validate fails")

    # (4) irrelevant skipped branches must not poison the selected path:
    # the PUBLISH branch of build-ready-write must not reference the resume
    # branch.
    def test_irrelevant_resume_branch_does_not_poison_fresh_publish(self):
        gate = self.gate("build-ready-write")
        publish_branch = gate.split("inputs.mode == 'RESUME_ADMITTED'")[0]
        self.assertNotIn("resume-admission", publish_branch)

    # (2)+(4) a skipped zero-recovery branch must not block a direct successful
    # zero-percent result from flowing into pre-promotion-proof.
    def test_skipped_recovery_branch_does_not_block_applied_path(self):
        gate = self.gate("pre-promotion-proof")
        self.assertIn("needs.zero-percent-result-write.outputs.result_state == 'APPLIED'", gate)
        self.assertIn("needs.zero-create-recovered-result.outputs.recovered == 'true'", gate)
        self.assertIn("always()", gate,
                      "pre-promotion-proof must observe even a skipped recovery branch")

    # Zero-carryforward: when the source run already recorded deploy_zero_percent
    # APPLIED, the resume path re-exposes the sealed zero intent/result under this
    # run's canonical artifact names so the pre-promotion-proof and promote chain
    # can complete WITHOUT re-recording (DuplicateMutation) or re-executing the
    # operation. This is the minimal bounded fix for the in-flight resume gap.
    # The carryforward chain re-exposes the source zero intent/result under this
    # run's canonical artifact names.  The build bundle and production baseline
    # must also be re-exposed by build-ready-write so that pre-promotion-proof
    # and all downstream jobs can download them by the current run's ID.
    def test_build_ready_write_reexposes_source_build_bundle_on_resume(self):
        gate = str(self.job("build-ready-write"))
        # The re-expose step must be gated on the resume path.
        self.assertIn(
            "a6-build-${{ github.run_id }}",
            gate,
            "build-ready-write must re-expose the source build bundle under this run's canonical name",
        )
        self.assertIn(
            "inputs.resume_source_run_id != ''",
            gate,
            "the build re-expose must only run on the resume path",
        )
        # Preserve the same paths as the original build artifact so resumed proof
        # jobs receive the route and media manifests at their contracted locations.
        for path in (
            "handoff/runner-evidence/publisher-sealed/",
            "handoff/runner-evidence/v1-build-bundle.json",
            "handoff/runner-evidence/current-v2-snapshot.json",
            "handoff/runner-evidence/prepromotion-local-gates.json",
            "handoff/runner-build/production-media-manifest.json",
            "handoff/runner-build/published-route-manifest.json",
        ):
            self.assertIn(path, gate, f"build re-expose must preserve {path}")
        self.assertIn("Restore and verify the source route manifest", gate)
        self.assertIn('bundle["payload"]["snapshot_sha256"]', gate)
        self.assertIn('bundle["payload"]["route_manifest_sha256"]', gate)
        self.assertIn("RESUME_ROUTE_MANIFEST_SHA256_MISMATCH", gate)

    def test_zero_carryforward_bypasses_zero_intent_write(self):
        gate = self.gate("zero-percent-intent-write")
        # The gate must NOT run when the carryforward job succeeded.
        self.assertIn(
            "needs.resume-zero-carryforward.result == 'success' && needs.resume-zero-carryforward.outputs.carried == 'true'",
            gate,
            "zero-percent-intent-write must be skipped when the zero carryforward job re-exposed the sealed evidence",
        )
        self.assertIn(
            "!(",
            gate,
            "the carryforward skip must be an explicit negation of the carried condition",
        )
        # The job must also depend on the carryforward job.
        self.assertIn(
            "resume-zero-carryforward",
            self.needs("zero-percent-intent-write"),
            "zero-percent-intent-write must list resume-zero-carryforward in needs",
        )

    def test_pre_promotion_proof_accepts_zero_carryforward(self):
        gate = self.gate("pre-promotion-proof")
        self.assertIn(
            "needs.resume-zero-carryforward.result == 'success' && needs.resume-zero-carryforward.outputs.carried == 'true'",
            gate,
            "pre-promotion-proof must accept the carried zero path",
        )
        self.assertIn(
            "resume-zero-carryforward",
            self.needs("pre-promotion-proof"),
            "pre-promotion-proof must list resume-zero-carryforward in needs",
        )

    def test_promote_intent_write_accepts_zero_carryforward(self):
        gate = self.gate("promote-intent-write")
        self.assertIn(
            "needs.resume-zero-carryforward.result == 'success' && needs.resume-zero-carryforward.outputs.carried == 'true'",
            gate,
            "promote-intent-write must accept the carried zero path",
        )
        self.assertIn(
            "resume-zero-carryforward",
            self.needs("promote-intent-write"),
            "promote-intent-write must list resume-zero-carryforward in needs",
        )

    def test_production_proof_accepts_zero_carryforward(self):
        gate = self.gate("production-proof")
        self.assertIn(
            "needs.resume-zero-carryforward.result == 'success' && needs.resume-zero-carryforward.outputs.carried == 'true'",
            gate,
            "production-proof must accept the carried zero-percent result",
        )
        self.assertIn(
            "resume-zero-carryforward",
            self.needs("production-proof"),
            "production-proof must list resume-zero-carryforward in needs",
        )

    def test_post_promotion_finalization_carries_applied_result_without_mutating(self):
        carry = self.job("resume-promote-carryforward")
        gate = str(carry.get("if", ""))
        self.assertIn("inputs.mode == 'POST_PROMOTION_FINALIZE'", gate)
        self.assertIn("resume-preproof-carryforward.outputs.carried == 'true'", gate)
        self.assertIn("resume-zero-carryforward.outputs.carried == 'true'", gate)
        commands = "\n".join(str(step.get("run", "")) for step in carry["steps"])
        self.assertIn("validate_effective_applied_result", commands)
        self.assertIn("EXPECTED_SOURCE_RUN_ID", str(carry))
        self.assertIn('promotion["result_state"] == "NOT_REPORTED"', commands)
        self.assertIn('attempt["result_digest"] is None', commands)
        self.assertIn('active["state"] == "operation_reported"', commands)
        self.assertIn('evidence.get("reference") == result["artifact_sha256"]', commands)
        self.assertIn('if [ "$already_applied" != "true" ]; then', commands)
        self.assertIn("record-result", commands)
        self.assertIn("carried=true", commands)
        self.assertNotIn("execute-operation", commands)
        self.assertNotIn("CLOUDFLARE_API_TOKEN", str(carry))
        self.assertIn("a6-promote-result-${{ inputs.resume_source_run_id }}", str(carry))
        zero_intent_gate = self.gate("zero-percent-intent-write")
        self.assertIn("inputs.mode != 'POST_PROMOTION_FINALIZE'", zero_intent_gate)
        self.assertIn("inputs.mode != 'POST_PROMOTION_FINALIZE'", self.gate("pre-promotion-proof"))

        promote_intent = self.job("promote-intent-write")
        self.assertIn("inputs.mode != 'POST_PROMOTION_FINALIZE'", str(promote_intent.get("if", "")))
        self.assertIn("resume-promote-carryforward", self.needs("production-proof"))
        self.assertIn("resume-promote-carryforward.outputs.result_state == 'APPLIED'",
                      self.gate("production-proof"))
        self.assertIn("resume-promote-carryforward", self.needs("rollback-intent-write"))

    def test_promotion_result_writer_passes_full_sealed_lineage(self):
        job = self.job("promote-result-write")
        run = "\n".join(str(step.get("run", "")) for step in job["steps"])
        for reference in (
            "handoff/runner-evidence/v1-build-bundle.json",
            "handoff/pre-promotion-proof.json",
            "handoff/zero-percent-intent.json",
            "handoff/zero-percent-result.json",
        ):
            self.assertIn(reference, str(job))
        self.assertIn('"${refs[@]}"', run)
        self.assertIn("zero-create-recovered-result.outputs.recovered", run)

    def test_resume_zero_carryforward_job_exists_and_gates_correctly(self):
        job = self.job("resume-zero-carryforward")
        gate = str(job.get("if", ""))
        # Must be gated on the resume path with APPLIED source result.
        self.assertIn("inputs.resume_source_run_id != ''", gate)
        self.assertIn("needs.resume-source-carryforward.result == 'success'", gate)
        self.assertIn("needs.resume-source-carryforward.outputs.source_result_state == 'APPLIED'", gate)
        # Must re-expose the source zero artifacts under this run's canonical names.
        job_str = str(job)
        self.assertIn("a6-zero-intent-${{ inputs.resume_source_run_id }}", job_str)
        self.assertIn("a6-zero-direct-result-${{ inputs.resume_source_run_id }}", job_str)
        self.assertIn("a6-zero-intent-${{ github.run_id }}", job_str)
        self.assertIn("a6-zero-direct-result-${{ github.run_id }}", job_str)
        # Must validate the journal state before re-exposing.
        self.assertIn('zero_op["result_state"] == "APPLIED"', job_str)
        self.assertIn("intent_artifact_sha256", job_str)
        # Must output carried=true on success.
        self.assertIn("carried=true", job_str)

    def test_resume_upload_carryforward_downloads_the_canonical_direct_result(self):
        job = self.job("resume-source-carryforward")
        self.assertIn("a6-upload-direct-result-${{ inputs.resume_source_run_id }}", str(job))
        self.assertNotIn("a6-upload-result-${{ inputs.resume_source_run_id }}", str(job))

    def test_zero_carryforward_accepts_reexposed_producers_but_matches_intent(self):
        job = self.job("resume-zero-carryforward")
        commands = "\n".join(str(step.get("run", "")) for step in job["steps"])
        self.assertIn('zero_result["producer"]["workflow_run_id"] == zero_intent["producer"]["workflow_run_id"]',
                      commands)
        self.assertNotIn('zero_result["producer"]["workflow_run_id"] == source_run', commands)

    # Missing or mismatched evidence must fail closed: if the carryforward job
    # did NOT run (resume not APPLIED), the zero-percent-intent-write gate
    # falls back to the normal direct/recovered path, and the pre-promotion-proof
    # gate does NOT fire on the carried path.
    def test_zero_carryforward_fails_closed_when_not_applied(self):
        # If resume-source-carryforward source_result_state is not APPLIED,
        # resume-zero-carryforward is skipped, so its gate is false and
        # zero-percent-intent-write is NOT skipped (it runs the normal path).
        gate = self.gate("zero-percent-intent-write")
        # The skip condition requires resume-zero-carryforward.result == 'success'
        # AND carried == 'true'. When the carryforward job is skipped (result is
        # not success), the negation is true and the normal path runs.
        self.assertIn(
            "needs.resume-zero-carryforward.result == 'success'",
            gate,
        )
        self.assertIn(
            "needs.resume-zero-carryforward.outputs.carried == 'true'",
            gate,
        )
        # pre-promotion-proof must NOT fire on the carried path when the
        # carryforward job did not succeed.
        pp_gate = self.gate("pre-promotion-proof")
        self.assertIn(
            "needs.resume-zero-carryforward.result == 'success' && needs.resume-zero-carryforward.outputs.carried == 'true'",
            pp_gate,
        )

    # every active job with multiple needs must carry an explicit gate.
    def test_multi_need_jobs_have_explicit_gates(self):
        implicit = set()
        for name, job in self.WORKFLOW["jobs"].items():
            if job.get("if") == "false":
                continue
            gate = str(job.get("if", ""))
            nn = [job.get("needs", [])]
            nn = [x for flat in nn for x in ([flat] if isinstance(flat, str) else flat)]
            if not gate and len(nn) > 1:
                implicit.add(name)
        self.assertEqual(set(), implicit,
                         f"multi-need jobs without an explicit gate: {implicit}")

    def test_browser_diagnostic_isolated_and_proof_jobs_install_locked_chromium(self):
        diagnostic = self.job("browser-runtime-diagnostic")
        self.assertIn("inputs.mode == 'BROWSER_DIAGNOSTIC'", str(diagnostic.get("if", "")))
        self.assertFalse(diagnostic.get("needs"))
        self.assertIn("inputs.mode == 'BROWSER_DIAGNOSTIC'", self.gate("journal-bootstrap"))
        commands = "\n".join(str(step.get("run", "")) for step in diagnostic.get("steps", []))
        self.assertIn("npm ci --prefix diagnostics/website/dreary-disk", commands)
        self.assertIn("--runtime-probe", commands)
        self.assertIn("--self-test", commands)
        self.assertIn("/posts/", commands)
        self.assertNotIn("CLOUDFLARE_API_TOKEN", str(diagnostic.get("env", {})))

        for job_name in ("pre-promotion-proof", "production-proof"):
            steps = self.job(job_name)["steps"]
            install = next((step for step in steps
                            if "Install lockfile-pinned Playwright Chromium" in str(step.get("name", ""))), None)
            self.assertIsNotNone(install, f"{job_name} must install Chromium before its browser observer")
            self.assertIn("npx playwright install --with-deps chromium", install["run"])
            self.assertLess(next(i for i, step in enumerate(steps) if step.get("run", "").startswith("npm ci ")),
                            steps.index(install))
            self_test = next((step for step in steps
                              if step.get("name") == "Run the existing browser gate self-test"), None)
            self.assertIsNotNone(self_test, f"{job_name} must smoke-test Chromium before crawling")
            self.assertIn("--self-test", self_test["run"])
            observer = next(i for i, step in enumerate(steps)
                            if str(step.get("name", "")).startswith("Observe and seal combined"))
            self.assertLess(steps.index(install), steps.index(self_test))
            self.assertLess(steps.index(self_test), observer)
            evidence_upload = next(step for step in steps if step.get("uses") == "actions/upload-artifact@v4")
            self.assertIn("always()", str(evidence_upload.get("if", "")))
            self.assertIn("browser-diagnostic.json", str(evidence_upload.get("with", {})))
            self.assertIn("browser-self-test.json", str(evidence_upload.get("with", {})))
            self.assertIn("-failed/**", evidence_upload["with"]["path"])
            self.assertIn("-screenshots/**", evidence_upload["with"]["path"])
            self.assertIn("preproof-status.json" if job_name == "pre-promotion-proof" else "proof-status.json",
                          evidence_upload["with"]["path"])

    def test_live_functionality_diagnostic_is_isolated_and_read_only(self):
        import pathlib
        path = pathlib.Path(__file__).resolve().parents[2] / ".github/workflows/mahoon-live-functionality.yml"
        text = path.read_text(encoding="utf-8")
        workflow = yaml.load(text, Loader=yaml.BaseLoader)
        self.assertEqual("read", workflow["permissions"]["contents"])
        self.assertEqual("read", workflow["permissions"]["actions"])
        self.assertIn("contents: read", text)
        self.assertIn("group: mahoon-read-only-functionality", text)
        self.assertIn("node-version: 22", text)
        self.assertIn("npx playwright install --with-deps chromium", text)
        self.assertIn("--self-test", text)
        self.assertIn("inputs.expected_version", text)
        self.assertIn("if: always()", text)
        self.assertIn("mahoon-live-functionality-${{ inputs.baseline_run_id }}", text)
        self.assertNotIn("a6-build-", text)
        for forbidden in ("contents: write", "secrets.", "execute-operation", "deploy"):
            self.assertNotIn(forbidden, text)
        script = (path.parents[2] / "tools/publisher/live_functionality_smoke.mjs").read_text(encoding="utf-8")
        self.assertIn("check('admin_authentication_boundary'", script)
        self.assertIn("boundary.get('https://api.mahoonartmagazine.ir/admin/health')", script)
        self.assertIn("assert.equal(response.status(), 401)", script)
        self.assertIn("checks.length === 8 + newPosts.length", script)
        self.assertIn("document.fonts.status === 'loaded'", script)
        self.assertIn("document.fonts.check('12px MahoonFont')", script)
        self.assertIn("candidate_pinned: candidatePinned", script)
        self.assertIn("extraHTTPHeaders: versionHeaders", script)
        self.assertNotIn("page.route(", script)
        self.assertIn("url.origin !== base", script)
        self.assertIn("classifyPublicRequest(request.url())", script)
        self.assertNotIn("&& candidateExternalRequests.length === 0", script)
        self.assertIn("inputs.pin_candidate", text)
        self.assertEqual("NO", workflow["on"]["workflow_dispatch"]["inputs"]["pin_candidate"]["default"])
        self.assertIn('page.locator(articleMediaSelectors[kind]).count()', script)
        self.assertIn('failure_stage: failureStage', script)
        self.assertIn('source_path: node.currentSrc', script)

    def test_production_proof_references_the_full_promotion_authority_chain(self):
        proof = self.job("production-proof")
        observer = next(step for step in proof["steps"]
                        if step.get("name") == "Observe and seal combined production proof")
        for path in (
            "runner-evidence/v1-build-bundle.json",
            "pre-promotion-proof.json",
            "admission.json",
        ):
            self.assertIn(f'--reference "$workspace/handoff/{path}"', observer["run"])

    def test_build_metadata_retains_bound_snapshot_without_large_site_transfer(self):
        step = next(s for s in self.job("build-validate")["steps"]
                    if s.get("name") == "Retain small sealed build metadata for independent content acceptance")
        self.assertEqual("actions/upload-artifact@v4", step["uses"])
        self.assertEqual("error", step["with"]["if-no-files-found"])
        for name in ("v1-build-bundle.json", "current-v2-snapshot.json", "production-media-manifest.json", "published-route-manifest.json"):
            self.assertIn(name, step["with"]["path"])
        self.assertNotIn("publisher-sealed/", step["with"]["path"])

    def test_finalization_references_authorities_and_uses_transaction_staging_root(self):
        for name in ("final-state-materialization", "final-persistence"):
            job = self.job(name)
            run = "\n".join(str(step.get("run", "")) for step in job["steps"])
            for path in ("runner-evidence/v1-build-bundle.json", "pre-promotion-proof.json", "admission.json"):
                self.assertIn("--reference handoff/" + path, run)
            self.assertIn("a6-preproof-${{ github.run_id }}", str(job))
            self.assertIn("diagnostics/tools/publisher/workflow_stage_cli.py", run)
        persistence = "\n".join(str(s.get("run", "")) for s in self.job("final-persistence")["steps"])
        self.assertIn('--state-dir "handoff/${tx_id}"', persistence)
        self.assertNotIn('--state-dir "handoff/${tx_id}/publisher-state"', persistence)
        self.assertIn('--journal publisher-state/production-transaction-journal.json', persistence)
        self.assertNotIn('--journal state/publisher-state/production-transaction-journal.json', persistence)

    def test_passing_production_proof_carryforward_is_explicit_and_revalidated(self):
        job = self.job("production-proof")
        carry = next(s for s in job["steps"] if s.get("name", "").startswith("Revalidate passing production proof"))
        self.assertIn("inputs.mode == 'POST_PROMOTION_FINALIZE'", carry["if"])
        self.assertIn("inputs.source_proof_run_id", carry["if"])
        self.assertIn("production-proof-carryforward", carry["run"])
        self.assertIn("--observations-dir retained-proof/runner-evidence/production-proof", carry["run"])
        observer = next(s for s in job["steps"] if s.get("name") == "Observe and seal combined production proof")
        self.assertIn("inputs.source_proof_run_id == ''", observer["if"])

    def test_passing_preproof_can_be_carried_forward_with_complete_lineage(self):
        inputs = self.WORKFLOW["on"]["workflow_dispatch"]["inputs"]
        self.assertIn("preproof_source_run_id", inputs)
        self.assertEqual("", inputs["preproof_source_run_id"]["default"])

        carry = self.job("resume-preproof-carryforward")
        gate = str(carry.get("if", ""))
        self.assertIn("inputs.preproof_source_run_id", gate)
        self.assertIn("needs.resume-zero-carryforward.outputs.carried == 'true'", gate)
        self.assertEqual({"contents": "read", "actions": "read"}, carry["permissions"])
        commands = "\n".join(str(step.get("run", "")) for step in carry["steps"])
        self.assertIn('expected_type="pre_promotion_proof_evidence"', commands)
        self.assertIn('"PASS"] is True', commands)
        self.assertIn('"build_bundle_artifact_sha256"] == build["artifact_sha256"]', commands)
        self.assertIn('"deploy_zero_percent_result_artifact_sha256"] == zero_result["artifact_sha256"]', commands)
        self.assertIn("candidate_version_id", commands)
        self.assertIn("baseline_version_id", commands)
        self.assertIn("zero_percent_deployment_id", commands)

        pp_gate = self.gate("pre-promotion-proof")
        self.assertIn("inputs.preproof_source_run_id == ''", pp_gate)
        promote = self.job("promote-intent-write")
        self.assertIn("resume-preproof-carryforward", self.needs("promote-intent-write"))
        self.assertIn("needs.resume-preproof-carryforward.outputs.carried == 'true'",
                      str(promote.get("if", "")))
        intent_checkout = next(step for step in promote["steps"]
                               if step.get("uses") == "actions/checkout@v4")
        self.assertEqual("${{ github.sha }}", intent_checkout["with"]["ref"])
        intent_command = next(step["run"] for step in promote["steps"]
                              if step.get("id") == "intent")
        self.assertIn("--reference handoff/runner-evidence/v1-build-bundle.json", intent_command)

    def test_post_run_reconciler_binds_and_reads_back_the_exact_orphan(self):
        steps = self.RECONCILER["jobs"]["reconcile"]["steps"]
        classify = next(step for step in steps if step.get("name") == "Identify and classify orphaned intent")
        self.assertIn('intent_value.get("artifact_sha256") == recorded_attempt.get("intent_artifact_sha256")',
                      classify["run"])
        self.assertIn('producer.get("workflow_run_id") == run_id', classify["run"])
        self.assertIn('producer.get("run_attempt") == source_attempt', classify["run"])
        self.assertIn('f"actions/runs/{run_id}/jobs?per_page=100"', classify["run"])
        self.assertNotIn("recorded_by_this_run and", classify["run"])

        failed = next(step for step in steps if step.get("name") == "Reconcile orphaned Class B intent (failed mutation)")
        self.assertEqual("${{ secrets.CLOUDFLARE_READ_API_TOKEN }}", failed["env"]["CLOUDFLARE_API_TOKEN"])
        self.assertEqual("npx wrangler@4.83.0", failed["env"]["MAHOON_WRANGLER"])
        self.assertIn("a6-preproof-${{ steps.classify.outputs.run_id }}", failed["run"])
        self.assertIn('"${refs[@]}"', failed["run"])

    def test_promote_operation_validates_the_build_bundle_as_a_reference(self):
        step = next(step for step in self.job("cloudflare-promote-operation")["steps"]
                    if step.get("name") == "Execute exact authorized promotion")
        self.assertIn("refs=(--reference handoff/runner-evidence/v1-build-bundle.json", step["run"])


if __name__ == "__main__":
    unittest.main()
