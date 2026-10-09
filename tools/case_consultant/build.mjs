// Assemble the page. dist/index.html is what the Artifact tool publishes (it adds the document skeleton);
// dist/standalone.html wraps the same content in that skeleton for the local server.
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
const here = dirname(fileURLToPath(import.meta.url));
const read = (p) => readFileSync(join(here, "src", p), "utf8");
const wordmark = read("wordmark.svg").replace(/<title>[^<]*<\/title>/, "").replace(/fill="#181918"/g, 'fill="currentColor"').replace("<svg ", '<svg focusable="false" ');
const page = [
  "<title>Case Consultant</title>",
  "<style>\n" + read("style.css") + "</style>",
  read("body.html").replace("{{WORDMARK}}", wordmark),
  "<script>\n" + read("core.js") + "</script>",
  "<script>\n" + read("app.js") + "</script>",
  ""
].join("\n");
const RESET = ":root{color-scheme:light;padding:env(safe-area-inset-top,0px) 0 env(safe-area-inset-bottom,0px)}body{margin:0;font:14px system-ui,sans-serif;background:#fafafa}img{max-width:100%}[hidden]{display:none!important}";
export const standalone = "<!doctype html><html><head><meta charset=utf8><meta name=viewport content=\"width=device-width,initial-scale=1,viewport-fit=cover\"><style>" + RESET + "</style></head><body>" + page + "</body></html>";
mkdirSync(join(here, "dist"), { recursive: true });
writeFileSync(join(here, "dist", "index.html"), page);
writeFileSync(join(here, "dist", "standalone.html"), standalone);
console.log("built", page.length, "bytes");
