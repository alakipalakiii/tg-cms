export function withVersionMetadata(response, versionId) {
  if (!versionId) return response;

  const headers = new Headers(response.headers);
  headers.set("X-Mahoon-Worker-Version", versionId);
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}
