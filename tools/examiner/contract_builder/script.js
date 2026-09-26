"use strict";
const D = JSON.parse(document.getElementById("data").textContent);
const K = D.constants;
const TERMS = D.terms;
const $ = (id) => document.getElementById(id);
// Embedded in the examiner, the page is told which world to open and may be sent a cell to check; alone, it reads the hash.
let INIT = {};
try { INIT = JSON.parse($("init").textContent); } catch (e) { INIT = {}; }
const EMBED = !!INIT.embedded && window.parent !== window;
const tell = (m) => { if (EMBED) window.parent.postMessage(m, "*"); };
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
let CELL = null;

const TERM_TEXT = {
  warranty: "Who pays a compatibility defect's fix, and its delay",
  damages: "Delay damages per week of defect delay, under fix + delay",
  liability_cap: "The most the integrator pays in one delivery",
  readiness: "Who pays standby if the facility is late",
  consequential: "Who carries a post-handover incident's loss",
  deposit: "Share of the hardware paid at signing",
  escrow: "The deposit held safe until delivery",
  burn_in: "A week's acceptance burn-in before handover",
};
const CELL_TEXT = {
  cheapest_is_not_best: "Cheapest is not best", buy_the_cover: "Buy the cover", keep_the_liability: "Keep the liability",
  take_the_cap: "Take the cap", just_enough_damages: "Just enough damages", protect_the_deposit: "Protect the deposit",
  buy_the_burn_in: "Buy the burn-in", hand_over_readiness: "Hand over readiness", raise_the_damages: "Raise the damages",
  sign_now: "Sign now", walk_away: "Walk away",
};
const SHORTCUT_TEXT = { cheapest_listed: "cheapest listed offer", base: "base contract", every_protection: "every protection" };
const PLAYBOOK_TEXT = { coordination: "Coordination", managed: "Managed", turnkey: "Turnkey" };

function levelText(k, v) {
  if (k === "warranty") return { none: "none", fix: "fix", fix_and_delay: "fix + delay" }[v];
  if (k === "damages") return `$${v}k/wk`;
  if (k === "liability_cap") return v === "uncapped" ? "uncapped" : `$${Number(v).toLocaleString()}k`;
  if (k === "escrow" || k === "burn_in") return v === "true" ? "yes" : "no";
  return v;
}
function k$(x) {
  const r = Math.round(x * 10) / 10 || 0; // no "−0"
  const s = Math.abs(r - Math.round(r)) < 0.05 ? Math.round(r).toLocaleString() : r.toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  return `$${s}k`;
}
function signed$(x) { return (x > 0.05 ? "+" : x < -0.05 ? "−" : "±") + k$(Math.abs(x)).replace("$", "$"); }
function pct(p) { return p >= 0.1 ? `${(p * 100).toFixed(1)}%` : p >= 0.001 ? `${(p * 100).toFixed(2)}%` : `${(p * 100).toFixed(3)}%`; }

// contracts: objects keyed by term, looked up by their normal form
const MENUS = {};
for (const [pb, rows] of Object.entries(D.menus)) {
  const list = rows.map((row) => Object.fromEntries(TERMS.map((k, i) => [k, String(row[i])])));
  const index = new Map(list.map((c, i) => [key(c), i]));
  MENUS[pb] = { list, index };
}
function key(c) { return TERMS.map((k) => c[k]).join("|"); }
const strs = (c) => Object.fromEntries(TERMS.map((k) => [k, String(c[k])]));
const cellIndex = () => (CELL && CELL.signed && CELL.world === W.id ? M.index.get(key(normal(strs(CELL.signed)))) : undefined);
function normal(c) {
  const n = { ...c };
  if (n.warranty !== "fix_and_delay") n.damages = "100";
  if (n.deposit === "none") n.escrow = "false";
  return n;
}

let W = null, M = null, cur = 0;
const total = (i) => W.th[W.th.length - 1][i] + W.cc[i];
const isFee = () => W.playbook !== "turnkey";

// ---- world picker
const sel = $("world");
const byCell = {};
D.worlds.forEach((w, i) => (byCell[w.cell] = byCell[w.cell] || []).push(i));
for (const [cell, idx] of Object.entries(byCell)) {
  const g = document.createElement("optgroup");
  g.label = CELL_TEXT[cell];
  for (const i of idx) {
    const w = D.worlds[i], o = document.createElement("option");
    o.value = String(i);
    o.textContent = `${CELL_TEXT[cell]} · ${PLAYBOOK_TEXT[w.playbook]} · ${w.id}`;
    g.appendChild(o);
  }
  sel.appendChild(g);
}
sel.addEventListener("change", () => setWorld(Number(sel.value)));

function setWorld(i, keepCell) {
  W = D.worlds[i]; M = MENUS[W.playbook];
  sel.value = String(i);
  if (!keepCell) CELL = null;
  const ci = cellIndex();
  cur = ci !== undefined ? ci : D.bases[W.playbook];
  renderWorld(); renderTermsPanel(); render();
  tell({ cbWorld: W.id });
}

function renderWorld() {
  const r = W.risks, c = W.client, t = W.type;
  $("lesson").textContent = `${CELL_TEXT[W.cell]}: ${W.lesson}.`;
  const chips = [
    [`${PLAYBOOK_TEXT[W.playbook]} playbook, ${M.list.length} contracts on its menu`, "accent"],
    [`client pays $${(1 + c.charge).toFixed(2)} per $1 of risk it carries`, ""],
    [`integrator: pre-staging costs ${k$(t.test_cost)}, risk charge ${t.risk_charge} (hidden from the client)`, "hidden-fact"],
    [`break-off ${pct(W.terms.breakoff)} after each refusal`, ""],
    [`better outside option: ${W.outside.best === "turnkey" ? "rival turnkey" : "self-manage"}`, ""],
  ];
  $("world-chips").innerHTML = chips.map(([s, cls]) => `<span class="chip ${cls}">${s}</span>`).join("");
  $("facts").textContent =
    `Defect ${pct(r.defect_without_test)} (${pct(r.defect_with_test)} if the integrator pre-stages), fix ${k$(r.defect_fix)}, ${r.defect_weeks} weeks late. ` +
    `Facility late ${pct(r.unready)} (${pct(r.unready * K.site_prep_effect)} once the site is prepared, which costs the integrator ${k$(W.extras.site_prep)}), standby ${k$(r.standby)}, ${r.unready_weeks} weeks. ` +
    `Incident ${pct(r.incident)}, loss ${k$(r.incident_loss)}. Each week late costs the client ${k$(c.delay)}. ` +
    `Integrator failure while holding a deposit ${pct(c.insolvency)}. Hardware ${k$(W.terms.hardware)}.`;
  $("reference").textContent = `The informed reference opens with: ${W.reference.first}; its expected cost is ${k$(W.reference.value)}.`;
}

// ---- terms panel
function renderTermsPanel() {
  const presets = [
    ["Base contract", D.bases[W.playbook]], ["Best contract", W.best],
    ["Cheapest listed", W.shortcuts.cheapest_listed], ["Every protection", W.shortcuts.every_protection],
  ];
  if (cellIndex() !== undefined) presets.unshift(["The checked cell's contract", cellIndex()]);
  $("presets").innerHTML = "";
  for (const [label, i] of presets) {
    const b = document.createElement("button");
    b.textContent = label; b.type = "button";
    b.addEventListener("click", () => { cur = i; render(); });
    $("presets").appendChild(b);
  }
  const neg = D.negotiable[W.playbook];
  $("terms").innerHTML = "";
  for (const k of TERMS) {
    const row = document.createElement("div");
    row.className = "term";
    row.innerHTML = `<div class="label">${k.replace("_", " ")}</div><div class="hint">${TERM_TEXT[k]}</div>`;
    const seg = document.createElement("div");
    seg.className = "seg"; seg.setAttribute("role", "group"); seg.setAttribute("aria-label", k);
    for (const v of D.levels[k]) {
      const b = document.createElement("button");
      b.type = "button"; b.dataset.term = k; b.dataset.level = String(v); b.id = `t-${k}-${v}`;
      b.textContent = levelText(k, String(v));
      b.addEventListener("click", () => choose(k, String(v)));
      seg.appendChild(b);
    }
    row.appendChild(seg);
    const note = document.createElement("div");
    note.className = "fixed-note"; note.id = `note-${k}`;
    row.appendChild(note);
    $("terms").appendChild(row);
    row.dataset.negotiable = neg.includes(k) ? "1" : "0";
  }
}
function choose(k, v) {
  const c = normal({ ...M.list[cur], [k]: v });
  const i = M.index.get(key(c));
  if (i !== undefined) { cur = i; render(); }
}
function renderTermsState() {
  const c = M.list[cur], neg = D.negotiable[W.playbook];
  for (const b of document.querySelectorAll(".seg button")) {
    const k = b.dataset.term, v = b.dataset.level;
    b.setAttribute("aria-pressed", String(c[k] === v));
    const target = M.index.get(key(normal({ ...c, [k]: v })));
    b.disabled = !neg.includes(k) || target === undefined || (k === "damages" && c.warranty !== "fix_and_delay") || (k === "escrow" && c.deposit === "none");
  }
  for (const k of TERMS) {
    let note = "";
    if (!neg.includes(k)) note = "Fixed on this playbook.";
    else if (k === "damages" && c.warranty !== "fix_and_delay") note = "Applies only under fix + delay.";
    else if (k === "escrow" && c.deposit === "none") note = "Applies only with a deposit.";
    $(`note-${k}`).textContent = note;
  }
}

// ---- outcomes, as risk_allocation_contracts.outcomes enumerates them
function outcomes(i) {
  const c = M.list[i], r = W.risks, cl = W.client, pre = W.pre[i] === 1, prep = W.prep[i] === 1;
  const pd = pre ? r.defect_with_test : r.defect_without_test;
  const pu = r.unready * (prep ? K.site_prep_effect : 1);
  const pi = r.incident * (c.burn_in === "true" ? K.burn_in_incident : 1);
  const pn = c.deposit !== "none" && c.escrow !== "true" ? cl.insolvency : 0;
  const fix = r.defect_fix, dd = r.defect_weeks * cl.delay, dmg = Number(c.damages) * r.defect_weeks;
  const ld = r.unready_weeks * cl.delay, loss = r.incident_loss, dep = K.deposit_share[c.deposit] * W.terms.hardware;
  const cap = c.liability_cap === "uncapped" ? Infinity : Number(c.liability_cap);
  const rows = [];
  for (const d of [0, 1]) for (const u of [0, 1]) for (const inc of [0, 1]) for (const n of [0, 1]) {
    const p = (d ? pd : 1 - pd) * (u ? pu : 1 - pu) * (inc ? pi : 1 - pi) * (n ? pn : 1 - pn);
    if (p === 0) continue;
    const real = (d ? fix + dd : 0) + (u ? r.standby + ld : 0) + (inc ? loss : 0) + (n ? dep : 0);
    let owed = 0;
    if (d) owed += (c.warranty !== "none" ? fix : 0) + (c.warranty === "fix_and_delay" ? dmg : 0);
    if (u && c.readiness === "integrator") owed += r.standby;
    if (inc && c.consequential === "included") owed += loss;
    const paid = Math.min(owed, cap);
    rows.push({ d, u, i: inc, n, p, owed, paid, loss: real - paid });
  }
  return rows;
}

// ---- rendering
function render() {
  renderTermsState();
  const c = M.list[cur], last = W.th.length - 1, me = total(cur);
  const order = M.list.map((_, i) => i).sort((a, b) => total(a) - total(b));
  const rank = order.indexOf(cur) + 1;
  const gap = me - W.best_cost;
  const outName = W.outside.best, out = W.outside[outName];
  $("verdict").innerHTML =
    `<span class="big num">${k$(me)}</span><span>rank <b class="num">${rank}</b> of ${M.list.length} on this menu · ` +
    (gap < 0.5 ? `<b style="color:var(--good)">the best contract</b>` : `<b class="num">${k$(gap)}</b> above the best contract`) + `</span>`;
  const chips = [];
  if (W.listed.includes(cur)) chips.push(["on the integrator's list", "accent"]);
  else chips.push(["not on the list: the client must ask for it", ""]);
  for (const [name, i] of Object.entries(W.shortcuts)) if (i === cur) chips.push([`the ${SHORTCUT_TEXT[name]}` + (W.losers.includes(name) ? ", which this world punishes" : ""), W.losers.includes(name) ? "warn" : ""]);
  chips.push(me < out ? [`beats walking to ${outName === "turnkey" ? "the rival turnkey" : "self-management"} by ${k$(out - me)}`, "good"] : [`walking is ${k$(me - out)} cheaper`, "bad"]);
  chips.push([W.pre[cur] ? "the integrator pre-stages" : "the integrator does not pre-stage", ""]);
  if (c.readiness === "integrator") chips.push([W.prep[cur] ? "the integrator prepares the site" : "the integrator does not prepare the site", ""]);
  $("verdict-chips").innerHTML = chips.map(([s, cls]) => `<span class="chip ${cls}">${s}</span>`).join("");

  const bars = [["This contract", me, "me"], ["Best contract", W.best_cost, "best"], ["Rival turnkey", W.outside.turnkey, ""], ["Self-manage", W.outside.self_manage, ""]];
  const lo = Math.min(...bars.map((b) => b[1])) - 400, hi = Math.max(...bars.map((b) => b[1]));
  $("compare").innerHTML = bars.map(([n, v, cls]) =>
    `<div class="crow ${cls}"><span>${n}</span><div class="track"><div class="fill" style="width:${(100 * (v - lo) / (hi - lo)).toFixed(1)}%"></div></div><span class="v">${k$(v)}</span></div>`).join("");

  // prices
  const hw = W.terms.hardware, unit = isFee() ? "fee" : "all in";
  const rows = [["Its list (round 0)", W.th[0][cur]], ["Its answer in round 1", W.th[1][cur]], ["Its answer in round 2", W.th[last][cur]]];
  $("prices").innerHTML = `<thead><tr><th>Price it signs at</th><th class="num">${unit}</th>${isFee() ? '<th class="num">all in</th>' : ""}</tr></thead><tbody>` +
    rows.map(([n, v]) => `<tr><td>${n}</td><td class="num">${k$(isFee() ? v - hw : v)}</td>${isFee() ? `<td class="num">${k$(v)}</td>` : ""}</tr>`).join("") +
    `<tr><td colspan="${isFee() ? 3 : 2}" class="note">Round 2's answer is the integrator's cost plus its ${k$(W.terms.margin)} margin, in $100 steps.</td></tr></tbody>`;

  // client cost
  const cl = W.client, share = K.deposit_share[c.deposit];
  const carried = (1 + cl.charge) * W.eloss[cur];
  const fin = c.deposit !== "none" ? cl.capital * share * hw * W.terms.deposit_weeks / 52 : 0;
  const esc = c.escrow === "true" ? K.escrow_fee : 0, burn = c.burn_in === "true" ? K.burn_in_weeks * cl.delay : 0;
  const cparts = [["Price, round 2", W.th[last][cur]], [`Expected loss carried × ${(1 + cl.charge).toFixed(2)}`, carried], ["Deposit financing", fin], ["Escrow fee", esc], ["Burn-in week's revenue", burn]];
  $("client-cost").innerHTML = `<thead><tr><th>The client's cost</th><th class="num">expected</th></tr></thead><tbody>` +
    cparts.map(([n, v]) => `<tr><td>${n}</td><td class="num">${k$(v)}</td></tr>`).join("") +
    `<tr class="total"><td>Total</td><td class="num">${k$(me)}</td></tr></tbody>`;

  // integrator cost
  const t = W.terms, ty = W.type, r = W.risks;
  const prepF = W.prep[cur] ? K.site_prep_effect : 1;
  const iparts = [
    ["Hardware and its own delivery", t.hardware + t.services],
    [W.pre[cur] ? "Pre-staging the cluster" : "Pre-staging (not done)", W.pre[cur] ? ty.test_cost : 0],
    [c.readiness === "integrator" ? (W.prep[cur] ? "Preparing the site" : "Preparing the site (not done)") : "Preparing the site (no reason to)", W.prep[cur] ? W.extras.site_prep : 0],
    ["Burn-in crew", c.burn_in === "true" ? K.burn_in_crew : 0],
    [`Expected payouts ${k$(W.epaid[cur])} × ${(1 + ty.risk_charge).toFixed(2)}`, (1 + ty.risk_charge) * W.epaid[cur]],
    ["Standby it cannot control", c.readiness === "integrator" ? t.contingency * r.unready * prepF * r.standby : 0],
    ["Using the deposit until delivery", c.deposit !== "none" && c.escrow !== "true" ? -t.icapital * share * hw * t.deposit_weeks / 52 : 0],
  ];
  $("integrator-cost").innerHTML = `<thead><tr><th>The integrator's cost (hidden from the client)</th><th class="num">expected</th></tr></thead><tbody>` +
    iparts.map(([n, v]) => `<tr><td>${n}</td><td class="num">${v < 0 ? "−" + k$(-v) : k$(v)}</td></tr>`).join("") +
    `<tr class="total"><td>Its cost, before its ${k$(t.margin)} margin</td><td class="num">${k$(W.icost[cur])}</td></tr></tbody>`;

  renderSensitivity(); renderStrip(order); renderOutcomes(); renderCell();
}

// ---- the cell being checked: the grader's published numbers beside the same quantities recomputed from this page's
// solver tables (realised cost = price signed + the contract's cost to the client + refused counters' round costs;
// cost over best attainable = realised cost − the cheaper of the best contract and the better walk)
function renderCell() {
  const box = $("cell"), panel = $("cell-panel");
  $("legend-cell").hidden = cellIndex() === undefined;
  if (!CELL || CELL.world !== W.id) { panel.hidden = true; return; }
  panel.hidden = false;
  const g = CELL.grade || {}, rounds = (CELL.refused || 0) * W.terms.round_cost;
  const outCost = W.outside[W.outside.best], target = Math.min(W.best_cost, outCost);
  const ci = cellIndex();
  let lines, realised, parts;
  if (CELL.signed && ci !== undefined) {
    const t = total(ci), pof = CELL.price_over_floor || 0;
    realised = t + pof + rounds;
    parts = { contract: t - target, price: pof, walk: 0, refused_counters: rounds };
    lines = [["The signed contract's cost to the client at the integrator's last-round price", t],
             ["Signed above that last-round price", pof]];
  } else if (CELL.signed) {
    box.innerHTML = `<p class="who">${esc(CELL.label)}</p><p class="bad">The signed contract is not on this world's menu; nothing to recompute.</p>`; return;
  } else {
    const o = W.outside[CELL.walked_to] ?? outCost;
    realised = o + rounds;
    parts = { contract: 0, price: 0, walk: o - target, refused_counters: rounds };
    lines = [[`Walked to ${CELL.walked_to === "turnkey" ? "the rival turnkey" : "self-management"}: its expected cost`, o]];
  }
  lines.push([`Refused counters: ${CELL.refused || 0} × ${k$(W.terms.round_cost)} a round`, rounds]);
  const over = realised - target;
  const check = (mine, theirs) => theirs == null ? "" : Math.abs(mine - theirs) < 0.05 ? ` <span class="ok">✓ grader</span>` : ` <span class="bad">✗ grader says ${k$(theirs)}</span>`;
  const sp = g.split || {};
  const best = W.best_cost <= outCost ? "the best contract" : `walking to ${W.outside.best === "turnkey" ? "the rival turnkey" : "self-management"}`;
  const moves = (CELL.decisions || []).map((d) => `<li>round ${d.round}: ${esc(d.action)} — regret <b>${k$(d.regret)}</b></li>`).join("");
  box.innerHTML = `<p class="who">${esc(CELL.label)}</p>
  <table><tbody>${lines.map(([n, v]) => `<tr><td>${esc(n)}</td><td class="num">${k$(v)}</td></tr>`).join("")}
  <tr class="total"><td>Realised cost</td><td class="num">${k$(realised)}${check(realised, g.realised_cost)}</td></tr>
  <tr><td>Best attainable here: ${best}</td><td class="num">${k$(target)}</td></tr>
  <tr class="total"><td>Cost over best attainable</td><td class="num">${k$(over)}${check(over, g.cost_over_best_attainable)}</td></tr>
  ${["contract", "price", "walk", "refused_counters"].map((p) => `<tr><td style="padding-left:18px">of which ${p.replace("_", " ")}</td><td class="num">${k$(parts[p])}${check(parts[p], sp[p])}</td></tr>`).join("")}
  </tbody></table>
  ${moves ? `<p class="who" style="margin-top:8px"><b>The grader's moves</b>, each against the best move a client that knows the integrator's type could make at that point; their sum is the decision regret, <b>${k$(g.decision_regret)}</b>:</p><ol>${moves}</ol><p class="note">Move regrets need the solver's round-by-round states and are not recomputed here; cost over best attainable is a different quantity from the decision regret.</p>` : ""}`;
}

function renderSensitivity() {
  const c = M.list[cur], me = total(cur), neg = D.negotiable[W.playbook];
  const width = Math.max(...neg.map((k) => D.levels[k].length));
  let html = `<thead><tr><th>Term</th><th class="num" colspan="${width}">Moving it to each level</th></tr></thead><tbody>`;
  for (const k of neg) {
    html += `<tr><td>${k.replace("_", " ")}</td>`;
    const levels = D.levels[k].map(String);
    for (let j = 0; j < width; j++) {
      const v = levels[j];
      if (v === undefined) { html += "<td></td>"; continue; }
      const i = M.index.get(key(normal({ ...c, [k]: v })));
      if (i === undefined) { html += `<td class="num" style="color:var(--faint)">${levelText(k, v)}: off menu</td>`; continue; }
      if (i === cur) { html += `<td class="cell now" title="current">${levelText(k, v)} · now</td>`; continue; }
      const dlt = total(i) - me;
      html += `<td class="cell ${dlt < -0.05 ? "gain" : "loss"}" data-i="${i}" tabindex="0" role="button" aria-label="Set ${k} to ${levelText(k, v)}">${levelText(k, v)} · ${signed$(dlt)}</td>`;
    }
    html += "</tr>";
  }
  $("sens").innerHTML = html + "</tbody>";
  for (const td of $("sens").querySelectorAll("td[data-i]")) {
    const go = () => { cur = Number(td.dataset.i); render(); };
    td.addEventListener("click", go);
    td.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
  }
}

function renderStrip(order) {
  const n = order.length, Wd = 1000, H = 190, padL = 46, padB = 18, padT = 8;
  const gaps = order.map((i) => total(i) - W.best_cost);
  const outGap = W.outside[W.outside.best] - W.best_cost;
  const maxG = Math.max(gaps[n - 1], outGap) * 1.04;
  const y = (g) => padT + (H - padT - padB) * (1 - g / maxG);
  const bw = (Wd - padL) / n;
  const marks = new Set(W.losers.map((s) => W.shortcuts[s]));
  let s = `<svg viewBox="0 0 ${Wd} ${H}" role="img" aria-label="Every contract's cost to the client above the best contract, sorted">`;
  const step = [50, 100, 200, 250, 500, 1000].find((st) => maxG / st <= 5) || 2000;
  for (let g = 0; g <= maxG; g += step) {
    s += `<line x1="${padL}" x2="${Wd}" y1="${y(g).toFixed(1)}" y2="${y(g).toFixed(1)}" stroke="var(--line-soft)"/>`;
    s += `<text x="${padL - 6}" y="${(y(g) + 4).toFixed(1)}" text-anchor="end">${g === 0 ? "best" : "+" + g}</text>`;
  }
  order.forEach((i, j) => {
    const fill = i === cur ? "var(--accent)" : i === cellIndex() ? "var(--cellc)" : i === W.best ? "var(--good)" : marks.has(i) ? "var(--warn)" : "var(--bar)";
    const top = y(Math.max(gaps[j], maxG * 0.004));
    const c = M.list[i];
    s += `<rect data-i="${i}" x="${(padL + j * bw).toFixed(2)}" y="${top.toFixed(1)}" width="${Math.max(bw - 0.4, 0.6).toFixed(2)}" height="${(H - padB - top).toFixed(1)}" fill="${fill}" style="cursor:pointer"><title>#${j + 1}: +${gaps[j].toFixed(1)} · ${TERMS.map((k) => levelText(k, c[k])).join(", ")}</title></rect>`;
  });
  s += `<line x1="${padL}" x2="${Wd}" y1="${y(outGap).toFixed(1)}" y2="${y(outGap).toFixed(1)}" stroke="var(--bad)" stroke-dasharray="4 3"/>`;
  s += `<text x="${Wd - 4}" y="${(y(outGap) - 4).toFixed(1)}" text-anchor="end" style="fill:var(--bad)">walking: +${outGap.toFixed(0)}</text>`;
  s += `<text x="${padL}" y="${H - 3}">cheapest for the client</text><text x="${Wd}" y="${H - 3}" text-anchor="end">dearest</text></svg>`;
  $("strip").innerHTML = s;
  $("strip-note").textContent = `All ${n} contracts sorted by the client's total at last-round prices, as $k above the best contract. The dashed line is walking to the better outside option. Select a bar to load that contract.`;
  for (const rect of $("strip").querySelectorAll("rect[data-i]")) rect.addEventListener("click", () => { cur = Number(rect.dataset.i); render(); });
}

function renderOutcomes() {
  const rows = outcomes(cur).sort((a, b) => b.p - a.p);
  const eLoss = rows.reduce((s, r) => s + r.p * r.loss, 0), ePaid = rows.reduce((s, r) => s + r.p * r.paid, 0);
  const fine = rows.find((r) => !r.d && !r.u && !r.i && !r.n);
  const capP = rows.filter((r) => r.paid < r.owed - 1e-9).reduce((s, r) => s + r.p, 0);
  const byLoss = [...rows].sort((a, b) => a.loss - b.loss);
  let acc = 0, p95 = byLoss[byLoss.length - 1].loss;
  for (const r of byLoss) { acc += r.p; if (acc >= 0.95) { p95 = r.loss; break; } }
  const worst = byLoss[byLoss.length - 1];
  $("tail").innerHTML = [
    ["Nothing goes wrong", pct(fine ? fine.p : 0)],
    ["Client's expected loss", k$(eLoss)],
    ["Client's loss, 1 in 20", k$(p95)],
    ["Client's worst case", `${k$(worst.loss)} (${pct(worst.p)})`],
    ["Integrator's expected payout", k$(ePaid)],
    ["Chance the cap binds", M.list[cur].liability_cap === "uncapped" ? "no cap" : pct(capP)],
  ].map(([n, v]) => `<div class="stat"><span class="label">${n}</span><span class="v">${v}</span></div>`).join("");
  const ev = (r) => {
    const names = [[r.d, "defect"], [r.u, "late facility"], [r.i, "incident"], [r.n, "integrator fails"]].filter((x) => x[0]).map((x) => `<span>${x[1]}</span>`);
    return `<div class="ev">${names.length ? names.join("") : '<span class="ok">all fine</span>'}</div>`;
  };
  $("outcomes").innerHTML = `<thead><tr><th>What happens</th><th class="num">chance</th><th class="num">integrator owes</th><th class="num">integrator pays</th><th class="num">client's loss</th></tr></thead><tbody>` +
    rows.map((r) => `<tr class="${r.paid < r.owed - 1e-9 ? "capped" : ""}"><td>${ev(r)}</td><td class="num">${pct(r.p)}</td><td class="num">${k$(r.owed)}</td><td class="num">${k$(r.paid)}</td><td class="num">${r.loss < 0 ? "−" + k$(-r.loss) + " (gain)" : k$(r.loss)}</td></tr>`).join("") +
    `</tbody>`;
}

window.addEventListener("message", (e) => {
  const m = e.data || {};
  if (!m.cbCell) return;
  CELL = m.cbCell;
  const i = D.worlds.findIndex((w) => w.id === CELL.world);
  if (i >= 0) setWorld(i, true);
  $("cell-panel").scrollIntoView({ block: "start" });
});
const start = D.worlds.findIndex((w) => w.id === (INIT.world || location.hash.slice(1)));
setWorld(start >= 0 ? start : 0);
if (EMBED) new ResizeObserver(() => tell({ cbHeight: document.documentElement.scrollHeight })).observe(document.body);
