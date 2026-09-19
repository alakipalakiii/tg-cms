"""Bounded production Worker-version convergence probing."""
from __future__ import annotations

import time
from collections.abc import Callable, Iterable


def _is_success(result: dict, expected_version: str) -> bool:
    return (
        result.get("http_status") == 200
        and result.get("actual_version") == expected_version
        and result.get("version_attribution_status") == "PROVEN"
        and result.get("override_header_sent") is False
    )


def probe_convergence(
    fetch: Callable[[str, str], dict],
    routes: Iterable[str],
    expected_version: str,
    *,
    rounds_required: int = 3,
    timeout_seconds: int = 300,
    interval_seconds: int = 10,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """Require consecutive complete rounds, bounded by a hard five-minute deadline."""
    route_list = list(dict.fromkeys(routes))
    if not route_list:
        raise ValueError("convergence probe requires at least one route")
    if not expected_version:
        raise ValueError("convergence probe requires an expected version")
    rounds_required = max(1, int(rounds_required))
    timeout_seconds = min(300, max(1, int(timeout_seconds)))
    interval_seconds = max(0, int(interval_seconds))
    started = monotonic()
    deadline = started + timeout_seconds
    attempts = 0
    consecutive = 0
    max_consecutive = 0
    mismatch_samples: list[dict] = []

    while monotonic() <= deadline:
        attempts += 1
        results = [fetch(route, expected_version) for route in route_list]
        failed = [item for item in results if not _is_success(item, expected_version)]
        if not failed:
            consecutive += 1
            max_consecutive = max(max_consecutive, consecutive)
            if consecutive >= rounds_required:
                return {
                    "PASS": True,
                    "rounds": consecutive,
                    "max_consecutive_rounds": max_consecutive,
                    "attempts": attempts,
                    "seconds": round(monotonic() - started, 3),
                    "timeout_seconds": timeout_seconds,
                    "interval_seconds": interval_seconds,
                    "routes": route_list,
                    "mismatches": [],
                }
        else:
            consecutive = 0
            mismatch_samples.extend(failed[:25])
            del mismatch_samples[25:]

        remaining = deadline - monotonic()
        if remaining <= 0:
            break
        sleep(min(interval_seconds, remaining) if interval_seconds else 0)

    return {
        "PASS": False,
        "rounds": consecutive,
        "max_consecutive_rounds": max_consecutive,
        "attempts": attempts,
        "seconds": round(min(monotonic() - started, timeout_seconds), 3),
        "timeout_seconds": timeout_seconds,
        "interval_seconds": interval_seconds,
        "routes": route_list,
        "mismatches": mismatch_samples,
    }
