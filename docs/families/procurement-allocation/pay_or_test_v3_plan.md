# Pay or test v3: plan

**Status:** declared 2026-10-19, before any version 3 world is played, at the owner's go ("yes go v3"). A development
pilot of two CLI subjects that sizes a later declared run; no claim. It builds on the
[design note](pay_or_test_v3_design_note.md) (its probe: on v2's option-value worlds both frontier subjects paid the
premium in 12 of 12 plays) and the [parameter specification](pay_or_test_v3_parameters.md).

## 1. What version 3 is

The case is v2's: buy 50 driver-board kits by a deadline from a recorded supplier at a premium or from newcomers of
stated cohort odds, where newcomers of one seller kind share a source with a stated probability. Version 3 is a new
identity: family `procurement_allocation_v1` 1.1.0, plugin `procurement_pay_or_test_v3_environment`
(`pay_or_test_v3_environment.py`, a subclass of the v1 environment, whose bytes every sealed procurement plan hashes),
generator `procurement_allocation_pay_or_test_case_matrix_v3` 3.0.0, brief `procurement_allocation_pay_or_test_v3_brief_v1`.

| Change | From | Why |
|---|---|---|
| Newcomer prices drawn from the 56 recorded-against-unrecorded pairs of the sourcing record | v2's fixed grid, always 2–40% cheaper | spec §2; a newcomer is now dearer about half the time |
| A newcomer answers a quote request with probability 1/3; the recorded supplier always; samples always arrive | every quote answered | spec §2 and §4 choices 1–2 (recommended values) |
| `look_up_source`: a listing's registered factory for $1, no days; shared newcomers name one factory | not in v2 or the spec | the owner's go on the source-lookup question (2026-10-19) |
| No inquiry, no counter-offer, no financing; the budget never binds and is not shown; prices are landed | v2 kept them | spec §1 and §4 choice 3 |
| Same-source probability from {0.5, 0.65, 0.8, 0.95} | {0.8, 0.9, 0.95} | a lookup is worth most where sharing is uncertain |
| Deadline drawn from 14 to 22 days; cells by kind only | tight and loose clocks | room for retried quotes; the clock is reported, not stratified |
| `myopic_pays` worlds must beat paying the premium by 10% of its value | no stake condition | the probe's stake was 2% to 15% (design note) |
| The one-step rule plans one newcomer's whole test exactly | a fixed quote-then-sample sequence | with unanswered quotes the fixed sequence undervalues every test (P-D-28) |

Admission is v2's otherwise: the one-step rule, the four fixed rules and the kind-blind shortcut each lose at least $10;
without a shared source the one-step rule is within $5 of the best policy; information headroom at least $10; pack mean
one-step loss at least $15. The rules (`pay_or_test_v3_reference`) are valued exactly; version 1's independent one-step
comparison is not carried over.

## 2. Checks before any model plays (spec §3)

Each check is scripted, provider-free and a test in `tests/test_procurement_pay_or_test_v3.py`; the numbers are the
committed pilot pack's (`cases/procurement_allocation_v1/pay_or_test_v3_pilot/pack.json`, 12 worlds from 809 seeds).

| Check | Result |
|---|---|
| 1. The reference is exact | On every pilot world the best policy's and the one-step rule's exact values equal 400 plays through the environment under the stated law (types, sharing, factories and replies redrawn) within 4 standard errors; on three development worlds, 3,000 plays each, within 0.4 (`test_each_pilot_worlds_values_are_its_own_average_through_the_environment`). With every quote answered and no shared source, the value is v2's exactly |
| 2. Not one-step arithmetic | The one-step rule loses at least $10 in every world (smallest $10.40) and $38.97 on average (at least $15). Looking two newcomers ahead loses $8.90 on average, so the shortfall is planning past one test |
| 3. Testing more attractive than in v2 | Paying the premium loses $83.72 a world (v2 pilot: $69.24). The best first action goes to a newcomer in 12 of 12 worlds, as in v2: 10 are tests and 2 are lookups. In the option-value worlds the best policy beats paying the premium by 10.1% to 22.7% (v2: 2.2% to 15.1%) |
| 4. Brief and environment agree | every action the brief lists is the environment's and no other; every `policy.` and `objective.` field it names is in what the buyer sees; the answer rate, lookup terms, award check, always-arriving sample and always-answering recorded supplier are each tested against the environment |
| 5. Free baselines through the kernel | not yet: the kernel does not trust the plugin (Section 3). Every rule's value is exact by construction and checks 1 and 2 cover the screened ones; with the plugin trusted inside a test, a best-policy and a lookup-first episode run through `execute_plan_cell`, score as the reference and replay byte for byte |

The option-value cell is rare under the stronger one-step rule: 6 worlds took 707 seeds, the one-test-ahead cell 102.

## 3. What blocks live play

The kernel must trust the version 3 plugin: a row `("procurement_allocation_v1", "1.1.0",
"procurement_pay_or_test_v3_environment")` in `registry.TRUSTED_BUILTIN_PLUGIN_KEYS`, with the scoring-contract
enrolment the kernel lane requires. Until then `pay_or_test_v3_runner.build_offline_setup` raises the registry's own
refusal (`test_the_kernel_refuses_the_version_three_plugin_until_it_is_trusted`); with the row present, an episode
with lookups and unanswered quotes runs through `execute_plan_cell`, scores as the reference does and its receipt
replays byte for byte (`test_once_trusted_...`). How the row is reviewed is the owner's decision.

## 4. The pilot

- **Pack:** `pay_or_test_v3_pilot`, 6 `myopic_pays` and 6 `myopic_tests` worlds, each the first admitted seed of its
  block from 9 300 000 (4 000 seeds a block), committed with the plan.
- **Subjects:** Opus 5.5 through Claude Code and Sol 6.1 through Codex, effort low, isolated as the data-center v2
  plan's amendments 1 and 2 require (`cli_isolation`); each CLI's context is probed before any world and the run
  refuses on any violation.
- **Plays:** two a world (replicate ordinals 0 and 1), 24 a subject. A failed cell is typed missingness, never rerun.
- **Ceilings:** $15 (Opus) and $10 (Codex) at list price for the panel, $1 a trajectory; subscription logins, nothing
  charged to OpenRouter. The v3 probe cost $1.21 and $0.66 for 12 plays.
- **Identities:** `procurement_allocation_pay_or_test_v3_pilot_v3_claude_code_opus55_v1` and
  `procurement_allocation_pay_or_test_v3_pilot_v3_codex_cli_sol61_v1` (from `procurement_cli.campaign_id`).
- **Driver:** `tools/cli_subjects/pay_or_test_v3_cli.py`.

## 5. Read-out, in this order

`tools/cli_subjects/pay_or_test_v3_pilot_report.py`, committed with this plan. Every play is replayed from its public
trace (it must reproduce the recorded margin) and priced action by action by the version 3 reference. Per subject and
cell:

1. how often the first information request (quote, sample or lookup) goes to a newcomer, and how often the first action
   is a best first action;
2. the share of the gap between paying the premium and the best policy the play closes, `1 - loss / (best - pay)`,
   world means with a 95% bootstrap interval over worlds;
3. mean decision loss beside the one-step and pay-the-premium rules' exact losses;
4. lookups: plays with any, and plays that settled a kind's sharing (two lookups in one kind);
5. unanswered quote requests and how often the subject asked the same newcomer again;
6. the per-world and within-world SDs of decision loss.

## 6. What the pilot decides

A confirmatory run under a new identity is planned only if both hold:

1. each subject completes at least 22 of its 24 plays;
2. at the pilot's per-world SD, the paired Codex-minus-Opus difference in decision loss needs at most 96 worlds for a
   $10 effect at power 0.8 and alpha 0.05/3 with 5% attrition (the v2 plan's settings).

Otherwise the pilot is reported as development evidence and the design is revisited. Either way the gap-closed
estimates of read-out 2 in the `myopic_pays` cell are reported: they are the first measure of whether a frontier
subject takes a test for what it says about another listing when missing it costs at least 10%.
