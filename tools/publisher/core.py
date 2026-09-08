from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


CONTRACT = "PUBLISHED_CONTENT_DELTA_CONTRACT_V2"


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def delta(previous: dict[str, str], current: dict[str, str]) -> dict[str, list[str] | str]:
    added = sorted(set(current) - set(previous))
    removed = sorted(set(previous) - set(current))
    changed = sorted(key for key in set(previous) & set(current) if previous[key] != current[key])
    return {"contract": CONTRACT, "added": added, "changed": changed, "removed": removed,
            "SAME_CONTRACT_DELTA": "PASS" if not changed and not removed else "REVIEW"}


def route_gate(routes: Iterable[str], html: dict[str, str], canonical_by_route: dict[str, str]) -> dict[str, Any]:
    expected = sorted(set(routes))
    missing = [route for route in expected if route not in html]
    duplicate_canonicals = len(canonical_by_route) - len(set(canonical_by_route.values()))
    return {"expected": len(expected), "present": len(expected) - len(missing),
            "missing": missing, "duplicate_canonicals": duplicate_canonicals,
            "PASS": not missing and duplicate_canonicals == 0}


@dataclass(frozen=True)
class PromotionGuard:
    candidate_version: str
    validation_candidate: str
    route_pass: bool
    seo_pass: bool
    media_pass: bool
    drift_none: bool
    zero_percent_proof: bool

    def allowed(self) -> bool:
        return (bool(self.candidate_version) and self.candidate_version == self.validation_candidate
                and self.route_pass and self.seo_pass and self.media_pass
                and self.drift_none and self.zero_percent_proof)


def save_state_after_promotion(path: Path, state: dict[str, Any], promoted: bool, production_pass: bool) -> None:
    if not promoted or not production_pass:
        raise RuntimeError("publisher state must not advance before successful promotion validation")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(state) + "\n", encoding="utf-8")
