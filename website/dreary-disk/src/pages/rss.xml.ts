import { escapeXml } from "../lib/posts";
import { SITE } from "../config";

type RssPost = {
  id?: number | null;
  slug?: string | null;
  text?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  seo_title?: string | null;
  seo_description?: string | null;
  media_type?: string | null;
  media_url?: string | null;
  photo_url?: string | null;
  media_mime_type?: string | null;
  media_file_name?: string | null;
};

const siteUrl = SITE.url.replace(/\/+$/, "");
const workerUrl = SITE.workerUrl.replace(/\/+$/, "");
const rssPostsEndpoint = `${workerUrl}/seo/rss-posts?limit=50&source=site-rss`;

function cleanText(value: string | null | undefined): string {
  return String(value || "")
    .replace(/https?:\/\/[^\s]+/giu, "")
    .replace(/@[a-zA-Z0-9_]+/g, "")
    .replace(/(^|\s)#([^\s#]+)/gu, " ")
    .replace(/[â€¢â—â–ªâ–«â—¦]/g, "")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/[ \t]{2,}/g, " ")
    .trim();
}

function makeTitle(post: RssPost): string {
  if (post.seo_title) return post.seo_title;

  const firstLine = cleanText(post.text)
    .split("\n")
    .map((line) => line.trim())
    .find(Boolean);

  if (firstLine) {
    return firstLine.length <= 72 ? firstLine : `${firstLine.slice(0, 72).trim()}...`;
  }

  return `مطلب شماره ${post.id || ""}`.trim();
}

function makeDescription(post: RssPost): string {
  if (post.seo_description) return post.seo_description;

  const source = cleanText(post.text).replace(/\s+/g, " ").trim();
  if (source) {
    return source.length <= 180 ? source : `${source.slice(0, 180).trim()}...`;
  }

  return SITE.description;
}

function parseDbDate(value: string | null | undefined): Date | null {
  if (!value) return null;

  const source = value.includes("T") ? value : `${value.replace(" ", "T")}Z`;
  const date = new Date(source);

  if (Number.isNaN(date.getTime())) return null;

  return date;
}

async function getRssPosts(): Promise<RssPost[]> {
  try {
    const response = await fetch(rssPostsEndpoint, {
      method: "GET",
      headers: {
        Accept: "application/json",
        "Cache-Control": "no-cache"
      },
      cache: "no-store"
    });

    if (!response.ok) return [];

    const payload = await response.json();
    if (!payload?.ok || !Array.isArray(payload.posts)) return [];

    return payload.posts;
  } catch {
    return [];
  }
}

function latestBuildDate(posts: RssPost[]): string {
  const latestTime = posts
    .map((post) => parseDbDate(post.updated_at || post.created_at)?.getTime() || 0)
    .filter((time) => time > 0)
    .sort((a, b) => b - a)[0];

  return new Date(latestTime || Date.now()).toUTCString();
}

function renderItem(post: RssPost): string {
  const slug = String(post.slug || "").trim();
  if (!slug) return "";

  const postUrl = `${siteUrl}/post/${encodeURIComponent(slug)}`;
  const pubDate = parseDbDate(post.created_at);

  return `
    <item>
      <title>${escapeXml(makeTitle(post))}</title>
      <link>${escapeXml(postUrl)}</link>
      <guid isPermaLink="true">${escapeXml(postUrl)}</guid>
      ${pubDate ? `<pubDate>${escapeXml(pubDate.toUTCString())}</pubDate>` : ""}
      <description>${escapeXml(makeDescription(post))}</description>
    </item>
  `;
}

export async function GET() {
  const posts = await getRssPosts();
  const items = posts.map(renderItem).join("");
  const rssUrl = `${siteUrl}/rss.xml`;

  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>${escapeXml(SITE.name)}</title>
    <link>${escapeXml(siteUrl)}</link>
    <description>${escapeXml(SITE.description)}</description>
    <language>fa-IR</language>
    <lastBuildDate>${escapeXml(latestBuildDate(posts))}</lastBuildDate>
    <atom:link href="${escapeXml(rssUrl)}" rel="self" type="application/rss+xml" />
    <generator>Mahoon Art Magazine CMS</generator>
    <ttl>60</ttl>
    ${items}
  </channel>
</rss>`;

  return new Response(xml, {
    headers: {
      "Content-Type": "application/rss+xml; charset=utf-8"
    }
  });
}
