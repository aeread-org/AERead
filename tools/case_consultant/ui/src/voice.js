// The interview as a voice call, on the hosted copy only. Vapi carries the call: speech to text,
// the model (Claude, on the Vapi account), and text to speech. The model speaks each question and
// then files the answer with the file_turn tool; this module applies the filing through core.js,
// exactly as a typed turn is applied, and sends back a NOW note saying where the interview stands.
// Measured on 2026-10-14: Vapi starts speaking only once the tool call is fully written, so a
// voice turn files only what is new (core.js mergeSectionAdditive), and tools carry an empty
// request-complete message so the model is not asked to speak again after filing.
import Vapi from "@vapi-ai/web";
import { ctl, save, refresh, setDraft } from "./controller.js";

const C = window.CaseCore;
const tool = (fn) => ({ type: "function", async: true, messages: [{ type: "request-complete", content: "" }], function: fn });
// Errors after which the call is gone. Others (audio processing, level meters) leave the call running.
const FATAL = /^(validation-error|daily-call-object-creation-error|daily-call-join-error|start-method-error|daily-error|reconnect-error)$/;
const LIST_ARGS = ["numbers", "new_gaps", "closed_gaps", "summary", "contradictions", "worked_checks", "would_be_invented"];

// Tool arguments arrive as an object or as a JSON string; a nested field sometimes arrives as a string too.
function readArgs(raw) {
  let a = raw;
  if (typeof a === "string") { try { a = JSON.parse(a); } catch { a = {}; } }
  if (!a || typeof a !== "object") a = {};
  ["sections"].concat(LIST_ARGS).forEach((k) => { if (typeof a[k] === "string") { try { a[k] = JSON.parse(a[k]); } catch { /* keep */ } } });
  ["numbers", "new_gaps", "closed_gaps"].forEach((k) => { if (a[k] !== undefined && !Array.isArray(a[k])) a[k] = []; });
  return a;
}
function describe(e) {
  const m = e && (e.errorMsg || (e.error && (e.error.message || e.error.msg || e.error)) || e.message || e);
  const text = Array.isArray(m) ? m.join(" ") : typeof m === "string" ? m : JSON.stringify(m);
  return String(text || "unknown error").slice(0, 220);
}

export function createVoice(cfg) {
  const v = {
    state: "idle",        // idle | connecting | live | ending
    speaking: false,      // the interviewer's voice is playing
    muted: false,
    hearing: "",          // the words being heard right now, not yet final
    heard: [],            // final pieces of the expert's current answer, spoken
    typed: [],            // typed during the call
    saying: "",           // the interviewer's reply as the model writes it
    afterStart: null,     // "readback" or a typed answer to send once the call is up
    readbackDue: false,
    readbackAsked: false, // the summary was asked for in this call and has not arrived
    readbackRestarts: 0,
    readbackTimer: 0,
    resumes: 0,           // calls restarted after an unexpected end, this page load
    summaryCall: false,   // end this call and start a fresh one that writes the summary
    quietTimer: 0,
    thinking: false,      // the expert has finished; the interviewer's turn has not arrived
    echo: "",             // a line the page asked Vapi to say, which Vapi reports back as model output
    echoSeen: "",
    sayingSpoken: false,  // the model's text has started to play: Vapi plays a reply only once it is complete
    askWhenQuiet: false,  // in a summary call: ask for the summary once the opening line has been said
    vapi: null,
  };
  const DEBUG = (() => { try { return localStorage.getItem("case-consultant:debug") === "1"; } catch { return false; } })();
  const trace = (...a) => { if (DEBUG) console.debug("[voice] " + a.map((x) => (typeof x === "string" ? x : JSON.stringify(x))).join(" ").replace(/\n/g, " / ")); };
  // Speak a line for the interviewer; the expert can talk over it.
  const speak = (text) => { if (v.vapi && text) { trace("say", text); v.echo = text; v.vapi.say(text, false, true); } };
  const squash = (t) => String(t || "").replace(/\s+/g, "");
  // True while model output is only Vapi repeating the line the page just said.
  // Chunks that match the line are held; if the output turns out to be something else, the held
  // chunks are given back, so a reply that merely starts like the line loses nothing.
  function isEcho(chunk) {
    if (!v.echo) return false;
    const seen = squash(v.echoSeen + chunk), want = squash(v.echo);
    if (!want.startsWith(seen)) { v.saying += v.echoSeen; v.echo = ""; v.echoSeen = ""; return false; }
    v.echoSeen += chunk;
    if (seen.length >= want.length) { v.echo = ""; v.echoSeen = ""; }
    return true;
  }

  function assistant(S, waitForUser, summary) {
    const a = {
      name: "AERead case consultant",
      firstMessageMode: waitForUser ? "assistant-waits-for-user" : "assistant-speaks-first",
      firstMessageInterruptionsEnabled: true,
      backgroundSound: "off",
      maxDurationSeconds: 3600,
      // Typed answers do not count as speech, so a typing expert would be cut off by a shorter limit
      // (a simulated run that only typed ended at fifteen minutes with 900).
      silenceTimeoutSeconds: 3600,
      artifactPlan: { recordingEnabled: false },
      clientMessages: ["transcript", "tool-calls", "model-output", "speech-update", "status-update", "user-interrupted"],
      startSpeakingPlan: { waitSeconds: 0.8 },
      stopSpeakingPlan: { numWords: 2 },
      model: {
        provider: "anthropic", model: cfg.model, maxTokens: 8000, temperature: 0.3,
        messages: [{ role: "system", content: C.voiceSystemPrompt(S, { summary }) }],
        tools: [tool(C.FILE_TURN_TOOL), tool(C.READBACK_TOOL)],
      },
      transcriber: { provider: "deepgram", model: "flux-general-en", language: "en" },
      // Vapi reads any number above 2025 digit by digit ("two zero zero zero zero"); amounts must be words.
      voice: { provider: "vapi", voiceId: cfg.voiceId || "Emma", chunkPlan: { formatPlan: { numberToDigitsCutoff: 1000000000 } } },
      metadata: { case: S.id, protocol: C.VERSION },
    };
    if (!waitForUser) a.firstMessage = C.voiceFirstMessage(S, { summary });
    return a;
  }

  const note = (text, respond) => {
    trace("note", (respond ? "respond " : "") + text.length + " chars: " + text.slice(0, 80));
    if (v.vapi && v.state === "live") v.vapi.send({ type: "add-message", message: { role: "system", content: text }, triggerResponseEnabled: !!respond });
  };
  const answerSoFar = () => {
    const spoken = v.heard.join(" ").trim(), typed = v.typed.join("\n").trim();
    return { text: [spoken, typed].filter(Boolean).join("\n"), spoken: !!spoken };
  };
  function takeAnswer() {
    const a = answerSoFar();
    v.heard = []; v.typed = [];
    if (a.text) C.addExpert(ctl.S, a.text, { spoken: a.spoken });
  }
  // The model replied without filing (Vapi cannot require a tool call): keep the exchange in the
  // transcript, count it as one of the part's clarifying questions so a part cannot stall, and ask
  // for the filing with the next turn.
  function keepAside() {
    if (!v.saying.trim()) return;
    const S = ctl.S;
    if (v.readbackAsked) summaryMissing();   // it spoke instead of writing the summary
    takeAnswer();
    C.addConsultant(S, v.saying);
    if (S.stage < C.READBACK) S.followups += 1;
    v.saying = "";
    v.sayingSpoken = false;
    v.thinking = false;
    ctl.busy = null;
    save();
    note("Your last reply was spoken without a file_turn call, so what the expert said before it is not filed. File it with your next file_turn. Every turn is one file_turn call.\n" + C.voiceStatus(S));
  }
  // Late in a long call Haiku 5.5 answered the request for the summary by repeating its last reply
  // instead of calling write_readback; at the start of a call it writes it. So the summary is
  // always written in a call of its own, which opens with the case file in its instructions.
  function summaryInNewCall() {
    v.readbackDue = false;
    if (v.state !== "live" || !v.vapi) { api.start({ readback: true }); return; }
    v.summaryCall = true;
    ctl.busy = { text: "Writing up what I understood. This takes about a minute.", abort: () => {} };
    api.stop();
  }
  function summaryMissing() {
    if (!v.readbackAsked) return;
    v.readbackAsked = false;
    clearTimeout(v.readbackTimer);
    ctl.busy = null;
    ctl.notice = { text: "The summary did not come back. Press Write the summary to try again." };
    refresh();
  }
  function askForReadback() {
    v.readbackDue = false;
    v.readbackAsked = true;
    clearTimeout(v.readbackTimer);
    v.readbackTimer = setTimeout(summaryMissing, 120000);
    ctl.busy = { text: "Writing up what I understood. This takes about a minute.", abort: () => {} };
    refresh();
    note(C.voiceReadbackNote(ctl.S), true);
  }

  // One reply can be spoken as two stretches of audio, so wait for a short silence, or at most maxMs.
  function whenQuiet(maxMs) {
    clearTimeout(v.quietTimer);
    v.quietTimer = setTimeout(() => { if (v.readbackDue && !v.speaking) summaryInNewCall(); else if (v.readbackDue) whenQuiet(maxMs); }, maxMs);
  }
  function fileTurn(args) {
    const S = ctl.S;
    takeAnswer();
    // The reply is the tool's reply field, spoken here. Text the model wrote outside the call has
    // already been spoken by Vapi, so it stands as the reply instead and nothing is said twice.
    const outside = v.saying.trim();
    let reply = outside || (typeof args.reply === "string" ? args.reply.trim() : "");
    v.saying = "";
    v.sayingSpoken = false;
    v.thinking = false;
    ctl.busy = null;
    if (!reply) reply = args.move === "next" && S.stage < C.READBACK ? C.STAGES[S.stage + 1].opening : "Go on.";
    if (!outside) speak(reply);
    try { C.applyTurn(S, Object.assign({}, args, { reply }), { additive: true }); }
    catch { C.addConsultant(S, reply); }
    save();
    // Ask for the summary once the closing reply has been spoken (it starts about a second after filing).
    if (S.stage === C.READBACK && !S.readback) { v.readbackDue = true; whenQuiet(20000); }
    else note(C.voiceStatus(S));
  }
  function writeReadback(args) {
    const S = ctl.S;
    v.readbackAsked = false;
    clearTimeout(v.readbackTimer);
    const outside = v.saying.trim();
    v.saying = "";
    v.sayingSpoken = false;
    v.thinking = false;
    ctl.busy = null;
    try {
      C.applyReadback(S, C.normalizeReadback(args));
      ctl.notice = null;
      if (!outside) speak("The summary is on your screen. Read it, and tell me what is wrong or missing.");
    } catch {
      ctl.notice = { text: "The summary came back empty. Press Write the summary to try again." };
    }
    save();
    note(C.voiceStatus(S));
  }

  function onMessage(m) {
    if (!m || typeof m !== "object") return;
    if (m.type === "status-update" && m.status === "ended") trace("ended", m.endedReason || "");
    if (m.type !== "transcript" || m.transcriptType === "final") trace(m.type, m.type === "tool-calls" ? (m.toolCallList || []).map((t) => t.function && [t.function.name, JSON.stringify(t.function.arguments).slice(0, 600)]) : m.output || m.transcript || m.status || "");
    if (m.type === "transcript" && m.role === "user") {
      if (m.transcriptType === "final") {
        if (v.saying.trim() && !v.speaking) keepAside();
        if (m.transcript && m.transcript.trim()) { v.heard.push(m.transcript.trim()); v.thinking = true; }
        v.hearing = "";
      } else { v.hearing = m.transcript || ""; v.thinking = false; }
      refresh();
    } else if (m.type === "model-output") {
      if (typeof m.output === "string" && !isEcho(m.output)) {
        // Two text blocks of one reply arrive back to back with no space between the sentences.
        v.saying += /[.?!]$/.test(v.saying) && /^[A-Z]/.test(m.output) ? " " + m.output : m.output;
        ctl.busy = { text: v.saying, abort: () => {} };
        refresh();
      }
    } else if (m.type === "tool-calls") {
      (m.toolCallList || []).forEach((tc) => {
        const name = tc && tc.function && tc.function.name;
        const args = readArgs(tc && tc.function && tc.function.arguments);
        if (name === "file_turn") fileTurn(args);
        else if (name === "write_readback") writeReadback(args);
      });
    } else if (m.type === "user-interrupted") {
      // The reply being written was cut off and will be written again; the words already filed stay.
      v.saying = "";
      if (ctl.busy && !v.readbackDue) ctl.busy = null;
      refresh();
    }
  }

  function finish(message) {
    clearTimeout(v.quietTimer);
    // A call that drops while the summary is due is started again for the summary alone, once.
    const S = ctl.S;
    const wasLive = v.state === "live";
    const retry = v.state !== "ending" && S.stage === C.READBACK && !S.readback && (v.readbackDue || v.readbackAsked) && v.readbackRestarts < 1;
    v.readbackAsked = false;
    if (v.vapi) { try { v.vapi.removeAllListeners(); } catch { /* gone */ } }
    v.vapi = null;
    v.state = "idle";
    v.speaking = false;
    v.hearing = "";
    v.afterStart = null;
    v.readbackDue = false;
    v.askWhenQuiet = false;
    if (v.saying.trim() && v.sayingSpoken) keepAside();
    v.saying = "";
    // An answer that was never filed stays in the transcript; the next call puts it back in the reply box.
    takeAnswer();
    ctl.busy = null;
    if (v.summaryCall) {
      v.summaryCall = false;
      ctl.busy = { text: "Writing up what I understood. This takes about a minute.", abort: () => {} };
      save();
      setTimeout(() => api.start({ readback: true }), 800);
      return;
    }
    if (retry) { v.readbackRestarts += 1; save(); trace("restart for the summary"); setTimeout(() => api.start({ readback: true }), 800); return; }
    // Any other unexpected end of a live call: carry on in a new call, a few times at most.
    if (message && wasLive && !S.approved && v.resumes < 3) {
      v.resumes += 1;
      ctl.notice = { text: "The line dropped. Reconnecting where we stopped." };
      save();
      trace("resume after an unexpected end");
      setTimeout(() => api.start({ resume: true }), 800);
      return;
    }
    if (message) ctl.notice = { text: message };
    save();
  }

  const api = {
    get state() { return v.state; },
    get speaking() { return v.speaking; },
    get muted() { return v.muted; },
    get writing() { return !!ctl.busy || v.thinking; },
    pendingAnswer() { return [v.heard.join(" "), v.typed.join("\n"), v.hearing].filter((x) => x && x.trim()).join(" ").trim(); },
    start(opts = {}) {
      if (v.state !== "idle") return;
      const S = ctl.S;
      // An answer left unfiled by an earlier call: after a dropped line it is sent on to the new call;
      // otherwise it goes back to the reply box instead of being lost.
      if (C.awaiting(S)) {
        const t = C.dropLastExpert(S);
        if (t && opts.resume) opts = Object.assign({}, opts, { typed: t });
        else if (t) { setDraft(t); ctl.restoreDraft = t; }
      }
      ctl.notice = null;
      v.state = "connecting";
      v.afterStart = opts.typed ? { typed: opts.typed } : opts.readback ? "readback" : null;
      v.echo = ""; v.echoSeen = ""; v.saying = ""; v.sayingSpoken = false;
      refresh();
      const vapi = new Vapi(cfg.publicKey);
      v.vapi = vapi;
      vapi.on("call-start", () => {
        v.state = "live";
        const after = v.afterStart;
        v.afterStart = null;
        refresh();
        if (after === "readback") {
          // Ask once the opening line has been said, so its audio is not mistaken for the model's reply.
          v.askWhenQuiet = true;
          ctl.busy = { text: "Writing up what I understood. This takes about a minute.", abort: () => {} };
          clearTimeout(v.quietTimer);
          v.quietTimer = setTimeout(() => { if (v.askWhenQuiet && !v.speaking) { v.askWhenQuiet = false; askForReadback(); } }, 12000);
        }
        else if (after && after.typed) api.sendTyped(after.typed);
      });
      vapi.on("call-end", () => finish(v.state === "ending" ? null : "The call ended. Press Talk to carry on where you stopped."));
      vapi.on("speech-start", () => { v.speaking = true; v.thinking = false; if (v.saying.trim()) v.sayingSpoken = true; refresh(); });
      vapi.on("speech-end", () => {
        v.speaking = false;
        refresh();
        clearTimeout(v.quietTimer);
        v.quietTimer = setTimeout(() => {
          if (v.speaking) return;
          if (v.saying.trim() && v.sayingSpoken) keepAside();   // a reply that came with no filing has been said in full
          if (v.askWhenQuiet) { v.askWhenQuiet = false; askForReadback(); }
          if (v.readbackDue) summaryInNewCall();
        }, 1500);
      });
      vapi.on("message", onMessage);
      vapi.on("error", (e) => {
        const type = e && e.type;
        if (type === "audio-start-failed") { ctl.notice = { text: "The browser blocked the interviewer's voice. Tap the page once to hear it." }; refresh(); return; }
        if (type ? !FATAL.test(type) : v.state === "live") { console.warn("[voice]", type || "", describe(e)); return; }
        if (v.state !== "idle") finish("The call stopped: " + describe(e) + " Press Talk to try again.");
      });
      vapi.start(assistant(S, !!opts.typed, !!opts.readback)).then((call) => {
        if (!call && v.state === "connecting") finish("The call did not start. Check that the microphone is allowed, then press Talk again.");
      }).catch((e) => { if (v.state !== "idle") finish("The call did not start: " + describe(e)); });
    },
    stop() {
      if (!v.vapi) { v.state = "idle"; refresh(); return; }
      v.state = "ending";
      refresh();
      v.vapi.stop().catch(() => finish(null));
    },
    toggleMute() {
      if (!v.vapi) return;
      v.muted = !v.vapi.isMuted();
      v.vapi.setMuted(v.muted);
      refresh();
    },
    sendTyped(text) {
      if (v.state === "idle") { api.start({ typed: text }); return; }
      if (v.state !== "live") { v.afterStart = { typed: text }; return; }
      if (v.saying.trim() && !v.speaking) keepAside();
      v.typed.push(text);
      v.thinking = true;
      v.vapi.send({ type: "add-message", message: { role: "user", content: text }, triggerResponseEnabled: true });
      refresh();
    },
    skip() {
      const S = ctl.S;
      if (S.stage >= C.READBACK) return;
      takeAnswer();
      C.skip(S);
      save();
      if (v.state !== "live") return;
      if (S.stage === C.READBACK) askForReadback();
      else { speak(C.STAGES[S.stage].opening); note(C.voiceStatus(S)); }
    },
    writeSummary() {
      if (v.state === "idle" || v.state === "live") summaryInNewCall();
    },
    approve() {
      C.approve(ctl.S);
      save();
      if (v.state === "live" && v.vapi) { v.state = "ending"; refresh(); v.vapi.say("Thank you. That is the finished case. You can download it from the menu.", true); }
    },
  };
  return api;
}
