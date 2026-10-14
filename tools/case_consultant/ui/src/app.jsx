// The Case Consultant screen: a chat in the style of ChatGPT and Claude, built on assistant-ui.
// The conversation is the interview transcript kept by controller.js; this file only draws it.
import React, { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { createRoot } from "react-dom/client";
import {
  AssistantRuntimeProvider, useExternalStoreRuntime, useAuiState, WebSpeechDictationAdapter,
  ThreadPrimitive, ComposerPrimitive, MessagePrimitive, ActionBarPrimitive,
} from "@assistant-ui/react";
import * as K from "./controller.js";

const { ctl } = K;
const C = ctl.C;
const coarse = !!(window.matchMedia && window.matchMedia("(pointer: coarse)").matches);

function micAllowed() {
  if (!WebSpeechDictationAdapter.isSupported()) return false;
  try {
    const fp = document.featurePolicy || document.permissionsPolicy;
    if (fp && typeof fp.allowsFeature === "function") return fp.allowsFeature("microphone");
  } catch { /* unknown */ }
  return true;
}
const partLabel = (stage) => (stage >= C.READBACK ? "Summary" : `Part ${stage + 1} of ${C.READBACK} · ${C.STAGES[stage].title}`);
const paras = (text) => String(text || "").split(/\n{2,}/).map((p) => p.trim()).filter(Boolean);

/* ---- icons ---- */
const Icon = {
  up: <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 13V3M3.5 7.5 8 3l4.5 4.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>,
  stop: <svg viewBox="0 0 16 16" aria-hidden="true"><rect x="4" y="4" width="8" height="8" rx="1.5" fill="currentColor" /></svg>,
  mic: <svg viewBox="0 0 16 16" aria-hidden="true"><rect x="5.5" y="1" width="5" height="9" rx="2.5" fill="currentColor" /><path d="M3 7.5a5 5 0 0 0 10 0M8 12.5V15" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" /></svg>,
  copy: <svg viewBox="0 0 16 16" aria-hidden="true"><rect x="5" y="5" width="8.5" height="8.5" rx="1.8" fill="none" stroke="currentColor" strokeWidth="1.3" /><path d="M3.2 10.5H3A1.5 1.5 0 0 1 1.5 9V3A1.5 1.5 0 0 1 3 1.5h6A1.5 1.5 0 0 1 10.5 3v.2" fill="none" stroke="currentColor" strokeWidth="1.3" /></svg>,
  check: <svg viewBox="0 0 16 16" aria-hidden="true"><path d="m3.5 8.5 3 3 6-7" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>,
  down: <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 3v10M3.5 8.5 8 13l4.5-4.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>,
  dots: <svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="3" cy="8" r="1.4" fill="currentColor" /><circle cx="8" cy="8" r="1.4" fill="currentColor" /><circle cx="13" cy="8" r="1.4" fill="currentColor" /></svg>,
};

/* ---- transcript -> chat messages ---- */
function toMessages(S, busy) {
  let lastRb = -1;
  S.transcript.forEach((m, i) => { if (m.kind === "readback") lastRb = i; });
  const out = S.transcript.map((m, i) => ({
    id: "m" + i,
    role: m.role === "expert" ? "user" : "assistant",
    content: [{ type: "text", text: m.text }],
    createdAt: m.at ? new Date(m.at) : undefined,
    status: m.role === "expert" ? undefined : { type: "complete", reason: "stop" },
    metadata: { custom: { kind: m.kind || "", stage: m.stage || 0, cover: m.cover || null, spoken: !!m.spoken, first: i === 0, readback: m.kind === "readback" ? (i === lastRb ? "current" : "old") : "" } },
  }));
  if (busy) out.push({ id: "pending", role: "assistant", content: [{ type: "text", text: busy.text || "" }], status: { type: "running" }, metadata: { custom: { kind: "pending" } } });
  return out;
}

function Readback({ current }) {
  const rb = ctl.S.readback;
  if (current !== "current" || !rb) return <p className="rb stale">An earlier summary, since rewritten.</p>;
  const differ = rb.worked_checks.filter((w) => w.agrees === false);
  return (
    <div className="rb">
      {rb.summary.map((p, i) => <p key={i}>{p}</p>)}
      {rb.contradictions.length > 0 && <><h4>Two of your answers seem to disagree</h4><ul>{rb.contradictions.map((c, i) => <li key={i}>“{c.a}” and “{c.b}”. {c.ask}</li>)}</ul></>}
      {differ.length > 0 && <><h4>Your rule and your choice differ here</h4><ul>{differ.map((w, i) => <li key={i}>{w.situation}: you chose “{w.stated_choice}”, your rule gives “{w.rule_says}”. {w.note}</li>)}</ul></>}
      {rb.would_be_invented.length > 0 && <><h4>Not yet clear enough to build from</h4><ul>{rb.would_be_invented.map((x, i) => <li key={i}>{x}</li>)}</ul></>}
      {rb.stale && <p className="stale">You have corrected this since it was written.</p>}
    </div>
  );
}

function AssistantMessage({ message }) {
  const meta = (message.metadata && message.metadata.custom) || {};
  const text = message.content.map((p) => (p.type === "text" ? p.text : "")).join("");
  const running = message.status && message.status.type === "running";
  if (meta.first) {
    return (
      <MessagePrimitive.Root className="hello">
        <h1>Tell us about one decision from your work</h1>
        {paras(text).map((p, i) => <p key={i}>{p}</p>)}
        <p className="fine">Refer to people and firms by their role, not their name. Leave out anything confidential to your employer.</p>
      </MessagePrimitive.Root>
    );
  }
  return (
    <>
      {meta.kind === "open" && meta.stage > 0 && <div className="part">{partLabel(meta.stage)}</div>}
      <MessagePrimitive.Root className={"msg a" + (meta.kind === "note" ? " note" : "")}>
        {running && !text ? <span className="typing" aria-label="Thinking"><span /><span /><span /></span> : paras(text).map((p, i) => <p key={i}>{p}</p>)}
        {meta.cover && <ul className="cover">{meta.cover.map((x, i) => <li key={i}>{x}</li>)}</ul>}
        {meta.readback && <Readback current={meta.readback} />}
        {!running && (
          <ActionBarPrimitive.Root className="abar" hideWhenRunning autohide="not-last" autohideFloat="single-branch">
            <ActionBarPrimitive.Copy className="abtn" aria-label="Copy">
              <span className="when-idle">{Icon.copy}</span><span className="when-copied">{Icon.check}</span>
            </ActionBarPrimitive.Copy>
          </ActionBarPrimitive.Root>
        )}
      </MessagePrimitive.Root>
    </>
  );
}

function UserMessage({ message }) {
  const meta = (message.metadata && message.metadata.custom) || {};
  const text = message.content.map((p) => (p.type === "text" ? p.text : "")).join("");
  return (
    <MessagePrimitive.Root className="msg u">
      <div className="bub">{text}</div>
      {meta.spoken && <span className="tag">spoken</span>}
    </MessagePrimitive.Root>
  );
}

/* ---- header ---- */
function Header() {
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const ref = useRef(null);
  const S = ctl.S;
  useEffect(() => {
    if (!open) return;
    const close = (e) => { if (ref.current && !ref.current.contains(e.target)) { setOpen(false); setConfirm(false); } };
    const esc = (e) => { if (e.key === "Escape") { setOpen(false); setConfirm(false); } };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);
  const share = S.approved ? 1 : Math.min(S.stage, C.READBACK) / (C.READBACK + 1);
  const can = K.canDownload();
  return (
    <header className="top">
      <a className="brand" href="https://aeread.org" target="_blank" rel="noopener" aria-label="AERead, aeread.org" dangerouslySetInnerHTML={{ __html: window.__WORDMARK__ || "AERead" }} />
      <span className="step">{S.approved ? "Done" : partLabel(S.stage)}</span>
      <div className="menuWrap" ref={ref}>
        <button type="button" className="iconBtn" aria-haspopup="true" aria-expanded={open} aria-label="Menu" onClick={() => { setOpen(!open); setConfirm(false); }}>{Icon.dots}</button>
        {open && (
          <div className="menu" role="menu">
            <p className="menuNote">{K.saveText()}</p>
            <button type="button" role="menuitem" onClick={() => { setOpen(false); K.download("md"); }}>{can ? "Download the case (.md)" : "Copy the case as text"}</button>
            {can && <button type="button" role="menuitem" onClick={() => { setOpen(false); K.download("json"); }}>Download the full record (.json)</button>}
            <button type="button" role="menuitem" className={confirm ? "danger" : ""} onClick={() => { if (!confirm) { setConfirm(true); return; } setOpen(false); setConfirm(false); K.newCase(); }}>
              {confirm ? "Clear this case and start over" : "Start over"}
            </button>
          </div>
        )}
      </div>
      <div className="bar" aria-hidden="true"><span style={{ width: Math.round(share * 100) + "%" }} /></div>
    </header>
  );
}

/* ---- under the conversation: one next step at a time ---- */
function NextStep({ runtime }) {
  const S = ctl.S, n = ctl.notice;
  if (ctl.busy) return null;
  if (n) {
    return (
      <div className="notice" role="status">
        <span className="txt">{n.text}</span>
        {n.retry && <button type="button" className="chip" onClick={K.retryNotice}>Try again</button>}
        {n.edit && C.awaiting(S) && <button type="button" className="chip" onClick={() => { const t = K.editLast(); runtime.thread.composer.setText(t); }}>Edit my reply</button>}
        <button type="button" className="chip ghost" onClick={K.dismissNotice}>Dismiss</button>
      </div>
    );
  }
  let txt = "", btns = [];
  if (C.awaiting(S)) { txt = "Your last reply has not been read yet."; btns = [["Continue", K.runTurn]]; }
  else if (S.stage >= C.READBACK) {
    if (!ctl.brain && ctl.brainKind !== "pending") btns = [["Download your answers", () => K.download("md")]];
    else if (!S.readback) { txt = "Next I write a short summary of what I understood, for you to check."; btns = [["Write the summary", K.runReadback]]; }
    else if (S.readback.stale) btns = [["Rewrite the summary with your corrections", K.runReadback]];
    else if (!S.approved) { txt = "If the summary is right, say so. If not, reply with what to change."; btns = [["This is right", K.approve]]; }
    else { txt = K.saveText(); btns = [["Download the case", () => K.download("md")]]; }
  }
  if (!btns.length) return null;
  return (
    <div className="next">
      {txt && <span className="txt">{txt}</span>}
      {btns.map(([label, fn]) => <button key={label} type="button" className="chip primary" onClick={fn}>{label}</button>)}
    </div>
  );
}

function Composer({ runtime, mic }) {
  const running = useAuiState((s) => s.thread.isRunning);
  const dictating = useAuiState((s) => !!s.composer.dictation);
  const text = useAuiState((s) => s.composer.text);
  const [example, setExample] = useState(false);
  const S = ctl.S;
  const st = C.STAGES[S.stage];
  const hasExample = !!st.example && S.stage < C.READBACK;
  useEffect(() => { K.setDraft(text); }, [text]);
  useEffect(() => { setExample(false); }, [S.stage]);
  return (
    <div className="dock">
      <NextStep runtime={runtime} />
      {example && hasExample && <aside className="example"><b>An answer at a useful level of detail, from a buyer of electronic parts</b>{st.example}</aside>}
      <ComposerPrimitive.Root className={"composer" + (dictating ? " hearing" : "")}>
        <ComposerPrimitive.Input className="input" rows={1} placeholder={S.stage >= C.READBACK && S.readback ? "Reply with what to change" : "Reply"} submitOnEnter={!coarse} autoFocus={!coarse} aria-label="Your reply" />
        <div className="tools">
          {mic && (dictating
            ? <ComposerPrimitive.StopDictation className="iconBtn mic on" aria-label="Stop listening">{Icon.mic}</ComposerPrimitive.StopDictation>
            : <ComposerPrimitive.Dictate className="iconBtn mic" aria-label="Speak" onClick={() => { ctl.spokenSinceSend = true; }}>{Icon.mic}</ComposerPrimitive.Dictate>)}
          {running
            ? <ComposerPrimitive.Cancel className="send" aria-label="Stop">{Icon.stop}</ComposerPrimitive.Cancel>
            : <ComposerPrimitive.Send className="send" aria-label="Send">{Icon.up}</ComposerPrimitive.Send>}
        </div>
      </ComposerPrimitive.Root>
      <div className="below">
        {hasExample && <button type="button" className="link" aria-expanded={example} onClick={() => setExample(!example)}>{example ? "Hide the example" : "See an example answer"}</button>}
        {S.stage < C.READBACK && !running && <button type="button" className="link" onClick={K.skip}>Skip this question</button>}
        <span className="hint">{coarse ? "" : dictating ? "Listening. Check the numbers before you send." : "Enter to send · Shift+Enter for a new line"}</span>
      </div>
    </div>
  );
}

function App() {
  const v = useSyncExternalStore(K.subscribe, K.snapshot);
  const messages = useMemo(() => toMessages(ctl.S, ctl.busy), [v]);
  const mic = useMemo(micAllowed, []);
  const adapters = useMemo(() => (mic ? { dictation: new WebSpeechDictationAdapter({ language: navigator.language || "en-US" }) } : undefined), [mic]);
  const runtime = useExternalStoreRuntime({
    messages,
    isRunning: !!ctl.busy,
    convertMessage: (m) => m,
    onNew: async (m) => { await K.send(m.content.map((p) => (p.type === "text" ? p.text : "")).join("\n")); },
    onCancel: async () => { K.cancel(); },
    adapters,
  });
  useEffect(() => { const d = K.getDraft(); if (d) runtime.thread.composer.setText(d); }, [runtime]);
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ThreadPrimitive.Root className="app">
        <Header />
        <ThreadPrimitive.Viewport className="viewport">
          <div className="col">
            <ThreadPrimitive.Messages>
              {({ message }) => (message.role === "user" ? <UserMessage message={message} /> : <AssistantMessage message={message} />)}
            </ThreadPrimitive.Messages>
          </div>
          <ThreadPrimitive.ViewportFooter className="footer">
            <ThreadPrimitive.ScrollToBottom className="toBottom" aria-label="Scroll to the latest message">{Icon.down}</ThreadPrimitive.ScrollToBottom>
            <Composer runtime={runtime} mic={mic} />
          </ThreadPrimitive.ViewportFooter>
        </ThreadPrimitive.Viewport>
      </ThreadPrimitive.Root>
    </AssistantRuntimeProvider>
  );
}

K.start();
createRoot(document.getElementById("root")).render(<App />);
