AERead working draft v10 — 17 October 2026

This wording revision clarifies how to interpret Data-center negotiation costs.
Section 5.2 (page 8) gives the fee shares in the confirmatory firm-population
panel: about 70% of Sol's and 40% of Opus's joint shortfall. It explains that
fees can accompany valuable contract improvements, and that a full-information
reference can agree immediately. The gap can therefore include negotiation
costs that agents with limited information may need to incur.

Appendix E.5 (page 27) adds a worked accounting example: improving the final
contract by $100k at a $25k fee reduces joint shortfall by $75k. It distinguishes
incurred costs from avoidable mistakes and explains that behavioral sensitivity
to alternative fees would require comparisons under declared alternative settings.
Figure 5.1's caption now explicitly names the full-information bound.

All existing table values, figure assets and analysis evidence are unchanged.
Only pages 8 and 27 differ in extracted text from v9. Both changed pages were
rendered and visually inspected. The draft remains 43 pages, with main text
on pages 1–10, Figure 5.1 on page 8, Table E.10 on page 30 and Appendix H on
pages 40–43. Both authors, all 15 references and the AgenticPay comparison remain.
No model calls, new experiments, fee recalibration or publication actions occurred.

Build the PDF:
  uv run --with markdown --with beautifulsoup4 --with pypdf python build.py
Requires pandoc and Google Chrome on macOS; no network assets are loaded.
The unchanged figure and analysis reproduction instructions are in figures/
README.md and analysis_evidence/shortfall_panels/README.md. Their historical
version/table references apply to the original production of those assets.

Changed editable text: source/paper_case_studies.md and
source/paper_appendix_details.md. These were synchronized locally to the
paper-sections worktree after confirming its target bytes matched v9.
NEGOTIATION_COST_SOURCE_SYNC.json records hashes and
NEGOTIATION_COST_REVISION.patch records the Markdown changes.
The build output filename is updated to v10; no renderer behavior changed.

PDF_CHECKS.json and HTML_CHECKS.json record the checks; LAYOUT_QA_LOG.txt records
visual review. SOURCE_MANIFEST.json binds this PDF and the source/evidence ZIP
contents. v9's complete manifest was verified before creating v10 and all v9
artifacts remain unchanged. V4_README.txt through V9_README.txt retain earlier
revision notes. Local working draft only.
