# Pay or test v3: Sol on the odds twins (diagnostic)

**Status:** declared 2026-10-20, before any play, at the owner's go ("both"). A diagnostic with no claim. It fills the
"not played" cell of the paper's Table 5.3. That cell is the row for the 20 twins of the confirmatory worlds at the
earlier pack's cohort odds, which only Opus played (arm B of the [confirmatory plan](pay_or_test_v3_confirmatory_plan.md)).

## What runs

- **Worlds:** `pay_or_test_v3_odds_diagnostic`, the 20 twins, as committed in `e67df11d`. Every listing, price, sample
  term, clock and sharing chance is its confirmatory world's; only the cohort records are redrawn from version 1's
  ranges. In every twin the best policy's first move goes to a newcomer.
- **Subject:** Sol 6.1 through Codex, effort low, isolated and probed as in every v3 run. The brief is v3's
  (`procurement_allocation_pay_or_test_v3_brief_v1`), as Opus's twin plays had.
- **Plays:** one a world, as Opus's twin plays; 20 in all. A failed cell is typed missingness and never rerun.
- **Ceiling:** $10 at list price on the subscription login.
- **Identity:** `procurement_allocation_pay_or_test_v3_odds_diagnostic_v3_codex_cli_sol61_v1`.
- **Run tree:** the tree carrying the registry row, as for every v3 run.

## Read-out, in this order

`tools/cli_subjects/pay_or_test_v3_twins_sol_analysis.py`, committed with this plan:

1. Plays touching a newcomer, and plays whose first information request goes to one.
2. Sol's share of the gap between paying the premium and the best policy, per world, with its mean and 95% t
   interval. Beside it are the exact rules on the same twins: the one-step rule (57.6%), the kind-blind shortcut
   (61.6%), the rule that may test two newcomers (89.6%), and Opus (0% in all 20).
3. Paired by world, Sol's share on each twin minus its share on the original world (each the mean of its plays),
   reported descriptively.

Nothing here is a hypothesis test. The paper may report the read-out only as a diagnostic.
