AERead working draft v6 — 17 October 2026

Added the AgenticPay comparison to Section 2, Economic decisions and
negotiation (page 2), with its reference on page 11. The existing BibTeX entry
was uncited in v5, so the rendered reference list omitted it. V6 cites it and
now contains 15 references. The primary source, arXiv:2602.06008v1, was checked
for authorship, private reservation values and the metrics in Section 4.4.

The comparison acknowledges agreement, surplus allocation and speed in
AgenticPay. AERead's emphasis is case-specific payoff units, explicit
full-information versus information-constrained references, and QC of world
distributions and measurement paths. Surrounding prose was tightened to
keep the opening compact. No empirical results or tables changed.

Review PDF: aeread_working_draft_20261017_v6.pdf
40 pages; Appendix H remains pages 37–40. Chenyu Li and Zeyu Sun remain in
the byline and PDF metadata. Only pages 2 and 11 render differently from v5;
both were visually inspected. All other pages render identically.

Build from this directory:
  uv run --with markdown --with beautifulsoup4 --with pypdf python build.py
Requires pandoc and Google Chrome on macOS. Edit source/sec_opening.tex for
the comparison, source/runtime.bib for citations, source/authors.json for
names. PDF_CHECKS.json and HTML_CHECKS.json record this revision's checks.
OPENING_SOURCE_CHECKS.txt records the primary-source basis for the comparison.

V4_README.txt and V5_README.txt retain earlier revision and evidence notes.
No scientific analysis or model run was repeated in this literature update.
The complete v5 source/evidence files and PDF remain unchanged. The updated
opening TeX is in this versioned artifact folder. SOURCE_MANIFEST.json binds
this PDF, sources, inherited evidence and review records. The ZIP contains
sources and evidence; the PDF is separate. This remains a local review draft.
