// One model call through the Claude Code CLI: no tools, no project settings, one prompt in, one text out.
import { spawn } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

export const MODELS = { default: "claude-sonnet-5-5", complex: "claude-opus-5-5" };
const SYSTEM = "You complete the one task in the message and reply with exactly the output it asks for, and nothing else.";
const EMPTY_DIR = mkdtempSync(join(tmpdir(), "case-consultant-"));

export function askClaude(input, { model = MODELS.default, effort = "low", timeoutMs = 240000, system = SYSTEM } = {}) {
  return new Promise((resolve, reject) => {
    const args = ["--safe-mode", "--print", "--model", model, "--effort", effort, "--tools", "", "--permission-mode", "dontAsk",
      "--no-session-persistence", "--output-format", "json", "--system-prompt", system];
    const started = Date.now();
    const child = spawn("claude", args, { cwd: EMPTY_DIR, stdio: ["pipe", "pipe", "pipe"] });
    let out = "", err = "";
    const timer = setTimeout(() => { child.kill("SIGKILL"); reject(new Error("The model did not answer within " + Math.round(timeoutMs / 1000) + " seconds.")); }, timeoutMs);
    child.stdout.on("data", (d) => { out += d; });
    child.stderr.on("data", (d) => { err += d; });
    child.on("error", (e) => { clearTimeout(timer); reject(e); });
    child.on("close", (code) => {
      clearTimeout(timer);
      let parsed = null;
      try { parsed = JSON.parse(out); } catch { /* fall through */ }
      if (!parsed || parsed.is_error || code !== 0) {
        // The CLI reports a refusal (for example exhausted credits) in stdout JSON, not stderr.
        return reject(new Error((parsed && parsed.result) || err.trim() || "The Claude CLI exited with code " + code + "."));
      }
      resolve({ text: String(parsed.result || ""), seconds: (Date.now() - started) / 1000, model });
    });
    child.stdin.end(input);
  });
}
