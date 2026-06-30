export async function GET({ url }: { url: URL }) {
  const baseUrl = url.origin;

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