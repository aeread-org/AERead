AERead working draft v9 — 17 October 2026

Figure 5.1 on page 8 presents the shortfall results as four stacked-bar panels.
Each panel uses its own units and reference, labels the total at the bar end,
and distinguishes the observed components by color. Data-center missed deals
also use a hatch. Bars use unrounded source amounts, with labels at one decimal.
The figure is vector artwork in the PDF, with standalone SVG and PNG exports
under figures/. It introduces no new estimate or model run.

As requested, the figure is in the main text and the exact-value table is in
the appendix: v8 Table 5.5 is now Table E.10 on page 30. All its values are
unchanged. All other existing numeric tables are unchanged, and the entire
analysis_evidence/ directory is byte-identical to v8. The original rules,
Housing interpretation limit and separate Data-center individual outcomes
remain explicit. Intervals remain in Table E.9; the figure shows point estimates.

Main text: pages 1–10. References: page 11. Total: 43 pages.
Appendix H: pages 40–43, still four pages with unchanged text.
The author names, 15 references, AgenticPay comparison and realistic-grounding
wording are retained. Nothing was posted, pushed or published.

Build the figure:
  uv run --with matplotlib python figures/plot_shortfalls.py
Build the PDF:
  uv run --with markdown --with beautifulsoup4 --with pypdf python build.py
The PDF build requires pandoc and Google Chrome on macOS. It loads no network
assets. figures/README.md explains the figure and its checks. The existing
accounting reproduction script remains in analysis_evidence/shortfall_panels/.
Historical references there to Table 5.5 use the v8 numbering.

The figure generator checks all eight component sums and records input/image
SHA-256 bindings. The PDF builder verifies plotted values against that source,
all 34 exact table values, and the copied SVG used by the editable Markdown.
HTML_CHECKS.json and PDF_CHECKS.json record structural and numerical checks.
LAYOUT_QA_LOG.txt records the rendered-page review. The previous v8 manifest
was reverified, and its source, PDF and evidence remain unchanged.

Editable source changes: source/paper_case_studies.md,
source/paper_appendix_details.md, build.py and paper.css.
Figure source: figures/plot_shortfalls.py.
The two Markdown sources and the new SVG were synchronized locally to
AERead-worktrees/paper-sections after comparing target bytes to v8.
FIGURE_SOURCE_SYNC.json records those hashes; FIGURE_REVISION.patch records
the Markdown diff. Existing working changes were preserved.

SOURCE_MANIFEST.json binds the PDF and editable sources/evidence. The ZIP
contains the source package and standalone figure; the PDF is separate.
V4_README.txt through V8_README.txt retain historical revision notes; their
numbering and page counts apply only to those earlier versions.
