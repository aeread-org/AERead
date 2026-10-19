AERead working draft v14 - 18 October 2026

Based on v13 (17 October). Text edits only, so the draft reads as a paper rather than an internal
record. It is meant to be shared outside the team as the PDF alone.

Changed:
- All 86 incident-log code mentions (HL-D-07, DC-D-35 and the like) removed from the PDF. Parenthetical codes
  were dropped; where a code named something in a sentence, it was replaced by what it refers to
  (e.g. "the corrected measure"). Table F.4 labels rows by case instead of code; the list of
  eight open defects is written out in words.
- Branch names, git commit hashes and issue/PR numbers removed from Appendix A (code references,
  now "relative to the AERead repository"), Appendix F, Appendix G and Appendix H. Executor,
  file and binary digests in Appendix H are kept: they identify what ran, not a branch.
- "By the owner's ruling" is now "by an explicit, recorded decision". The trajectory viewer is no
  longer named. Review-bookkeeping phrases (raw ID unions, renamed rows, "14 October review",
  "unmerged branch", "kernel fixes merged under a waiver") rewritten as plain statements.
- Abstract: "The cases remain incompletely qualified" is now "No case has yet passed every
  quality-control gate". Same claim, plain words.
- Subtitle: "Working draft · 18 October 2026 · Not for circulation".

Unchanged: every number, table value, figure, reference (15) and author (Chenyu Li, Zeyu Sun).
A word-level diff against v13 changes no data value; the only numbers that differ are removed
dates, codes, issue numbers and page numbers. Main-text pages 1-10 start on the same lines as v13.
Appendix pages reflow from page 25; still 44 pages.

Not changed (internal by design): the "Sources for the numbers" tables at the end of the section
files, which the build excludes from the PDF and which keep their codes and commits for
traceability; the technical supplement; the editable sources zip. Do not send the zip.

EXTERNAL_READING_REVISION.patch records every source change against v13, so each removed code
and commit can still be traced. ARCHITECTURE_CHECKS.json was re-bound to the three edited
sources it hashes (text-only edits; the figure is unchanged).

Build PDF:
  uv run --with markdown --with beautifulsoup4 --with pypdf python build.py
Requires pandoc and Google Chrome on macOS. All PDF assets are local.
No model calls, scoring changes, commits or pushes.
