// The hosted copy (aeread.org/interview): the interview runs as a voice call. Imported before app.jsx
// so the call exists when the screen starts. build.mjs writes window.__VOICE__ into that page only.
import { ctl } from "./controller.js";
import { createVoice } from "./voice.js";

const cfg = window.__VOICE__;
if (cfg && cfg.publicKey) ctl.voice = createVoice(cfg);
