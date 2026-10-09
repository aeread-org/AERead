import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
const C = createRequire(import.meta.url)("../src/core.js");

const turn = (o) => Object.assign({ sections: {}, numbers: [], new_gaps: [], closed_gaps: [], move: "stay", reason: "missing", reply: "And then?" }, o);

test("a new case opens on part one with a scripted question", () => {
  const S = C.newState();
  assert.equal(S.stage, 0);
  assert.equal(S.transcript.at(-1).text, C.STAGES[0].opening);
  assert.equal(C.awaiting(S), false);
  assert.equal(C.STAGES.length, 14);
  assert.equal(C.READBACK, 13);
});

test("every part's opening avoids the banned jargon and every section has an object it becomes", () => {
  const banned = /\b(environment|simulation|agent|model|policy|parameter|observation|reward|benchmark|schema)\b/i;
  for (const s of C.STAGES) { assert.ok(!banned.test(s.opening), s.id); for (const c of s.cover) assert.ok(!banned.test(c), s.id + ": " + c); }
  for (const s of C.SECTIONS) assert.ok(s.becomes.length > 10 && s.expect.length > 10, s.id);
});

test("filing merges a section and a blank never erases what was filed", () => {
  const S = C.newState();
  C.addExpert(S, "I buy parts.");
  C.applyTurn(S, turn({ sections: { meta: { field: "Electronics", role: "Buyer", experience: "11 years" } }, move: "next", reply: "Tell me about one decision." }));
  assert.equal(S.stage, 1);
  C.addExpert(S, "more");
  C.applyTurn(S, turn({ sections: { meta: { field: "", role: "Head of purchasing" }, bogus: { x: 1 } } }));
  assert.equal(S.caseFile.meta.field, "Electronics");
  assert.equal(S.caseFile.meta.role, "Head of purchasing");
  assert.equal(S.caseFile.bogus, undefined);
});

test("clarifying questions are capped per part, and what the part still needs is carried as open questions", () => {
  const S = C.newState();
  S.stage = 1;
  for (let i = 0; i < C.MAX_FOLLOWUPS; i++) { C.addExpert(S, "hmm"); const info = C.applyTurn(S, turn({ reason: "vague" })); assert.equal(info.advanced, false); }
  assert.equal(S.followups, C.MAX_FOLLOWUPS);
  assert.match(C.turnPrompt((C.addExpert(S, "still vague"), S)), /They are used up/);
  const info = C.applyTurn(S, turn({ reply: "One more?" }));
  assert.deepEqual(info, { advanced: true, forced: true });
  assert.equal(S.stage, 2);
  assert.equal(S.transcript.at(-1).text, C.STAGES[2].opening, "a forced move asks the scripted opening");
  assert.ok(S.gaps.some((g) => g.status === "open" && /One real decision/.test(g.text)));
});

test("numbers are upserted by id and flagged until they have a range and a source", () => {
  const S = C.newState();
  C.addExpert(S, "a sample costs 250");
  C.applyTurn(S, turn({ numbers: [{ id: "Sample Cost", name: "Sample test", unit: "USD", typical: 250 }] }));
  assert.equal(S.numbers[0].id, "sample_cost");
  assert.deepEqual(C.numberIssues(S.numbers[0]), ["range", "source"]);
  C.addExpert(S, "200 to 300, from invoices");
  C.applyTurn(S, turn({ numbers: [{ id: "sample_cost", low: "200", high: "300", source: "data" }, { id: "fee", typical: "30%", fixed: "yes", source: "rumour" }] }));
  assert.equal(S.numbers.length, 2);
  assert.equal(S.numbers[0].typical, "250");
  assert.deepEqual(C.numberIssues(S.numbers[0]), []);
  assert.deepEqual(C.numberIssues(S.numbers[1]), ["source"], "an unknown source word is not accepted");
});

test("a malformed reply throws and leaves the case untouched", () => {
  const S = C.newState();
  C.addExpert(S, "x");
  const before = JSON.stringify(S);
  assert.throws(() => C.applyTurn(S, { sections: { meta: { field: "X" } }, reply: "" }));
  assert.throws(() => C.applyTurn(S, "nope"));
  assert.equal(JSON.stringify(S), before);
});

test("part status is computed from the file", () => {
  const S = C.newState();
  assert.equal(C.stageStatus(S, "reveals").state, "empty");
  S.caseFile.reveals.list = [{ move: "Sample test", comes_back: "pass or fail", catches: "7 of 10", false_alarms: "", wait: "", gamed: "" }];
  const st = C.stageStatus(S, "reveals");
  assert.equal(st.state, "partial");
  assert.match(st.missing[0], /good cases of ten "Sample test" wrongly flags/);
  S.caseFile.reveals.list[0].false_alarms = "1 of 10";
  S.caseFile.reveals.list.push({ move: "Call the rep", comes_back: "little", catches: "", false_alarms: "", wait: "", gamed: "" });
  assert.equal(C.stageStatus(S, "reveals").state, "complete", "a step that is not a test needs no error rates");
});

test("without a model the same parts run as a worksheet", () => {
  const S = C.newState();
  S.mode = "worksheet";
  C.addExpert(S, "I buy parts."); C.worksheetStep(S);
  assert.equal(S.transcript.at(-1).kind, "check");
  C.addExpert(S, "nothing to add"); C.worksheetStep(S);
  assert.equal(S.stage, 1);
  assert.match(C.toMarkdown(S), /Answers as given/);
});

test("read-back, corrections and approval", () => {
  const S = C.newState();
  S.stage = C.READBACK;
  assert.throws(() => C.applyReadback(S, { summary: [] }));
  C.applyReadback(S, { summary: ["Here is what I understood."], contradictions: [{ a: "catches everything", b: "7 of 10", ask: "Which?" }], worked_checks: [{ situation: "A", stated_choice: "bid", rule_says: "inspect", agrees: false, note: "n" }], would_be_invented: ["x"] });
  assert.equal(S.transcript.at(-1).kind, "readback");
  C.approve(S);
  assert.ok(S.approved);
  C.addExpert(S, "actually it is 6 of 10");
  C.applyTurn(S, turn({ reply: "Changed. Anything else?" }));
  assert.equal(S.approved, null, "a correction withdraws the approval");
  assert.equal(S.readback.stale, true);
  const r = C.readiness(S);
  assert.equal(r.find((x) => /disagree/.test(x.label)).ok, false);
  assert.deepEqual(S.gaps.filter((g) => g.origin === "audit").map((g) => g.kind), ["contradiction", "missing"], "audit findings become open questions");
  C.applyReadback(S, { summary: ["Again."] });
  assert.equal(S.gaps.filter((g) => g.origin === "audit" && g.status === "open").length, 0, "a rewrite retires the earlier audit's questions");
  assert.match(C.toMarkdown(S), /## Audit/);
});

test("tolerant JSON and the streamed reply", () => {
  assert.deepEqual(C.parseJson("Sure:\n```json\n{\"a\":1}\n```"), { a: 1 });
  assert.deepEqual(C.parseJson("x {\"a\":{\"b\":2}} y"), { a: { b: 2 } });
  assert.throws(() => C.parseJson("no json"));
  assert.equal(C.partialReply('{"move":"stay","reply":"Out of ten, how m'), "Out of ten, how m");
  assert.equal(C.partialReply('{"reply":"He said \\"no\\" and\\'), 'He said "no" and');
  assert.equal(C.partialReply('{"move":"stay"'), "");
});

test("the numbers part asks about figures that lack a range or a source, with its own cap", () => {
  const S = C.newState();
  S.stage = C.STAGES.findIndex((s) => s.id === "numbers");
  S.numbers.push({ id: "sample_cost", name: "Sample test", unit: "USD", low: "", typical: "250", high: "", of_ten: "", fixed: "", source: "", note: "" });
  S.numbers.push({ id: "fee", name: "Cancel fee", unit: "%", low: "", typical: "30", high: "", of_ten: "", fixed: "yes", source: "data", note: "" });
  const st = C.stageStatus(S, "numbers");
  assert.equal(st.state, "partial");
  assert.deepEqual(st.missing, ['the lowest and the highest of "Sample test" (said: 250)', 'where "Sample test" comes from']);
  assert.equal(C.capFor(C.STAGES[S.stage]), 6);
  assert.match(C.turnPrompt((C.addExpert(S, "x"), S)), /Clarifying questions used in this part: 0 of 6/);
  C.skip(S);
  assert.equal(C.STAGES[S.stage].id, "missed");
  assert.equal(S.gaps.filter((g) => g.status === "open").length, 1, "one summary question, not one per figure");
});
