"""Regression tests for the M11-E publish DAG skip-defect fix.

The defect: `build-ready-write` had no `if:` gate. Its implicit default
context was `success()`, which requires ALL needs to have concluded
success.  Because `build-validate` needs `[admission, resume-admission]`,
a fresh PUBLISH run (admission=success, resume-admission=skipped) produced
a skipped `build-ready-write` even though `build-validate` itself had
succeeded.  The fix adds explicit fail-closed gates to the two root jobs of
the A6 mutation chain so that an irrelevant skipped branch cannot poison
the selected execution path.
"""
import re
import unittest

import yaml


class PublishDagGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pathlib
        cls.WORKFLOW = yaml.load(
            (pathlib.Path(__file__).resolve().parents[2]
             / ".github/workflows/mahoon-static-publisher.yml").read_text(encoding="utf-8"),
            Loader=yaml.BaseLoader,
        )

    def job(self, name):
        return self.WORKFLOW["jobs"][name]

    def needs(self, name):
        n = self.job(name).get("needs", [])
        return [n] if isinstance(n, str) else list(n)

    # --- Structural gate assertions ------------------------------------

    def test_build_ready_write_has_explicit_gate(self):
        gate = str(self.job("build-ready-write").get("if", ""))
        self.assertIn("needs.build-validate.result == 'success'", gate,
                       "build-ready-write must require build-validate success")
        self.assertIn("!cancelled()", gate,
                       "build-ready-write must not run after cancellation")
        self.assertIn("inputs.mode == 'PUBLISH'", gate,
                       "gate must cover the PUBLISH branch explicitly")
        self.assertIn("inputs.mode == 'RESUME_ADMITTED'", gate,
                       "gate must cover the RESUME branch explicitly")

    def test_build_ready_write_gate_fresh_publish_path(self):
        gate = str(self.job("build-ready-write").get("if", ""))
        # Fresh PUBLISH: admission success + build-validate success,
        # resume-admission skipped → gate must evaluate true.
        self.assertIn("(inputs.mode == 'PUBLISH' || inputs.mode == 'PROMOTE_AND_VALIDATE')", gate,
                       "PUBLISH branch must be present as a single unit")
        self.assertRegex(
            gate,
            r"needs\.build-validate\.result == 'success' && needs\.admission\.result == 'success'",
        )

    def test_build_ready_write_gate_resume_path(self):
        gate = str(self.job("build-ready-write").get("if", ""))
        # RESUME: resume-admission success + ADMITTED + build-validate success.
        self.assertRegex(
            gate,
            r"inputs\.mode == 'RESUME_ADMITTED' && needs\.build-validate\.result == 'success'"
            r" && needs\.resume-admission\.result == 'success' && needs\.resume-admission\.outputs\.decision == 'ADMITTED'",
        )

    def test_production_baseline_reconciliation_has_explicit_gate(self):
        gate = str(self.job("production-baseline-reconciliation").get("if", ""))
        self.assertIn("needs.build-ready-write.result == 'success'", gate,
                       "baseline reconciliation must require build-ready-write success")
        self.assertIn("!cancelled()", gate)

    def test_upload_intent_write_gate_requires_build_ready(self):
        gate = str(self.job("upload-intent-write").get("if", ""))
        self.assertIn("needs.build-ready-write.result == 'success'", gate)

    # --- No Cloudflare job may run after a failed prerequisite ----------

    def test_no_cloudflare_job_runs_after_failed_prerequisite(self):
        cf_jobs = [n for n, j in self.WORKFLOW["jobs"].items()
                   if n.startswith(("cloudflare-upload", "cloudflare-zero",
                                     "cloudflare-promote", "cloudflare-rollback"))]
        for job_name in cf_jobs:
            gate = str(self.job(job_name).get("if", ""))
            needs_list = self.needs(job_name)
            # A Cloudflare operation job is safe if either:
            #   (a) it has an explicit if-gate referencing one of its own
            #       needs (direct success gate), OR
            #   (b) it has no if-gate, but its single prerequisite job
            #       transitively requires an explicit success-gate chain
            #       back to build-ready-write (the root of the A6 mutation
            #       chain that now has a fail-closed gate).
            has_direct = any(f"needs.{n}.result == 'success'" in gate for n in needs_list) or \
                         any(f"needs.{n}.outputs" in gate for n in needs_list)
            if has_direct:
                continue
            # (b): walk the transitive prerequisite chain; every ancestor
            # must itself carry an explicit gate, or be a single-need job
            # whose need is also transitively gated (i.e. a safe chain).
            visited = set()
            def is_transitively_gated(name, depth=0):
                if depth > 20:
                    return False
                if name in visited:
                    return False
                visited.add(name)
                j = self.job(name)
                g = str(j.get("if", ""))
                if g and g != "false":
                    return True
                nn = [j.get("needs", [])]
                nn = [x for flat in nn for x in ([flat] if isinstance(flat, str) else flat)]
                if len(nn) == 1:
                    return is_transitively_gated(nn[0], depth + 1)
                # Multiple needs and no gate → not transitively safe
                return False
            self.assertTrue(
                all(is_transitively_gated(n) for n in needs_list),
                f"{job_name} has no explicit success gate and no safe transitive "
                f"prerequisite chain back to a gated root job",
            )

    # --- Upstream failure blocks all mutation jobs ----------------------

    def test_build_failure_blocks_all_mutation_jobs(self):
        """If build-validate fails, every job in the mutation chain is blocked.

        Proof: for each mutation job, walk upward through its `needs` graph.
        Job J is blocked by build-validate failure when every execution path
        to J leads through a job that has an explicit
        `needs.build-validate.result == 'success'` gate.

        The chain is:
          build-ready-write (gated on build-validate)
            → production-baseline-reconciliation (gated on build-ready-write)
            → upload-intent-write (gated on build-ready-write + baseline)
            → cloudflare-upload-operation (implicit, single need: upload-intent-write)
            → upload-result-write (implicit, single need: cloudflare-upload-operation)
            → zero-percent-intent-write (gated on upload-result-write)
            → cloudflare-zero-percent-operation (gated on zero-percent-intent-write)
            → zero-percent-result-write (implicit, single need: cloudflare-zero-percent-operation)
            → pre-promotion-proof (gated on zero-percent-result-write)
            → promote-intent-write (gated on pre-promotion-proof)
            → cloudflare-promote-operation (implicit, single need: promote-intent-write)
            → promote-result-write (implicit, single need: cloudflare-promote-operation)
            → production-proof (gated on all result writers)
            → final-state-materialization (gated on production-proof)
            → final-persistence (gated on final-state-materialization)
        """
        mutation_jobs = [
            "build-ready-write",
            "production-baseline-reconciliation",
            "upload-intent-write",
            "cloudflare-upload-operation",
            "upload-result-write",
            "zero-percent-intent-write",
            "cloudflare-zero-percent-operation",
            "zero-percent-result-write",
            "pre-promotion-proof",
            "promote-intent-write",
            "cloudflare-promote-operation",
            "promote-result-write",
            "production-proof",
            "final-state-materialization",
            "final-persistence",
        ]
        jobs = self.WORKFLOW["jobs"]

        def needs_list(name):
            n = jobs[name].get("needs", [])
            return [n] if isinstance(n, str) else list(n)

        def has_build_validate_gate(name, depth=0):
            """True when a failed `build-validate` transitively blocks `name`.

            Rule: a job is blocked when every gate-conjunct that references a
            prerequisite carries a fail-closed dependency:
              - `needs.X.result == 'success'`  — blocks when X is not success
              - `needs.X.outputs.Y == 'V'` with a non-empty V — blocks when X
                is not success, because GitHub outputs are empty for a
                non-successful job, so the comparison is always false.
            Gating on an output with an empty value (or no gate at all) is
            NOT fail-closed on build-validate.
            """
            if depth > 60:
                return False
            gate = str(jobs[name].get("if", ""))
            if "needs.build-validate.result == 'success'" in gate:
                return True
            if not gate:
                nn = needs_list(name)
                if not nn:
                    return False
                # Implicit success() context: all needs must conclude success.
                return all(has_build_validate_gate(n, depth + 1) for n in nn)
            # Gated job: check every needs.<X> ref (result or outputs).
            refs = re.findall(r"needs\.([\w-]+)", gate)
            if not refs:
                return False
            for need_name in refs:
                if need_name not in jobs:
                    continue
                success_ref = f"needs.{need_name}.result == 'success'" in gate
                m = re.search(
                    rf"needs\.{re.escape(need_name)}\.outputs\.[\w-]+\s*==\s*'([^']*)'",
                    gate)
                if success_ref:
                    if not has_build_validate_gate(need_name, depth + 1):
                        return False
                elif m is not None:
                    # Comparison against a non-empty value: empty GitHub
                    # outputs for a failed job make the test false → blocked.
                    if m.group(1) == "":
                        return False
                    if not has_build_validate_gate(need_name, depth + 1):
                        return False
                else:
                    # Need referenced but in neither a success nor an
                    # output-comparison context: not fail-closed.
                    return False
            return True

        for job_name in mutation_jobs:
            self.assertIn(job_name, jobs, f"missing job: {job_name}")
            self.assertTrue(
                has_build_validate_gate(job_name),
                f"{job_name} can run even when build-validate fails — "
                f"the mutation chain is not fail-closed at this node",
            )

    def test_cancelled_blocks_mutation(self):
        for job_name in ("build-ready-write", "production-baseline-reconciliation"):
            gate = str(self.job(job_name).get("if", ""))
            self.assertIn("!cancelled()", gate,
                          f"{job_name} must not run when workflow is cancelled")

    # --- Irrelevant skipped branch must not poison selected branch ------

    def test_irrelevant_resume_branch_cannot_poison_fresh_publish(self):
        """The RESUME path is fully gated behind inputs.mode == 'RESUME_ADMITTED'.

        A skipped `resume-admission` (fresh PUBLISH) must NOT cause
        `build-ready-write` to be skipped — the gate expression explicitly
        selects the PUBLISH sub-branch when mode != RESUME_ADMITTED.
        """
        gate = str(self.job("build-ready-write").get("if", ""))
        # The PUBLISH sub-branch must not reference resume-admission.
        publish_branch = gate.split("inputs.mode == 'RESUME_ADMITTED'")[0]
        self.assertNotIn("resume-admission", publish_branch,
                         "PUBLISH branch must not reference the resume-admission branch")

    # --- build-validate's own gate is correct --------------------------

    def test_build_validate_gate_selects_one_branch(self):
        gate = str(self.job("build-validate").get("if", ""))
        self.assertIn("always()", gate)
        self.assertIn("inputs.mode == 'RESUME_ADMITTED'", gate)
        self.assertIn("needs.admission.result == 'success'", gate)
        self.assertIn("needs.resume-admission.result == 'success'", gate)

    # --- All active A6 jobs are reachable --------------------------------

    def test_all_active_jobs_have_explicit_gates_or_single_unconditional_need(self):
        """Every job that participates in the A6 mutation chain must have an
        explicit `if:` gate OR a single unconditional need (i.e. the implicit
        default context will not be poisoned by a skipped sibling)."""
        implicit_default_jobs = set()
        for name, job in self.WORKFLOW["jobs"].items():
            if job.get("if") == "false":
                continue
            gate = str(job.get("if", ""))
            needs_list = [job.get("needs", [])]
            needs_list = [n for flat in needs_list for n in ([flat] if isinstance(flat, str) else flat)]
            if not gate and len(needs_list) > 1:
                # Multiple needs and no explicit gate → implicit default context
                # is poisoned if any one need is skipped.
                implicit_default_jobs.add(name)
        self.assertEqual(set(), implicit_default_jobs,
                         f"Jobs with multiple unconditional needs will be silently "
                         f"skipped when any need is skipped: {implicit_default_jobs}")


if __name__ == "__main__":
    unittest.main()
