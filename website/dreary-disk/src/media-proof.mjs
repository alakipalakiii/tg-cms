import { withVersionMetadata } from "./version-metadata.mjs";

const PROOF_PREFIX = "/__mahoon-proof/media/";
const MEDIA_PATH = /^\/media\/[0-9a-f]{2}\/[0-9a-f]{64}\.(jpg|png|gif|webp|mp3|ogg|mp4)$/;
const PROOF_QUERY = "__mahoon_proof";
const PROOF_NONCE = /^[0-9a-f]{32}$/;
const STATUS_NOT_FOUND = 404;

export function parseMediaProofPath(pathname) {
  if (!pathname.startsWith(PROOF_PREFIX) || pathname.includes("%")) return null;
  const assetPath = "/media/" + pathname.slice(PROOF_PREFIX.length);
  if (!MEDIA_PATH.test(assetPath)) return null;
  return { assetPath, extension: assetPath.slice(assetPath.lastIndexOf(".") + 1) };
}

function validProofQuery(url, versionId) {
  const entries = [...url.searchParams.entries()];
  if (entries.length === 0) return true;
  if (entries.length !== 1 || entries[0][0] !== PROOF_QUERY) return false;

  const value = entries[0][1];
  const separator = value.lastIndexOf("-");
  if (separator <= 0 || !PROOF_NONCE.test(value.slice(separator + 1))) return false;
  return !versionId || value.slice(0, separator) === versionId;
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
  if (!validProofQuery(url, versionId) || !parseMediaProofPath(url.pathname)) {
    return new Response("Not Found", { status: STATUS_NOT_FOUND });
  }

  const { assetPath } = parseMediaProofPath(url.pathname);
  const assetUrl = new URL(assetPath, url);
  assetUrl.search = "";
  const assetRequest = new Request(assetUrl, {
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