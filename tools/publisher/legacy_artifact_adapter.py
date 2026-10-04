"""Read-only adapters for historical publisher artifacts during V1 migration."""
from __future__ import annotations

import copy
from typing import Any, Mapping


LEGACY_TYPES = frozenset({
    "transaction.json",
    "bundle-index.json",
    "remote-proof-result.json",
    "production-result.json",
})


class LegacyArtifactError(ValueError):
    pass


def adapt_legacy_read_only(name: str, value: Mapping[str, Any]) -> dict:
    """Wrap legacy data for historical reconciliation; never grants authority."""
    if name not in LEGACY_TYPES:
        raise LegacyArtifactError("unsupported legacy artifact")
    if not isinstance(value, Mapping):
        raise LegacyArtifactError("legacy artifact must be an object")
    return {
        "legacy_type": name,
        "authority": "READ_ONLY",
        "may_authorize_mutation": False,
        "may_authorize_replay": False,
        "may_authorize_ready_to_persist": False,
        "may_authorize_completed": False,
        "data": copy.deepcopy(dict(value)),
    }


def assert_no_new_path_authority(adapted: Mapping[str, Any]) -> None:
    expected = {
        "authority": "READ_ONLY",
        "may_authorize_mutation": False,
        "may_authorize_replay": False,
        "may_authorize_ready_to_persist": False,
        "may_authorize_completed": False,
    }
    if any(adapted.get(key) != value for key, value in expected.items()):
        raise LegacyArtifactError("legacy artifact cannot authorize new-path state")
