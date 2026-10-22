AERead working draft, version 15.49 (22 October 2026), as a LaTeX project.

Build:  lualatex main && bibtex main && lualatex main && lualatex main
Fonts:  Times New Roman (macOS system font), with STIX Two Math, Apple Symbols, Helvetica Neue and Arial Unicode MS as a
        fallback for the Unicode symbols the Markdown sections use; swap them in main.tex if needed.

Where each section comes from (regenerate with `python export_latex.py` in the paper folder):
- sections/abstract, sec_opening, sec_runtime, sec_discussion, app_runtime, tab_*: the paper's own LaTeX,
  copied; Figure 1.1, Table 2.1, Figure 4.1 and Figure H.1 replace the HTML build's placeholders.
- sections/sec_cases (Section 5), sec_qc (Section 6), app_case_specs (Appendices A-D) and app_details
  (Appendices E-G): converted from the Markdown sources by pandoc. Table and figure captions are LaTeX
  captions numbered as the paper numbers them (\thetable / \thefigure set per float; labels tab:5.2,
  fig:5.1, ...). A caption over several panel tables (Table E.10) stays a bold paragraph. Cross-references in
  the text are literal numbers that match the captions. Section and appendix numbers come from LaTeX and follow
  the same order. The per-section sources tables are not in the paper, as in the PDF.
- figures/: the PNGs the PDF build draws (Figures 1.1, 4.1, 5.1, 5.2).
Known rough edges to integrate by hand: a few wide tables run slightly past the margin and may need
\small or landscape; symbols such as C_I are written as text with an underscore, as in the Markdown.
