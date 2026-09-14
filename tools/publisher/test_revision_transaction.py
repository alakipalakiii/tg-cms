from __future__ import annotations

from revision_transaction import run_revision_transaction


def test_no_change_stops_before_export() -> None:
    calls = []
    status, counters = run_revision_transaction(
        10, 10,
        lambda: calls.append("export"),
        lambda _snapshot: calls.append("build"),
        lambda _snapshot: True,
        lambda _snapshot: True,
        lambda _revision: calls.append("persist"),
    )
    assert status == "NO_CHANGE"
    assert calls == []
    assert counters.revision_requests == 1
    assert counters.full_v2_exports == 0
    assert counters.builds == 0
    assert counters.uploads == 0
    assert counters.deployments == 0
    assert counters.state_updates == 0


def test_changed_revision_reuses_one_snapshot() -> None:
    calls = []
    snapshot = {"revision": 10}
    status, counters = run_revision_transaction(
        10, 9,
        lambda: calls.append("export") or snapshot,
        lambda value: calls.append(("build", value)),
        lambda value: calls.append(("validate", value)) or True,
        lambda value: calls.append(("promote", value)) or True,
        lambda revision: calls.append(("persist", revision)),
    )
    assert status == "PUBLISHED"
    assert calls == [
        "export",
        ("build", snapshot),
        ("validate", snapshot),
        ("promote", snapshot),
        ("persist", 10),
    ]
    assert counters.full_v2_exports == 1
    assert counters.builds == 1
    assert counters.state_updates == 1


def test_fail_closed_keeps_state_unchanged() -> None:
    persisted = []
    try:
        run_revision_transaction(
            11, 10,
            lambda: {"revision": 11},
            lambda _snapshot: None,
            lambda _snapshot: False,
            lambda _snapshot: True,
            persisted.append,
        )
    except RuntimeError as error:
        assert str(error) == "CANDIDATE_VALIDATION_FAILED"
    else:
        raise AssertionError("candidate failure was not fail-closed")
    assert persisted == []


def test_mid_build_revision_remains_pending_for_next_run() -> None:
    persisted = []
    current = {"revision": 10}

    def export() -> dict:
        snapshot = {"revision": current["revision"]}
        current["revision"] = 11
        return snapshot

    status, _counters = run_revision_transaction(
        10, 9, export, lambda _snapshot: None, lambda _snapshot: True,
        lambda _snapshot: True, persisted.append,
    )
    assert status == "PUBLISHED"
    assert persisted == [10]
    assert current["revision"] == 11
    next_status, next_counters = run_revision_transaction(
        current["revision"], persisted[-1], lambda: {"revision": 11},
        lambda _snapshot: None, lambda _snapshot: True,
        lambda _snapshot: True, persisted.append,
    )
    assert next_status == "PUBLISHED"
    assert next_counters.full_v2_exports == 1
    assert persisted == [10, 11]


if __name__ == "__main__":
    test_no_change_stops_before_export()
    test_changed_revision_reuses_one_snapshot()
    test_fail_closed_keeps_state_unchanged()
    test_mid_build_revision_remains_pending_for_next_run()
    print("NOCHANGE_TEST=PASS")
    print("CHANGE_TRANSACTION_TEST=PASS")
    print("FAIL_CLOSED_REVISION_TESTS=PASS")
    print("MID_TRANSACTION_REVISION_TEST=PASS")
