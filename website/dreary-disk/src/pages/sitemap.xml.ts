import { getPosts, parsePostContent, escapeXml } from "../lib/posts";

export async function GET({ url }: { url: URL }) {
  const baseUrl = url.origin;
  const posts = await getPosts();

  const staticPages = ["", "/about", "/contact"];

  const tags = Array.from(
    new Set(
      posts.flatMap(post => parsePostContent(post.text).hashtags)
    )
  );

  const urls = [
    ...staticPages.map(path => ({
      loc: `${baseUrl}${path}`,
      priority: path === "" ? "1.0" : "0.7"
    })),

    ...posts.map(post => ({
      loc: `${baseUrl}/post/${encodeURIComponent(post.slug)}`,
      priority: "0.8"
    })),

    ...tags.map(tag => ({
      loc: `${baseUrl}/tag/${encodeURIComponent(tag)}`,
      priority: "0.6"
    }))
  ];

  const xmlUrls = urls
    .map(item => {
      return `
        <url>
          <loc>${escapeXml(item.loc)}</loc>
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