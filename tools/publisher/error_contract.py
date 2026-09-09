"""Reserved-field-safe publisher error construction and serialization."""
from __future__ import annotations

RESERVED_FIELDS = {"stage", "code", "message", "exception_class", "timestamp", "candidate_version", "deployment_id", "path", "expected", "observed", "retry_count"}


def safe_details(details: dict) -> dict:
    return {(f"detail_{key}" if key in RESERVED_FIELDS else key): value for key, value in details.items()}


class PublisherStageError(RuntimeError):
    def __init__(self, stage: str, code: str, message: str, **details):
        super().__init__(message)
        self.stage = stage
        self.code = code
        self.message = message
        self.details = safe_details(details)


def build_error(stage: str, code: str, message: str, **details) -> PublisherStageError:
    return PublisherStageError(stage, code, message, **safe_details(details))
