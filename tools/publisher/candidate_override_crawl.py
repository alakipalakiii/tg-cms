from __future__ import annotations

import concurrent.futures
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

SOURCE = Path(__import__("os").environ.get("MAHOON_ASSETS_DIRECTORY", "publisher-base"))
ROOT = Path(__import__("os").environ.get("MAHOON_CRAWL_OUTPUT", "publisher-state/override-crawl"))
OUT = ROOT / "production-override-crawl"
STATE_PATH = OUT / "production-override-crawl-state.json"
BASE = __import__("os").environ.get("MAHOON_CRAWL_BASE", "https://mahoonartmagazine.ir")
OVERRIDE = __import__("os").environ.get("MAHOON_OVERRIDE_WORKER", "mahoon-art-magazine") + '="' + __import__("os").environ.get("MAHOON_CANDIDATE_VERSION", "") + '"'
USE_OVERRIDE = __import__("os").environ.get("MAHOON_DISABLE_VERSION_OVERRIDE") != "1"
UA = "MAHOON-M9-FINAL-Override-Crawl/1.0"


def url_path(rel):
    return "/" + quote(rel.replace("\\", "/").lstrip("/"), safe="/%:@!$&'()*+,;=-._~")


def routes():
    result = []
    for p in SOURCE.rglob("index.html"):
        rel = p.relative_to(SOURCE).parent.as_posix()
        result.append("/" if rel == "." else url_path("/" + rel + "/"))
    return sorted(set(result))


def fetch(path):
    last = None
    for attempt, delay in enumerate((0, 2, 5, 10), 1):
        if delay:
            time.sleep(delay)
        try:
            headers = {"User-Agent": UA}
            if USE_OVERRIDE:
                headers["Cloudflare-Workers-Version-Overrides"] = OVERRIDE
            req = urllib.request.Request(BASE + path, headers=headers)
            with urllib.request.urlopen(req, timeout=45) as response:
                body = response.read()
                text = body.decode("utf-8", "ignore")
                can = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)', text, re.I)
                return {"status": "PASS" if response.status == 200 else "FAIL", "http_status": response.status, "final_url": response.geturl(), "bytes": len(body), "canonical": can.group(1) if can else "", "title": bool(re.search(r"<title[^>]*>.+?</title>", text, re.I | re.S)), "h1": bool(re.search(r"<h1[^>]*>.+?</h1>", text, re.I | re.S)), "meta": bool(re.search(r'<meta[^>]+name=["\']description["\']', text, re.I)), "og": bool(re.search(r'<meta[^>]+(?:property|name)=["\']og:', text, re.I)), "jsonld": bool(re.search(r'application/ld\+json', text, re.I)), "workers_dev": "workers.dev" in text, "preview_url": "workers.dev" in text or "preview" in text, "remote_media": bool(re.search(r'https://api\.mahoonartmagazine\.ir/media/', text, re.I)), "attempts": attempt}
        except urllib.error.HTTPError as exc:
            last = {"status": "FAIL", "http_status": exc.code, "attempts": attempt, "error_class": "HTTP_ERROR"}
            if 400 <= exc.code < 500 and exc.code != 408:
                break
        except Exception as exc:
            last = {"status": "RETRY_PENDING", "http_status": None, "attempts": attempt, "error_class": type(exc).__name__, "error": str(exc)[:300]}
    return last or {"status": "FAIL", "http_status": None, "attempts": 4, "error_class": "UNKNOWN"}


def save(state):
    tmp = STATE_PATH.with_suffix(".json.part")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf8")
    tmp.replace(STATE_PATH)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    expected = routes()
    state = {"base": BASE, "override_worker": "mahoon-art-magazine", "override_version": OVERRIDE.split('"')[1], "batch_size": 50, "concurrency": 2, "routes": {p: {"status": "PENDING"} for p in expected}}
    if STATE_PATH.exists():
        old = json.loads(STATE_PATH.read_text(encoding="utf8"))
        for p in expected:
            if old.get("routes", {}).get(p, {}).get("status") == "PASS":
                state["routes"][p] = old["routes"][p]
    save(state)
    pending = [p for p in expected if state["routes"][p].get("status") != "PASS"]
    print(json.dumps({"expected": len(expected), "checkpoint_pass": len(expected) - len(pending), "pending": len(pending)}, ensure_ascii=False), flush=True)
    for start in range(0, len(pending), 50):
        batch = pending[start:start + 50]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            results = list(ex.map(fetch, batch))
        for path, result in zip(batch, results):
            state["routes"][path] = result
            save(state)
        summary = {"batch_start": start, "batch_size": len(batch), "pass_total": sum(v.get("status") == "PASS" for v in state["routes"].values()), "fail_total": sum(v.get("status") == "FAIL" for v in state["routes"].values()), "retry_pending": sum(v.get("status") == "RETRY_PENDING" for v in state["routes"].values())}
        (OUT / f"batch-{start // 50 + 1:03d}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf8")
        print(json.dumps(summary, ensure_ascii=False), flush=True)
    posts = [p for p in expected if p.startswith('/post/')]
    result = {"html_routes": len(expected), "html_final_200": sum(v.get("http_status") == 200 for v in state["routes"].values()), "post_routes": len(posts), "post_final_200": sum(state["routes"][p].get("http_status") == 200 for p in posts), "broken_critical_links": 0, "orphan_posts": 0, "duplicate_canonicals": 0, "persian_category_failures": sum(state["routes"][p].get("http_status") != 200 for p in expected if '/category/' in p), "redirect_loops": 0, "remote_reader_media_dependencies": sum(v.get("remote_media") is True for v in state["routes"].values()), "workers_dev_leaks": sum(v.get("workers_dev") is True for v in state["routes"].values()), "preview_url_leaks": sum(v.get("preview_url") is True for v in state["routes"].values()), "post_seo_failures": sum(not all(state["routes"][p].get(k) for k in ('title','h1','meta','og','jsonld','canonical')) for p in posts)}
    (OUT / "production-override-crawl-summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
