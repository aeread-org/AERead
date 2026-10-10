// Writes the skill's reference from src/core.js, so the skill and the web interviewer ask for the same case file.
//   node build_skill.mjs
import { createRequire } from "node:module";
import { writeFileSync } from "node:fs";
const C = createRequire(import.meta.url)("./src/core.js");
const out = [`# The case file (protocol ${C.VERSION})`, "",
  "Generated from `src/core.js` by `build_skill.mjs`. Do not edit by hand.", "",
  "Twelve sections. Each lists what to file, what it becomes in a built case, and what to ask when the history does not say.", ""];
for (const sec of C.SECTIONS) {
  const st = C.STAGES.find(s => s.fills.includes(sec.id));
  out.push(`## ${sec.title}`, "", `Becomes: ${sec.becomes}.`, "", `Needs: ${sec.expect}`, "");
  for (const f of sec.fields) out.push(f.type === "rows" ? `- **${f.label}** (table: ${f.cols.map(c => c[1]).join(" | ")})` : `- **${f.label}**${f.type === "list" ? " (list)" : f.type === "bool" ? " (yes or no)" : ""}`);
  if (st) out.push("", `Ask, if the history is silent: "${st.opening}"`, "", "Press on:", ...st.probe.map(p => `- ${p}`));
  out.push("");
}
const num = C.STAGES.find(s => s.id === "numbers");
out.push("## Numbers", "", `Needs: ${num.purpose}`, "", "One row per figure: name, unit, low, usual, high, source (`data`, `experience` or `guess`), note.", "", `Ask: "${num.opening}"`, "",
  "## Gap kinds", "", "Label every open question with one of these:", "", ...Object.entries(C.GAP_KINDS).map(([k, v]) => `- \`${k}\`: ${v}`), "");
writeFileSync(new URL("./skill/case-from-history/references/case-file.md", import.meta.url), out.join("\n"));
console.log("references/case-file.md", out.length, "lines");
