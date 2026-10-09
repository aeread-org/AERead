// Local host for the Case Consultant: serves the page on localhost, where the browser allows the
// microphone, and answers the page's model calls through the Claude Code CLI on this machine.
//   node serve.mjs [--port 8787] [--data ./cases] [--model claude-sonnet-5-5] [--readback-model claude-opus-5-5]
import http from "node:http";
import { readFileSync, writeFileSync, mkdirSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { askClaude, MODELS } from "./backend.mjs";
import "./build.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const arg = (name, fallback) => { const i = process.argv.indexOf("--" + name); return i > 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback; };
const PORT = Number(arg("port", "8787"));
const DATA = resolve(arg("data", join(here, "cases")));
const MODEL = { default: arg("model", MODELS.default), complex: arg("readback-model", MODELS.complex) };
const MAX_BODY = 600 * 1024;        // a turn prompt is about 10 to 100 KB
const ID = /^[a-z0-9]{6,20}$/;
mkdirSync(DATA, { recursive: true });

function send(res, status, body, type = "application/json; charset=utf-8") {
  const data = typeof body === "string" ? body : JSON.stringify(body);
  res.writeHead(status, { "content-type": type, "cache-control": "no-store", "x-content-type-options": "nosniff" });
  res.end(data);
}
function readJson(req) {
  return new Promise((ok, fail) => {
    if (!/^application\/json/.test(req.headers["content-type"] || "")) return fail(new Error("JSON only"));
    let size = 0; const chunks = [];
    req.on("data", (c) => { size += c.length; if (size > MAX_BODY) { fail(new Error("too large")); req.destroy(); } else chunks.push(c); });
    req.on("end", () => { try { ok(JSON.parse(Buffer.concat(chunks).toString("utf8"))); } catch (e) { fail(e); } });
    req.on("error", fail);
  });
}
function listCases() {
  return readdirSync(DATA).filter((f) => f.endsWith(".json")).map((f) => { try { return JSON.parse(readFileSync(join(DATA, f), "utf8")); } catch { return null; } }).filter(Boolean);
}

const server = http.createServer(async (req, res) => {
  // Loopback only, and only when addressed as such: this endpoint spends the owner's model usage.
  const host = (req.headers.host || "").replace(/:\d+$/, "");
  if (host !== "localhost" && host !== "127.0.0.1") return send(res, 403, { error: "local use only" });
  const url = new URL(req.url, "http://localhost");
  try {
    if (req.method === "GET" && url.pathname === "/") return send(res, 200, readFileSync(join(here, "dist", "standalone.html"), "utf8"), "text/html; charset=utf-8");
    if (req.method === "GET" && url.pathname === "/api/health") return send(res, 200, { ok: true, backend: "claude-cli", models: MODEL });
    if (req.method === "GET" && url.pathname === "/api/cases") return send(res, 200, listCases());
    if (req.method === "GET" && url.pathname === "/api/case") {
      const id = url.searchParams.get("id") || "";
      if (!ID.test(id)) return send(res, 400, { error: "bad id" });
      return send(res, 200, readFileSync(join(DATA, id + ".json"), "utf8"));
    }
    if (req.method === "POST" && url.pathname === "/api/save") {
      const body = await readJson(req);
      if (!body || !ID.test(body.id || "")) return send(res, 400, { error: "bad id" });
      writeFileSync(join(DATA, body.id + ".json"), JSON.stringify(body, null, 2));
      return send(res, 200, { ok: true });
    }
    if (req.method === "POST" && url.pathname === "/api/consult") {
      const body = await readJson(req);
      if (!body || typeof body.input !== "string" || !body.input) return send(res, 400, { error: "no input" });
      const complex = body.tier === "complex";
      const out = await askClaude(body.input, { model: complex ? MODEL.complex : MODEL.default, effort: complex ? "medium" : "low" });
      console.log(new Date().toISOString().slice(11, 19), complex ? "read-back" : "turn", out.seconds.toFixed(1) + "s");
      return send(res, 200, { text: out.text, seconds: out.seconds, model: out.model });
    }
    return send(res, 404, { error: "not found" });
  } catch (e) {
    return send(res, 502, { error: String((e && e.message) || e).slice(0, 400) });
  }
});
server.listen(PORT, "127.0.0.1", () => {
  console.log("Case Consultant: http://localhost:" + PORT + "  (cases saved in " + DATA + ")");
  console.log("Use Chrome, Edge or Safari for the Speak button. Stop with Ctrl+C.");
});
