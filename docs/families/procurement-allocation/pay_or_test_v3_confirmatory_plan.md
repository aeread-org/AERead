# Pay or test v3: confirmatory plan (arm A) and odds diagnostic (arm B)

**Status:** declared 2026-10-19, before any world below is played, at the owner's go ("go") on the two arms proposed
after the [pilot](pay_or_test_v3_pilot_results.md). Arm A is one confirmatory test. Arm B is a diagnostic with no
claim. Both come from patterns the pilot raised rather than tested, so both run on fresh worlds.

## 1. Worlds

- **Arm A pack** `pay_or_test_v3_confirm`: 20 option-value (`myopic_pays`) worlds, each the first admitted seed of its
  block from 9 400 000 (4 000 seeds a block, above the pilot's 9 300 000 to 9 348 000). The generator, admission rule
  and brief are the pilot's ([plan](pay_or_test_v3_plan.md), Sections 1 and 2) and unchanged.
- **Arm B pack** `pay_or_test_v3_odds_diagnostic`: each arm A world with only its cohort records redrawn from version
  1's ranges (4 or 8 of 40 unreliable, 8 to 24 of 40 failing inspection; arm A's are 2 to 6 and 18 to 30). Listings,
  prices, sample terms, clock, sharing chance and reply draws are the twin's. Twins are valued exactly and not admitted:
  under better odds the best policy may simply test, and the pack records whether its first move goes to a newcomer.

Both packs are committed with this plan.

## 2. Subjects and plays

| Arm | Subject | Pack | Plays a world | Plays |
|---|---|---|---:|---:|
| A (and B's control) | Sol 6.1 through Codex | `pay_or_test_v3_confirm` | 2 | 40 |
| B's control | Opus 5.5 through Claude Code | `pay_or_test_v3_confirm` | 2 | 40 |
| B | Opus 5.5 through Claude Code | `pay_or_test_v3_odds_diagnostic` | 1 | 20 |

The pilot's controls hold: effort low; isolation as the data-center v2 plan's amendments 1 and 2 require, probed before
any world, with the run refusing on any violation; one sealed attempt an action; a failed cell is typed missingness and
never rerun; list-price ceilings of $10 a run on subscription logins. The pilot cost $2.29 and $2.17 for 24 plays each.
The driver is `tools/cli_subjects/pay_or_test_v3_cli.py --pack ...`. Runs play from the tree carrying the registry
row that trusts the version 3 plugin, as the pilot did, merged with this commit. That row still awaits its
kernel-lane review.

## 3. Sizing

At the pilot's SD of Sol's world-mean gap closed (0.30 over 6 option-value worlds), 20 worlds give power 0.8 for an
effect of 19 percentage points at two-sided alpha 0.05, and power 0.96 for the pilot's 25-point planning effect.

## 4. Tests, in this order

`tools/cli_subjects/pay_or_test_v3_confirmatory_analysis.py`, committed with this plan. Every play is replayed from its
public trace (it must reproduce the recorded margin) and priced action by action by the version 3 reference.

**Arm A (the confirmatory test).** For each world, Sol's share of the pay-to-best gap it closes,
`1 - loss / (best - pay)`, averaged over the world's plays; then a two-sided one-sample t-test of mean zero over the
20 worlds at alpha 0.05, with its 95% t interval and a 95% bootstrap interval.
- **Claim:** "Sol 6.1 closes a positive share of the gap between paying the premium and the best policy in worlds
  where the best first move is a test worth only what it reveals." It holds only if the t interval's lower end is
  above zero.
- **Missingness:** if more than 2 of the 20 worlds lack a completed play, the test is reported as inconclusive by
  dropout.
- No other hypothesis is tested, so no multiplicity correction applies.

**Arm B (diagnostic, no claim).** For each world, whether Opus touched a newcomer (quote, sample or lookup) on the arm
A world and on its twin, paired; Opus's gap closed on each; and on how many twins the best policy's first move goes
to a newcomer.
- **Declared reading:** the cohort odds are named the likely cause of Opus never testing only if it touches a
  newcomer on at least 10 of 20 twins and on at most 2 of 20 arm A worlds.
- Otherwise the odds alone do not explain it, and the next candidates are the version 3 rules and the brief.
- Either reading is a hypothesis for a later declared test, not a finding.

## 5. What is not claimed

No model ranking: Opus plays arm A as arm B's control, not as a comparison subject, and the pilot's ranking contrast
already sized past its cap. Nothing here moves the published pay-or-test results or Table 5.3's worlds.
