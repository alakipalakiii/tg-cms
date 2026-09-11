from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import urllib.request
import urllib.error
from pathlib import Path
from urllib.parse import quote
from export_v2 import export_complete

API = "https://api.mahoonartmagazine.ir/posts-full-public-v2"


def sha_cloud(data: bytes, ext: str) -> str:
    return hashlib.sha256(base64.b64encode(data) + ext.encode()).hexdigest()[:32]


def sniff_mime(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"ID3") or (len(data) > 1 and data[0] == 0xff and data[1] & 0xe0 == 0xe0):
        return "audio/mpeg"
    if data.startswith(b"OggS"):
        return "audio/ogg"
    if len(data) > 12 and data[4:8] == b"ftyp":
        return "video/mp4"
    return None


def page(post: dict, media_path: str | None) -> str:
    identity, content, seo = post["identity"], post["content"], post["seo"]
    title = content["title"]
    canonical = identity["canonical_url"]
    ld = json.dumps({"@context": "https://schema.org", "@type": "Article", "headline": title, "url": canonical}, ensure_ascii=False)
    media = (f"<audio src='{media_path}' controls></audio>" if media_path and post["media"].get("media_type") in {"audio", "voice"}
             else f"<video src='{media_path}' controls></video>" if media_path and post["media"].get("media_type") == "video"
             else f"<img src='{media_path}' alt='{html.escape(title)}'>" if media_path else "")
    return ("<!doctype html><html lang='fa' dir='rtl'><head><meta charset='UTF-8'>"
            f"<title>{html.escape(title)} | مجله هنری ماهون</title>"
            f"<meta name='description' content='{html.escape(seo['meta_description'])}'>"
            f"<meta property='og:title' content='{html.escape(title)}'><meta property='og:description' content='{html.escape(seo['meta_description'])}'>"
            f"<link rel='canonical' href='{canonical}'><script type='application/ld+json'>{ld}</script></head><body><main>"
            f"<h1>{html.escape(title)}</h1><article><p>{html.escape(content['body']).replace(chr(10), '<br>')}</p>{media}</article></main></body></html>")


def normalize(raw: dict) -> dict:
    text = str(raw.get("text") or "")
    clean = " ".join(line.strip() for line in text.splitlines() if line.strip())
    title = raw.get("seo_title") or next((line.strip() for line in text.splitlines() if line.strip()), "روایت ماهون")
    media_id = raw.get("media_file_id") or raw.get("photo_file_id")
    media_url = f"https://api.mahoonartmagazine.ir/media/{quote(str(media_id), safe='')}" if media_id else None
    mime = raw.get("media_mime_type") or ("image/jpeg" if raw.get("photo_file_id") else None)
    slug = raw.get("slug") or f"post-{raw['id']}"
    return {"identity": {"database_id": int(raw["id"]), "slug": slug, "canonical_url": "https://mahoonartmagazine.ir/post/" + quote(slug, safe=""), "created_at": raw.get("created_at")},
            "content": {"title": title, "body": text, "excerpt": clean[:160], "category": None, "tags": []},
            "media": {"current_url": media_url, "media_type": raw.get("media_type"), "mime_type": mime, "file_size": raw.get("media_size")},
            "seo": {"meta_description": raw.get("seo_description") or clean[:160]}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--media-manifest", required=True)
    parser.add_argument("--route-manifest", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    media_manifest = json.loads(Path(args.media_manifest).read_text(encoding="utf-8"))
    routes = json.loads(Path(args.route_manifest).read_text(encoding="utf-8"))
    existing_ids = {int(p.parent.name) for p in (output / "post").glob("*/index.html") if p.parent.name.isdigit()}
    payload, proof = export_complete(API)
    added = [normalize(p) for p in payload["posts"] if int(p.get("id", 0)) not in existing_ids]
    known_ids = {int(p.parent.name) for p in (output / "post").glob("*/index.html") if p.parent.name.isdigit()}
    if any(int(p.get("id", 0)) in known_ids for p in payload["posts"]):
        pass
    classifications = {"mime_canonicalized": 0, "safe_static_fallback": 0, "new_static_ready": 0}
    for post in added:
        identity, content, media = post["identity"], post["content"], post["media"]
        post_id, slug = int(identity["database_id"]), identity["slug"]
        media_path = None
        if media.get("current_url"):
            request = urllib.request.Request(media["current_url"], headers={"User-Agent": "MAHOON-M9-PUBLISHER-NEW-MEDIA/1.0"})
            try:
                with urllib.request.urlopen(request, timeout=180) as response:
                    data = response.read()
                    detected = sniff_mime(data)
                    if len(data) != media.get("file_size") or not detected:
                        raise RuntimeError("NEW_MEDIA_STATIC_LIMIT_OR_MIME_GATE_FAILED")
                    if detected != media.get("mime_type"):
                        raise RuntimeError("NEW_MEDIA_CONTENT_TYPE_CONFLICT")
                    if response.headers.get_content_type() != detected:
                        classifications["mime_canonicalized"] += 1
                    media["mime_type"] = detected
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
                classifications["safe_static_fallback"] += 1
                media_path = None
                data = None
            if data is not None:
                digest = hashlib.sha256(data).hexdigest()
                ext = "." + media["mime_type"].split("/")[-1].replace("jpeg", "jpg")
                media_path = f"/media/{digest[:2]}/{digest}{ext}"
                target = output / media_path.lstrip("/")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                media_manifest[media_path] = {"mahoon_sha256": digest, "cloudflare_hash": sha_cloud(data, ext[1:]), "size": len(data), "mime": media["mime_type"], "source": media["current_url"], "readiness": "PASS"}
                classifications["new_static_ready"] += 1
        rendered = page(post, media_path)
        for relative in (Path("post") / str(post_id) / "index.html", Path("post") / slug / "index.html"):
            target = output / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(rendered, encoding="utf-8")
        redirects = output / "_redirects"
        existing_redirects = redirects.read_text(encoding="utf-8") if redirects.exists() else ""
        redirects.write_text(existing_redirects + f"/post/{quote(slug, safe='')} /post/{post_id}/ 200\n", encoding="utf-8")
        routes["routes"].append(f"/post/{post_id}/index.html")
    Path(args.media_manifest).write_text(json.dumps(media_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    routes["routes"] = sorted(set(routes["routes"]))
    routes["route_count"] = len(routes["routes"])
    Path(args.route_manifest).write_text(json.dumps(routes, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"added_posts": [int(p["identity"]["database_id"]) for p in added], "new_media": sum(bool(p["media"].get("current_url")) for p in added), "classifications": classifications, "export": proof}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
