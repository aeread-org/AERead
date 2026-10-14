// The interview outside the screen: state, saving, the model connection and export.
// core.js (window.CaseCore) holds the protocol; this module runs it and tells the screen when anything changed.
// On the hosted copy, ctl.voice (voice.js) runs the interview as a call instead of model calls from here.
const C = window.CaseCore;
const LS_STATE = "case-consultant:state:v1", LS_DRAFT = "case-consultant:draft";
const UNAVAILABLE = ["not_granted", "sampling_disabled", "not_declared", "capability_disabled", "capability_removed"];

const inViewer = !!(window.claude && typeof window.claude.use === "function");
const listeners = new Set();
let version = 0;

export const ctl = {
  C,
  S: null,
  busy: null,          // { text, abort } while a model call runs
  notice: null,        // { text, retry, edit }
  brain: null,
  brainKind: "pending",
  brainReady: null,
  inViewer,
  downloads: null,
  spokenSinceSend: false,
  voice: null,         // the call, on the hosted copy only (voice.js)
  store: { db: null, uid: null, http: false, where: "device", localOk: true, timer: 0, writing: false, dirty: false },
};

/* ---- change notification for the screen ---- */
export function subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); }
export function snapshot() { return version; }
function changed() { version += 1; listeners.forEach((fn) => fn()); }
export const refresh = changed;

/* ---- storage: this browser always; the viewer's account or the local server when there is one ---- */
function lsGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function lsSet(k, v) { try { localStorage.setItem(k, v); return true; } catch { return false; } }
export function getDraft() { return lsGet(LS_DRAFT) || ""; }
export function setDraft(text) { lsSet(LS_DRAFT, text); }

function saveLocal() { ctl.store.localOk = lsSet(LS_STATE, JSON.stringify(ctl.S)); }
function commit() {
  ctl.S.updatedAt = new Date().toISOString();
  saveLocal();
  queueRemote();
  changed();
}
export const save = commit;
function queueRemote() {
  const st = ctl.store;
  if (!st.db && !st.http) return;
  st.dirty = true;
  clearTimeout(st.timer);
  st.timer = setTimeout(flushRemote, 1200);
}
function flushRemote() {
  const st = ctl.store;
  clearTimeout(st.timer);
  if (st.writing || !st.dirty || (!st.db && !st.http)) return Promise.resolve();
  st.dirty = false;
  st.writing = true;
  const payload = C.clone(ctl.S);
  const p = st.db
    ? st.db.doc("interviews/" + st.uid + "/cases/" + payload.id).set(payload)
    : fetch("api/save", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) }).then((r) => { if (!r.ok) throw new Error("save failed"); });
  return p.then(() => { st.where = st.db ? "account" : "disk"; })
    .catch((e) => {
      st.where = "device";
      // A viewer who may not write here gets invalid_argument on every write: stop trying.
      if (st.db && e && e.code === "invalid_argument") st.db = null;
    })
    .then(() => { st.writing = false; changed(); if (st.dirty) queueRemote(); });
}
export function saveText() {
  const st = ctl.store;
  if (st.where === "account") return "Saved to your Claude account as you go.";
  if (st.where === "disk") return "Saved on the interviewer's computer as you go.";
  return st.localOk ? "Saved in this browser as you go." : "Not saved: this browser blocks storage. Download the case before you close the page.";
}
function adopt(data) {
  if (!data || !data.caseFile || !Array.isArray(data.transcript)) return false;
  const fresh = C.newState();
  for (const k in fresh) if (data[k] === undefined) data[k] = fresh[k];
  C.SECTIONS.forEach((sec) => { if (!data.caseFile[sec.id]) data.caseFile[sec.id] = fresh.caseFile[sec.id]; });
  ctl.S = data;
  return true;
}
const hasAnswers = () => ctl.S.transcript.some((m) => m.role === "expert");
function connectStore() {
  if (!inViewer) return Promise.resolve();
  return Promise.all([window.claude.use("db"), window.claude.use("user")]).then(([db, user]) => {
    if (!db || !user) return;
    return user.id().then((uid) => {
      if (!uid) return;
      ctl.store.db = db; ctl.store.uid = uid;
      // Pick up a newer copy of this case saved from another device.
      return db.doc("interviews/" + uid + "/cases/" + ctl.S.id).get().then((snap) => {
        const d = snap.exists ? snap.data() : null;
        if (d && d.updatedAt && d.updatedAt > ctl.S.updatedAt && !ctl.busy && adopt(C.clone(d))) saveLocal();
        if (snap.exists) ctl.store.where = "account";
        // Save a case started before the account was reachable; never write an untouched one.
        if (!snap.exists && hasAnswers()) queueRemote();
        changed();
      });
    });
  }).catch(() => { /* stay in this browser */ });
}
export function newCase() {
  return flushRemote().then(() => {
    ctl.S = C.newState();
    ctl.notice = null;
    lsSet(LS_DRAFT, "");
    commit();
  });
}

/* ---- the model: Claude in the viewer, or the local server; neither means questions without follow-ups ---- */
function viewerBrain(sample) {
  return { json(input, o) {
    const opts = { cache: false, modelTier: o.tier === "complex" ? "complex" : "default" };
    if (o.signal) opts.signal = o.signal;
    if (o.onText) opts.onText = (u) => o.onText(u.text);
    if (typeof sample.json === "function") return sample.json(input, opts);
    return sample(input, opts).then((r) => {
      try { return C.parseJson(r.text); } catch (e) { throw { code: "invalid_json", message: e.message, text: r.text }; }
    });
  } };
}
function httpBrain() {
  return { json(input, o) {
    return fetch("api/consult", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ input, tier: o.tier || "default" }), signal: o.signal })
      .then((r) => r.json().then((j) => { if (!r.ok) throw { code: "upstream_error", message: (j && j.error) || "HTTP " + r.status }; return j; }))
      .then((j) => { try { return C.parseJson(j.text); } catch (e) { throw { code: "invalid_json", message: e.message, text: j.text }; } })
      .catch((e) => {
        if (e && e.name === "AbortError") throw { code: "cancelled", message: "stopped" };
        throw e && e.code ? e : { code: "upstream_error", message: String((e && e.message) || e) };
      });
  } };
}
function connectBrain() {
  if (ctl.voice) { ctl.brainKind = "voice"; changed(); return Promise.resolve(); }
  const viewer = inViewer ? window.claude.use("sample").catch(() => null) : Promise.resolve(null);
  return viewer.then((sample) => {
    if (sample) { ctl.brain = viewerBrain(sample); ctl.brainKind = "claude"; return; }
    return fetch("api/health", { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)).then((j) => {
      if (j && j.ok) { ctl.brain = httpBrain(); ctl.brainKind = "local"; ctl.store.http = true; ctl.store.where = "disk"; if (hasAnswers()) queueRemote(); }
      else ctl.brainKind = "none";
    }).catch(() => { ctl.brainKind = "none"; });
  }).then(() => {
    if (ctl.brainKind === "none" && !hasAnswers()) {
      ctl.notice = { text: "The interviewer cannot reach Claude here, so you will get each part's questions without follow-ups. Your answers are kept the same way." };
    }
    changed();
  });
}
function explain(e) {
  const code = e && e.code ? e.code : e instanceof Error ? "invalid_json" : "upstream_error";
  if (code === "cancelled") return "Stopped. Your reply is kept.";
  if (code === "rate_limited") return "Claude is busy, or your usage limit is reached. Wait a moment, then try again.";
  if (code === "session_expired") return "You have been signed out. Sign in again, then try again.";
  if (code === "refused") return "Claude declined to read that reply. Change the wording and send it again.";
  if (code === "prompt_too_large") return "This case has grown too long to send in one piece. Download it, then start over for the rest.";
  if (code === "invalid_json" || code === "empty_completion") return "The reply came back unreadable. Try again.";
  return "The reply did not come through. Try again." + (ctl.brainKind === "local" && e && e.message ? " (" + String(e.message).slice(0, 180) + ")" : "");
}
export function runTurn() {
  if (ctl.busy) return Promise.resolve();
  ctl.notice = null;
  return ctl.brainReady.then(() => {
    const S = ctl.S;
    if (!C.awaiting(S)) { changed(); return; }
    if (!ctl.brain) { S.mode = "worksheet"; C.worksheetStep(S); commit(); return; }
    S.mode = "consultant";
    const ac = new AbortController();
    ctl.busy = { text: "", abort: () => ac.abort() };
    changed();
    return ctl.brain.json(C.turnPrompt(S), { tier: "default", signal: ac.signal, onText: (t) => {
      const p = C.partialReply(t);
      if (p && ctl.busy) { ctl.busy.text = p; changed(); }
    } }).then((out) => { C.applyTurn(S, out); }).catch((e) => {
      if (e && UNAVAILABLE.includes(e.code)) {
        ctl.brain = null; ctl.brainKind = "none"; S.mode = "worksheet"; C.worksheetStep(S);
        ctl.notice = { text: "Claude is not available here, so the interview goes on with each part's questions, without follow-ups." };
      } else ctl.notice = { text: explain(e), retry: runTurn, edit: true };
    }).then(() => { ctl.busy = null; commit(); });
  });
}
export function runReadback() {
  if (ctl.busy || !ctl.brain) return Promise.resolve();
  ctl.notice = null;
  const ac = new AbortController();
  ctl.busy = { text: "Writing up what I understood. This can take a minute.", abort: () => ac.abort() };
  changed();
  return ctl.brain.json(C.readbackPrompt(ctl.S), { tier: "complex", signal: ac.signal }).then((out) => { C.applyReadback(ctl.S, out); }).catch((e) => {
    if (e && UNAVAILABLE.includes(e.code)) { ctl.brain = null; ctl.brainKind = "none"; ctl.notice = { text: "Claude is not available here, so the summary cannot be written. Download your answers as they are." }; }
    else ctl.notice = { text: explain(e), retry: runReadback };
  }).then(() => { ctl.busy = null; commit(); });
}
export function send(text) {
  text = String(text || "").trim();
  if (text && ctl.voice) { lsSet(LS_DRAFT, ""); ctl.voice.sendTyped(text); return Promise.resolve(); }
  if (!text || ctl.busy) return Promise.resolve();
  C.addExpert(ctl.S, text, { spoken: ctl.spokenSinceSend });
  ctl.spokenSinceSend = false;
  lsSet(LS_DRAFT, "");
  commit();
  return runTurn();
}
export function cancel() { if (ctl.busy) ctl.busy.abort(); }
export function skip() { if (ctl.busy) return; ctl.notice = null; C.skip(ctl.S); commit(); }
export function approve() { C.approve(ctl.S); commit(); }
export function dismissNotice() { ctl.notice = null; changed(); }
export function retryNotice() { const r = ctl.notice && ctl.notice.retry; ctl.notice = null; if (r) r(); else changed(); }
export function editLast() { const t = C.dropLastExpert(ctl.S); ctl.notice = null; commit(); return t; }

/* ---- export ---- */
function fileBase() {
  const t = C.caseTitle(ctl.S).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 48);
  return "case-" + (t || "untitled") + "-" + ctl.S.id;
}
function copyText(text) {
  const done = (ok) => { ctl.notice = { text: ok ? "Copied. Paste it into an email or a document." : "Copying is blocked here. Open the page in a browser to download the case." }; changed(); };
  const fallback = () => {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.cssText = "position:fixed;left:-9999px;top:0";
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch { ok = false; }
    ta.remove();
    done(ok);
  };
  if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(() => done(true), fallback); else fallback();
}
export function canDownload() { return !inViewer || !!ctl.downloads; }
export function download(kind) {
  const name = fileBase() + (kind === "json" ? ".json" : ".md");
  const text = kind === "json" ? JSON.stringify(ctl.S, null, 2) : C.toMarkdown(ctl.S);
  if (inViewer) {
    if (!ctl.downloads) { copyText(text); return; }
    ctl.downloads.save({ filename: name, data: text }).catch((e) => { if (!e || e.code !== "declined") copyText(text); });
    return;
  }
  const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
  const a = document.createElement("a");
  a.href = url; a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

/* ---- start ---- */
export function start() {
  let saved = null;
  try { saved = JSON.parse(lsGet(LS_STATE) || "null"); } catch { saved = null; }
  if (!adopt(saved)) ctl.S = C.newState();
  saveLocal();
  ctl.brainReady = connectBrain();
  connectStore();
  if (inViewer) window.claude.use("downloads").then((d) => { ctl.downloads = d; changed(); }).catch(() => { ctl.downloads = null; });
}
