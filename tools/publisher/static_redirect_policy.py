"""Fail-closed generation and validation of static candidate redirects."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Mapping
from urllib.parse import unquote, urlsplit


@dataclass(frozen=True)
class RedirectRule:
    source: str
    destination: str
    status: int
    line_number: int


# An entry is intentionally required for every retained historical rule. Add
# one only when the source has a documented, current compatibility purpose.
CURRENT_COMPATIBILITY_REDIRECTS: dict[str, dict[str, object]] = {}
_SUPPORTED_STATUS = {200, 301, 302, 303, 307, 308}


def normalize_route(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        raise ValueError(f"REDIRECT_ROUTE_MUST_BE_RELATIVE:{value}")
    path = unquote(parsed.path)
    if not path.startswith("/"):
        path = "/" + path
    if "\\" in path or any(part in {".", ".."} for part in path.split("/")):
        raise ValueError(f"REDIRECT_ROUTE_INVALID_PATH:{value}")
    return path.rstrip("/") or "/"


def parse_redirects(text: str) -> list[RedirectRule]:
    rules: list[RedirectRule] = []
    for line_number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) not in {2, 3}:
            raise ValueError(f"REDIRECT_RULE_MALFORMED_LINE:{line_number}")
        source, destination = fields[:2]
        source_url = urlsplit(source)
        if source_url.query or source_url.fragment:
            raise ValueError(f"REDIRECT_SOURCE_QUERY_UNSUPPORTED_LINE:{line_number}")
        try:
            status = int(fields[2]) if len(fields) == 3 else 302
        except ValueError as exc:
            raise ValueError(f"REDIRECT_STATUS_INVALID_LINE:{line_number}") from exc
        if status not in _SUPPORTED_STATUS:
            raise ValueError(f"REDIRECT_STATUS_UNSUPPORTED_LINE:{line_number}")
        normalized_source = normalize_route(source)
        destination_url = urlsplit(destination)
        if destination_url.scheme and destination_url.scheme not in {"http", "https"}:
            raise ValueError(f"REDIRECT_DESTINATION_SCHEME_INVALID_LINE:{line_number}")
        if status == 200 and (destination_url.scheme or not destination_url.path.startswith("/")):
            raise ValueError(f"REDIRECT_PROXY_DESTINATION_INVALID_LINE:{line_number}")
        rules.append(RedirectRule(source, destination, status, line_number))
    return rules


def _source_matches(source: str, route: str) -> bool:
    pattern = normalize_route(source)
    if "*" not in pattern and not re.search(r":[A-Za-z]\w*", pattern):
        return pattern == route
    pieces: list[str] = []
    index = 0
    for match in re.finditer(r"\*|:[A-Za-z]\w*", pattern):
        pieces.append(re.escape(pattern[index:match.start()]))
        pieces.append(".*" if match.group() == "*" else "[^/]+")
        index = match.end()
    pieces.append(re.escape(pattern[index:]))
    return re.fullmatch("".join(pieces), route) is not None


def _direct_html_path(asset_root: Path, route: str) -> Path | None:
    normalized = normalize_route(route)
    if normalized in {"/robots.txt", "/rss.xml", "/sitemap.xml"}:
        return None
    relative = normalized.lstrip("/")
    if not relative:
        return asset_root / "index.html"
    return asset_root / Path(relative) / "index.html"


def _policy_entry(
    policy: Mapping[str, Mapping[str, object]], rule: RedirectRule
) -> Mapping[str, object] | None:
    for source, entry in policy.items():
        if normalize_route(source) == normalize_route(rule.source):
            if (
                entry.get("required") is True
                and str(entry.get("reason", "")).strip()
                and entry.get("destination") == rule.destination
                and entry.get("status") == rule.status
            ):
                return entry
    return None


def _matching_routes(source: str, routes: set[str]) -> set[str]:
    normalized_source = normalize_route(source)
    if "*" not in normalized_source and not re.search(r":[A-Za-z]\w*", normalized_source):
        return {normalized_source} & routes
    return {route for route in routes if _source_matches(source, route)}


def _validate_text(
    text: str,
    routes: list[str] | set[str],
    asset_root: Path,
    compatibility_policy: Mapping[str, Mapping[str, object]],
) -> dict[str, int | bool]:
    manifest_routes = {normalize_route(route) for route in routes}
    direct_html_routes = {
        route
        for route in manifest_routes
        if (asset_path := _direct_html_path(asset_root, route)) is not None and asset_path.is_file()
    }
    rules = parse_redirects(text)
    seen_sources: set[str] = set()
    shadowing = 0
    for rule in rules:
        normalized_source = normalize_route(rule.source)
        if normalized_source in seen_sources:
            raise ValueError(f"REDIRECT_DUPLICATE_SOURCE:{normalized_source}")
        seen_sources.add(normalized_source)
        matched = _matching_routes(rule.source, manifest_routes)
        shadowed = matched & direct_html_routes
        if shadowed:
            shadowing += 1
            if _policy_entry(compatibility_policy, rule) is None:
                sample = sorted(shadowed)[0]
                raise ValueError(f"CANDIDATE_REDIRECT_SHADOWS_MATERIALIZED_ROUTE:{sample}")
    return {
        "candidate_redirect_rules": len(rules),
        "candidate_shadowing_redirect_rules": shadowing,
        "STATIC_ROUTING_POLICY_PROOF": True,
    }


def validate_candidate_redirects(
    candidate_path: Path,
    routes: list[str] | set[str],
    asset_root: Path,
    compatibility_policy: Mapping[str, Mapping[str, object]] = CURRENT_COMPATIBILITY_REDIRECTS,
) -> dict[str, int | bool]:
    if not candidate_path.is_file():
        raise ValueError("CANDIDATE_REDIRECTS_MISSING")
    return _validate_text(
        candidate_path.read_text(encoding="utf-8-sig"), routes, asset_root, compatibility_policy
    )


def generate_candidate_redirects(
    historical_path: Path,
    candidate_path: Path,
    routes: list[str] | set[str],
    asset_root: Path,
    compatibility_policy: Mapping[str, Mapping[str, object]] = CURRENT_COMPATIBILITY_REDIRECTS,
) -> dict[str, int | bool]:
    if not historical_path.is_file():
        raise ValueError("HISTORICAL_REDIRECTS_MISSING")
    historical_text = historical_path.read_text(encoding="utf-8-sig")
    rules = parse_redirects(historical_text)
    manifest_routes = {normalize_route(route) for route in routes}
    direct_html_routes = {
        route
        for route in manifest_routes
        if (asset_path := _direct_html_path(asset_root, route)) is not None and asset_path.is_file()
    }
    output_rules: list[str] = []
    removed = 0
    compatibility_count = 0
    for rule in rules:
        matched = _matching_routes(rule.source, manifest_routes)
        shadowed = matched & direct_html_routes
        if shadowed:
            if matched - direct_html_routes:
                raise ValueError(f"REDIRECT_PATTERN_MIXES_MATERIALIZED_AND_COMPATIBILITY_ROUTES:{rule.source}")
            removed += 1
            continue
        if _policy_entry(compatibility_policy, rule) is None:
            raise ValueError(f"NON_SHADOWING_REDIRECT_REQUIRES_COMPATIBILITY_REASON:{rule.source}")
        compatibility_count += 1
        policy_entry = _policy_entry(compatibility_policy, rule)
        assert policy_entry is not None
        reason = " ".join(str(policy_entry["reason"]).split())
        output_rules.append(f"# Compatibility: {reason}")
        output_rules.append(f"{rule.source} {rule.destination} {rule.status}")

    generated = "# Generated from publisher-base/_redirects by static redirect policy v1.\n"
    if output_rules:
        generated += "\n".join(output_rules) + "\n"
    proof = _validate_text(generated, routes, asset_root, compatibility_policy)
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.write_text(generated, encoding="utf-8", newline="\n")
    return {
        "historical_redirect_rules_total": len(rules),
        "legacy_post_proxy_rules": sum(
            rule.status == 200
            and re.fullmatch(r"/post/[^/:*]+", normalize_route(rule.source), re.I) is not None
            and re.fullmatch(r"/post/[0-9]+/?", rule.destination, re.I) is not None
            for rule in rules
        ),
        "shadowing_proxy_rules_removed": removed,
        "shadowing_proxy_rules_remaining": proof["candidate_shadowing_redirect_rules"],
        "compatibility_rules_classified": compatibility_count,
        **proof,
    }
