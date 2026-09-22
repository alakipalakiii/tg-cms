import test from "node:test";
import assert from "node:assert/strict";
import worker, { tick } from "../src/index.mjs";

function fakeFetch(calls, response) {
  return async (url, init = {}) => {
    calls.push({ url, init });
    return { ok: true, status: response?.status ?? 200, json: async () => response?.json ?? { workflow_runs: [] } };
  };
}

test("missing secret fails closed", async () => {
  const calls = [];
  const result = await tick({}, fakeFetch(calls));
  assert.equal(result.outcome, "CREDENTIAL_SETUP_REQUIRED");
  assert.equal(calls.length, 0);
});

test("active queued or in-progress run suppresses dispatch", async () => {
  const calls = [];
  const logs = [];
  const originalLog = console.log;
  console.log = (value) => logs.push(String(value));
  const result = await tick({ GITHUB_ACTIONS_TOKEN: "test-token" }, fakeFetch(calls, {
    json: { workflow_runs: [{ status: "queued" }, { status: "in_progress" }] },
  }));
  console.log = originalLog;
  assert.equal(result.outcome, "SKIPPED_ACTIVE_TRANSACTION");
  assert.equal(calls.length, 1);
  assert.match(calls[0].init.headers.authorization, /^Bearer /);
  assert.ok(logs.every((value) => !value.includes("test-token")));
});

test("no active run dispatches exactly one AUTO_TICK to main", async () => {
  const calls = [];
  const result = await tick({ GITHUB_ACTIONS_TOKEN: "test-token" }, fakeFetch(calls, { json: { workflow_runs: [] } }));
  assert.equal(result.outcome, "AUTO_TICK_DISPATCHED");
  assert.equal(calls.length, 2);
  assert.match(calls[1].url, /dispatches$/);
  assert.deepEqual(JSON.parse(calls[1].init.body), {
    ref: "main",
    inputs: { mode: "AUTO_TICK" },
  });
});

test("public fetch surface is not an application endpoint", async () => {
  const response = await worker.fetch(new Request("https://example.com/"));
  assert.equal(response.status, 404);
});