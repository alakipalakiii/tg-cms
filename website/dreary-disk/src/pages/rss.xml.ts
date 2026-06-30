import { SITE } from "../config";
import { getPosts, parsePostContent, escapeXml } from "../lib/posts";

export async function GET({ url }: { url: URL }) {
  const baseUrl = url.origin;
  const posts = await getPosts();

  const items = posts
    .map(post => {
      const parsed = parsePostContent(post.text);
      const postUrl = `${baseUrl}/post/${encodeURIComponent(post.slug)}`;

      const title = escapeXml(parsed.title);
      const description = escapeXml(parsed.excerpt);

      const pubDate = post.created_at
        ? new Date(post.created_at.replace(" ", "T") + "Z").toUTCString()
        : new Date().toUTCString();

      return `
        <item>
          <title>${title}</title>
          <link>${escapeXml(postUrl)}</link>
          <guid>${escapeXml(postUrl)}</guid>
          <description>${description}</description>
          <pubDate>${pubDate}</pubDate>
        </item>
      `;
    })
    .join("");

  const xml = `<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0">
  <channel>
    <title>${escapeXml(SITE.name)}</title>
    <link>${escapeXml(baseUrl)}</link>
    <description>${escapeXml(SITE.description)}</description>
    <language>fa-ir</language>
    ${items}
  </channel>
</rss>`;

  return new Response(xml, {
    headers: {
      "Content-Type": "application/rss+xml; charset=utf-8"
    }
  });
}