# Data-center fee sensitivity evidence

The supplied analysis was rerun on 17 October 2026 without model calls. All 240 original states and six score leaves matched retained states and receipts; the native transition and grade functions replayed 1,440 trajectories across six fees. The four JSON outputs and analyze.py match the supplied files byte for byte. report.md is regenerated; supplied_report.md retains the supplied prose, whose only reproduction difference is minus-sign placement for the negative joint-loss crossover.

The interpretation in those reports must be read as applying to the 45 deal-feasible worlds. It does not hold for all 60 worlds: at zero fees Sol has lower joint loss, with a fixed-action crossover near $6,378 per redline. COHORT_CHECKS.json and the paper's Appendix E.9 state both samples explicitly. No model adaptation or optimal-fee claim follows.

Run against the retained local dc-agreement worktree and campaign logs:

    uv run --with numpy --with scipy python analyze.py
    python3 verify_cohorts.py

analyze.py retains its supplied absolute source-worktree location. The compact package contains derived rows and edit diagnostics, not the full raw execution logs. Source event streams and referenced payloads are verified in the replay; source_hashes.json records all 240 event-stream digests. code_source_hashes.json binds the analysis and Data-center Python source files used locally. Worktree HEAD at reproduction: 92cd26dcfca585bfd5c932b3cd87a1ffe0980c8f; code hashes, not HEAD alone, identify local bytes.

verify_cohorts.py checks equal weighting of two focal seats per world, both cohort sizes, all 42 displayed table cells, linear fee sensitivities, useful-redline counts, and the concrete $87,500 clause-value improvement. It also checks the retained event streams and therefore requires the original log locations.
