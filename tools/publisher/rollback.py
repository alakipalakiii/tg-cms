from __future__ import annotations

from .deployment import rollback as restore_deployment


def automatic_rollback(previous_deployment: dict) -> dict:
    """Restore the exact captured deployment; callers must validate the result."""
    if not previous_deployment or not previous_deployment.get("versions"):
        raise RuntimeError("ROLLBACK_TARGET_MISSING")
    return restore_deployment(previous_deployment)
