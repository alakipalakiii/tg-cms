"""Fail-closed, atomic transport for sealed publisher V1 artifacts."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from publisher import artifact_contract as contracts


def read_artifact(path: str | Path, *, expected_type: str | None = None,
                  expected_transaction: Mapping[str, Any] | None = None,
                  expected_source_sha: str | None = None,
                  referenced_artifacts: Mapping[str, Any] | None = None) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise contracts.ArtifactContractError("artifact JSON is unreadable or malformed") from exc
    value = contracts.validate_artifact(
        value, expected_transaction=expected_transaction,
        expected_source_sha=expected_source_sha,
        referenced_artifacts=referenced_artifacts,
    )
    if expected_type is not None and value["artifact_type"] != expected_type:
        raise contracts.ArtifactContractError("artifact type mismatch")
    return value


def references(*artifacts: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    result = {}
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            raise contracts.ArtifactContractError("referenced artifact must be an object")
        digest = artifact.get("artifact_sha256")
        if not isinstance(digest, str):
            raise contracts.ArtifactContractError("referenced artifact has no digest")
        if digest in result and contracts.canonical_json_bytes(result[digest]) != contracts.canonical_json_bytes(artifact):
            raise contracts.ArtifactContractError("conflicting artifacts share a digest")
        result[digest] = artifact
    for digest, artifact in tuple(result.items()):
        checked = contracts.validate_artifact(artifact, referenced_artifacts=result)
        if checked["artifact_sha256"] != digest:
            raise contracts.ArtifactContractError("referenced artifact digest key mismatch")
        result[digest] = checked
    return result


def read_references(paths: list[str | Path]) -> dict[str, Mapping[str, Any]]:
    values = []
    for path in paths:
        try:
            values.append(json.loads(Path(path).read_text(encoding="utf-8")))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise contracts.ArtifactContractError("referenced artifact JSON is unreadable or malformed") from exc
    return references(*values)


def write_artifact(path: str | Path, artifact: object, *, expected_type: str | None = None,
                   referenced_artifacts: Mapping[str, Any] | None = None,
                   allow_identical: bool = False) -> dict:
    target = Path(path)
    checked = contracts.validate_artifact(artifact, referenced_artifacts=referenced_artifacts)
    if expected_type is not None and checked["artifact_type"] != expected_type:
        raise contracts.ArtifactContractError("artifact type mismatch")
    raw = contracts.canonical_json_bytes(checked) + b"\n"
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists():
        if not allow_identical:
            raise FileExistsError("destination already contains an artifact")
        existing = read_artifact(target, expected_type=expected_type,
                                 referenced_artifacts=referenced_artifacts)
        if existing["artifact_sha256"] == checked["artifact_sha256"]:
            return existing
        raise FileExistsError("destination already contains an artifact")

    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    temp = Path(temp_name)
    published_by_us = False
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        staged = read_artifact(temp, expected_type=expected_type,
                               referenced_artifacts=referenced_artifacts)
        if staged["artifact_sha256"] != checked["artifact_sha256"]:
            raise contracts.ArtifactContractError("staged artifact digest changed")
        # A hard link publishes the complete same-directory file atomically and
        # fails rather than replacing an artifact created concurrently.
        os.link(temp, target)
        published_by_us = True
        published = read_artifact(target, expected_type=expected_type,
                                  referenced_artifacts=referenced_artifacts)
        if published["artifact_sha256"] != checked["artifact_sha256"]:
            raise contracts.ArtifactContractError("published artifact digest changed")
        return published
    except Exception:
        if published_by_us and target.exists():
            try:
                if target.read_bytes() == raw:
                    target.unlink()
            except OSError:
                pass
        raise
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
