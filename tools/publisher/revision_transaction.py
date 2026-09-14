"""Small deterministic state machine for revision-gated Publisher runs."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Any


@dataclass
class TransactionCounters:
    revision_requests: int = 1
    full_v2_exports: int = 0
    builds: int = 0
    uploads: int = 0
    deployments: int = 0
    state_updates: int = 0


def run_revision_transaction(
    current_revision: int,
    published_revision: int,
    export_snapshot: Callable[[], Any],
    build: Callable[[Any], Any],
    validate: Callable[[Any], bool],
    promote: Callable[[Any], bool],
    persist: Callable[[int], None],
) -> tuple[str, TransactionCounters]:
    counters = TransactionCounters()
    if current_revision == published_revision:
        return "NO_CHANGE", counters
    counters.full_v2_exports = 1
    snapshot = export_snapshot()
    counters.builds = 1
    build(snapshot)
    if not validate(snapshot):
        raise RuntimeError("CANDIDATE_VALIDATION_FAILED")
    if not promote(snapshot):
        raise RuntimeError("PROMOTION_FAILED")
    persist(current_revision)
    counters.state_updates = 1
    return "PUBLISHED", counters
