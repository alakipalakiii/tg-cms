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


if __name__ == "__main__":
    unittest.main()
