import { escapeXml } from "../lib/posts";
import { SITE } from "../config";

type SitemapPost = {
  id?: number;
  slug?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

const workerUrl = SITE.workerUrl.replace(/\/+$/, "");
const sitemapPostsEndpoint = `${workerUrl}/seo/sitemap-posts?limit=1000&source=site-sitemap`;

function hasValidSlug(post: SitemapPost): boolean {
  return Boolean(String(post.slug || "").trim());
}

function validDate(value: string | null | undefined): string | null {
  if (!value) return null;

  const date = new Date(value.replace(" ", "T"));
  if (Number.isNaN(date.getTime())) return null;

  return date.toISOString();
}

async function getSitemapPosts(): Promise<SitemapPost[]> {
  try {
    const response = await fetch(sitemapPostsEndpoint, {
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
  } catch (error) {
    console.error("Mahoon sitemap posts error:", error);
    return [];
  }
}

export async function GET() {
  const baseUrl = SITE.url.replace(/\/+$/, "");
  const posts = await getSitemapPosts();

  const staticPages = ["", "/about", "/contact"];

  const urls = [
    ...staticPages.map(path => ({
      loc: `${baseUrl}${path}`,
      priority: path === "" ? "1.0" : "0.7"
    })),

    ...posts
      .filter(hasValidSlug)
      .map(post => ({
        loc: `${baseUrl}/post/${encodeURIComponent(String(post.slug))}`,
        lastmod: validDate(post.updated_at || post.created_at),
        priority: "0.8"
      }))
  ];

  const xmlUrls = urls
    .map(item => {
      return `
        <url>
          <loc>${escapeXml(item.loc)}</loc>
          ${item.lastmod ? `<lastmod>${escapeXml(item.lastmod)}</lastmod>` : ""}
          <changefreq>daily</changefreq>
          <priority>${item.priority}</priority>
        </url>
      `;
    })
    .join("");

  const xml = `<?xml version="1.0" encoding="UTF-8" ?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  ${xmlUrls}
</urlset>`;

  return new Response(xml, {
    headers: {
      "Content-Type": "application/xml; charset=utf-8"
    }
  });
}
