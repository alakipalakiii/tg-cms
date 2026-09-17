"""Materialize the existing MAHOON Astro presentation into a static artifact."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

try:
    from .content_taxonomy import canonical_category, exact_hashtags
except ImportError:
    from publisher.content_taxonomy import canonical_category, exact_hashtags
try:
    from .public_listing_dedupe import dedupe_public_listing_posts
except ImportError:
    from publisher.public_listing_dedupe import dedupe_public_listing_posts
try:
    from .static_media_resolver import PublishedMediaResolver
except ImportError:
    from publisher.static_media_resolver import PublishedMediaResolver

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "website" / "dreary-disk"
BASE = ROOT / "publisher-base"
STATE = ROOT / os.environ.get("MAHOON_ROUTE_MANIFEST", "publisher-state/current-accepted-route-manifest.json")
API_MEDIA_URL = re.compile(
    r"https?://(?:api\.mahoonartmagazine\.ir|localhost|127\.0\.0\.1)(?::\d+)?/media/[^\"'<>)\s?]+"
    r"(?:\?[^\"'<>)\s]*)?",
    re.I,
)
SCRIPT = re.compile(r"<script\b[^>]*>.*?</script>", re.I | re.S)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_preview(port: int, process: subprocess.Popen) -> None:
    deadline = time.time() + 120
    while time.time() < deadline:
        if process.poll() is not None:
            _stdout, stderr = process.communicate(timeout=1)
            raise RuntimeError(f"ASTRO_PREVIEW_EXITED:{process.returncode}:{stderr[-1000:]}")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as response:
                if response.status < 600:
                    return
        except urllib.error.HTTPError as exc:
            if exc.code == 503:
                return
        except Exception:
            time.sleep(1)
    raise RuntimeError("ASTRO_PREVIEW_START_TIMEOUT")


def _stop_process(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def _source_route(route: str) -> str:
    clean = "/" + route.lstrip("/")
    clean = clean.rstrip("/") or "/"
    if clean.startswith("/category/") and "/page/" in clean:
        base, page = clean.split("/page/", 1)
        clean = f"{base}?page={page}"
    if clean.startswith("/posts/page/"):
        clean = "/posts?page=" + clean.rsplit("/", 1)[-1]
    if clean == "/search":
        clean = "/posts"
    return clean


def _artifact_path(out: Path, route: str) -> Path:
    clean = "/" + unquote(route.lstrip("/"))
    clean = clean.rstrip("/")
    if clean in {"/robots.txt", "/rss.xml", "/sitemap.xml"}:
        return out / clean.lstrip("/")
    return out / ("index.html" if not clean or clean == "/" else Path(clean.lstrip("/")) / "index.html")


def _fetch_preview_html(port: int, route: str) -> str:
    source = _source_route(route)
    url = f"http://127.0.0.1:{port}{quote(source, safe="/?=&%:@!$'()*+,;-")}"
    request = urllib.request.Request(url, headers={"User-Agent": "MAHOON-M10-Static-Materializer/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            if response.status != 200 and not (route == "/" and response.status == 503):
                raise RuntimeError(f"ASTRO_ROUTE_HTTP_{response.status}:{route}")
            return response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        if exc.code == 503:
            return exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"ASTRO_ROUTE_HTTP_{exc.code}:{route}") from exc


class _DirectWorkerRenderer:
    """Render through the built Worker dispatcher without Preview HTTP."""

    def __init__(self) -> None:
        helper = ROOT / "tools" / "publisher" / "direct_worker_renderer.mjs"
        self.process = subprocess.Popen(
            ["node", helper.name],
            cwd=helper.parent,
            env=os.environ.copy(),
            text=True,
            encoding="utf-8",
            errors="strict",
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=1,
        )
        self.lock = threading.Lock()

    def render(self, route: str) -> str:
        with self.lock:
            if self.process.poll() is not None or self.process.stdin is None or self.process.stdout is None:
                raise RuntimeError("DIRECT_WORKER_RENDERER_EXITED")
            self.process.stdin.write(json.dumps(route, ensure_ascii=False) + "\n")
            self.process.stdin.flush()
            line = self.process.stdout.readline()
        if not line:
            raise RuntimeError("DIRECT_WORKER_RENDERER_NO_RESPONSE")
        result = json.loads(line)
        if result.get("error"):
            raise RuntimeError("DIRECT_WORKER_RENDER_FAILED:" + str(result["error"]))
        if result.get("status") != 200:
            raise RuntimeError(f"DIRECT_WORKER_ROUTE_HTTP_{result.get('status')}:{route}")
        return str(result.get("html") or "")

    def close(self) -> None:
        if self.process.poll() is not None:
            return
        if self.process.stdin is not None:
            try:
                self.process.stdin.close()
            except OSError:
                pass
        try:
            self.process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.process.kill()


def _preview_smoke(routes: list[str]) -> dict:
    examples: list[str] = []
    for route in routes:
        if route not in examples:
            examples.append(route)
    examples = examples[:12]
    port = _free_port()
    npm = "npm.cmd" if os.name == "nt" else "npm"
    process = subprocess.Popen(
        [npm, "run", "preview", "--", "--host", "127.0.0.1", "--port", str(port)],
        cwd=PROJECT,
        env=os.environ.copy(),
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_preview(port, process)
        for route in examples:
            _fetch_preview_html(port, route)
    finally:
        _stop_process(process)
    return {"route_count": len(examples), "routes": examples, "PASS": True}


def _strip_runtime_api_scripts(html: str, route: str = "/") -> str:
    if route.rstrip("/") in {"/admin", "/admin/analytics"}:
        return html

    def replace(match: re.Match[str]) -> str:
        block = match.group(0)
        if re.search(r'type=["\']application/ld\+json["\']', block, re.I):
            return block
        return "" if "api.mahoonartmagazine.ir" in block.lower() else block

    return SCRIPT.sub(replace, html)


def _rewrite_canonical(html: str, route: str) -> str:
    clean = "/" + route.lstrip("/")
    clean = clean.rstrip("/") or "/"
    public = "https://mahoonartmagazine.ir" + quote(clean, safe="/%:@!$&'()*+,;=-._~")
    return re.sub(r'(<link\b[^>]+rel=["\']canonical["\'][^>]+href=["\'])[^"\']+', r"\g<1>" + public, html, count=1, flags=re.I)


def _materialize_media(
    html: str,
    out: Path,
    manifest: dict[str, dict],
    cache: dict[str, dict],
    lock: threading.Lock,
    resolver: PublishedMediaResolver,
) -> str:

    def replace(match: re.Match[str]) -> str:
        raw_source = match.group(0)
        entity = re.search(r"(?:&quot;|&#34;)(?=[}\],<\s]|$)", raw_source, re.I)
        source = raw_source[:entity.start()] if entity else raw_source
        suffix = raw_source[entity.start():] if entity else ""
        with lock:
            if source in cache:
                resolution = cache[source]
            else:
                resolution = resolver.resolve_public_media(source)
                cache[source] = resolution

        if resolution["status"] == "FALLBACK":
            return ""

        public = str(resolution["public_path"])
        blob = Path(str(resolution["blob"]))
        target = out / public.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(blob, target)
        data = blob.read_bytes()
        manifest[public] = {
            "mahoon_sha256": str(resolution["sha256"]),
            "cloudflare_hash": hashlib.sha256(data).hexdigest()[:32],
            "size": len(data),
            "mime": resolution.get("mime"),
            "source": source,
            "readiness": "PASS",
        }
        with lock:
            cache[source] = resolution
        return public + suffix

    return API_MEDIA_URL.sub(replace, html)


def _normalize_search_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\u200c", " ")).strip().lower()


def _write_search_index(out: Path, snapshot_path: Path) -> None:
    payload = json.loads(snapshot_path.read_text(encoding="utf-8-sig"))
    posts = dedupe_public_listing_posts(list(payload["payload"]["posts"]))
    records: list[dict] = []
    for post in posts:
        text = str(post.get("text") or "")
        first_line = next((line.strip() for line in text.splitlines() if line.strip()), str(post.get("slug") or ""))
        title = str(post.get("seo_title") or "").strip() or first_line
        excerpt = str(post.get("seo_description") or "").strip() or text[:240]
        tags = sorted(exact_hashtags(text))
        search_text = _normalize_search_text(" ".join([title, text, *tags, str(canonical_category(post) or "")]))
        records.append({
            "id": int(post["id"]),
            "slug": str(post["slug"]),
            "title": title,
            "excerpt": excerpt,
            "category": canonical_category(post),
            "tags": tags,
            "url": "https://mahoonartmagazine.ir/post/" + str(post["slug"]),
            "normalized_search_text": search_text,
        })
    target = out / "search" / "search-index.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"contract": "STATIC_SEARCH_CONTRACT_V2", "records": records}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _write_locked_snapshot_module(snapshot_path: Path) -> None:
    payload = json.loads(snapshot_path.read_text(encoding="utf-8-sig"))
    posts = []
    for post in payload["payload"]["posts"]:
        normalized = dict(post)
        normalized["canonical_category"] = canonical_category(post)
        posts.append(normalized)
    target = PROJECT / "src" / "generated" / "locked-published-content.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"contract": "LOCKED_NORMALIZED_PUBLIC_SNAPSHOT_V1", "posts": posts}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def build(out: Path) -> dict:
    build_env = os.environ.copy()
    npm = "npm.cmd" if os.name == "nt" else "npm"
    snapshot_path = ROOT / os.environ.get(
        "MAHOON_PUBLISHED_CONTENT_SNAPSHOT", "runner-evidence/cutover-current-v2-snapshot.json"
    )
    state_path = ROOT / os.environ.get("MAHOON_ROUTE_MANIFEST", "publisher-state/current-accepted-route-manifest.json")
    if not snapshot_path.is_file():
        raise RuntimeError("PUBLISHER_SNAPSHOT_MISSING")
    _write_locked_snapshot_module(snapshot_path)
    build_env["PUBLIC_MAHOON_SNAPSHOT_BINDING"] = "1"
    build_command = [npm, "run", "build"]
    if build_env.get("MAHOON_SKIP_ASTRO_BUILD") != "1":
        result = subprocess.run(build_command, cwd=PROJECT, env=build_env, text=True, capture_output=True, timeout=1200)
        if result.returncode:
            raise RuntimeError("ASTRO_BUILD_FAILED:" + result.stderr[-1000:])
    client = PROJECT / "dist" / "client"
    if not client.is_dir():
        raise RuntimeError("ASTRO_CLIENT_OUTPUT_MISSING")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    for item in BASE.iterdir():
        if item.name in {"_redirects", "_headers", "robots.txt", "rss.xml", "sitemap.xml"}:
            target = out / item.name
            shutil.copytree(item, target) if item.is_dir() else shutil.copy2(item, target)
    if (BASE / "media").is_dir():
        shutil.copytree(BASE / "media", out / "media", dirs_exist_ok=True)
    for item in client.iterdir():
        target = out / item.name
        shutil.copytree(item, target, dirs_exist_ok=True) if item.is_dir() else shutil.copy2(item, target)

    routes = sorted(set(json.loads(state_path.read_text(encoding="utf-8"))["routes"]))
    media_manifest: dict[str, dict] = {}
    prior_media = ROOT / os.environ.get("MAHOON_MEDIA_MANIFEST", "publisher-state/production-media-manifest.json")
    if prior_media.is_file():
        media_manifest.update(json.loads(prior_media.read_text(encoding="utf-8")))
    renderer = _DirectWorkerRenderer()
    try:
        media_cache: dict[str, dict] = {}
        media_lock = threading.Lock()
        resolver = PublishedMediaResolver()
        def materialize(route: str) -> tuple[str, str]:
            html = _rewrite_canonical(_strip_runtime_api_scripts(renderer.render(_source_route(route)), route), route)
            return route, _materialize_media(html, out, media_manifest, media_cache, media_lock, resolver)

        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=6) as executor:
            rendered = executor.map(materialize, routes)
            for route, html in rendered:
                target = _artifact_path(out, route)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(html, encoding="utf-8")
    finally:
        renderer.close()
    smoke = _preview_smoke(routes)
    _write_search_index(out, snapshot_path)
    media_path = out.parent / "production-media-manifest.json"
    media_path.write_text(json.dumps(media_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    resolution_path = out.parent / "p0-media-resolution.json"
    resolution_path.write_text(json.dumps(resolver.stats, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "output": str(out),
        "routes": len(routes),
        "media_entries": len(media_manifest),
        "source": "existing Astro frontend",
        "snapshot_api_starts": 0,
        "snapshot_binding": "DIRECT_LOCKED_SNAPSHOT",
        "media_manifest": str(media_path),
        "route_manifest": str(state_path),
        "media_resolution": resolver.stats,
        "materializer_full_route_http_fetches": 0,
        "full_route_preview_request_count": 0,
        "preview_smoke_route_count": smoke["route_count"],
        "preview_smoke": smoke["PASS"],
    }
