AERead working draft v13 - 17 October 2026

Based on the restored v11, preserving its fuller main text. The v12 cuts are not applied.
The main text remains ten pages. The complete draft has 44 pages.

Section 5.2 (page 8) now reports fixed-action fee sensitivity with explicit sample scope.
Appendix E.5 (page 27) points to the completed sensitivity analysis.
New Appendix E.9 (pages 31-32), Tables E.11-E.12, reports six fee levels.

Important distinction: the original $25k fee contributes 69.9% of Sol's and 40.3% of
Opus's joint loss across all 60 worlds. On the 45 deal-feasible worlds, Opus retains
lower joint loss at zero fees; removing fees raises Sol's earnings lead from $26.4k
to $54.8k, with a fixed-action earnings crossover near $48.3k per redline.
Across all 60 worlds, zero-fee joint loss is instead lower for Sol ($31.1k versus
$42.3k), with a joint-loss crossover near $6.4k. These are scoring sensitivities,
not evidence of adaptation, an optimal fee, or new confirmatory significance tests.

The supplied analysis reproduced all 240 original final states and six score leaves
and replayed 1,440 fee-specific trajectories through native apply/grade. The four
JSON result files match the supplied outputs byte for byte. The report's minor
minus-sign typography difference is documented; the supplied report is preserved.
All 42 sensitivity table cells, world/seat averaging, thresholds and the concrete
useful redline are checked. The source package retains derived evidence and hashes;
raw campaign logs are required for complete native reproduction.

Architecture Figure 4.1, all four Procurement subjects in Figure 5.1 and Table E.10,
all prior numerical results, authors Chenyu Li and Zeyu Sun, and 15 references remain.
The original v11 and v12 packages are unchanged.

Build PDF:
  uv run --with markdown --with beautifulsoup4 --with pypdf python build.py
Requires pandoc and Google Chrome on macOS. All PDF assets are local.
Reproduce fee analysis: see analysis_evidence/datacenter_fee_sensitivity/README.md.

FEE_SENSITIVITY_SOURCE_SYNC.json records synchronization of the two changed Markdown
sources into the paper-sections worktree. FEE_SENSITIVITY_REVISION.patch records
changes against v11. PDF_CHECKS.json and LAYOUT_QA_LOG.txt record verification.
SOURCE_MANIFEST.json binds the PDF and source/evidence package. Prior revision notes
are retained as historical records. Local draft only; no new model calls, publication,
commits or pushes.
