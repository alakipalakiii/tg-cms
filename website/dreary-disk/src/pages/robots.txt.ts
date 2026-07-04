import { SITE } from "../config";

export async function GET() {
  const baseUrl = SITE.url.replace(/\/+$/, "");

  const body = `User-agent: *
Allow: /
Disallow: /admin
Disallow: /admin/

Sitemap: ${baseUrl}/sitemap.xml
`;

  return new Response(body, {
    headers: {
      "Content-Type": "text/plain; charset=utf-8"
    }
  });
}
