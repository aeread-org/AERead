AERead working draft v7 — 17 October 2026

Updated Sections 5 and 7 to recognize that Procurement and Data center are
grounded in realistic purchasing and contracting decisions. Section 5 names
supplier verification under deadlines and negotiation over liability,
deposits and risk allocation. Section 7 distinguishes these realistic
contexts from empirical calibration and transfer to field settings.
The categorical statements that no practitioner set or reviewed the numerical
assumptions have been removed. Human-baseline, campaign and scope limitations
remain. This wording revision does not claim new validation or change results.

Review PDF: aeread_working_draft_20261017_v7.pdf
40 pages, with Appendix H on pages 37–40. Review pages 8 and 10 for the changed
wording; page 9 has text reflow. These three pages were visually inspected.
All other pages render identically to v6, and every table is unchanged.
Chenyu Li and Zeyu Sun remain in the byline and PDF metadata. The AgenticPay
comparison and all 15 references are retained.

Editable changes: source/paper_case_studies.md and source/sec_discussion.tex.
The revised case-study Markdown was hash-checked and synced locally to
AERead-worktrees/paper-sections on docs/paper-case-studies-qc; other working
changes were preserved. GROUNDING_SOURCE_SYNC.json and GROUNDING_REVISION.patch
record this update. The conclusion TeX remains in this versioned source folder.

Build from this directory:
  uv run --with markdown --with beautifulsoup4 --with pypdf python build.py
Requires pandoc and Google Chrome on macOS. No network assets are rendered.
PDF_CHECKS.json and HTML_CHECKS.json record the current checks. Earlier revision
and evidence notes are retained in V4_README.txt, V5_README.txt and V6_README.txt.
No scientific analysis or model run was repeated for this wording correction.
The v6 PDF and all its manifest-bound source/evidence files are preserved.
SOURCE_MANIFEST.json binds the new PDF and its source/evidence package. The ZIP
contains sources and evidence; the PDF is supplied separately. Local draft only.
