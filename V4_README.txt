AERead working draft v4 — 16 October 2026

Review PDF: aeread_working_draft_20261016_v4.pdf
40 pages. Appendix H remains four pages (37–40).
The complete v3 folder and its manifest-bound files are preserved unchanged.

Changes from v3
- Related Work uses aeread.org's comparison axes: a principal's mandate,
  responsive counterparts, and the economic payoff of decisions. Statements
  about GDPval, Agents' Last Exam and Terminal-Bench remain grounded in their
  original papers. The homepage's target scope is not claimed as implemented,
  and its categorical description of Terminal-Bench having no other parties
  is not repeated. Related Work stays compact on page 2.
- Data-center agreement confirmatory results now lead Section 5.1 and Tables
  5.1 and 5.4. On the 45 deal worlds, the seat-averaged Sol-minus-Opus earnings
  difference is $190.1k [148.0, 232.1] head to head and $26.4k [10.5, 42.4]
  against the firm population. The latter rejects zero (Holm p=0.0017) but
  remains below the declared $50k minimum. The client walk-away comparison
  uses all 60 worlds: Opus 27/60, Sol 3/60. Development results remain in E.
- Three reported analyses were declared before their runs. Data center's
  eight departures and partial Gate 5 verdict are explicit. The family QC
  profile was locally updated from its stale not_run verdict; the paper does
  not claim that the campaign or case passes every qualification gate.
- Procurement v2's 50-cell gate/pilot cost $0.22. Sizing required 326–3,464
  worlds against a 96-world cap, so no confirmatory run followed.
- Replay coverage is 1,295 scored Data-center receipts; the new driver froze
  a five-consecutive-failure halt and cost/wall-time ceilings. Total historical
  plus confirmatory CLI failures are 40. The reader-fit result is identified
  as using a misspecified model fitted on confounded development data.
- Incident counts are HL 51, P 57, DC 90, RF/RV25 23. The branch union yielded
  89 DC IDs because two different incidents shared DC-D-34. The reader-fit
  row is now DC-D-37; the generator defect keeps DC-D-34.
- The abstract and Section 7 are unchanged from v3. Housing and Procurement
  v1 headline values and their verified post-run derivations are preserved.

Verification and limits
The Data-center confirmatory analysis was freshly regenerated from sealed
receipt leaves and matched the published JSON exactly. Manifest artifact
hashes for all five public bundles were checked. Historical replay reports
covering 1,295 scored receipts were inspected; full replay was not rerun.
The excluded receipt's digest, cell binding and event seal were freshly checked
separately. This check does not change the frozen verifier or its manifest.
The campaign retains the post-data analysis-digest mismatch and manual
exclusion treatment described in Appendix F.5. No model was called.

analysis_evidence/campaign_refresh/README.txt explains the new evidence and
its boundaries. analysis_evidence/README.txt retains the earlier Housing and
Procurement verification instructions. Their recorded 24- and 58-test suites
are historical verification from the preceding revision, not new v4 runs.
The original Housing seat-attribution gap remains open; Procurement's future
receipt-level decision-loss integration is separate from the verified panels.

Local source synchronization
The three revised paper Markdown files were copied back, hash-checked, and
left as uncommitted edits on docs/paper-case-studies-qc in the paper-sections
worktree. Related-work and runtime TeX remain in this versioned source folder.
The Data-center QC-profile update and incident-ID fix are also local,
uncommitted documentation edits in the dc-agreement worktree. Both patches
and the paper synchronization record are included under campaign_refresh/review.
No frozen plan, receipt, campaign source or published bundle was changed.

Editable content and build
source/ contains the editable LaTeX and Markdown inputs; paper.css controls
layout. build.py generates the complete HTML and PDF using pandoc and Google
Chrome on macOS. From this directory run:
  uv run --with markdown --with beautifulsoup4 --with pypdf python build.py
No network assets are loaded by the renderer. complete_main_text.md is a
reading copy; edit source/ inputs when rebuilding. technical_supplement/
retains the longer archived 14 October runtime review for provenance.
SECTION_7_REVISION.txt records the preceding v3 revision, retained unchanged.

Review targets
- Page 2: concise comparison with GDPval, ALE and interactive benchmarks.
- Page 7: confirmatory Data-center headline, denominators and limitations.
- Pages 28–32: updated QC gates, Procurement stopping point, declarations,
  departures and incident counts.
- Pages 37–40: runtime contract and actual execution/measurement coverage.

Packaging and checks
PDF_CHECKS.json records pagination, table changes, page bounds and visual QA;
HTML_CHECKS.json records links and structure. SOURCE_MANIFEST.json binds the
source/evidence files and final PDF. The ZIP contains sources, HTML, public
sanitized evidence projections and checks; the PDF is supplied separately.
Raw provider text and private run roots are not included. The original run
roots remain necessary for independent event replay.
This is a local review draft. It has not been posted, pushed or published.
