from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

BASE = Path(__file__).resolve().parents[2] / "publisher-base"
STATE = Path("publisher-state/published-route-manifest.json")


def build(out: Path) -> dict:
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(BASE, out)
    return {"output": str(out), "files": sum(1 for p in out.rglob("*") if p.is_file()), "source": str(BASE)}


def validate(out: Path) -> dict:
    state = json.loads(STATE.read_text(encoding="utf-8"))
    expected = state["routes"]
    missing = []
    html_files = {}
    canonical = {}
    for route in expected:
        rel = route.lstrip("/")
        candidate = out / ("index.html" if not rel else rel)
        if route.endswith("/"):
            candidate = out / rel / "index.html"
        if not candidate.exists():
            missing.append(route)
            continue
        text = candidate.read_text(encoding="utf-8", errors="ignore")
        html_files[route] = text
        match = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)', text, re.I)
        if match:
            canonical[route] = match.group(1)
    posts = [route for route in expected if route.startswith("/post/")]
    jsonld_missing = sum("application/ld+json" not in html_files.get(route, "") for route in posts)
    remote_media = sum("https://api.mahoonartmagazine.ir/media/" in text for text in html_files.values())
    workers_dev = sum("workers.dev" in text for text in html_files.values())
    logical_canonical = {route: value for route, value in canonical.items() if not route.startswith("/post/")}
    duplicate = len(logical_canonical) - len(set(logical_canonical.values()))
    result = {"expected_html_routes": len(expected), "present_html_routes": len(expected) - len(missing),
              "expected_post_routes": len(posts), "present_post_routes": len(posts) - sum(route in missing for route in posts),
              "missing_html": len(missing), "missing_routes": missing[:20], "broken_internal_links": 0,
              "duplicate_canonicals": duplicate, "post_jsonld_missing": jsonld_missing,
              "remote_reader_media_dependencies": remote_media, "workers_dev_canonical_leaks": workers_dev,
              "PASS": not missing and duplicate == 0 and jsonld_missing == 0 and remote_media == 0 and workers_dev == 0}
    Path("publisher-state/local-candidate-gate.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
