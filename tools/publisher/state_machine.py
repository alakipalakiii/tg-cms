"""Fail-closed Static-only deployment state guards."""
from __future__ import annotations


def _versions(deployment: dict) -> dict[str, int]:
    items = deployment.get("versions")
    if not isinstance(items, list) or any(
        not isinstance(item, dict) or not isinstance(item.get("version_id"), str)
        or not isinstance(item.get("percentage"), int)
        for item in items
    ):
        return {}
    result = {item["version_id"]: item["percentage"] for item in items}
    return result if len(result) == len(items) else {}


def live_static_baseline(deployment: dict, expected_static_version: str) -> tuple[bool, dict]:
    observed = _versions(deployment)
    expected = {expected_static_version: 100}
    passed = bool(expected_static_version and deployment.get("id")
                  and observed.get(expected_static_version) == 100
                  and sum(observed.values()) == 100
                  and all(version == expected_static_version or percentage == 0
                          for version, percentage in observed.items()))
    return passed, {"deployment_id": deployment.get("id"), "expected": expected,
                    "observed": observed, "PASS": passed}


def static_deployment_plan(worker: str, current_static_version: str,
                           candidate_version: str) -> dict:
    if (not worker or not current_static_version or not candidate_version
            or current_static_version == candidate_version):
        raise ValueError("static deployment plan requires two distinct version IDs and a worker")
    return {
        "worker": worker,
        "baseline": {current_static_version: 100},
        "candidate_zero_percent": {current_static_version: 100, candidate_version: 0},
        "promotion": {candidate_version: 100, current_static_version: 0},
        "rollback": {current_static_version: 100, candidate_version: 0},
        "contains_ssr_version": False,
    }


def zero_percent_split(worker: str, current: dict, candidate_version: str,
                       expected_static_version: str) -> dict:
    passed, diagnostic = live_static_baseline(current, expected_static_version)
    if not passed or not candidate_version or candidate_version == expected_static_version:
        raise ValueError(f"live Static baseline mismatch: {diagnostic}")
    return {"worker": worker, "expected_current_deployment_id": current["id"],
            "current_static_version": expected_static_version,
            "candidate_version": candidate_version,
            "expected_versions": {expected_static_version: 100, candidate_version: 0}}


def promotion_precondition(zero_deployment: dict, current_static_version: str,
                           candidate_version: str) -> dict:
    expected = _versions(zero_deployment)
    passed = bool(zero_deployment.get("id")
                  and expected.get(current_static_version) == 100
                  and expected.get(candidate_version) == 0
                  and sum(expected.values()) == 100
                  and all(version in {current_static_version, candidate_version} or percentage == 0
                          for version, percentage in expected.items()))
    if not passed:
        raise ValueError("zero-percent deployment readback does not match Static baseline")
    return {"expected_current_deployment_id": zero_deployment["id"],
            "current_static_version": current_static_version,
            "candidate_version": candidate_version, "expected_versions": expected}


def verify_promotion_precondition(current: dict, anchor: dict,
                                  worker: str = "mahoon-art-magazine") -> tuple[bool, dict]:
    observed_versions = _versions(current)
    expected_versions = anchor.get("expected_versions")
    expected = {"worker": worker, "deployment_id": anchor.get("expected_current_deployment_id"),
                "versions": expected_versions}
    observed = {"worker": worker, "deployment_id": current.get("id"),
                "versions": observed_versions}
    passed = (bool(expected_versions) and current.get("id") == anchor.get("expected_current_deployment_id")
              and observed_versions == expected_versions)
    return passed, {"expected": expected, "observed": observed, "PASS": passed}


def verify_promoted_static(current: dict, candidate_version: str,
                           previous_static_version: str) -> tuple[bool, dict]:
    observed = _versions(current)
    expected = {candidate_version: 100, previous_static_version: 0}
    passed = bool(current.get("id")
                  and observed.get(candidate_version) == 100
                  and observed.get(previous_static_version) == 0
                  and sum(observed.values()) == 100
                  and all(version in {candidate_version, previous_static_version} or percentage == 0
                          for version, percentage in observed.items()))
    return passed, {"deployment_id": current.get("id"), "expected": expected,
                    "observed": observed, "PASS": passed}
