import { withVersionMetadata } from "./version-metadata.mjs";

const PROOF_PREFIX = "/__mahoon-proof/media/";
const MEDIA_PATH = /^\/media\/[0-9a-f]{2}\/[0-9a-f]{64}\.(jpg|png|gif|webp|mp3|ogg|mp4)$/;
const STATUS_NOT_FOUND = 404;

export function parseMediaProofPath(pathname) {
  if (!pathname.startsWith(PROOF_PREFIX) || pathname.includes("%")) return null;
  const assetPath = "/media/" + pathname.slice(PROOF_PREFIX.length);
  if (!MEDIA_PATH.test(assetPath)) return null;
  return { assetPath, extension: assetPath.slice(assetPath.lastIndexOf(".") + 1) };
}

export async function handleMediaProof(request, env, versionId) {
  const url = new URL(request.url);
  if (!url.pathname.startsWith(PROOF_PREFIX)) return null;
  if (request.method !== "GET" && request.method !== "HEAD") {
    return new Response("Method Not Allowed", {
      status: 405,
      headers: { Allow: "GET, HEAD" },
    });
  }
  if (url.search || !parseMediaProofPath(url.pathname)) {
    return new Response("Not Found", { status: STATUS_NOT_FOUND });
  }

  const { assetPath } = parseMediaProofPath(url.pathname);
  const assetRequest = new Request(new URL(assetPath, url), {
    method: request.method,
    headers: request.headers,
  });
  const assetResponse = await env.ASSETS.fetch(assetRequest);
  const response = new Response(request.method === "HEAD" ? null : assetResponse.body, {
    status: assetResponse.status,
    statusText: assetResponse.statusText,
    headers: assetResponse.headers,
  });
  return withVersionMetadata(response, versionId);
}
