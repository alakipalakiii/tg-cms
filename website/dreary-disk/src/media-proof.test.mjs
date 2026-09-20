import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import { handleMediaProof, parseMediaProofPath } from "./media-proof.mjs";

const digest = "a".repeat(64);
const publicPath = "/media/aa/" + digest + ".jpg";
const proofPath = "/__mahoon-proof" + publicPath;
const version = "candidate-v2";
const nonce = "b".repeat(32);
const validProofQuery = `?__mahoon_proof=${version}-${nonce}`;

function makeEnv(status = 200) {
  const requests = [];
  return {
    requests,
    env: {
      ASSETS: {
        async fetch(request) {
          requests.push(request);
          return new Response(status === 200 ? "jpeg-bytes" : "Not Found", {
            status,
            headers: { "content-type": status === 200 ? "image/jpeg" : "text/plain" },
          });
        },
      },
    },
  };
}

test("valid GET maps to the same-version /media asset and attaches attribution", async () => {
  const { env, requests } = makeEnv();
  const response = await handleMediaProof(new Request("https://example.test" + proofPath), env, version);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("X-Mahoon-Worker-Version"), version);
  assert.equal(response.headers.get("content-type"), "image/jpeg");
  assert.equal(await response.text(), "jpeg-bytes");
  assert.equal(requests[0].url, "https://example.test" + publicPath);
  assert.equal(requests[0].method, "GET");
});

test("valid HEAD maps to the same asset without downloading a body", async () => {
  const { env, requests } = makeEnv();
  const response = await handleMediaProof(new Request("https://example.test" + proofPath, { method: "HEAD" }), env, version);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("X-Mahoon-Worker-Version"), version);
  assert.equal(await response.text(), "");
  assert.equal(requests[0].url, "https://example.test" + publicPath);
  assert.equal(requests[0].method, "HEAD");
});

test("cache-busted proof accepts only the version-bound internal query and strips it from ASSETS", async () => {
  const { env, requests } = makeEnv();
  const response = await handleMediaProof(
    new Request("https://example.test" + proofPath + validProofQuery, { method: "HEAD" }),
    env,
    version,
  );
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("Content-Type"), "image/jpeg");
  assert.equal(response.headers.get("X-Mahoon-Worker-Version"), version);
  assert.equal(requests[0].url, "https://example.test" + publicPath);
  assert.equal(new URL(requests[0].url).search, "");
  assert.equal(requests[0].method, "HEAD");
});

test("missing candidate asset remains a version-attributed 404", async () => {
  const { env } = makeEnv(404);
  const response = await handleMediaProof(new Request("https://example.test" + proofPath, { method: "HEAD" }), env, version);
  assert.equal(response.status, 404);
  assert.equal(response.headers.get("X-Mahoon-Worker-Version"), version);
});

test("media proof query security rejects every non-contract shape", async () => {
  const rejectedQueries = [
    "?alternate=/media/x",
    `${validProofQuery}&extra=1`,
    `${validProofQuery}&__mahoon_proof=${version}-${nonce}`,
    `?__mahoon_proof=other-version-${nonce}`,
    `?__mahoon_proof=${version}-`,
    `?__mahoon_proof=${version}-/media/${digest}.jpg`,
  ];
  for (const query of rejectedQueries) {
    const { env, requests } = makeEnv();
    const response = await handleMediaProof(new Request("https://example.test" + proofPath + query), env, version);
    assert.equal(response.status, 404, query);
    assert.equal(requests.length, 0, query);
  }
});

test("malformed, traversal, and unsupported extension paths are rejected", async () => {
  assert.deepEqual(parseMediaProofPath(proofPath), { assetPath: publicPath, extension: "jpg" });
  assert.equal(parseMediaProofPath("/__mahoon-proof/media/aa/" + digest + ".jpeg"), null);
  assert.equal(parseMediaProofPath("/__mahoon-proof/media/aa/" + digest.toUpperCase() + ".jpg"), null);
  assert.equal(parseMediaProofPath("/__mahoon-proof/media/aa/%2e%2e/" + digest + ".jpg"), null);
  const { env } = makeEnv();
  assert.equal((await handleMediaProof(new Request("https://example.test" + proofPath, { method: "POST" }), env, version)).status, 405);
  assert.equal((await handleMediaProof(new Request("https://example.test" + publicPath), env, version)), null);
});

test("worker-first config is proof-only for media", () => {
  const config = JSON.parse(fs.readFileSync(new URL("../wrangler.jsonc", import.meta.url), "utf8"));
  const routes = config.assets.run_worker_first;
  assert.ok(routes.includes("/__mahoon-proof/media/*"));
  assert.ok(!routes.includes("/media/*"));
});