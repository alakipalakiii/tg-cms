import { escapeXml } from "../lib/posts";
import { SITE } from "../config";
import { IS_LOCKED_SNAPSHOT_BUILD, LOCKED_SNAPSHOT_POSTS } from "../lib/lockedSnapshot";
import { toSeoIsoDate } from "../lib/seoSchema";
import { MAHOON_CATEGORIES } from "../lib/taxonomy";

type SitemapPost = {
  slug?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

async function getSitemapPosts(): Promise<SitemapPost[] | null> {
  if (IS_LOCKED_SNAPSHOT_BUILD) return LOCKED_SNAPSHOT_POSTS;
  const workerUrl = SITE.workerUrl.replace(/\/+$/, "");
  try {
    const response = await fetch(`${workerUrl}/seo/sitemap-posts?limit=1000&source=site-sitemap`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal: AbortSignal.timeout(5000)
    });
    if (!response.ok) return null;
    const payload = await response.json();
    return payload?.ok && Array.isArray(payload.posts) ? payload.posts : null;
  } catch {
    return null;
  }
}

export async function GET() {
  const posts = await getSitemapPosts();
  if (!posts) return new Response("Sitemap temporarily unavailable", { status: 503, headers: { "Retry-After": "120" } });

  const baseUrl = SITE.url.replace(/\/+$/, "");
  const urls = new Map<string, string | undefined>();
  const categories = MAHOON_CATEGORIES.map(({ title }) => `/category/${encodeURIComponent(title)}`);
  for (const path of ["/", "/posts", "/about", "/contact", ...categories]) {
    urls.set(`${baseUrl}${path}`, undefined);
  }
  for (const post of posts) {
    const slug = String(post.slug || "").trim();
    if (!slug) continue;
    const loc = `${baseUrl}/post/${encodeURIComponent(slug)}`;
    const lastmod = toSeoIsoDate(post.updated_at) || toSeoIsoDate(post.created_at);
    if (!urls.has(loc) || (lastmod && lastmod > (urls.get(loc) || ""))) urls.set(loc, lastmod);
  }
  const entries = Array.from(urls, ([loc, lastmod]) =>
    `  <url><loc>${escapeXml(loc)}</loc>${lastmod ? `<lastmod>${escapeXml(lastmod)}</lastmod>` : ""}</url>`
  ).join("\n");
  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${entries}
</urlset>`;

  return new Response(xml, { headers: { "Content-Type": "application/xml; charset=utf-8" } });
}
