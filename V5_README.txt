AERead working draft v5 — 17 October 2026

Added Chenyu Li and Zeyu Sun, in that order, beneath the paper title and in the
PDF author metadata. Editable author names are in source/authors.json.
The working-draft date is now 17 October; evidence review dates remain unchanged.

Review PDF: aeread_working_draft_20261017_v5.pdf
40 pages; Appendix H remains pages 37–40. Page 1 was visually inspected.
Pages 2–40 render identically to v4. All existing content sources and the main
text reading copy are byte-identical to v4; no research content changed.
The v4 PDF and all its manifest-bound source/evidence files are preserved.

Build from this directory:
  uv run --with markdown --with beautifulsoup4 --with pypdf python build.py
Requires pandoc and Google Chrome on macOS. No network assets are rendered.

V4_README.txt describes the preceding scientific revision, verification scope,
source synchronization and limitations. Those notes are historical context;
this author-only revision does not rerun scientific analyses or model calls.
PDF_CHECKS.json records this revision's checks. SOURCE_MANIFEST.json binds
this PDF and its editable sources, inherited evidence and review records.
The sources-and-evidence ZIP supplies those materials; the PDF is separate.
