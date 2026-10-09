// Score a finished interview against the facts the simulated expert holds (persona_equipment.md).
//   node test/score.mjs cases/sim-<id>.json
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
const C = createRequire(import.meta.url)("../src/core.js");

export function score(S) {
  const SMALL = { zero: 0, one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9, ten: 10, eleven: 11, twelve: 12, thirteen: 13, fourteen: 14, fifteen: 15, sixteen: 16, seventeen: 17, eighteen: 18, nineteen: 19 };
  const TENS = { twenty: 20, thirty: 30, forty: 40, fifty: 50, sixty: 60, seventy: 70, eighty: 80, ninety: 90 };
  // Speech writes figures as words: "forty-five grand", "sixty thousand five hundred", "seven in ten".
  function norm(t) {
    t = t.toLowerCase().replace(/(\d),(\d{3})/g, "$1$2").replace(/\$/g, "");
    t = t.replace(new RegExp("\\b(" + Object.keys(TENS).join("|") + ")[- ](" + Object.keys(SMALL).slice(1, 10).join("|") + ")\\b", "g"), (m, a, b) => String(TENS[a] + SMALL[b]));
    t = t.replace(new RegExp("\\b(" + Object.keys(TENS).join("|") + ")\\b", "g"), (m, a) => String(TENS[a]));
    t = t.replace(new RegExp("\\b(" + Object.keys(SMALL).join("|") + ")\\b", "g"), (m, a) => String(SMALL[a]));
    t = t.replace(/\b(\d+) hundred(?: and)? (\d{1,2})\b/g, (m, a, b) => String(a * 100 + Number(b))).replace(/\b(\d+) hundred\b/g, (m, a) => String(a * 100));
    t = t.replace(/\b(\d+(?:\.\d+)?) ?(?:thousand|grand|k)\b(?:,? (?:and )?(\d{1,3})\b(?! ?(?:%|percent|of|in|out|days?|weeks?|months?|hours?|times)))?/g, (m, a, b) => String(Math.round(a * 1000) + (b ? Number(b) : 0)));
    return t.replace(/\bpercent\b/g, "%");
  }
  const of10 = (n) => new RegExp("\\b" + n + " ?(of|in|out of|/) ?10\\b|\\b" + n + "0 ?%");
  const FACTS = [
    ["inspection usually $550", /\b550\b/], ["inspection range $450 to $700", /\b450\b[\s\S]{0,400}\b700\b/], ["inspection catches 7 of 10", of10(7)],
    ["inspection wrongly flags 1 of 10", of10(1)], ["no records: fault 4 in 10", of10(4)], ["buyer's premium 10%", /10 ?%[^.]{0,40}premium|premium[^.]{0,40}10 ?%/],
    ["deposit forfeited", /deposit/], ["transport usually $2,400", /\b2400\b/], ["sound repairs usually $3,000", /\b3000\b/], ["bad repairs usually $20,000", /\b20000\b/],
    ["flip level about $45,000", /\b45000\b|\b45k\b/], ["inspect above $50,000", /\b50000\b|\b50k\b/], ["inspection takes 2 days to schedule", /\b2 (working |business )?days\b/],
    ["oil sample $90", /\b90\b/], ["last time: won at $60,500", /\b60500\b/], ["resale about $78,000", /\b78000\b/], ["comes up 3 times a month", /\b3 (times )?(a|per) month\b|3x/],
    ["3 in 10 sit near the line", of10(3)], ["newcomer works 6 in 10", of10(6)], ["professional: 75% of resale", /\b75 ?%/], ["professional: resale minus $12,000", /\b12000\b/],
    ["situation one at $38,000", /\b38000\b/], ["situation two at $70,000", /\b70000\b/], ["situation three at $48,000", /\b48000\b/],
    ["at most 2 inspections a week", /\b2 (inspections? )?(a|per) week\b|2 inspections/], ["inventory cap $400,000", /\b400000\b/], ["newcomer vs professional $4,000", /\b4000\b/], ["financing at 9%", /\b9 ?%/]
  ];
  const said = norm(S.transcript.filter((m) => m.role === "expert").map((m) => m.text).join("\n"));
  const filed = norm(JSON.stringify(S.caseFile) + JSON.stringify(S.numbers));
  const rows = FACTS.map(([name, re]) => ({ name, said: re.test(said), filed: re.test(filed) }));
  const saidRows = rows.filter((r) => r.said);
  // Numbers in the consultant's own questions that the expert had not yet said (10 is the "of ten" frame).
  const leading = [];
  let heard = new Set(["1", "10"]);
  for (const m of S.transcript) {
    const nums = (norm(m.text).match(/\b\d[\d.]*\b/g) || []);
    if (m.role === "expert") nums.forEach((n) => heard.add(n));
    else if (m.kind === "clarify" || (m.kind === "open" && m.text !== C.STAGES[m.stage].opening)) nums.filter((n) => !heard.has(n)).forEach((n) => leading.push({ n, text: m.text }));
  }
  // Nothing invented: every figure in the file should have been said by the expert.
  const saidNums = new Set(said.match(/\d+(?:\.\d+)?/g) || []);
  const filedText = norm(JSON.stringify(S.caseFile) + " " + S.numbers.map((q) => [q.name, q.low, q.typical, q.high, q.of_ten, q.note].join(" ")).join(" "));
  const invented = [...new Set(filedText.match(/\d+(?:\.\d+)?/g) || [])].filter((n) => !saidNums.has(n));
  const noRange = S.numbers.filter((q) => C.numberIssues(q).includes("range")).length;
  const noSource = S.numbers.filter((q) => C.numberIssues(q).includes("source")).length;
  return {
    numbers: { filed: S.numbers.length, withoutRange: noRange, withoutSource: noSource, bySource: Object.fromEntries(C.SOURCES.map((k) => [k, S.numbers.filter((q) => q.source === k).length])) },
    facts: { total: rows.length, saidByExpert: saidRows.length, filedOfSaid: saidRows.filter((r) => r.filed).length, saidNotFiled: saidRows.filter((r) => !r.filed).map((r) => r.name), neverSaid: rows.filter((r) => !r.said).map((r) => r.name), filedButNeverSaid: rows.filter((r) => r.filed && !r.said).map((r) => r.name) },
    figuresFiledButNeverSaid: invented,
    looseClaimChallenged: S.transcript.some((m) => m.role === "consultant" && /everything/i.test(m.text)) || S.gaps.some((g) => /everything/i.test(g.text)),
    leadingNumbers: leading,
    clarifyingByKind: S.transcript.filter((m) => m.kind === "clarify" && m.reason).reduce((o, m) => { o[m.reason] = (o[m.reason] || 0) + 1; return o; }, {}),
    openQuestions: S.gaps.filter((g) => g.status === "open").length
  };
}
if (process.argv[1] && process.argv[1].endsWith("score.mjs")) console.log(JSON.stringify(score(JSON.parse(readFileSync(process.argv[2], "utf8"))), null, 2));
