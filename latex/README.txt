AERead working draft, version 15.36 (21 October 2026), as a LaTeX project.

Build:  lualatex main && bibtex main && lualatex main && lualatex main
Fonts:  Times New Roman (macOS system font), with STIX Two Math, Apple Symbols, Helvetica Neue and Arial Unicode MS as a
        fallback for the Unicode symbols the Markdown sections use; swap them in main.tex if needed.

Where each section comes from (regenerate with `python export_latex.py` in the paper folder):
- sections/abstract, sec_opening, sec_runtime, sec_discussion, app_runtime, tab_*: the paper's own LaTeX,
  copied; Figure 1.1, Table 2.1, Figure 4.1 and Figure H.1 replace the HTML build's placeholders.
- sections/sec_cases (Section 5), sec_qc (Section 6), app_case_specs (Appendices A-D) and app_details
  (Appendices E-G): converted from the Markdown sources by pandoc. Their tables are longtables, their table
  and figure captions are bold paragraphs that carry their own numbers (Table 5.3, Figure 5.2...), and
  cross-references in the text are literal numbers, as in the PDF. Section and appendix numbers come from
  LaTeX and follow the same order. The per-section sources tables are not in the paper, as in the PDF.
- figures/: the PNGs the PDF build draws (Figures 1.1, 4.1, 5.1, 5.2).
Known rough edges to integrate by hand: the widest tables (Tables 5.2, E.5, E.10) may need \small or
landscape; symbols such as C_I are written as text with an underscore, as in the Markdown.
