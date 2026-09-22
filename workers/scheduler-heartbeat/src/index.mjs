const REPOSITORY = "alakipalakiii/tg-cms";
const WORKFLOW = "mahoon-static-publisher.yml";
const API_ROOT = "https://api.github.com";
const ACTIVE_STATUSES = new Set(["queued", "in_progress"]);

function headers(token) {
  return {
    accept: "application/vnd.github+json",
    authorization: `Bearer ${token}`,
    "x-github-api-version": "2026-03-10",
    "user-agent": "mahoon-scheduler-heartbeat",
  };
}

async function requestGitHub(path, token, init = {}, fetchImpl = fetch) {
  const response = await fetchImpl(`${API_ROOT}${path}`, {
    ...init,
    headers: { ...headers(token), ...(init.headers || {}) },
  });
  if (!response.ok) throw new Error(`GITHUB_API_HTTP_${response.status}`);
  return response.status === 204 ? null : response.json();
}

function activeRuns(payload) {
  return (payload?.workflow_runs || []).filter((run) => ACTIVE_STATUSES.has(run.status));
}

export async function tick(env, fetchImpl = fetch) {
  if (!env?.GITHUB_ACTIONS_TOKEN) {
    console.error("CREDENTIAL_SETUP_REQUIRED");
    return { outcome: "CREDENTIAL_SETUP_REQUIRED" };
  }

  const listPath = `/repos/${REPOSITORY}/actions/workflows/${WORKFLOW}/runs?per_page=20&exclude_pull_requests=true`;
  const response = await requestGitHub(listPath, env.GITHUB_ACTIONS_TOKEN, {}, fetchImpl);
  const active = activeRuns(response);
  if (active.length) {
    const result = { automation_source: "cloudflare_cron", outcome: "SKIPPED_ACTIVE_TRANSACTION", active_count: active.length };
    console.log(JSON.stringify(result));
    return result;
  }

  const dispatchPath = `/repos/${REPOSITORY}/actions/workflows/${WORKFLOW}/dispatches`;
  await requestGitHub(dispatchPath, env.GITHUB_ACTIONS_TOKEN, {
    method: "POST",
    body: JSON.stringify({ ref: "main", inputs: { mode: "AUTO_TICK" } }),
    headers: { "content-type": "application/json" },
  }, fetchImpl);
  const result = { automation_source: "cloudflare_cron", outcome: "AUTO_TICK_DISPATCHED" };
  console.log(JSON.stringify(result));
  return result;
}

export default {
  async fetch() {
    return new Response("Not Found", { status: 404 });
  },
  async scheduled(_controller, env) {
    await tick(env);
  },
};