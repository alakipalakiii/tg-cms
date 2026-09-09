"""Pure deployment state-machine guards used by the publisher transaction."""
from __future__ import annotations


def _versions(deployment: dict) -> dict[str, int]:
    return {item.get("version_id"): item.get("percentage") for item in deployment.get("versions", [])}


def rollback_anchor(deployment: dict) -> dict:
    versions = _versions(deployment)
    return {
        "rollback_deployment_id": deployment.get("id"),
        "rollback_ssr_version": next((v for v, p in versions.items() if p == 100), None),
        "rollback_static_versions": [v for v, p in versions.items() if p == 0],
        "rollback_traffic_percentages": dict(versions),
        "deployment": deployment,
    }


def promotion_precondition(deployment: dict, candidate_version: str, ssr_version: str) -> dict:
    return {
        "expected_current_deployment_id": deployment.get("id"),
        "expected_ssr_version": ssr_version,
        "expected_candidate_version": candidate_version,
        "expected_traffic": {"SSR": 100, "candidate": 0},
    }


def verify_promotion_precondition(current: dict, anchor: dict, worker: str = "mahoon-art-magazine") -> tuple[bool, dict]:
    observed_versions = _versions(current)
    expected_id = anchor.get("expected_current_deployment_id")
    expected_ssr = anchor.get("expected_ssr_version")
    expected_candidate = anchor.get("expected_candidate_version")
    expected = {
        "worker": worker,
        "deployment_id": expected_id,
        "ssr_version": expected_ssr,
        "candidate_version": expected_candidate,
        "traffic": {"SSR": 100, "candidate": 0},
    }
    nonzero_unknown = [v for v, p in observed_versions.items() if v not in {expected_ssr, expected_candidate} and p not in (0, None)]
    observed = {
        "worker": worker,
        "deployment_id": current.get("id"),
        "versions": observed_versions,
        "traffic": {"SSR": observed_versions.get(expected_ssr), "candidate": observed_versions.get(expected_candidate)},
        "unknown_nonzero_versions": nonzero_unknown,
    }
    passed = (
        current.get("id") == expected_id
        and observed_versions.get(expected_ssr) == 100
        and observed_versions.get(expected_candidate) == 0
        and not nonzero_unknown
        and len([v for v, p in observed_versions.items() if p not in (0, None)]) == 1
    )
    return passed, {"expected": expected, "observed": observed, "PASS": passed}
