import assert from "node:assert/strict";
import test from "node:test";
import { withVersionMetadata } from "../src/version-metadata.mjs";

test("adds the actual Cloudflare Worker version without changing status or body", async () => {
  const source = new Response("static page", {
    status: 201,
    headers: { "content-type": "text/html", "x-existing": "preserved" },
  });

  const response = withVersionMetadata(source, "candidate-version-id");

  assert.equal(response.status, 201);
  assert.equal(response.headers.get("content-type"), "text/html");
  assert.equal(response.headers.get("x-existing"), "preserved");
  assert.equal(response.headers.get("X-Mahoon-Worker-Version"), "candidate-version-id");
  assert.equal(await response.text(), "static page");
});

test("does not invent an attribution header when the metadata binding is absent", () => {
  const source = new Response("unattributed");
  assert.equal(withVersionMetadata(source, undefined), source);
  assert.equal(source.headers.get("X-Mahoon-Worker-Version"), null);
});
