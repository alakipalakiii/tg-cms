from __future__ import annotations

from content_revision import fetch_public_content_revision


def test_revision_lookup_is_one_request_and_stable() -> None:
    calls = []

    def fake_fetcher(url):
        calls.append(url)
        return {"revision": 10, "changed_at": "2026-09-14T13:00:00Z"}, {"status": 200}

    revision, changed_at, _meta = fetch_public_content_revision("https://revision.test", fake_fetcher)
    assert revision == 10
    assert changed_at == "2026-09-14T13:00:00Z"
    assert calls == ["https://revision.test"]
    assert len(calls) == 1


def test_revision_lookup_fails_closed() -> None:
    def fake_fetcher(_url):
        return {"revision": "10", "changed_at": "2026-09-14T13:00:00Z"}, {"status": 200}

    try:
        fetch_public_content_revision("https://revision.test", fake_fetcher)
    except RuntimeError as error:
        assert str(error) == "PUBLIC_CONTENT_REVISION_CONTRACT_INVALID"
    else:
        raise AssertionError("invalid revision contract was accepted")


def test_sqlite_timestamp_is_normalized_to_utc() -> None:
    def fake_fetcher(_url):
        return {"revision": 99, "changed_at": "2026-10-04 21:26:00"}, {"status": 200}

    revision, changed_at, _meta = fetch_public_content_revision("https://revision.test", fake_fetcher)
    assert revision == 99
    assert changed_at == "2026-10-04T21:26:00+00:00"


def test_invalid_changed_at_values_fail_closed() -> None:
    for changed_at in (
        "2026-10-04T21:26:00",
        "",
        "2026-02-30 21:26:00",
        " 2026-10-04T21:26:00Z",
        123,
    ):
        def fake_fetcher(_url, value=changed_at):
            return {"revision": 99, "changed_at": value}, {"status": 200}

        try:
            fetch_public_content_revision("https://revision.test", fake_fetcher)
        except RuntimeError as error:
            assert str(error) == "PUBLIC_CONTENT_REVISION_CONTRACT_INVALID"
        else:
            raise AssertionError(f"invalid changed_at was accepted: {changed_at!r}")


if __name__ == "__main__":
    test_revision_lookup_is_one_request_and_stable()
    test_revision_lookup_fails_closed()
    test_sqlite_timestamp_is_normalized_to_utc()
    test_invalid_changed_at_values_fail_closed()
    print("REVISION_ENDPOINT_TESTS=PASS")
