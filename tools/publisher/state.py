from __future__ import annotations

import json
from pathlib import Path


def persist_after_public_pass(directory: Path, state: dict, production_pass: bool) -> None:
    if not production_pass:
        raise RuntimeError("PUBLISHED_STATE_COMMIT_REFUSED")
    directory.mkdir(parents=True, exist_ok=True)
    for name, value in state.items():
        (directory / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
