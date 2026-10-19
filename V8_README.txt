AERead working draft v8 — 17 October 2026

Review Table 5.5 on page 8: four case-specific panels arranged 2 by 2,
with separate model columns, case-specific references, units and denominators.
The main text remains pages 1–10; the full draft is 42 pages. Appendix H
remains four pages, now 39–42, with unchanged text.

Housing uses corrected reply-conditioned v2 amounts. The historical priority
classification was checked against all 1,764 completed cells. Data center
uses the confirmatory firm-population bundle, averaging both focal roles
within each of all 60 worlds. Its panel separates inferior clauses, harmful
agreements, missed beneficial deals and redline fees. Below-walk-away signings
remain separate individual outcomes. Procurement and Refund retain their
original development panels, checked against the packaged source analyses.
All 34 displayed component/total values are verified in the PDF build.

Table 5.1's Data-center joint losses were mislabeled per deal world in v7.
They average all 60 worlds; v8 corrects the denominator and names each role
assignment. Earnings contrasts in Table 5.4 still use the 45 deal worlds.
Appendix E.5 makes corrected Housing values primary, with original values in
brackets. Appendix E.7 (page 29) gives all confirmatory Data-center pairings
and descriptive total intervals/distributions. Historical Data-center tables
E.3, E.6 and E.7 are retained. Every other pre-existing table is unchanged.

The classification rules and limitations remain explicit: these are
post-run descriptive accounting categories, not causal diagnoses or new
confirmatory tests. The new descriptive t intervals do not replace the
campaigns' declared analyses. Refund has only six fixed cases, so its intervals
do not support general model rankings or field-population inference.

Chenyu Li and Zeyu Sun remain in the byline and PDF metadata. The grounding
clarifications, AgenticPay comparison and all 15 references are retained.
No new model calls were made and no publication action was taken.

Build the PDF:
  uv run --with markdown --with beautifulsoup4 --with pypdf python build.py
Requires pandoc and Google Chrome on macOS. No network assets are rendered.

Reproduce the new accounting derivation:
  uv run --with scipy python analysis_evidence/shortfall_panels/derive_panels.py
See that folder's README.md for identities, aggregation rules, precision,
missingness and the distinction between the current entry point and historical
classification snapshots. All used inputs are SHA-256 bound in panels.json.

Editable changes are in source/paper_case_studies.md and
source/paper_appendix_details.md, with layout changes in build.py and paper.css.
The two Markdown files were byte-checked against v7 before synchronizing them
locally to docs/paper-case-studies-qc. SHORTFALL_SOURCE_SYNC.json records hashes;
SHORTFALL_REVISION.patch records the source changes. The paper incident log
records the denominator correction as RES-J-05 and the stopped audit's initial
input/schema mistakes as RES-T-01. Prior working changes were preserved.

PDF_CHECKS.json, HTML_CHECKS.json and LAYOUT_QA_LOG.txt record verification.
SOURCE_MANIFEST.json binds the PDF and included source/evidence files.
The ZIP contains editable sources and evidence; the PDF is supplied separately.
V4_README.txt through V7_README.txt retain historical revision notes. Their
page counts and claims refer to those prior versions. The complete v7 manifest
was reverified and every v7 artifact remains unchanged. Local review draft only.
