"""Render the draft paper sections 5 (case studies) and 6 (quality control) as one PDF.

The markdown on branch docs/paper-case-studies-qc is the source of truth; this script only
lays it out, so edit the markdown and rerun:

    python3 build_paper_pdf.py [<worktree>] [<out.pdf>]

It drops each file's status preamble (everything before the first horizontal rule), joins
the two sections, merges their reference lists, moves the two "Sources for the numbers"
tables into an appendix, writes HTML beside the PDF and prints it with headless Chrome.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import markdown

HERE = Path(__file__).parent
ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "AERead-worktrees/paper-sections"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "aeread_paper_sections_5_6_draft.pdf"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
FILES = [
    ("Case studies", ROOT / "docs/research/paper_case_studies.md"),
    ("Quality control", ROOT / "docs/research/paper_qc_design.md"),
]


def split(text: str) -> tuple[str, list[str], str]:
    """Body without preamble, its reference lines, and its sources table."""
    body = text.split("\n---\n", 1)[1]
    body, _, sources = body.partition("### Sources for the numbers in this section")
    body, _, refs_part = body.partition("### References")
    refs = [line for line in refs_part.splitlines() if line.startswith("- [")]
    return body.strip(), refs, sources.strip()


_B = r"(?<![A-Za-z0-9_])([A-Za-zα-ωℓΠΛΘ])"
_W = r"([A-Za-z0-9ℓσβθρκ*]+)"
_MATH = [
    (re.compile(_B + r"\^" + _W + "_" + _W), r"\1<sup>\2</sup><sub>\3</sub>"),
    (re.compile(_B + r"_\{([^}]+)\}"), r"\1<sub>\2</sub>"),
    (re.compile(_B + "_" + _W + r"\^" + _W), r"\1<sub>\2</sub><sup>\3</sup>"),
    (re.compile(r"(?<![A-Za-z0-9_])(max|min)_" + _W), r"\1<sub>\2</sub>"),
    (re.compile(_B + "_" + _W), r"\1<sub>\2</sub>"),
    (re.compile(r"([A-Za-z0-9)\]*])\^\(([^)]*)\)"), r"\1<sup>\2</sup>"),
    (re.compile(_B + r"\^" + _W), r"\1<sup>\2</sup>"),
    (re.compile(r"(?<=\*)\^" + _W), r"<sup>\1</sup>"),
]


def typeset(html: str) -> str:
    """Subscripts and superscripts in prose; code spans and tags are left alone."""
    parts = re.split(r"(<code>.*?</code>|<pre>.*?</pre>|<[^>]+>)", html, flags=re.S)
    for i, part in enumerate(parts):
        if part.startswith("<"):
            continue
        for pattern, repl in _MATH:
            part = pattern.sub(repl, part)
        parts[i] = part
    return "".join(parts)


def to_html(md: str) -> str:
    out = typeset(markdown.markdown(md, extensions=["tables", "fenced_code"]))
    out = out.replace("<p><strong>Table", '<p class="caption"><strong>Table')
    out = out.replace("10⁻⁸", "10<sup>−8</sup>")
    # Keep incident ids (HL-D-04) on one line.
    out = re.sub(r"(?<![\w/-])((?:HL|P|DC)-[DOTJ]-\d+)", r'<span class="nb">\1</span>', out)
    # Relative links point into the repository, which the PDF does not carry.
    return re.sub(r'<a href="(?!https?:)[^"]*">(.*?)</a>', r"\1", out)


bodies, references, sources = [], [], []
for name, path in FILES:
    body, refs, src = split(path.read_text(encoding="utf-8"))
    bodies.append(body)
    seen = {r.split("]")[0] for r in references}
    references += [r for r in refs if r.split("]")[0] not in seen]
    sources.append((name, src))

def appendix_body(name: str) -> str:
    text = (ROOT / "docs/research" / name).read_text(encoding="utf-8")
    return text.split("\n---\n", 1)[1].strip()


specs = appendix_body("paper_appendix_case_specs.md")
details = appendix_body("paper_appendix_details.md")
appendix = "\n\n".join(f"### G.{i} {name}\n\n{src}" for i, (name, src) in enumerate(sources, 1))
md = "\n\n".join(bodies) + "\n\n## References\n\n" + "\n".join(references)
md += "\n\n" + specs + "\n\n" + details
# Appendix G (artifacts) is the last part of paper_appendix_details.md; the per-number
# source tables stay in the repository files and are not printed.

CSS = """
@page { size: letter; margin: 0.85in 0.9in 0.9in 0.9in;
        @bottom-center { content: counter(page); font: 9pt "Helvetica Neue", Arial, sans-serif; color: #666; } }
html { -webkit-print-color-adjust: exact; }
body { font-family: Charter, "Iowan Old Style", Georgia, serif; font-size: 10.4pt; line-height: 1.38;
       color: #111; margin: 0; }
.title { font-family: "Helvetica Neue", Arial, sans-serif; font-size: 19pt; font-weight: 700;
         line-height: 1.2; margin: 0 0 4pt; }
.author { font-family: "Helvetica Neue", Arial, sans-serif; font-size: 11pt; margin: 0 0 2pt; }
.sub { font-family: "Helvetica Neue", Arial, sans-serif; font-size: 9.5pt; color: #555; margin: 0 0 6pt; }
.note { font-size: 9pt; color: #333; background: #f3f4f6; border-left: 3px solid #9ca3af;
        padding: 6pt 9pt; margin: 8pt 0 14pt; }
h2, h3 { font-family: "Helvetica Neue", Arial, sans-serif; break-after: avoid; }
h2 { font-size: 14pt; margin: 18pt 0 6pt; padding-top: 4pt; border-top: 1.2pt solid #111; }
h3 { font-size: 11pt; margin: 13pt 0 4pt; }
p { margin: 0 0 7pt; text-align: justify; hyphens: auto; }
ul, ol { margin: 0 0 7pt; padding-left: 18pt; }
li { margin: 0 0 3pt; }
code { font-family: Menlo, monospace; font-size: 8.3pt; }
pre { background: #f6f6f6; padding: 6pt 9pt; font-size: 8.3pt; break-inside: avoid; }
p.caption { font-size: 9pt; margin: 10pt 0 3pt; text-align: left; break-after: avoid; }
table { border-collapse: collapse; width: 100%; font-size: 8.3pt; line-height: 1.28;
        margin: 0 0 10pt; border-top: 1.1pt solid #111; border-bottom: 1.1pt solid #111; }
thead th { border-bottom: 0.7pt solid #111; font-family: "Helvetica Neue", Arial, sans-serif;
           font-weight: 600; text-align: left; vertical-align: bottom; }
th, td { padding: 2.6pt 5pt; vertical-align: top; }
tbody tr + tr td { border-top: 0.3pt solid #ddd; }
tr { break-inside: avoid; }
.nb { white-space: nowrap; }
td code { font-size: 6.9pt; }
sup { font-size: 70%; line-height: 0; }
td[style*="right"] { white-space: nowrap; }
th { white-space: normal; }
h2:last-of-type ~ h3 + table { font-size: 7.6pt; }
"""

html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>AERead: case studies and quality control (draft)</title><style>{CSS}</style></head><body>
<p class="title">AERead: case studies and quality control</p>
<p class="author">Chenyu Li</p>
<p class="sub">Draft of sections 5 and 6 and appendices A–G of the environment paper · 13 October 2026</p>
<p class="note">Working draft. One result is confirmatory (Housing v14), one is a test declared
before its runs (the data-center signalling test), and everything else is a development probe
and is labelled so. Incident ids (HL-, P-, DC-) refer to the incident log on each case's
branch. Source: <code>docs/research/paper_case_studies.md</code> and
<code>docs/research/paper_qc_design.md</code> on branch <code>docs/paper-case-studies-qc</code>.</p>
{to_html(md)}
</body></html>"""

html_path = OUT.with_suffix(".html")
html_path.write_text(html, encoding="utf-8")
subprocess.run(
    [CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
     f"--print-to-pdf={OUT}", html_path.resolve().as_uri()],
    check=False, capture_output=True,
)
# Headless Chrome sometimes exits non-zero in teardown after writing the file; trust the file.
if not OUT.exists() or OUT.stat().st_mtime < html_path.stat().st_mtime:
    raise SystemExit("Chrome did not write the PDF")
print(OUT)
