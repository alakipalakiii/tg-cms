import { SITE } from "../config";

export async function GET({ url }: { url: URL }) {
  const baseUrl = SITE.url.replace(/\/+$/, "");

  const body = `User-agent: *
Allow: /

Sitemap: ${baseUrl}/sitemap.xml
`;

  return new Response(body, {
    headers: {
      "Content-Type": "text/plain; charset=utf-8"
    }
  });
}
