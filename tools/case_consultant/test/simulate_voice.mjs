// A full interview on the hosted voice page (dist/interview.html) in headless Chrome with a silent
// microphone. The simulated expert (persona_equipment.md, through the Claude Code CLI) types each answer
// into the page, which is the typed path of a live call; the interviewer runs on Vapi and replies by voice.
// The call is billed to the Vapi account behind the key built into the page.
//   PLAYWRIGHT_CORE=<path to node_modules/playwright-core> node test/simulate_voice.mjs [persona.md] [--port 8796] [--minutes 50]
//   --from cases/<id>.json starts from a saved interview; one saved after the last part runs only the read-back.
//   --url <address> runs against a deployed copy instead of dist/interview.html.
import http from "node:http";
import { createRequire } from "node:module";
import { readFileSync, writeFileSync, mkdirSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { askClaude } from "../backend.mjs";
import { score } from "./score.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const C = require("../src/core.js");
const { chromium } = require(process.env.PLAYWRIGHT_CORE || "playwright-core");
const arg = (name, fallback) => { const i = process.argv.indexOf("--" + name); return i > 0 ? process.argv[i + 1] : fallback; };
const personaFile = process.argv[2] && !process.argv[2].startsWith("--") ? process.argv[2] : "persona_equipment.md";
const persona = readFileSync(join(here, personaFile), "utf8");
const PORT = Number(arg("port", "8796"));
const LIMIT = Date.now() + Number(arg("minutes", "50")) * 60000;
const outDir = join(here, "..", "cases");
mkdirSync(outDir, { recursive: true });
const say = (s) => process.stdout.write(s + "\n");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// A silent microphone: the expert types, so the call hears nothing.
const wav = join(mkdtempSync(join(tmpdir(), "voice-sim-")), "silence.wav");
{
  const n = 16000 * 600, b = Buffer.alloc(44 + n * 2);
  b.write("RIFF", 0); b.writeUInt32LE(36 + n * 2, 4); b.write("WAVE", 8); b.write("fmt ", 12); b.writeUInt32LE(16, 16); b.writeUInt16LE(1, 20); b.writeUInt16LE(1, 22);
  b.writeUInt32LE(16000, 24); b.writeUInt32LE(32000, 28); b.writeUInt16LE(2, 32); b.writeUInt16LE(16, 34); b.write("data", 36); b.writeUInt32LE(n * 2, 40);
  writeFileSync(wav, b);
}
const html = readFileSync(join(here, "..", "dist", "interview.html"));
const server = http.createServer((req, res) => {
  if (req.url === "/" || req.url.startsWith("/?")) { res.writeHead(200, { "content-type": "text/html; charset=utf-8" }); return res.end(html); }
  res.writeHead(404); res.end();
}).listen(PORT, "127.0.0.1");

const browser = await chromium.launch({ executablePath: process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: true,
  args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--use-file-for-fake-audio-capture=" + wav, "--autoplay-policy=no-user-gesture-required"] });
const ctx = await browser.newContext({ permissions: ["microphone"] });
const page = await ctx.newPage();
const FROM = arg("from", "");
const saved = FROM ? JSON.parse(readFileSync(FROM, "utf8")) : null;
if (saved) { saved.readback = null; saved.approved = null; }
await page.addInitScript((st) => {
  try {
    localStorage.setItem("case-consultant:debug", "1");
    if (st && !sessionStorage.getItem("loaded")) { localStorage.setItem("case-consultant:state:v1", st); sessionStorage.setItem("loaded", "1"); }
  } catch { /* none */ }
}, saved ? JSON.stringify(saved) : null);
const consoleLines = [];
page.on("console", (m) => consoleLines.push(m.type() + " " + m.text()));
page.on("pageerror", (e) => { consoleLines.push("PAGEERROR " + e.message); say("PAGEERROR " + e.message); });
await page.goto(arg("url", "http://localhost:" + PORT + "/"));   // --url https://aeread.org/interview tests the live page

const state = () => page.evaluate(() => JSON.parse(localStorage.getItem("case-consultant:state:v1") || "null"));
const callStatus = () => page.evaluate(() => { const el = document.querySelector(".call .txt"); return el ? el.textContent : null; });
const log = { turns: 0, stalls: 0, latency: [], filing: [], perStage: {}, clarifying: {}, asides: 0 };

// Wait until the interviewer has filed a reply after `count` transcript entries and finished saying it.
// The page speaks the reply once it is filed, so wait for speech after filing, then a short silence.
async function waitForTurn(count, maxMs = 90000) {
  const t0 = Date.now();
  let spokeAt = 0, filedAt = 0, quietSince = 0, downSince = 0;
  while (Date.now() - t0 < maxMs) {
    const [S, st] = [await state(), await callStatus()];
    const now = Date.now();
    if (S && S.transcript.length > count && S.transcript.at(-1).role === "consultant" && !filedAt) filedAt = now;
    if (st === "Speaking") { if (!spokeAt) spokeAt = now; quietSince = 0; }
    else if (st === "Listening") { if (!quietSince) quietSince = now; }
    else quietSince = 0;
    if (filedAt && quietSince && now - quietSince > 1200 && ((spokeAt && spokeAt >= filedAt - 3000) || now - filedAt > 12000)) return { S, spoke: spokeAt ? (spokeAt - t0) / 1000 : null, filed: (filedAt - t0) / 1000 };
    if (st === null) {
      // The page reconnects after a dropped line; only a call that stays down has ended.
      if (!downSince) downSince = now;
      if (now - downSince > 20000 && S && S.transcript.length > count) return { S, ended: true };
    } else downSince = 0;
    await sleep(300);
  }
  log.stalls += 1;
  return { S: await state(), stalled: true };
}
async function expert(S) {
  const convo = S.transcript.filter((m) => m.kind !== "note").map((m) => {
    const rb = m.kind === "readback" && S.readback ? "\n" + S.readback.summary.join("\n") + (S.readback.contradictions.length ? "\nTwo of your answers seem to disagree: " + S.readback.contradictions.map((c) => c.a + " / " + c.b + ". " + c.ask).join(" | ") : "") + (S.readback.would_be_invented.length ? "\nNot yet clear enough to build from: " + S.readback.would_be_invented.join(" | ") : "") : "";
    return (m.role === "expert" ? "DANA: " : "INTERVIEWER: ") + m.text + rb;
  }).join("\n");
  const r = await askClaude("THE INTERVIEW SO FAR\n" + convo + "\n\nGive Dana's answer to the interviewer's last message.", { system: persona, effort: "low" });
  return r.text.trim();
}
async function answer(S) {
  const a = await expert(S);
  await page.fill("textarea.input", a);
  await page.press("textarea.input", "Enter");
  return a;
}

let S;
if (saved && saved.stage >= C.READBACK) {
  await page.click("text=Write the summary");
  S = await state();
  say("started at the read-back of " + saved.id);
} else {
  await page.click("button.talk");
  const first = await waitForTurn(saved ? saved.transcript.length - 1 : 1, 60000);   // the spoken introduction and first question
  S = first.S;
  say("call up; first question: " + S.transcript.at(-1).text);
}

while (S.stage < C.READBACK && log.turns < 90 && Date.now() < LIMIT) {
  const stageBefore = S.stage, before = S.transcript.length;
  const a = await answer(S);
  const t = await waitForTurn(before + 1);
  if (t.ended) { say("!! the call ended"); break; }
  S = t.S;
  log.turns += 1;
  if (t.spoke != null) log.latency.push(t.spoke);
  if (t.filed != null) log.filing.push(t.filed);
  log.perStage[C.STAGES[stageBefore].id] = (log.perStage[C.STAGES[stageBefore].id] || 0) + 1;
  const m = S.transcript.at(-1);
  if (m.kind === "clarify") log.clarifying[m.reason] = (log.clarifying[m.reason] || 0) + 1;
  if (m.kind === "aside") log.asides += 1;
  say(`[${stageBefore + 1}] DANA: ${a}`);
  say(`    ${m.kind === "clarify" ? "CLARIFY(" + m.reason + ")" : m.kind === "aside" ? "ASIDE" : "NEXT"} ${t.spoke != null ? t.spoke.toFixed(1) + "s" : ""}${t.stalled ? " (stalled)" : ""}: ${m.text}\n`);
}

// The read-back: the page asks for it once the closing reply has been spoken.
const waitReadback = async (after) => {
  const t0 = Date.now();
  while (Date.now() - t0 < 180000) { const s = await state(); if (s && s.readback && s.readback.at !== after && (await callStatus()) === "Listening") return s; await sleep(1000); }
  return null;
};
say(S.stage < C.READBACK ? "--- stopped before the read-back" : "--- read-back");
const rbStart = Date.now();
if (S.stage >= C.READBACK) S = (await waitReadback(null)) || (await state());
log.readbackSeconds = (Date.now() - rbStart) / 1000;
const audit1 = S.readback ? { contradictions: S.readback.contradictions.length, wouldBeInvented: S.readback.would_be_invented.length } : null;
if (S.readback) say(S.readback.summary.join("\n"));
log.readbackRounds = 0;
for (let round = 0; round < 4 && S.readback && Date.now() < LIMIT; round++) {
  const before = S.transcript.length;
  const a = await answer(S);
  const t = await waitForTurn(before + 1);
  S = t.S;
  log.readbackRounds += 1;
  const m = S.transcript.at(-1);
  say(`[read-back] DANA: ${a}\n    CONSULTANT(${m.reason || m.kind}): ${m.text}\n`);
  if (!S.gaps.some((g) => g.status === "open" && g.origin === "audit")) break;
}
const clicked = (sel) => page.click(sel, { timeout: 60000 }).then(() => true, () => { say("!! could not press " + sel); return false; });
if (S.readback && S.readback.stale) {
  const at = S.readback.at;
  if (await clicked("text=Rewrite the summary with your corrections")) S = (await waitReadback(at)) || (await state());
}
if (S.readback && (await clicked("text=This is right"))) await sleep(9000);
S = await state();
if (await callStatus()) { await page.click("button.chip.end").catch(() => {}); await sleep(3000); }

const scored = score(S);
const report = {
  channel: "voice (typed answers into a live Vapi call)", turns: log.turns, stalls: log.stalls, asides: log.asides,
  secondsToSpeech: { median: log.latency.slice().sort((a, b) => a - b)[Math.floor(log.latency.length / 2)], max: Math.max(...log.latency) },
  secondsToFiled: { median: log.filing.slice().sort((a, b) => a - b)[Math.floor(log.filing.length / 2)] },
  readbackSeconds: log.readbackSeconds, turnsPerPart: log.perStage, clarifying: log.clarifying,
  partsFiled: C.STAGES.slice(1, C.READBACK).filter((s) => C.stageStatus(S, s.id).state === "complete").map((s) => s.id),
  ...scored, firstAudit: audit1, readbackRounds: log.readbackRounds, approved: !!S.approved,
  finalAudit: S.readback ? { contradictions: S.readback.contradictions.length, wouldBeInvented: S.readback.would_be_invented.length, workedAgree: S.readback.worked_checks.map((w) => w.agrees) } : null,
  readiness: C.readiness(S).map((r) => (r.ok ? "ok   " : "open ") + r.label + (r.detail ? " | " + r.detail : "")),
};
writeFileSync(join(outDir, "sim-voice-" + S.id + ".json"), JSON.stringify(S, null, 2));
writeFileSync(join(outDir, "sim-voice-" + S.id + ".md"), C.toMarkdown(S));
writeFileSync(join(outDir, "sim-voice-" + S.id + ".report.json"), JSON.stringify(report, null, 2));
writeFileSync(join(outDir, "sim-voice-" + S.id + ".console.txt"), consoleLines.join("\n"));
say("\n=== REPORT ===\n" + JSON.stringify(report, null, 2));
say("DONE sim-voice-" + S.id);
await browser.close();
server.close();
