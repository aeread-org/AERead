"""Export the working draft as a LaTeX project (``latex/``) from the same sources ``build.py`` reads.

    python export_latex.py            # writes latex/ and compiles latex/main.pdf with lualatex + bibtex

The LaTeX sections (abstract, Sections 1-4 and 7, Appendix H) are copied with their placeholders replaced by the
figures and Table 2.1 that ``build.py`` draws for HTML. The Markdown sections (Sections 5 and 6, Appendices A-G) go
through pandoc with the numbers taken out of their headings, so LaTeX numbers them in the same order the HTML build
does. Sources tables are left out, as ``build.py`` leaves them out of the PDF. Requires pandoc and lualatex.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source"
OUT = ROOT / "latex"
TITLE = "AERead: Evaluating Economic Decisions in Interactive Environments"
CITES = {"[AV]": "[@li2026activities]", "[ABC]": "[@zhu2025abc]", "[TB]": "[@zhang2026termsbench]"}
PROPERTIES = ["Value against a reference with stated information", "Counterpart is part of the case", "Typed shortfall",
              "World generator with admission", "Quality control over populations of worlds",
              "Scores recomputed from sealed evidence", "Several economic activities on one runtime"]
CASE_CAPTION = (r"\textbf{The three levels of an AERead evaluation,} with the Data-center agreement as the example. The "
                r"runtime hosts several case families (left). A case draws a population of worlds and admits those where "
                r"the decision matters; quality control runs over that population (centre). In one world, the agent holds "
                r"a seat, a counterpart holds another, and the score is compared with the case reference and split into "
                r"shortfall classes (right). Dashed lines mean ``contains'', not a sequence. Each panel lists the "
                r"properties of Section~1 that belong to its level. The dot pattern and the score bar are schematic.")
ARCH_CAPTION = (r"\textbf{AERead architecture.} Families define the economic world and reference; the runtime coordinates "
                r"seat policies and retains execution evidence. Agents receive only their seat observations, while "
                r"scoring uses explicitly declared reference access. Replay checks receipt consistency; separate headline "
                r"derivations require their own verification. Applied coverage and QC verdicts vary by campaign "
                r"(Appendices F and H).")
RUNTIME_TIKZ = r"""\begin{tikzpicture}[box/.style={draw=black!70, fill=black!3, rounded corners=1pt, minimum width=4.2cm,
  minimum height=1.05cm, align=center, font=\footnotesize}, >=Stealth]
\node[box] (a) at (0,0) {World, block, profiles, seeds\\Resolved plan};
\node[box] (b) at (4.7,0) {Freeze observations\\Act, then transition};
\node[box] (c) at (9.4,0) {Provider / tool events\\Action envelopes};
\node[box] (d) at (9.4,-1.7) {Reconstruct state and score\\Seal evidence};
\node[box] (e) at (4.7,-1.7) {Receipt with typed scores\\Reference values};
\node[box] (f) at (0,-1.7) {Replay state and score\\No model call};
\draw[->] (a) -- (b); \draw[->] (b) -- (c); \draw[->] (c) -- (d); \draw[->] (d) -- (e); \draw[->] (e) -- (f);
\end{tikzpicture}"""

PREAMBLE = r"""\documentclass[10pt]{article}
\usepackage[margin=0.9in]{geometry}
\usepackage{fontspec}
\directlua{luaotfload.add_fallback("aereadfallback", {"STIX Two Math:mode=harf;", "Apple Symbols:mode=harf;", "Helvetica Neue:mode=harf;",
  "Arial Unicode MS:mode=harf;"})}
\setmainfont{Times New Roman}[RawFeature={fallback=aereadfallback}]
\setsansfont{Helvetica Neue}[RawFeature={fallback=aereadfallback}]
\setmonofont{Menlo}[Scale=0.85, RawFeature={fallback=aereadfallback}]
\usepackage{amsmath,amssymb}
\usepackage{graphicx,booktabs,longtable,array,calc,multirow,xcolor,tikz,caption,etoolbox}
\AtBeginEnvironment{longtable}{\footnotesize\setlength{\tabcolsep}{4pt}\sloppy}
\setlength{\emergencystretch}{3em}
\usetikzlibrary{arrows.meta}
\usepackage[round,authoryear]{natbib}
\usepackage[hidelinks]{hyperref}
\usepackage{xurl}  % long URLs break anywhere instead of running into the margin
\setcounter{secnumdepth}{2}
\captionsetup{font=small,labelfont=bf,labelsep=period}
% pandoc's helpers
\providecommand{\tightlist}{\setlength{\itemsep}{0pt}\setlength{\parskip}{0pt}}
\makeatletter
\newsavebox\pandoc@box
\newcommand*\pandocbounded[1]{\sbox\pandoc@box{#1}\ifdim\wd\pandoc@box>\linewidth\resizebox{\linewidth}{!}{#1}\else#1\fi}
\makeatother
% the sources' own macros
\newcommand{\code}[1]{\texttt{#1}}
\newcommand{\qcref}{Section~\ref{sec:qc}}
\newcommand{\casesref}{Section~\ref{sec:cases}}
\renewcommand{\arraystretch}{1.12}
\newcolumntype{P}[1]{>{\raggedright\arraybackslash}p{#1}}
"""


LATEX_SPECIALS = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
                  "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}


def latex_text(text: str) -> str:
    return "".join(LATEX_SPECIALS.get(char, char) for char in text)


def display_equations(text: str) -> str:
    """`[[eq A.3]] expression` paragraphs become numbered display equations (raw LaTeX through pandoc)."""
    def block(match: re.Match) -> str:
        body = re.sub(r"\*\*|`", "", match[2].strip())  # the expression is set as text; drop Markdown emphasis and code marks
        text = latex_text(body)
        # text inside math cannot break; a long expression goes in a box that wraps, left-aligned like the PDF
        inner = rf"\parbox{{0.86\linewidth}}{{\raggedright {text}}}" if len(body) > 70 else rf"\text{{{text}}}"
        return f"```{{=latex}}\n\\[ {inner} \\tag{{{match[1]}}} \\]\n```"
    return re.sub(r"^\[\[eq ([A-Z]?\.?[0-9]+(?:\.[0-9]+)*)\]\][ \t]*(.+(?:\n(?!\n).+)*)", block, text, flags=re.M)


def pandoc_md(text: str) -> str:
    text = display_equations(text)
    for old, new in CITES.items():
        text = text.replace(old, new)
    text = re.sub(r"\]\(figures/([^)]+)\.svg\)", r"](figures/\1.png)", text)
    out = subprocess.run(["pandoc", "-f", "markdown-tex_math_dollars-raw_tex-implicit_figures", "-t", "latex", "--natbib",
                          "--wrap=preserve", "--columns=40"], input=text, capture_output=True, text=True, check=True)
    if out.stderr.strip():
        print(out.stderr.strip())
    return out.stdout


def markdown_body(name: str) -> str:
    text = (SOURCE / name).read_text().split("\n---\n", 1)[1]
    text = text.partition("### Sources for the numbers in this section")[0]
    return text.partition("### References")[0].strip()


def renumber(text: str) -> str:
    """Take the numbers out of the headings and set their depth from them, so LaTeX numbers in the same order."""
    def heading(match: re.Match) -> str:
        hashes, rest = match.group(1), match.group(2).strip()
        m = re.match(r"^(?:Appendix\s+)?([A-H]|\d+)((?:\.\d+)*)\.?\s+(.*)$", rest)
        if not m:
            return f"{'#' * max(1, len(hashes) - 1)} {rest}"  # an unnumbered heading keeps its depth
        depth = 1 + m.group(2).count(".")
        title = m.group(3)
        if depth >= 3:  # LaTeX numbers to depth 2; a deeper number stays in the title
            return f"### {m.group(1)}{m.group(2)} {title}"
        return f"{'#' * depth} {title}"
    return re.sub(r"^(#{2,4})\s+(.*)$", heading, text, flags=re.M)


def prepare_tex(text: str) -> str:
    text = re.sub(r"\\code\{([^}]+)\}", lambda m: r"\texttt{" + m[1].replace("_", r"\_") + "}", text)
    return text


def comparison_table() -> str:
    spec = json.loads((SOURCE / "comparison_table.json").read_text())
    marks = {"full": r"$\bullet$", "partial": r"$\circ$", "no": "--"}
    rows = []
    for row in spec["rows"]:
        name = row["name"] + (r"$^{*}$" if row.get("this_paper") else "")
        rows.append(name.replace("&", r"\&") + " & " + " & ".join(marks[m] for m in row["marks"]) + r" \\")
    head = "Benchmark & " + " & ".join(str(i) for i in range(1, len(PROPERTIES) + 1)) + r" \\"
    legend = "; ".join(f"{i}. {p}" for i, p in enumerate(PROPERTIES, 1))
    note = spec["note"].replace("%", r"\%").replace("&", r"\&")
    return (r"\begin{table}[htbp]\centering\small\renewcommand{\thetable}{2.1}" "\n"
            r"\caption{\textbf{The seven properties in related benchmarks,} read from each paper's description of its "
            r"own method: $\bullet$ present, $\circ$ partly present, -- absent. Columns: " + legend + ". " + note + "}\n"
            r"\label{tab:comparison}" "\n" r"\begin{tabular}{l" + "c" * len(PROPERTIES) + "}\n\\toprule\n" + head +
            "\n\\midrule\n" + "\n".join(rows) + "\n\\bottomrule\n\\end{tabular}\n\\end{table}\n")


#: Unicode subscript letters no installed text font carries in full; written as LaTeX so any font works.
SUBSCRIPTS = {"ₐ": "a", "ₑ": "e", "ₒ": "o", "ₓ": "x", "ₕ": "h", "ₖ": "k", "ₗ": "l", "ₘ": "m", "ₙ": "n", "ₚ": "p",
              "ₛ": "s", "ₜ": "t", "ᵢ": "i", "ⱼ": "j", "ᵣ": "r", "ᵤ": "u", "ᵥ": "v"}


def subscripts(text: str) -> str:
    for char, letter in SUBSCRIPTS.items():
        text = text.replace(char, r"\textsubscript{" + letter + "}")
    return sloppy_code_paragraphs(breakable_code(text))


def sloppy_code_paragraphs(text: str) -> str:
    """A paragraph made mostly of code paths cannot be justified; let it set loosely instead of overflowing."""
    blocks = text.split("\n\n")
    for i, block in enumerate(blocks):
        if block.count(r"\texttt{") >= 5 and not block.lstrip().startswith("\\"):
            blocks[i] = "\\begin{sloppypar}\n" + block + "\n\\end{sloppypar}"
    return "\n\n".join(blocks)


def breakable_code(text: str) -> str:
    """Let long code paths break after a slash, an underscore or a dot, so they stay inside the margin."""
    def inner(match: re.Match) -> str:
        body = match.group(1)
        if len(body) < 12:
            return match.group(0)
        body = body.replace("/", "/\\allowbreak{}").replace(r"\_", r"\_\allowbreak{}").replace(".", ".\\allowbreak{}")
        return r"\texttt{" + body + "}"
    return re.sub(r"\\texttt\{([^{}]*)\}", inner, text)


def figure(path: str, caption: str, label: str, number: str, width: str = r"\linewidth") -> str:
    return (f"\\begin{{figure}}[htbp]\\centering\\renewcommand{{\\thefigure}}{{{number}}}\n"
            f"\\includegraphics[width={width}]{{{path}}}\n\\caption{{{caption}}}\n\\label{{{label}}}\n\\end{{figure}}\n")


TABLE_CAPTION = re.compile(r"\\textbf\{Table ([A-Z0-9]+(?:\.[0-9]+)*)\. ")
FIGURE_CAPTION = re.compile(r"\\textbf\{Figure ([A-Z0-9]+(?:\.[0-9]+)*)\. ")
IMAGE = re.compile(r"^\\pandocbounded\{\\includegraphics\[keepaspectratio\]\{([^}]+)\}\}$")


def real_captions(latex: str) -> tuple[str, int, int]:
    """Turn the Markdown's bold caption paragraphs into LaTeX captions numbered as the paper numbers them.

    A table caption is the bold paragraph right before a longtable; a figure caption is the bold paragraph right after
    an image. Anything else (a caption over several panel tables, say) stays a bold paragraph.
    """
    blocks = latex.split("\n\n")
    tables = figures = 0
    for i, block in enumerate(blocks):
        table = TABLE_CAPTION.match(block)
        if table and i + 1 < len(blocks) and blocks[i + 1].lstrip().startswith(r"\begin{longtable}"):
            number = table.group(1)
            caption = block.replace(f"\\textbf{{Table {number}. ", "\\textbf{", 1)
            head = blocks[i + 1]
            at = head.index(r"\toprule")
            # longtable's \caption must open its row, so the number is set just before the table
            blocks[i + 1] = (f"\\renewcommand{{\\thetable}}{{{number}}}\n" + head[:at] + f"\\caption{{{caption}}}"
                             f"\\label{{tab:{number}}}\\tabularnewline\n" + head[at:])
            blocks[i] = ""
            tables += 1
        image = IMAGE.match(block.strip())
        if image and i + 1 < len(blocks) and FIGURE_CAPTION.match(blocks[i + 1]):
            number = FIGURE_CAPTION.match(blocks[i + 1]).group(1)
            caption = blocks[i + 1].replace(f"\\textbf{{Figure {number}. ", "\\textbf{", 1)
            blocks[i] = figure(image.group(1), caption, f"fig:{number}", number).rstrip("\n")
            blocks[i + 1] = ""
            figures += 1
    return "\n\n".join(b for b in blocks if b), tables, figures


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "sections").mkdir(parents=True)
    (OUT / "figures").mkdir()
    for png in (ROOT / "figures").glob("*.png"):
        shutil.copy2(png, OUT / "figures" / png.name)
    shutil.copy2(SOURCE / "runtime.bib", OUT / "runtime.bib")
    version = json.loads((SOURCE / "version.json").read_text())
    authors = json.loads((SOURCE / "authors.json").read_text())

    tex = {name: prepare_tex((SOURCE / f"{name}.tex").read_text()) for name in
           ("abstract", "sec_opening", "sec_runtime", "sec_discussion", "app_runtime", "tab_cli_controls", "tab_case_paths")}
    tex["sec_opening"] = (tex["sec_opening"]
                          .replace("CASEFIGUREPLACEHOLDER", figure("figures/evaluation_levels.png", CASE_CAPTION, "fig:case", "1.1"))
                          .replace("COMPARISONTABLEPLACEHOLDER", comparison_table()))
    tex["sec_runtime"] = tex["sec_runtime"].replace(
        "ARCHITECTUREFIGUREPLACEHOLDER", figure("figures/architecture_overview.png", ARCH_CAPTION, "fig:architecture", "4.1"))
    tex["app_runtime"] = (tex["app_runtime"].replace("RUNTIMEFIGUREPLACEHOLDER", r"\renewcommand{\thefigure}{H.1}" + RUNTIME_TIKZ)
                          .replace(r"\input{tab_cli_controls}", r"\input{sections/tab_cli_controls}")
                          .replace(r"\input{tab_case_paths}", r"\input{sections/tab_case_paths}"))
    tex["tab_case_paths"] = tex["tab_case_paths"].replace("P{3.06in}", "P{3.0in}")  # 3pt wider than the text block
    for name, number in (("tab_cli_controls", "H.1"), ("tab_case_paths", "H.2")):  # the order the appendix inputs them
        tex[name] = f"\\renewcommand{{\\thetable}}{{{number}}}\n" + tex[name]
    for name, body in tex.items():
        (OUT / "sections" / f"{name}.tex").write_text(subscripts(body))

    md = {"sec_cases": "paper_case_studies.md", "sec_qc": "paper_qc_design.md",
          "app_case_specs": "paper_appendix_case_specs.md", "app_details": "paper_appendix_details.md"}
    labels = {"sec_cases": "sec:cases", "sec_qc": "sec:qc"}
    captions = {}
    for name, source in md.items():
        latex = pandoc_md(renumber(markdown_body(source)))
        if name in labels:  # the first section heading carries the label the LaTeX sections cite
            latex = re.sub(r"(\\section\{[^\n]*\}(\\label\{[^}]*\})?)", lambda m: m.group(1) + f"\\label{{{labels[name]}}}", latex, count=1)
        latex, tables, figures = real_captions(latex)
        captions[name] = (tables, figures)
        (OUT / "sections" / f"{name}.tex").write_text(subscripts(latex))

    author_line = r" \hspace{3em} ".join(authors) + r" \\[3pt] {\small contact@aeread.org}"  # one block, so the address centres under both names
    main_tex = PREAMBLE + (
        f"\\title{{{TITLE}}}\n\\author{{{author_line}}}\n"
        f"\\date{{Research working paper, version {version['version']}, {version['date']}. Preliminary results; "
        "feedback and contributions welcome.}\n\n\\begin{document}\n\\maketitle\n"
        "\\input{sections/abstract}\n\\input{sections/sec_opening}\n\\input{sections/sec_runtime}\n"
        "\\input{sections/sec_cases}\n\\input{sections/sec_qc}\n\\input{sections/sec_discussion}\n\n"
        "\\bibliographystyle{plainnat}\n\\bibliography{runtime}\n\n\\appendix\n"
        "\\input{sections/app_case_specs}\n\\input{sections/app_details}\n\\input{sections/app_runtime}\n"
        "\\end{document}\n")
    (OUT / "main.tex").write_text(main_tex)
    (OUT / "README.txt").write_text(
        f"AERead working draft, version {version['version']} ({version['date']}), as a LaTeX project.\n\n"
        "Build:  lualatex main && bibtex main && lualatex main && lualatex main\n"
        "Fonts:  Times New Roman (macOS system font), with STIX Two Math, Apple Symbols, Helvetica Neue and Arial Unicode MS as a\n"
        "        fallback for the Unicode symbols the Markdown sections use; swap them in main.tex if needed.\n\n"
        "Where each section comes from (regenerate with `python export_latex.py` in the paper folder):\n"
        "- sections/abstract, sec_opening, sec_runtime, sec_discussion, app_runtime, tab_*: the paper's own LaTeX,\n"
        "  copied; Figure 1.1, Table 2.1, Figure 4.1 and Figure H.1 replace the HTML build's placeholders.\n"
        "- sections/sec_cases (Section 5), sec_qc (Section 6), app_case_specs (Appendices A-D) and app_details\n"
        "  (Appendices E-G): converted from the Markdown sources by pandoc. Table and figure captions are LaTeX\n"
        "  captions numbered as the paper numbers them (\\thetable / \\thefigure set per float; labels tab:5.2,\n"
        "  fig:5.1, ...). A caption over several panel tables (Table E.10) stays a bold paragraph. Cross-references in\n"
        "  the text are literal numbers that match the captions. Section and appendix numbers come from LaTeX and follow\n"
        "  the same order. The per-section sources tables are not in the paper, as in the PDF.\n"
        "- figures/: the PNGs the PDF build draws (Figures 1.1, 4.1, 5.1, 5.2).\n"
        "Known rough edges to integrate by hand: a few wide tables run slightly past the margin and may need\n"
        "\\small or landscape; symbols such as C_I are written as text with an underscore, as in the Markdown.\n")
    print(json.dumps({"captions": captions}))


def compile_pdf() -> None:
    """Build latex/main.pdf in a scratch copy (lualatex, bibtex, lualatex twice), so latex/ keeps only its sources."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "latex"
        shutil.copytree(OUT, work)
        steps = [["lualatex", "-interaction=nonstopmode", "-halt-on-error", "main"], ["bibtex", "main"],
                 ["lualatex", "-interaction=nonstopmode", "-halt-on-error", "main"],
                 ["lualatex", "-interaction=nonstopmode", "-halt-on-error", "main"]]
        for step in steps:
            done = subprocess.run(step, cwd=work, capture_output=True, text=True)
            if done.returncode != 0:
                raise SystemExit(f"{' '.join(step)} failed; see {work / 'main.log'}")
        log = (work / "main.log").read_text(encoding="latin-1")
        assert "Missing character" not in log and "undefined on input line" not in log, "unresolved glyphs or references"
        shutil.copy2(work / "main.pdf", OUT / "main.pdf")


if __name__ == "__main__":
    main()
    compile_pdf()
