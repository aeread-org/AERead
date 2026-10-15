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

/* ---- voice ---- */
test("a voice turn adds to lists and tables instead of replacing them, and a matching row is updated", () => {
  const S = C.newState();
  S.stage = 4;
  C.addExpert(S, "Samples cost $250.");
  C.applyTurn(S, turn({ sections: { moves: { list: [{ name: "Samples", money: "$250" }], commit: "the purchase order" } } }), { additive: true });
  C.addExpert(S, "References are free, and samples take eight days.");
  C.applyTurn(S, turn({ sections: { moves: { list: [{ name: "references", money: "free" }, { name: "samples", time: "8 days" }], commit: "" } } }), { additive: true });
  assert.deepEqual(S.caseFile.moves.list.map((r) => [r.name, r.money, r.time]), [["Samples", "$250", "8 days"], ["references", "free", ""]]);
  assert.equal(S.caseFile.moves.commit, "the purchase order");
  C.addExpert(S, "And the build date is fixed.");
  C.applyTurn(S, turn({ sections: { variation: { fixed: ["The build date"] } } }), { additive: true });
  C.applyTurn(S, turn({ sections: { variation: { fixed: ["the build date", "Price list"] } } }), { additive: true });
  assert.deepEqual(S.caseFile.variation.fixed, ["The build date", "Price list"]);
  // A typed turn still returns whole sections and replaces lists, as before.
  C.applyTurn(S, turn({ sections: { variation: { fixed: ["Only this"] } } }));
  assert.deepEqual(S.caseFile.variation.fixed, ["Only this"]);
});

test("the NOW note carries the part, what it still needs, the cap and the next opening", () => {
  const S = C.newState();
  let note = C.voiceStatus(S);
  assert.match(note, /^NOW .*part 1 of 13, You and your work/);
  assert.match(note, /still needs: your line of work; your role/);
  assert.ok(note.includes(C.STAGES[1].opening));
  S.stage = 1;
  S.followups = C.MAX_FOLLOWUPS;
  note = C.voiceStatus(S);
  assert.match(note, /They are used up/);
  S.stage = C.READBACK - 1;
  assert.match(C.voiceStatus(S), /This is the last part/);
  S.stage = C.READBACK;
  assert.match(C.voiceStatus(S), /calling write_readback once/);
  C.applyReadback(S, C.normalizeReadback({ summary: ["You buy machines."], worked_checks: [{ situation: "one", agrees: "no" }, { situation: "two", agrees: "cannot tell" }, { situation: "three", agrees: "yes" }] }));
  assert.deepEqual(S.readback.worked_checks.map((w) => w.agrees), [false, null, true]);
  assert.match(C.voiceStatus(S), /The summary is on the expert's screen/);
});

test("the call's system prompt holds the voice rules and, for a continued interview, what was filed", () => {
  const S = C.newState();
  let p = C.voiceSystemPrompt(S);
  assert.ok(p.includes("HOW EACH TURN GOES") && p.includes("THE CASE FILE: SECTIONS AND THEIR FIELDS"));
  assert.ok(!p.includes("REPLY WITH ONLY THIS JSON OBJECT"));
  assert.ok(!p.includes("CONTINUED INTERVIEW"));
  assert.equal(C.voiceFirstMessage(S), C.INTRO + " " + C.STAGES[0].opening);
  C.addExpert(S, "I buy parts.");
  C.applyTurn(S, turn({ sections: { meta: { field: "Electronics" } }, move: "next", reply: "Pick one decision." }), { additive: true });
  p = C.voiceSystemPrompt(S);
  assert.ok(p.includes("CONTINUED INTERVIEW") && p.includes("\"field\":\"Electronics\""));
  assert.equal(C.voiceFirstMessage(S), "Let's carry on where we stopped. Pick one decision.");
  for (const t of [C.FILE_TURN_TOOL, C.READBACK_TOOL]) assert.equal(t.parameters.type, "object");
  assert.deepEqual(C.FILE_TURN_TOOL.parameters.properties.reason.enum, Object.keys(C.GAP_KINDS));
});

// The voice work shares RULES and READBACK_SPEC with the typed interview. These digests pin the typed
// prompts as they were before it, so a change to them is deliberate: update the digests when it is.
test("the typed interview's prompts are unchanged by the voice protocol", async () => {
  const { createHash } = await import("node:crypto");
  const h = (s) => createHash("sha256").update(s).digest("hex").slice(0, 16);
  const S = C.newState();
  C.addExpert(S, "I buy used excavators for a rental fleet, nine years.");
  C.applyTurn(S, { sections: { meta: { field: "equipment rental", role: "fleet buyer", experience: "nine years" } }, numbers: [], new_gaps: [], closed_gaps: [], move: "next", reply: "Pick one decision." });
  C.addExpert(S, "Whether to buy a machine at auction or from a dealer. Auction is about 15% cheaper.", { spoken: true });
  C.applyTurn(S, { sections: { decision: { decision: "auction or dealer", options: ["auction", "dealer"] } }, numbers: [{ id: "auction_discount", name: "Auction discount", unit: "%", typical: "15" }], new_gaps: [{ kind: "range", about: "auction_discount", text: "Lowest and highest discount?" }], closed_gaps: [], move: "stay", reason: "range", reply: "What is the lowest and highest discount?" });
  C.addExpert(S, "Between 5 and 30.");
  assert.equal(h(C.turnPrompt(S)), "afd9bbd36483ebca");
  assert.equal(h(C.readbackPrompt(S)), "7f4809704b8a2ccb");
  S.stage = C.READBACK;
  assert.equal(h(C.turnPrompt(S)), "7aa4e725c68700ca");
});

test("the NOW note names what to ask next, and says to move on once a part's needs are met", () => {
  const S = C.newState();
  assert.match(C.voiceStatus(S), /Ask next about: your line of work\./);
  C.addExpert(S, "Electronics buyer.");
  C.applyTurn(S, turn({ sections: { meta: { field: "Electronics", role: "Buyer" } } }), { additive: true });
  assert.match(C.voiceStatus(S), /This part's needs are met\. .*move on now/);
});

test("a voice turn's '7 in 10' as the usual value is filed as a count of ten", () => {
  const S = C.newState();
  C.addExpert(S, "It catches about seven in ten.");
  C.applyTurn(S, turn({ numbers: [{ id: "catch_rate", name: "Catch rate", typical: "about 7 in 10" }, { id: "fee", name: "Fee", typical: "550" }] }), { additive: true });
  assert.equal(S.numbers[0].of_ten, "7 of 10");
  assert.equal(S.numbers[0].typical, "");
  assert.deepEqual(C.numberIssues(S.numbers[0]).includes("range"), false);
  assert.equal(S.numbers[1].typical, "550");
});
