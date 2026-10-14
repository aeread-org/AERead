// Assemble the page. dist/index.html is what the Artifact tool publishes (it adds the document skeleton);
// dist/standalone.html wraps the same content in that skeleton for the local server or a static host.
// The chat screen (ui/src) is React on assistant-ui, bundled here by esbuild into one inline script:
// run `npm ci --prefix ui` once before building.
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
const here = dirname(fileURLToPath(import.meta.url));
const read = (p) => readFileSync(join(here, "src", p), "utf8");
const esbuild = createRequire(join(here, "ui", "package.json"))("esbuild");

const bundleOf = (entry) => esbuild.build({
  entryPoints: [join(here, "ui", "src", entry)],
  bundle: true, write: false, minify: true, format: "iife", target: "es2020",
  jsx: "automatic", define: { "process.env.NODE_ENV": '"production"' }, legalComments: "none", logLevel: "error",
}).then((r) => r.outputFiles[0].text);
const bundle = await bundleOf("app.jsx");
// An inline script ends at the first "</script", wherever it appears.
const inline = (js) => js.replace(/<\/script/gi, "<\\/script");
const wordmark = read("wordmark.svg").replace(/<title>[^<]*<\/title>/, "").replace(/fill="#181918"/g, 'fill="currentColor"').replace("<svg ", '<svg focusable="false" ');
const page = [
  "<title>Case Consultant</title>",
  "<style>\n" + read("style.css") + "</style>",
  '<div id="root"></div>',
  "<script>window.__WORDMARK__ = " + inline(JSON.stringify(wordmark)) + ";</script>",
  "<script>\n" + inline(read("core.js")) + "</script>",
  "<script>\n" + inline(bundle) + "</script>",
  ""
].join("\n");
const RESET = ":root{color-scheme:light;padding:env(safe-area-inset-top,0px) 0 env(safe-area-inset-bottom,0px)}body{margin:0;font:14px system-ui,sans-serif;background:#fafafa}img{max-width:100%}[hidden]{display:none!important}";
export const standalone = "<!doctype html><html><head><meta charset=utf8><meta name=viewport content=\"width=device-width,initial-scale=1,viewport-fit=cover\"><style>" + RESET + "</style></head><body>" + page + "</body></html>";
mkdirSync(join(here, "dist"), { recursive: true });
writeFileSync(join(here, "dist", "index.html"), page);
writeFileSync(join(here, "dist", "standalone.html"), standalone);
console.log("built", page.length, "bytes");

// The hosted copy with voice, dist/interview.html, for aeread.org/interview. It needs a Vapi public key
// (a browser key, limited by its allowed origins), read from the environment and written only into this
// file: VAPI_PUBLIC_KEY=... node build.mjs. Optional: VAPI_MODEL, VAPI_VOICE.
const KEY = (process.env.VAPI_PUBLIC_KEY || "").trim();
if (KEY) {
  const voice = { publicKey: KEY, model: process.env.VAPI_MODEL || "claude-haiku-5-5", voiceId: process.env.VAPI_VOICE || "Emma" };
  const hosted = "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1,viewport-fit=cover\">" +
    "<meta name=\"robots\" content=\"noindex, nofollow\"><title>Case Consultant · AERead</title><link rel=\"icon\" href=\"/favicon.svg\" type=\"image/svg+xml\">" +
    "<style>" + RESET + "\n" + read("style.css") + "</style></head><body>" + [
      '<div id="root"></div>',
      "<script>window.__WORDMARK__ = " + inline(JSON.stringify(wordmark)) + ";window.__VOICE__ = " + inline(JSON.stringify(voice)) + ";</script>",
      "<script>\n" + inline(read("core.js")) + "</script>",
      "<script>\n" + inline(await bundleOf("hosted.jsx")) + "</script>",
    ].join("\n") + "</body></html>";
  writeFileSync(join(here, "dist", "interview.html"), hosted);
  console.log("built interview.html", hosted.length, "bytes, model", voice.model);
}
