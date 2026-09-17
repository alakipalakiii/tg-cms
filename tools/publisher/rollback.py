from __future__ import annotations

from . import cloudflare_wrangler as deployment
from .state_machine import verify_promoted_static


def automatic_rollback(worker: str, previous_static_version: str,
                       failed_candidate_version: str, promoted_deployment_id: str,
                       preserve_zero_versions: tuple[str, ...] = ()) -> dict:
    """Restore the exact Static pair only if the failed candidate still owns traffic."""
    current = deployment.active_deployment(worker)
    passed, _ = verify_promoted_static(current, failed_candidate_version, previous_static_version)
    if not passed or current.get("id") != promoted_deployment_id:
        raise RuntimeError("ROLLBACK_LIVE_STATE_DRIFT")
    if preserve_zero_versions:
        deployment.rollback_to_previous_static(worker, previous_static_version, failed_candidate_version,
                                               preserve_zero_versions)
    else:
        deployment.rollback_to_previous_static(worker, previous_static_version, failed_candidate_version)
    expected = {previous_static_version: 100, failed_candidate_version: 0}
    expected.update({version: 0 for version in preserve_zero_versions})
    return deployment.wait_for_active(worker, expected)
