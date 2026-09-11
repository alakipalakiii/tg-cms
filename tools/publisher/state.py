from __future__ import annotations

import json
from pathlib import Path


def persist_after_public_pass(directory: Path, state: dict, production_pass: bool) -> None:
    if not production_pass:
        raise RuntimeError("PUBLISHED_STATE_COMMIT_REFUSED")
    directory.mkdir(parents=True, exist_ok=True)
    for name, value in state.items():
        (directory / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def persist_checked(directory: Path, state: dict, *, mode: str, promotion: bool,
                    production_validation: bool, zero_origin: bool,
                    candidate_version: str, validated_version: str,
                    candidate_fingerprint: str, validated_fingerprint: str) -> None:
    if not (mode == "PUBLISH" and promotion and production_validation and zero_origin
            and candidate_version == validated_version
            and candidate_fingerprint == validated_fingerprint):
        raise RuntimeError("PUBLISHED_STATE_CONDITION_REFUSED")
    persist_after_public_pass(directory, state, True)
