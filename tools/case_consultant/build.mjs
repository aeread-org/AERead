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

const bundle = await esbuild.build({
  entryPoints: [join(here, "ui", "src", "app.jsx")],
  bundle: true, write: false, minify: true, format: "iife", target: "es2020",
  jsx: "automatic", define: { "process.env.NODE_ENV": '"production"' }, legalComments: "none", logLevel: "error",
});
// An inline script ends at the first "</script", wherever it appears.
const inline = (js) => js.replace(/<\/script/gi, "<\\/script");
const wordmark = read("wordmark.svg").replace(/<title>[^<]*<\/title>/, "").replace(/fill="#181918"/g, 'fill="currentColor"').replace("<svg ", '<svg focusable="false" ');
const page = [
  "<title>Case Consultant</title>",
  "<style>\n" + read("style.css") + "</style>",
  '<div id="root"></div>',
  "<script>window.__WORDMARK__ = " + inline(JSON.stringify(wordmark)) + ";</script>",
  "<script>\n" + inline(read("core.js")) + "</script>",
  "<script>\n" + inline(bundle.outputFiles[0].text) + "</script>",
  ""
].join("\n");
const RESET = ":root{color-scheme:light;padding:env(safe-area-inset-top,0px) 0 env(safe-area-inset-bottom,0px)}body{margin:0;font:14px system-ui,sans-serif;background:#fafafa}img{max-width:100%}[hidden]{display:none!important}";
export const standalone = "<!doctype html><html><head><meta charset=utf8><meta name=viewport content=\"width=device-width,initial-scale=1,viewport-fit=cover\"><style>" + RESET + "</style></head><body>" + page + "</body></html>";
mkdirSync(join(here, "dist"), { recursive: true });
writeFileSync(join(here, "dist", "index.html"), page);
writeFileSync(join(here, "dist", "standalone.html"), standalone);
console.log("built", page.length, "bytes");
