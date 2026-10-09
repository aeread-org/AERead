// A full interview against a simulated expert who holds a fixed set of facts.
// Measures: does every turn parse; which clarifying questions fire; how much of what the expert said is filed;
// whether the consultant ever puts a number in the expert's mouth.
import { createRequire } from "node:module";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { askClaude, MODELS } from "../backend.mjs";
import { score } from "./score.mjs";
const here = dirname(fileURLToPath(import.meta.url));
const C = createRequire(import.meta.url)("../src/core.js");
const persona = readFileSync(join(here, process.argv[2] || "persona_equipment.md"), "utf8");
const outDir = join(here, "..", "cases");
mkdirSync(outDir, { recursive: true });

const S = C.newState();
const log = { turns: 0, parseFailures: 0, forcedMoves: 0, seconds: [], clarifying: {}, perStage: {} };
const say = (s) => process.stdout.write(s + "\n");

async function expert() {
  const convo = S.transcript.filter((m) => m.kind !== "note").map((m) => {
    const rb = m.kind === "readback" && S.readback ? "\n" + S.readback.summary.join("\n") + (S.readback.contradictions.length ? "\nTwo of your answers seem to disagree: " + S.readback.contradictions.map((c) => c.a + " / " + c.b + ". " + c.ask).join(" | ") : "") + (S.readback.would_be_invented.length ? "\nNot yet clear enough to build from: " + S.readback.would_be_invented.join(" | ") : "") : "";
    return (m.role === "expert" ? "DANA: " : "INTERVIEWER: ") + m.text + (m.cover ? " " + m.cover.join("; ") : "") + rb;
  }).join("\n");
  const r = await askClaude("THE INTERVIEW SO FAR\n" + convo + "\n\nGive Dana's answer to the interviewer's last message.", { system: persona, effort: "low" });
  return r.text.trim();
}
async function consultant(prompt, opts) {
  for (let attempt = 0; attempt < 2; attempt++) {
    const r = await askClaude(prompt, opts);
    log.seconds.push(r.seconds);
    try { return C.parseJson(r.text); } catch { log.parseFailures += 1; }
  }
  throw new Error("two unreadable replies in a row");
}

while (S.stage < C.READBACK && log.turns < 90) {
  const a = await expert();
  C.addExpert(S, a, { spoken: false });
  const stageBefore = S.stage;
  let info;
  try { info = C.applyTurn(S, await consultant(C.turnPrompt(S))); }
  catch (e) { log.parseFailures += 1; say("!! " + e.message); C.skip(S); info = { advanced: true, forced: true }; }
  log.turns += 1;
  const m = S.transcript.at(-1);
  log.perStage[C.STAGES[stageBefore].id] = (log.perStage[C.STAGES[stageBefore].id] || 0) + 1;
  if (info.forced) log.forcedMoves += 1;
  if (m.kind === "clarify") log.clarifying[m.reason] = (log.clarifying[m.reason] || 0) + 1;
  say(`[${stageBefore + 1}] DANA: ${a}`);
  say(`    ${m.kind === "clarify" ? "CLARIFY(" + m.reason + ")" : "NEXT" + (info.forced ? " (forced)" : "")}: ${m.text}\n`);
}

say("--- read-back");
C.applyReadback(S, await consultant(C.readbackPrompt(S), { model: MODELS.complex, effort: "medium" }));
say(S.readback.summary.join("\n"));
say("contradictions: " + JSON.stringify(S.readback.contradictions));
const audit1 = { contradictions: S.readback.contradictions.length, wouldBeInvented: S.readback.would_be_invented.length };
log.readbackRounds = 0;
for (let round = 0; round < 6; round++) {
  const a = await expert();
  C.addExpert(S, a);
  C.applyTurn(S, await consultant(C.turnPrompt(S)));
  log.readbackRounds += 1;
  const m = S.transcript.at(-1);
  if (m.reason) log.clarifying["readback:" + m.reason] = (log.clarifying["readback:" + m.reason] || 0) + 1;
  say(`[read-back] DANA: ${a}\n    CONSULTANT(${m.reason || "corrections"}): ${m.text}\n`);
  if (!S.gaps.some((g) => g.status === "open" && g.origin === "audit")) break;
}
C.applyReadback(S, await consultant(C.readbackPrompt(S), { model: MODELS.complex, effort: "medium" }));
C.approve(S);

/* ---- scoring ---- */
const scored = score(S);
const ready = C.readiness(S);
const report = {
  turns: log.turns, parseFailures: log.parseFailures, forcedMoves: log.forcedMoves, medianSeconds: log.seconds.slice().sort((a, b) => a - b)[Math.floor(log.seconds.length / 2)],
  turnsPerPart: log.perStage, partsFiled: C.STAGES.slice(1, C.READBACK).filter((s) => C.stageStatus(S, s.id).state === "complete").map((s) => s.id),
  ...scored, firstAudit: audit1, readbackRounds: log.readbackRounds,
  finalAudit: { contradictions: S.readback.contradictions.length, wouldBeInvented: S.readback.would_be_invented.length, workedAgree: S.readback.worked_checks.map((w) => w.agrees) },
  missed: S.caseFile.notes.missed, readiness: ready.map((r) => (r.ok ? "ok   " : "open ") + r.label + (r.detail ? " | " + r.detail : ""))
};
writeFileSync(join(outDir, "sim-" + S.id + ".json"), JSON.stringify(S, null, 2));
writeFileSync(join(outDir, "sim-" + S.id + ".md"), C.toMarkdown(S));
writeFileSync(join(outDir, "sim-" + S.id + ".report.json"), JSON.stringify(report, null, 2));
say("\n=== REPORT ===\n" + JSON.stringify(report, null, 2));
say("DONE sim-" + S.id);
