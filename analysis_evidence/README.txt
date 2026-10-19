Headline verification package — 16 October 2026

Procurement: 15f5ff3b2ca6bf8a6e031028b368e6b10b2d23ae
Patch base: 29c00d8344b3b94e86ca4d83f78dceeaab7e49c8
Branch: codex/paper-headline-reanalysis-20261016 (local only).
The patch contains the scorer/extractor, tests, incident record and new
public projection. Apply it to a clean checkout of the base commit.
With Python 3.13.5 and the project's dependencies installed, run:
  PYTHONPATH=src python -m aeread_families.procurement_allocation.pay_or_test_reanalysis --check
To repeat the original execution audit, add:
  --cli-runs <CLI-parent-run-directory> --flash-runs <flash-parent-run-directory>
The CLI directory holds the four pay_or_test_v1_accounting/finalquotes runs;
the flash directory holds the two pay_or_test_v1_finalquotes_openrouter runs.
All 144 original receipts passed state and score replay, and all decision
losses match. Original bootstrap ordering reproduces Table 5.3's intervals.
The reference, extraction, report, runtime Python sources and case pack are
bound in source_pins.json. Published projections omit free-text messages.
The new analysis does not modify old receipts or create a prospective
receipt-level headline metric. It is retrospective, with one recorded
trajectory per subject/world and unmeasured run-to-run variance.

Housing: 10a95651b7a2f9fa2e3d0c13ca3b7c432a90f65f
Branch: codex/housing-lemons-outside-demand.
The existing correction was checked with:
  PYTHONPATH=src python -m aeread_families.housing.price_reply_conditioned --check --from-runs
It re-extracted 1812 trajectory rows from the retained sealed records and
regenerated the committed analysis exactly. The bundled projection allows
score regeneration from that repository revision with --check; extraction
against original event logs requires its retained runs/ directory.
Original v14, fill and controls bundles remain in that revision.
Housing's historical per-seat attribution error is still open. Reanalysis
verification does not retroactively make the corrected measure preregistered.

Testing: Procurement's focused suite passed 58 tests; its final six-panel
regression rerun passed 9. Housing's correction suite passed 24 tests.
The 9 are included in the 58, not nine additional distinct tests.

Recommended inspection: the new module's extract() (sealed evidence and
coverage), derive() (reference and intervals), reports/headline.json (six
panels), and source_pins.json (exact code and case bytes).
No paid model calls, remote writes, or publication occurred.
