/* Case Consultant page: the thread, the live case file, voice input, storage and the model connection. */
(function () {
  "use strict";
  var C = window.CaseCore;
  var LS_STATE = "case-consultant:state:v1", LS_DRAFT = "case-consultant:draft", LS_LANG = "case-consultant:lang";
  var $ = function (id) { return document.getElementById(id); };

  var S = null;
  var brain = null, brainKind = "pending", brainReady = null;
  var busy = null;     // { label, text, ctl } while a model call runs
  var notice = null;   // { text, retry, edit }
  var store = { db: null, uid: null, http: false, where: "device", localOk: true, failed: false, timer: 0, writing: false, dirty: false, docs: {} };
  var inViewer = !!(window.claude && typeof window.claude.use === "function");
  var downloads = null;
  var ui = { tab: "talk", example: false, cases: false, casesList: null, confirmNew: false, copyText: "", toast: "", toastTimer: 0 };
  var inFrame = (function () { try { return window.self !== window.top; } catch (e) { return true; } })();

  /* ---- small helpers ---- */
  function lsGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function lsSet(k, v) { try { localStorage.setItem(k, v); return true; } catch (e) { return false; } }
  function el(tag, props) {
    var n = document.createElement(tag), k, v, i;
    if (props) for (k in props) {
      v = props[k];
      if (v == null || v === false) continue;
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k.slice(0, 2) === "on") n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? "" : v);
    }
    for (i = 2; i < arguments.length; i++) append(n, arguments[i]);
    return n;
  }
  function append(n, kid) {
    if (kid == null || kid === false) return;
    if (Array.isArray(kid)) { kid.forEach(function (x) { append(n, x); }); return; }
    n.appendChild(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  function paragraphs(text, cls) {
    return String(text).split(/\n{2,}/).filter(function (p) { return p.trim(); }).map(function (p) { return el("p", { class: cls, text: p.trim() }); });
  }
  function button(label, cls, fn, extra) {
    var props = { type: "button", class: "btn " + (cls || ""), onclick: fn, text: label };
    if (extra) for (var k in extra) props[k] = extra[k];
    return el("button", props);
  }
  function toast(text) {
    ui.toast = text;
    $("toast").textContent = text;
    clearTimeout(ui.toastTimer);
    ui.toastTimer = setTimeout(function () { ui.toast = ""; $("toast").textContent = ""; }, 3500);
  }
  function openGaps() { return S.gaps.filter(function (g) { return g.status === "open"; }); }
  function filedCount() {
    return C.STAGES.slice(0, C.READBACK).filter(function (s) { return C.stageStatus(S, s.id).state === "complete"; }).length;
  }

  /* ---- render: header, rail, tabs ---- */
  function renderPills() {
    var b = $("brainPill"), s = $("savePill");
    b.className = "pill " + (brainKind === "pending" ? "" : brain ? "on" : "off");
    b.textContent = brainKind === "pending" ? "Connecting" : brainKind === "claude" ? "Consultant: Claude" : brainKind === "local" ? "Consultant: local Claude" : "Worksheet, no consultant";
    var text = store.where === "account" ? "Saved to your account" : store.where === "disk" ? "Saved to disk" : store.localOk ? "Saved on this device" : "Not saved";
    if (store.failed && store.localOk) text = "Saved on this device only";
    s.className = "pill " + (store.localOk || store.where !== "device" ? "" : "off");
    s.textContent = text;
  }
  function renderRail() {
    var rail = $("rail");
    rail.replaceChildren();
    C.STAGES.forEach(function (st, i) {
      var state = i < S.stage ? "done" : i === S.stage ? "now" : "todo";
      rail.appendChild(el("li", { class: "seg " + state, title: (i + 1) + ". " + st.title, "aria-current": i === S.stage ? "step" : null },
        el("span", { class: "vh", text: (i + 1) + ". " + st.title + (state === "done" ? ", done" : state === "now" ? ", current" : "") })));
    });
    var lab = $("railLabel");
    if (S.stage >= C.READBACK) lab.replaceChildren(el("b", { text: "Read-back" }), " · you check what was understood");
    else lab.replaceChildren(el("b", { text: "Part " + (S.stage + 1) + " of " + C.READBACK }), " · " + C.STAGES[S.stage].title);
  }
  function renderTabs() {
    var talk = ui.tab === "talk";
    $("tabTalk").setAttribute("aria-selected", talk ? "true" : "false");
    $("tabFile").setAttribute("aria-selected", talk ? "false" : "true");
    $("paneTalk").classList.toggle("is-active", talk);
    $("paneFile").classList.toggle("is-active", !talk);
    $("tabFile").textContent = "Case file · " + filedCount() + " of " + C.READBACK + " filed";
  }

  /* ---- render: the interview ---- */
  function readbackNode(current) {
    var rb = S.readback;
    if (!current || !rb) return el("p", { class: "rb stale", text: "An earlier read-back, since rewritten." });
    var box = el("div", { class: "rb" }, paragraphs(rb.summary.join("\n\n")));
    if (rb.contradictions.length) {
      box.appendChild(el("h4", { text: "Two of your answers seem to disagree" }));
      box.appendChild(el("ul", null, rb.contradictions.map(function (c) {
        return el("li", { text: "“" + c.a + "” and “" + c.b + "”. " + c.ask });
      })));
    }
    var differ = rb.worked_checks.filter(function (w) { return w.agrees === false; });
    if (differ.length) {
      box.appendChild(el("h4", { text: "Your rule and your choice differ here" }));
      box.appendChild(el("ul", null, differ.map(function (w) {
        return el("li", { text: w.situation + ": you chose “" + w.stated_choice + "”, your rule gives “" + w.rule_says + "”. " + w.note });
      })));
    }
    if (rb.would_be_invented.length) {
      box.appendChild(el("h4", { text: "Not yet clear enough to build from" }));
      box.appendChild(el("ul", null, rb.would_be_invented.map(function (x) { return el("li", { text: x }); })));
    }
    if (rb.stale) box.appendChild(el("p", { class: "stale", text: "You have corrected this since it was written. Rewrite it to see the corrections." }));
    return box;
  }
  function messageNode(m, isLastReadback) {
    if (m.role === "expert") {
      return el("div", { class: "msg e" }, el("p", { class: "who", text: m.spoken ? "You · spoken" : "You" }), el("p", { class: "say", text: m.text }));
    }
    var lab = "";
    if (m.kind === "open") lab = m.stage >= C.READBACK ? "Read-back" : "Part " + (m.stage + 1) + " · " + C.STAGES[m.stage].title;
    else if (m.kind === "clarify") lab = m.reason && C.GAP_KINDS[m.reason] ? "Clarifying · " + C.GAP_KINDS[m.reason] : m.stage >= C.READBACK ? "Corrections" : "Clarifying";
    else if (m.kind === "check") lab = "Checklist";
    else if (m.kind === "readback") lab = "Read-back";
    var node = el("div", { class: "msg c " + (m.kind || "") }, lab ? el("p", { class: "who", text: lab }) : null, paragraphs(m.text, "say"));
    if (m.cover) node.appendChild(el("ul", { class: "cover" }, m.cover.map(function (x) { return el("li", { text: x }); })));
    if (m.kind === "readback") node.appendChild(readbackNode(isLastReadback));
    return node;
  }
  function pendingNode() {
    return el("div", { class: "msg c pending", id: "pending" }, el("p", { class: "who", text: busy.label }), el("p", { class: "say", text: busy.text || "" }));
  }
  function renderThread(stick) {
    var box = $("thread");
    var nearEnd = stick || box.scrollHeight - box.scrollTop - box.clientHeight < 140;
    var lastRb = -1;
    S.transcript.forEach(function (m, i) { if (m.kind === "readback") lastRb = i; });
    box.replaceChildren();
    S.transcript.forEach(function (m, i) { box.appendChild(messageNode(m, i === lastRb)); });
    if (busy) box.appendChild(pendingNode());
    if (nearEnd) box.scrollTop = box.scrollHeight;
  }
  function renderPending() {
    var p = $("pending");
    if (!p || !busy) return;
    p.children[0].textContent = busy.label;
    p.children[1].textContent = busy.text || "";
    var box = $("thread");
    box.scrollTop = box.scrollHeight;
  }
  function renderActions() {
    var box = $("actions"), kids = [];
    if (busy) kids = [el("span", { class: "txt", text: busy.label + "." }), button("Stop", "", function () { if (busy && busy.ctl) busy.ctl.abort(); })];
    else if (notice) kids = [];
    else if (C.awaiting(S)) kids = [el("span", { class: "txt", text: "Your last answer has not been read yet." }), button("Continue", "primary", runTurn)];
    else if (S.stage >= C.READBACK) {
      if (!brain && brainKind !== "pending") kids = [el("span", { class: "txt", text: "That is every question. Download the case file and send it back." })];
      else if (!S.readback) kids = [el("span", { class: "txt", text: "Next: a plain summary of what you said, for you to check." }), button("Write the read-back", "primary", runReadback)];
      else if (S.readback.stale) kids = [el("span", { class: "txt", text: "Your corrections are filed." }), button("Rewrite the read-back", "primary", runReadback)];
      else if (!S.approved) kids = [el("span", { class: "txt", text: "If the summary is right, approve it. If not, say what to change, or answer one of the open points." }), button("This is right", "primary", function () { C.approve(S); commit(true); })];
      else kids = [el("span", { class: "txt", text: "Approved. Copy or download the case file to send it." })];
    }
    box.replaceChildren();
    kids.forEach(function (k) { box.appendChild(k); });
    box.hidden = kids.length === 0;
  }
  function renderNotice() {
    var box = $("notice");
    box.replaceChildren();
    box.hidden = !notice;
    if (!notice) return;
    box.appendChild(el("span", { class: "txt", text: notice.text }));
    if (notice.retry) box.appendChild(button("Try again", "", function () { var r = notice.retry; notice = null; r(); }));
    if (notice.edit && C.awaiting(S)) box.appendChild(button("Edit my answer", "", function () {
      var text = C.dropLastExpert(S);
      notice = null;
      $("answer").value = text;
      commit();
      $("answer").focus();
    }));
    box.appendChild(button("Dismiss", "ghost", function () { notice = null; renderAll(); }));
  }
  function renderExample() {
    var box = $("example"), st = C.STAGES[S.stage];
    var show = ui.example && !!st.example;
    box.hidden = !show;
    $("exampleBtn").setAttribute("aria-expanded", show ? "true" : "false");
    $("exampleBtn").hidden = !st.example;
    box.replaceChildren();
    if (show) {
      box.appendChild(el("b", { text: "An answer at a useful level of detail" }));
      box.appendChild(document.createTextNode(st.example + " (An illustration from a buyer of electronic parts, not from your field.)"));
    }
  }
  function renderComposer() {
    $("sendBtn").disabled = !!busy;
    $("skipBtn").disabled = !!busy;
    $("skipBtn").hidden = S.stage >= C.READBACK;
    $("answer").placeholder = S.stage >= C.READBACK ? "Say what to change, or answer one of the open points" : voice.usable() ? "Type your answer, or press Speak and say it" : "Type your answer";
  }

  /* ---- render: the case file ---- */
  function tableNode(caption, cols, rows, cellClass) {
    var head = el("tr", null, cols.map(function (c) { return el("th", { scope: "col", text: c[1] }); }));
    var body = rows.map(function (r) {
      return el("tr", null, cols.map(function (c) {
        var v = r[c[0]];
        return el("td", { class: cellClass ? cellClass(c[0]) : null }, v && v.nodeType ? v : (v == null ? "" : String(v)));
      }));
    });
    return el("div", { class: "scroll" }, el("table", null, caption ? el("caption", { text: caption }) : null, el("thead", null, head), el("tbody", null, body)));
  }
  /* Rows of prose read badly as a table: each row becomes a short record under its first field. */
  function recordsNode(caption, cols, rows) {
    var box = el("div", { class: "records" }, caption ? el("p", { class: "cap", text: caption }) : null);
    rows.forEach(function (r) {
      var dl = el("dl", { class: "kv" });
      cols.slice(1).forEach(function (c) {
        if (!C.filled(r[c[0]])) return;
        dl.appendChild(el("dt", { text: c[1] }));
        dl.appendChild(el("dd", { text: r[c[0]] }));
      });
      box.appendChild(el("div", { class: "rec" }, el("p", { class: "rh", text: r[cols[0][0]] || "Not named" }), dl.children.length ? dl : null));
    });
    return box;
  }
  function sectionBody(sec, v) {
    var out = [], dl = null;
    function flush() { if (dl && dl.children.length) out.push(dl); dl = null; }
    function pair(label, dd) { if (!dl) dl = el("dl", { class: "kv" }); dl.appendChild(el("dt", { text: label })); dl.appendChild(dd); }
    sec.fields.forEach(function (f) {
      var val = v[f.k];
      if (f.type === "text") { if (C.filled(val)) pair(f.label, el("dd", { text: val })); }
      else if (f.type === "bool") { if (val) pair(f.label, el("dd", { text: "Yes" })); }
      else if (f.type === "list") { if (val.length) pair(f.label, el("dd", null, el("ul", null, val.map(function (x) { return el("li", { text: x }); })))); }
      else if (val.length) { flush(); out.push(recordsNode(f.label, f.cols, val)); }
    });
    flush();
    return out;
  }
  function sectionNode(sec) {
    var v = S.caseFile[sec.id];
    var stage = C.STAGES.filter(function (s) { return s.fills.indexOf(sec.id) >= 0; })[0];
    var touched = C.sectionTouched(sec, v);
    var status = stage ? C.stageStatus(S, stage.id) : { state: touched ? "complete" : "empty", missing: [] };
    var chipText = status.state === "complete" ? "Filed" : status.state === "partial" ? "In progress" : "Not yet";
    var node = el("section", { class: "sec " + status.state, id: "sec-" + sec.id },
      el("header", null, el("h3", { text: sec.title }), el("span", { class: "chip " + status.state, text: chipText })),
      el("p", { class: "becomes", text: "Becomes: " + sec.becomes.charAt(0).toLowerCase() + sec.becomes.slice(1) + "." }));
    if (!touched) node.appendChild(el("p", { class: "expect", text: sec.expect }));
    else sectionBody(sec, v).forEach(function (n) { node.appendChild(n); });
    if (status.state === "partial" && status.missing.length) node.appendChild(el("p", { class: "needs", text: "Still needed: " + status.missing.join("; ") + "." }));
    return node;
  }
  function numbersNode() {
    var node = el("section", { class: "sec", id: "sec-numbers" },
      el("header", null, el("h3", { text: "Numbers" }), el("span", { class: "chip", text: S.numbers.length + " filed" })),
      el("p", { class: "becomes", text: "Becomes: the settings of the build, each with a range and where it comes from." }));
    if (!S.numbers.length) { node.appendChild(el("p", { class: "expect", text: "Every price, cost, duration, share and rate you mention, as lowest, usual and highest, marked data, experience or guess." })); return node; }
    var rows = S.numbers.map(function (q) {
      var issues = C.numberIssues(q);
      var name = el("span", null, q.name || q.id, q.unit ? " (" + q.unit + ")" : "", issues.indexOf("range") >= 0 ? el("span", { class: "flag", text: "needs a range" }) : null);
      var src = C.SOURCES.indexOf(q.source) >= 0 ? el("span", { class: "src " + q.source, text: q.source }) : el("span", { class: "src none", text: "not said" });
      return { name: name, low: q.low, typical: q.typical, high: q.high, of_ten: q.of_ten, source: src };
    });
    node.appendChild(tableNode("", [["name", "Number"], ["low", "Low"], ["typical", "Usual"], ["high", "High"], ["of_ten", "Of ten"], ["source", "Source"]], rows,
      function (k) { return k === "low" || k === "typical" || k === "high" || k === "of_ten" ? "num" : null; }));
    return node;
  }
  function gapsNode() {
    var open = openGaps();
    var node = el("section", { class: "sec", id: "sec-gaps" },
      el("header", null, el("h3", { text: "Open questions" }), el("span", { class: "chip " + (open.length ? "partial" : ""), text: open.length + " open" })));
    if (!open.length) node.appendChild(el("p", { class: "expect", text: "Anything you could not answer, or that was passed over, is listed here and stays in the document." }));
    else node.appendChild(el("ul", { class: "gaps" }, open.map(function (g) { return el("li", null, el("span", { class: "k", text: C.GAP_KINDS[g.kind] }), el("span", { text: g.text })); })));
    return node;
  }
  function auditNode() {
    var rb = S.readback;
    var node = el("section", { class: "sec", id: "sec-audit" }, el("header", null, el("h3", { text: "Audit" })));
    node.appendChild(el("p", { class: "becomes", text: "Your own rule applied to your own situations, and what a builder would still have to make up." }));
    if (rb.worked_checks.length) node.appendChild(recordsNode("", [["situation", "Situation"], ["stated_choice", "Stated choice"], ["rule_says", "The rule says"], ["agrees", "Agrees"], ["note", "Note"]],
      rb.worked_checks.map(function (w) { return { situation: w.situation, stated_choice: w.stated_choice, rule_says: w.rule_says, agrees: w.agrees === true ? "Yes" : w.agrees === false ? "No" : "Cannot tell", note: w.note }; })));
    if (rb.would_be_invented.length) {
      node.appendChild(el("p", { class: "needs", text: "A builder would have to invent:" }));
      node.appendChild(el("ul", { class: "gaps" }, rb.would_be_invented.map(function (x) { return el("li", { text: x }); })));
    }
    return node;
  }
  function readyNode() {
    var node = el("section", { class: "sec", id: "sec-ready" }, el("header", null, el("h3", { text: "Ready to build from?" })));
    node.appendChild(el("ul", { class: "ready" }, C.readiness(S).map(function (r) {
      return el("li", { class: r.ok ? "ok" : "" }, el("span", { class: "mark", "aria-hidden": "true", text: r.ok ? "✓" : "○" }),
        el("span", { text: r.label + (r.ok ? "" : " (not yet)") }), r.detail ? el("span", { class: "d", text: r.detail }) : null);
    })));
    return node;
  }
  function renderDoc() {
    var doc = $("doc"), top = doc.scrollTop;
    $("fileTitle").textContent = C.caseTitle(S) === "Untitled case" ? "Case file" : C.caseTitle(S);
    $("fileSub").textContent = filedCount() + " of " + C.READBACK + " parts filed · " + S.numbers.length + " numbers · " + openGaps().length + " open questions";
    doc.replaceChildren();
    if (ui.copyText) {
      var ta = el("textarea", { class: "copyBox", id: "copyBox", readonly: true, "aria-label": "The case file as Markdown. Select all and copy." });
      ta.value = ui.copyText;
      doc.appendChild(el("section", { class: "sec" }, el("p", { class: "needs", text: "Copying is blocked here. Select all of this text and copy it." }), ta, button("Hide", "ghost", function () { ui.copyText = ""; renderDoc(); })));
    }
    if (S.readback) {
      doc.appendChild(el("section", { class: "sec rbdoc", id: "sec-readback" },
        el("header", null, el("h3", { text: "Read-back" }), el("span", { class: "chip " + (S.approved ? "complete" : "partial"), text: S.approved ? "Approved" : S.readback.stale ? "Out of date" : "To check" })),
        paragraphs(S.readback.summary.join("\n\n"))));
    }
    C.SECTIONS.forEach(function (sec) { doc.appendChild(sectionNode(sec)); });
    doc.appendChild(numbersNode());
    doc.appendChild(gapsNode());
    if (S.readback) doc.appendChild(auditNode());
    doc.appendChild(readyNode());
    doc.scrollTop = top;
  }

  /* ---- render: saved cases ---- */
  function summarise(d) {
    return { id: d.id, title: C.caseTitle(d), updatedAt: d.updatedAt || "", stage: d.stage || 0, approved: !!d.approved };
  }
  function renderCases() {
    var box = $("casesPanel");
    $("casesBtn").setAttribute("aria-expanded", ui.cases ? "true" : "false");
    box.hidden = !ui.cases;
    box.replaceChildren();
    if (!ui.cases) return;
    box.appendChild(el("h2", { text: "Your cases" }));
    var remote = !!(store.db || store.http);
    if (remote) {
      if (!ui.casesList) box.appendChild(el("p", { class: "m", text: "Loading." }));
      else box.appendChild(el("ul", null, ui.casesList.map(function (c) {
        var cur = c.id === S.id;
        return el("li", null, el("span", { class: "t", text: c.title }),
          el("span", { class: "m", text: (c.approved ? "Approved" : c.stage >= C.READBACK ? "Read-back" : "Part " + (c.stage + 1) + " of " + C.READBACK) + " · " + c.updatedAt.slice(0, 10) }),
          cur ? el("span", { class: "m", text: "Open now" }) : button("Open", "", function () { openCase(c.id); }));
      })));
    }
    var foot = el("div", { class: "foot" });
    if (remote) foot.appendChild(button("Start a new case", "", newCase));
    else if (!ui.confirmNew) {
      foot.appendChild(el("span", { text: "This case is kept on this device only." }));
      foot.appendChild(button("Start a new case", "", function () { ui.confirmNew = true; renderCases(); }));
    } else {
      foot.appendChild(el("span", { text: "Starting another clears this one from this device. Download it first if you need it." }));
      foot.appendChild(button("Clear it and start", "", newCase));
      foot.appendChild(button("Cancel", "ghost", function () { ui.confirmNew = false; renderCases(); }));
    }
    box.appendChild(foot);
  }
  function loadCases() {
    ui.casesList = null;
    var p = store.db
      ? store.db.collection("interviews/" + store.uid + "/cases").get().then(function (q) {
        return q.docs.map(function (d) { var v = d.data(); if (v && v.id) store.docs[v.id] = v; return v; });
      })
      : store.http ? fetch("api/cases", { cache: "no-store" }).then(function (r) { return r.json(); }) : Promise.resolve([]);
    p.then(function (list) {
      var rows = (list || []).filter(function (d) { return d && d.id && d.caseFile; }).map(summarise);
      if (!rows.some(function (r) { return r.id === S.id; })) rows.push(summarise(S));
      rows.sort(function (a, b) { return a.updatedAt < b.updatedAt ? 1 : -1; });
      ui.casesList = rows;
      renderCases();
    }).catch(function () { ui.casesList = [summarise(S)]; renderCases(); });
  }
  function adopt(data) {
    if (!data || !data.caseFile || !Array.isArray(data.transcript)) return false;
    var fresh = C.newState(), k;
    for (k in fresh) if (data[k] === undefined) data[k] = fresh[k];
    C.SECTIONS.forEach(function (sec) { if (!data.caseFile[sec.id]) data.caseFile[sec.id] = fresh.caseFile[sec.id]; });
    S = data;
    return true;
  }
  function openCase(id) {
    var p = store.db ? Promise.resolve(store.docs[id]) : fetch("api/case?id=" + encodeURIComponent(id), { cache: "no-store" }).then(function (r) { return r.json(); });
    flushRemote().then(function () { return p; }).then(function (data) {
      if (!adopt(C.clone(data))) return;
      notice = null; ui.cases = false; ui.copyText = "";
      saveLocal();
      $("answer").value = "";
      renderAll(true);
    }).catch(function () { toast("That case could not be opened."); });
  }
  function newCase() {
    flushRemote().then(function () {
      S = C.newState();
      notice = null; ui.cases = false; ui.confirmNew = false; ui.copyText = ""; ui.example = false;
      $("answer").value = "";
      lsSet(LS_DRAFT, "");
      commit(true);
    });
  }

  function renderAll(stick) {
    renderPills(); renderRail(); renderTabs(); renderThread(stick); renderActions(); renderNotice(); renderExample(); renderComposer(); renderDoc(); renderCases(); voice.render();
  }

  /* ---- storage: this device always; the viewer's account or the local server when there is one ---- */
  function saveLocal() { store.localOk = lsSet(LS_STATE, JSON.stringify(S)); }
  function commit(stick) {
    S.updatedAt = new Date().toISOString();
    saveLocal();
    queueRemote();
    renderAll(stick);
  }
  function queueRemote() {
    if (!store.db && !store.http) return;
    store.dirty = true;
    clearTimeout(store.timer);
    store.timer = setTimeout(flushRemote, 1200);
  }
  function flushRemote() {
    clearTimeout(store.timer);
    if (store.writing || !store.dirty || (!store.db && !store.http)) return Promise.resolve();
    store.dirty = false;
    store.writing = true;
    var payload = C.clone(S);
    var p = store.db
      ? store.db.doc("interviews/" + store.uid + "/cases/" + payload.id).set(payload)
      : fetch("api/save", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) }).then(function (r) { if (!r.ok) throw new Error("save failed"); });
    return p.then(function () {
      store.failed = false;
      store.where = store.db ? "account" : "disk";
      if (store.db) store.docs[payload.id] = payload;
    }).catch(function (e) {
      store.failed = true;
      store.where = "device";
      // A viewer who may not write here gets invalid_argument on every write: stop trying.
      if (store.db && e && e.code === "invalid_argument") store.db = null;
    }).then(function () {
      store.writing = false;
      renderPills();
      if (store.dirty) queueRemote();
    });
  }
  function connectStore() {
    if (!inViewer) return Promise.resolve();
    return Promise.all([window.claude.use("db"), window.claude.use("user")]).then(function (r) {
      var db = r[0], user = r[1];
      if (!db || !user) return;
      return user.id().then(function (uid) {
        if (!uid) return;
        store.db = db; store.uid = uid;
        // Pick up a newer copy of this case saved from another device.
        return db.doc("interviews/" + uid + "/cases/" + S.id).get().then(function (snap) {
          var d = snap.exists ? snap.data() : null;
          if (d && d.updatedAt && d.updatedAt > S.updatedAt && !busy && adopt(C.clone(d))) { saveLocal(); renderAll(true); }
          if (snap.exists) store.where = "account";
          renderPills();
        });
      });
    }).catch(function () { /* stay on this device */ });
  }

  /* ---- the model: Claude in the viewer, or the local server; neither means a worksheet ---- */
  function viewerBrain(sample) {
    return { json: function (input, o) {
      var opts = { cache: false, modelTier: o.tier === "complex" ? "complex" : "default" };
      if (o.signal) opts.signal = o.signal;
      if (o.onText) opts.onText = function (u) { o.onText(u.text); };
      if (typeof sample.json === "function") return sample.json(input, opts);
      return sample(input, opts).then(function (r) {
        try { return C.parseJson(r.text); } catch (e) { throw { code: "invalid_json", message: e.message, text: r.text }; }
      });
    } };
  }
  function httpBrain() {
    return { json: function (input, o) {
      return fetch("api/consult", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ input: input, tier: o.tier || "default" }), signal: o.signal })
        .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw { code: "upstream_error", message: (j && j.error) || "HTTP " + r.status }; return j; }); })
        .then(function (j) { try { return C.parseJson(j.text); } catch (e) { throw { code: "invalid_json", message: e.message, text: j.text }; } })
        .catch(function (e) {
          if (e && e.name === "AbortError") throw { code: "cancelled", message: "stopped" };
          throw e && e.code ? e : { code: "upstream_error", message: String((e && e.message) || e) };
        });
    } };
  }
  function connectBrain() {
    var viewer = inViewer ? window.claude.use("sample").catch(function () { return null; }) : Promise.resolve(null);
    return viewer.then(function (sample) {
      if (sample) { brain = viewerBrain(sample); brainKind = "claude"; return; }
      return fetch("api/health", { cache: "no-store" }).then(function (r) { return r.ok ? r.json() : null; }).then(function (j) {
        if (j && j.ok) { brain = httpBrain(); brainKind = "local"; store.http = true; store.where = "disk"; store.dirty = true; queueRemote(); }
        else brainKind = "none";
      }).catch(function () { brainKind = "none"; });
    }).then(function () { renderAll(); });
  }
  var UNAVAILABLE = ["not_granted", "sampling_disabled", "not_declared", "capability_disabled", "capability_removed"];
  function explain(e) {
    var code = e && e.code ? e.code : e instanceof Error ? "invalid_json" : "upstream_error";
    if (code === "cancelled") return "Stopped. Your answer is kept.";
    if (code === "rate_limited") return "Claude is busy, or your usage limit is reached. Wait a moment, then try again.";
    if (code === "session_expired") return "You have been signed out. Sign in again, then try again.";
    if (code === "refused") return "Claude declined to read that answer. Change the wording and send it again.";
    if (code === "prompt_too_large") return "This case has grown too long to send in one piece. Download it, then start a new case for the rest.";
    if (code === "invalid_json" || code === "empty_completion") return "The reply came back unreadable. Try again.";
    return "The reply did not come through. Try again." + (brainKind === "local" && e && e.message ? " (" + String(e.message).slice(0, 180) + ")" : "");
  }
  function runTurn() {
    if (busy) return Promise.resolve();
    notice = null;
    return brainReady.then(function () {
      if (!C.awaiting(S)) { renderAll(); return; }
      if (!brain) { S.mode = "worksheet"; C.worksheetStep(S); commit(true); return; }
      S.mode = "consultant";
      var ctl = new AbortController();
      busy = { label: "Reading your answer", text: "", ctl: ctl };
      renderAll(true);
      return brain.json(C.turnPrompt(S), { tier: "default", signal: ctl.signal, onText: function (t) {
        var p = C.partialReply(t);
        if (p && busy) { busy.label = "Asking"; busy.text = p; renderPending(); }
      } }).then(function (out) { C.applyTurn(S, out); }).catch(function (e) {
        if (e && UNAVAILABLE.indexOf(e.code) >= 0) {
          brain = null; brainKind = "none"; S.mode = "worksheet"; C.worksheetStep(S);
          notice = { text: "Claude is not available in this view, so the interview continues as a worksheet: the same questions, without follow-ups." };
        } else notice = { text: explain(e), retry: runTurn, edit: true };
      }).then(function () { busy = null; commit(true); });
    });
  }
  function runReadback() {
    if (busy || !brain) return Promise.resolve();
    notice = null;
    var ctl = new AbortController();
    busy = { label: "Writing up what I understood. This can take a minute", text: "", ctl: ctl };
    renderAll(true);
    return brain.json(C.readbackPrompt(S), { tier: "complex", signal: ctl.signal }).then(function (out) { C.applyReadback(S, out); }).catch(function (e) {
      if (e && UNAVAILABLE.indexOf(e.code) >= 0) { brain = null; brainKind = "none"; notice = { text: "Claude is not available in this view, so the read-back cannot be written. Download the case file and send it back as it is." }; }
      else notice = { text: explain(e), retry: runReadback };
    }).then(function () { busy = null; commit(true); });
  }
  function send() {
    var box = $("answer"), text = box.value.trim();
    if (!text || busy) return;
    voice.stop();
    C.addExpert(S, text, { spoken: voice.used });
    voice.used = false;
    box.value = "";
    lsSet(LS_DRAFT, "");
    ui.example = false;
    commit(true);
    runTurn();
  }

  /* ---- voice: the browser's speech recognition, written into the answer box as it is heard ---- */
  var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  var DICTATE = "Dictation from your keyboard works in the answer box. Mac: press the microphone key, or Fn twice. iPhone and Android: tap the microphone on the keyboard. Windows: press Windows and H.";
  var TIPS = {
    blocked: "This viewer does not let a page use the microphone. " + DICTATE,
    unsupported: "This browser has no built-in speech recognition. Chrome, Edge and Safari have it. " + DICTATE,
    denied: "The microphone is blocked for this page. Allow it in the browser's site settings, then press Speak again.",
    network: "Speech recognition could not reach its service. Check the connection, then press Speak again.",
    nomic: "No microphone was found."
  };
  var voice = {
    on: false, rec: null, blocked: false, used: false, interim: "", tip: "", startedAt: 0, quick: 0,
    usable: function () { return !!SR && !voice.blocked; },
    policyAllows: function () {
      try {
        var fp = document.featurePolicy || document.permissionsPolicy;
        if (fp && typeof fp.allowsFeature === "function") return fp.allowsFeature("microphone");
      } catch (e) { /* unknown: let a click decide */ }
      return true;
    },
    toggle: function () {
      if (voice.on) { voice.stop(); return; }
      if (!SR) { voice.tip = voice.tip === "unsupported" ? "" : "unsupported"; voice.render(); return; }
      if (voice.blocked) { voice.tip = voice.tip ? "" : inFrame ? "blocked" : "denied"; voice.render(); return; }
      voice.start();
    },
    start: function () {
      var rec = new SR();
      rec.continuous = true;
      rec.interimResults = true;
      rec.maxAlternatives = 1;
      rec.lang = $("lang").value || navigator.language || "en-US";
      rec.onstart = function () { voice.startedAt = Date.now(); };
      rec.onresult = function (e) {
        var interim = "", i, r;
        for (i = e.resultIndex; i < e.results.length; i++) {
          r = e.results[i];
          if (r.isFinal) voice.write(r[0].transcript); else interim += r[0].transcript;
        }
        voice.interim = interim.trim();
        voice.render();
      };
      rec.onerror = function (e) {
        var err = e && e.error;
        if (err === "not-allowed" || err === "service-not-allowed") { voice.blocked = true; voice.on = false; voice.tip = inFrame ? "blocked" : "denied"; }
        else if (err === "network") { voice.on = false; voice.tip = "network"; }
        else if (err === "audio-capture") { voice.on = false; voice.tip = "nomic"; }
        voice.render();
      };
      rec.onend = function () {
        voice.interim = "";
        if (voice.on && voice.rec === rec) {
          // Browsers end a session after a pause. While the toggle is on, start again, unless it keeps dying at once.
          voice.quick = Date.now() - voice.startedAt < 1500 ? voice.quick + 1 : 0;
          if (voice.quick >= 3) { voice.on = false; voice.tip = "network"; }
          else setTimeout(function () {
            if (!voice.on || voice.rec !== rec) return;
            try { rec.start(); } catch (e2) { voice.on = false; }
            voice.render();
          }, 250);
        }
        voice.render();
      };
      voice.rec = rec; voice.on = true; voice.tip = ""; voice.quick = 0; voice.interim = "";
      try { rec.start(); } catch (e) { voice.on = false; }
      voice.render();
    },
    stop: function () {
      if (!voice.on) return;
      voice.on = false;
      voice.interim = "";
      try { voice.rec.stop(); } catch (e) { /* already stopped */ }
      voice.render();
    },
    write: function (text) {
      var t = String(text || "").trim();
      if (!t) return;
      var box = $("answer"), cur = box.value;
      if (!cur.trim() || /[.!?。！？]\s*$/.test(cur)) t = t.charAt(0).toUpperCase() + t.slice(1);
      box.value = cur + (cur && !/\s$/.test(cur) ? " " : "") + t;
      voice.used = true;
      lsSet(LS_DRAFT, box.value);
      box.scrollTop = box.scrollHeight;
    },
    render: function () {
      var btn = $("micBtn"), live = $("live"), tip = $("voiceTip");
      btn.setAttribute("aria-pressed", voice.on ? "true" : "false");
      btn.classList.toggle("off", !voice.usable());
      $("micLabel").textContent = voice.on ? "Stop" : voice.usable() ? "Speak" : "Dictate";
      $("lang").hidden = !voice.usable();
      $("answer").classList.toggle("hearing", voice.on);
      live.hidden = !voice.on;
      live.className = "live" + (voice.interim ? " words" : "");
      live.textContent = voice.interim || "Listening. Your browser's speech service writes what it hears. Check numbers before you send.";
      tip.hidden = !voice.tip;
      tip.textContent = voice.tip ? TIPS[voice.tip] : "";
    }
  };

  /* ---- export ---- */
  function fileBase() {
    var t = C.caseTitle(S).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 48);
    return "case-" + (t || "untitled") + "-" + S.id;
  }
  function saveFile(name, text) {
    if (inViewer) {
      if (!downloads) { toast("Downloads are not available here. Use Copy."); return; }
      downloads.save({ filename: name, data: text }).then(function () { toast("Saved."); }).catch(function (e) {
        if (!e || e.code !== "declined") toast("The file could not be saved here. Use Copy.");
      });
      return;
    }
    var url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
    var a = el("a", { href: url, download: name });
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 2000);
  }
  function copyMarkdown() {
    var md = C.toMarkdown(S);
    var fallback = function () { ui.copyText = md; renderDoc(); var b = $("copyBox"); if (b) { b.focus(); b.select(); } };
    if (!navigator.clipboard || !navigator.clipboard.writeText) { fallback(); return; }
    navigator.clipboard.writeText(md).then(function () { toast("Copied."); }, fallback);
  }

  /* ---- start ---- */
  function start(hotData) {
    var saved = null;
    if (hotData && hotData.state) saved = hotData.state;
    else { try { saved = JSON.parse(lsGet(LS_STATE) || "null"); } catch (e) { saved = null; } }
    if (!adopt(saved)) S = C.newState();
    voice.blocked = !!SR && !voice.policyAllows();

    $("answer").value = (hotData && hotData.draft) || lsGet(LS_DRAFT) || "";
    $("lang").value = lsGet(LS_LANG) || "";
    $("composer").addEventListener("submit", function (e) { e.preventDefault(); send(); });
    $("answer").addEventListener("keydown", function (e) { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); send(); } });
    $("answer").addEventListener("input", function () { lsSet(LS_DRAFT, $("answer").value); });
    $("lang").addEventListener("change", function () { lsSet(LS_LANG, $("lang").value); if (voice.on) { voice.stop(); voice.start(); } });
    $("micBtn").addEventListener("click", voice.toggle);
    $("skipBtn").addEventListener("click", function () { if (busy) return; notice = null; C.skip(S); ui.example = false; commit(true); });
    $("exampleBtn").addEventListener("click", function () { ui.example = !ui.example; renderExample(); });
    $("casesBtn").addEventListener("click", function () { ui.cases = !ui.cases; ui.confirmNew = false; if (ui.cases) loadCases(); renderCases(); });
    $("tabTalk").addEventListener("click", function () { ui.tab = "talk"; renderTabs(); });
    $("tabFile").addEventListener("click", function () { ui.tab = "file"; renderTabs(); });
    $("copyMd").addEventListener("click", copyMarkdown);
    $("dlMd").addEventListener("click", function () { saveFile(fileBase() + ".md", C.toMarkdown(S)); });
    $("dlJson").addEventListener("click", function () { saveFile(fileBase() + ".json", JSON.stringify(S, null, 2)); });

    store.localOk = lsSet(LS_STATE, JSON.stringify(S));
    renderAll(true);
    brainReady = connectBrain();
    connectStore();
    if (inViewer) window.claude.use("downloads").then(function (d) {
      downloads = d;
      $("dlMd").hidden = !d;
      $("dlJson").hidden = !d;
    }).catch(function () { $("dlMd").hidden = true; $("dlJson").hidden = true; });
  }

  var hot = window.claude && window.claude.hot;
  try { if (hot && hot.snapshot) hot.snapshot(function () { return { state: S, draft: $("answer") ? $("answer").value : "" }; }); } catch (e) { /* optional */ }
  if (hot && typeof hot.ready === "function") hot.ready(start); else start((hot && hot.data) || {});
})();
