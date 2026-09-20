import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";

const sourcePath = "tools/publisher/static_version_main.js";
const source = await readFile(sourcePath, "utf8");
const workerSource = source
  .replace(
    '"../../website/dreary-disk/src/media-proof.mjs"',
    JSON.stringify(pathToFileURL("website/dreary-disk/src/media-proof.mjs").href),
  )
  .replace(
    '"../../website/dreary-disk/src/version-metadata.mjs"',
    JSON.stringify(pathToFileURL("website/dreary-disk/src/version-metadata.mjs").href),
  );
const { default: staticWorker } = await import(
  `data:text/javascript,${encodeURIComponent(workerSource)}`
);

const VERSION = "candidate-entrypoint-test-version";
const MEDIA_PATH = "/media/af/af961ddbe4c051211d454e91ea15230662129bc469ef6a366da517cc70e96bc0.jpg";
const PROOF_PATH = "/__mahoon-proof" + MEDIA_PATH;

function makeEnv(assetResponse, seenRequests) {
  return {
    CF_VERSION_METADATA: { id: VERSION },
    ASSETS: {
      fetch(request) {
        seenRequests.push(request);
        return Promise.resolve(assetResponse(request));
      },
    },
  };
}

test("proof GET maps to the public media asset and preserves the body", async () => {
  const seen = [];
  const body = "proof-body";
  const response = await staticWorker.fetch(
    new Request("https://example.test" + PROOF_PATH),
    makeEnv(() => new Response(body, { status: 200, headers: { "Content-Type": "image/jpeg" } }), seen),
  );

  assert.equal(response.status, 200);
  assert.equal(response.headers.get("X-Mahoon-Worker-Version"), VERSION);
  assert.equal(response.headers.get("Content-Type"), "image/jpeg");
  assert.equal(await response.text(), body);
  assert.equal(seen.length, 1);
  assert.equal(new URL(seen[0].url).pathname, MEDIA_PATH);
  assert.equal(seen[0].method, "GET");
});

test("proof HEAD maps to the public media asset and keeps HEAD", async () => {
  const seen = [];
  const response = await staticWorker.fetch(
    new Request("https://example.test" + PROOF_PATH, { method: "HEAD" }),
    makeEnv(() => new Response(null, { status: 200, headers: { "Content-Type": "image/jpeg" } }), seen),
  );

  assert.equal(response.status, 200);
  assert.equal(response.headers.get("X-Mahoon-Worker-Version"), VERSION);
  assert.equal(seen.length, 1);
  assert.equal(new URL(seen[0].url).pathname, MEDIA_PATH);
  assert.equal(seen[0].method, "HEAD");
  assert.equal(await response.text(), "");
});

test("missing mapped media remains 404 and carries the version header", async () => {
  const seen = [];
  const response = await staticWorker.fetch(
    new Request("https://example.test" + PROOF_PATH),
    makeEnv(() => new Response("missing", { status: 404 }), seen),
  );

  assert.equal(response.status, 404);
  assert.equal(response.headers.get("X-Mahoon-Worker-Version"), VERSION);
  assert.equal(seen.length, 1);
  assert.equal(new URL(seen[0].url).pathname, MEDIA_PATH);
});

test("normal routes preserve the original asset request and version metadata", async () => {
  for (const path of ["/", "/posts", "/media/example.jpg"]) {
    const seen = [];
    const request = new Request("https://example.test" + path);
    const response = await staticWorker.fetch(
      request,
      makeEnv(() => new Response("normal", { status: 200 }), seen),
    );

    assert.equal(response.status, 200);
    assert.equal(response.headers.get("X-Mahoon-Worker-Version"), VERSION);
    assert.equal(seen.length, 1);
    assert.equal(seen[0], request);
  }
});
