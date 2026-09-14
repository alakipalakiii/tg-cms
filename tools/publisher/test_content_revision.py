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


if __name__ == "__main__":
    test_revision_lookup_is_one_request_and_stable()
    test_revision_lookup_fails_closed()
    print("REVISION_ENDPOINT_TESTS=PASS")
