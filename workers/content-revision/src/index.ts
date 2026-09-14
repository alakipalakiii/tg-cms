interface Env {
  DB: D1Database;
}

const REVISION_KEY = "public_content_revision";
const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
  "Cache-Control": "no-store",
  "Content-Type": "application/json; charset=utf-8"
};

function response(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), { status, headers: CORS_HEADERS });
}

function parseRevision(value: unknown): { revision: number; changed_at: string } {
  let parsed: unknown;
  try {
    parsed = JSON.parse(String(value ?? ""));
  } catch {
    throw new Error("invalid revision");
  }
  const record = parsed as { revision?: unknown; changed_at?: unknown };
  const revision = Number(record.revision);
  const changedAt = String(record.changed_at ?? "").trim();
  if (!Number.isSafeInteger(revision) || revision < 1 || !changedAt) {
    throw new Error("invalid revision");
  }
  return { revision, changed_at: changedAt };
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS_HEADERS });
    if (request.method !== "GET" || url.pathname !== "/public/content-revision-v1") {
      return response({ error: "Not found" }, 404);
    }
    try {
      const row = await env.DB.prepare(
        "SELECT value FROM site_settings WHERE key = ? LIMIT 1"
      ).bind(REVISION_KEY).first<{ value: string }>();
      if (!row) return response({ error: "Public content revision unavailable" }, 503);
      return response(parseRevision(row.value));
    } catch {
      return response({ error: "Public content revision unavailable" }, 503);
    }
  }
};
