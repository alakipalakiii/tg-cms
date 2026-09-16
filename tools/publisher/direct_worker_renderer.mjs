import readline from "node:readline";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { unstable_dev } from "../../website/dreary-disk/node_modules/wrangler/wrangler-dist/cli.js";

const project = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../website/dreary-disk");
const worker = await unstable_dev(path.join(project, "dist/server/entry.mjs"), {
  config: path.join(project, "wrangler.jsonc"),
  compatibilityDate: process.env.MAHOON_LOCAL_RUNTIME_COMPATIBILITY_DATE || "2026-04-22",
  dev: { remote: false, persist: false, inspector: false, logLevel: "none" },
  sendMetrics: false,
});

const input = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
for await (const line of input) {
  if (!line.trim()) continue;
  try {
    const route = JSON.parse(line);
    const response = await worker.fetch(`http://mahoon.local${route}`);
    process.stdout.write(`${JSON.stringify({ route, status: response.status, html: await response.text() })}\n`);
  } catch (error) {
    process.stdout.write(`${JSON.stringify({ error: String(error) })}\n`);
  }
}
await worker.stop();
