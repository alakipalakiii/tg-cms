import { SITE } from "../config";
import { MAHOON_CATEGORIES } from "../lib/taxonomy";

export const prerender = true;

export function GET() {
  const url = SITE.url.replace(/\/+$/, "");
  const sections = MAHOON_CATEGORIES.map(({ title }) =>
    `- [${title}](${url}/category/${encodeURIComponent(title)})`
  );
  return new Response([
    `# ${SITE.name} (Mahoon Art Magazine)`,
    "",
    `> ${SITE.description}. A Persian-language magazine covering books, art, literature, film dialogue and audio.`,
    "",
    "## Start here",
    "",
    `- [صفحهٔ اصلی](${url}/): مجله و آخرین مطالب`,
    `- [آرشیو مطالب](${url}/posts): مرور مطالب منتشرشده`,
    `- [دربارهٔ ماهون](${url}/about): معرفی مجله`,
    "",
    "## Topics",
    "",
    ...sections,
    "",
    "## Published content feeds",
    "",
    `- [Sitemap](${url}/sitemap.xml): canonical article URLs and their last significant updates`,
    `- [RSS](${url}/rss.xml): recent published articles`,
    ""
  ].join("\n"), { headers: { "Content-Type": "text/plain; charset=utf-8" } });
}
