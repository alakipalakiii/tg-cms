"""Reserved-field-safe publisher error construction and serialization."""
from __future__ import annotations

RESERVED_FIELDS = {"stage", "code", "message", "details", "exception_class", "timestamp", "candidate_version", "deployment_id", "path", "expected", "observed", "retry_count"}


def safe_details(details: dict) -> dict:
    return {(f"detail_{key}" if key in RESERVED_FIELDS else key): value for key, value in details.items()}


class PublisherStageError(RuntimeError):
    def __init__(self, stage: str, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.stage = stage
        self.code = code
        self.message = message
        self.details = safe_details(details or {})


def build_error(stage: str, code: str, message: str, details: dict | None = None) -> PublisherStageError:
    return PublisherStageError(stage, code, message, details=details)
