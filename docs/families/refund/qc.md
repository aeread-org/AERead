# Refund QC profile

**Standard:** [AERead benchmark QC](../../operations/benchmark_qc.md)

**Campaign procedure:** [experiment campaign SOP](../../operations/experiment_campaign_sop.md)

**Release under review:** [Refund V2.5 four-seat developmental release](refund_v2_5_release.md)

**Status:** as of 2026-10-13, case-specific profile for family id `refund_v2`
at version 2.5.0 (the V2.5 developmental release), with V2.1 (2.1.0) as its
published history;
`profile_admission=passed`, while
`task_distribution_admission=partial`,
`environment_and_verifier_qc=partial`,
`construct_validity=failed`,
`attribution_and_controls=partial`,
`confirmatory_reliability=not_run`, and
`normative_refund_profile=failed`.
Supporting track: `provider_free_conformance=passed` (816 of 816 trajectories,
rerun 2026-10-13). That is environment conformance, not a measurement.

The construct gate is **failed**, and that is the most important line in this
profile. Since 2026-10-13 it fails on a measurement rather than for want of
one. Lower controls now exist for every seat, and a beatability rule was
declared before any of them ran. The reference fails that rule on all 11 public
cohorts in the policy seat, the seat comparison campaigns use. An
unconditional full refund that collects no fact passes the strict
`end_to_end` on 38 of the 180 case IDs (Gate 3). Customer and payments fail
too; only intake passes. A model's policy-seat score therefore includes cases
a constant answer passes, and must not be read as policy judgment.

This profile binds the shared gates to Refund. Requirements inherited from the
standard are not repeated unless Refund supplies a specific implementation,
threshold, policy or artifact. Before this document the family was `failed` at
Gate 0.

## Scope

| Identity | What it is | Status under this profile |
|---|---|---|
| `refund_v2` 2.5.0 | V2.5: four seats (customer, intake, policy, payments), qualified contribution `aeread.refund_v25`, provider-free only | the statuses above |
| `refund_v2` 2.1.0 | V2.1 1:N pilot, six scenarios; seven bundles under `evidence/refund/` dated 2026-09-12 | development evidence only; the gates below say where it falls short |
| `refund_v1` 1.3.0 | V1.3 two-seat negotiation ([case contract](case.md)) | every gate `not_run`, blocker: not evaluated by this profile; no result under it may be described as measuring the construct |

`evidence/refund/` also holds one legacy DeepSeek run dated 2026-08-31,
retained for provenance and outside V2.1.

## 0. Profile admission

`passed` as of 2026-10-13: this document is the profile, it records a typed
status for the family and for each of Gates 1 through 5, and it states a
blocker for every gate not `passed`.

The Gate 0 test could not see the gap. `refund_v2` registers through the
qualified contribution path, not `TRUSTED_BUILTIN_PLUGIN_KEYS`, so
`tests/test_benchmark_qc_profiles.py` never listed it as profiled or exempt.
It is now in that file's `FAMILY_PROFILES`, so the profile's existence and its
reference to the standard are tested. The exemption list is unchanged at 18.

## 1. Task-distribution admission

**Status: partial.**

The 11 public cohorts at seed 301 hold 204 placements and 180 distinct case
IDs, because the 24 core cases also sit inside the 76-case policy cohort.
Recomputed 2026-10-13 from the resolved plans:

| Unit | Count |
|---|---:|
| cohort placements | 204 |
| trajectories, all four seats (`--panel all`) | 816 |
| distinct case IDs (= distinct payload digests) | 180 |
| declared minimal pairs | 90 |
| distinct interaction contents (claim, policy text, price, tax, facts; labels, IDs and seat context removed) | 124 |
| scenario templates | 44 |

Evidence on hand:

- Generation is deterministic. The public factory rebuilds the exact plan
  (`test_public_factory_reconstructs_exact_plan`), and plan identity binds the
  implementation pins.
- Every case is a member of a minimal pair with declared changed facts.
  Admission checks fact domains, resolution invariants, rendered contract
  markers, pair rules, ledger validity, acyclic prerequisites and the
  collection budget. A planted counterexample is rejected in
  `tests/test_refund_v25_*.py` for a tampered unit contract, a nonunique ledger
  revision, an undeclared pair change, a cyclic prerequisite, an insufficient
  budget and an undeclared seat scope. The branch compiler is checked against
  hand-written goldens only by agreement. No test plants a disagreement.
- Collection budgets derive from the finite fact graph (whole case at most
  2N+5 logical actions), so a legal one-fact-at-a-time path cannot run out of
  budget.

Blockers to `passed`:

1. **Headroom is measured only from below.** The lower-control screen (Gate 3)
   tests the *trivial* ground. In the policy seat a full-refund constant
   solves 38 of the 180 case IDs, so those cases are trivial. The *floored* and
   *saturated* grounds need a model control at several seeds, and none has
   run.
2. **The independent unit is undeclared.** It could be 44 templates, 90 pairs,
   124 contents or 180 case IDs, and only one seed has been qualified. V2.1
   made this mistake once: its 120-cell panel is six cases (RF-D-01).
3. **No split has been executed.** All 180 public cases are split `dev`. The V4
   and V5 builders can add held-out pairs, and their disjointness from
   development is tested, but no holdout has been run.
4. Seed variation is implemented per builder and has not been inspected per
   cohort, as the release document itself requires.

## 2. Environment and verifier

**Status: partial.**

| Golden | Evidence |
|---|---|
| Successful | `test_v25_provider_free_conformance_for_each_active_seat`; hand-written branch outcomes in `test_independent_terminal_goldens`, not generated from the compiler |
| Valid but poor | `test_v25_partial_semantics_report_coverage_and_fail_strict_primary` |
| Invalid or unauthorized | `test_payment_negative_controls_and_redelivery`, `test_customer_negative_controls`, `test_new_settlement_on_redelivery_blocks_a_second_mutation` |
| Malformed output | `test_v25_unknown_or_unhashable_values_fail_safely`, `test_v25_invalid_amount_types_fail_safely` |
| Degenerate reference | `not_applicable` for denominators: every leaf is pass/fail on [0, 1] with no normalizer. Collaboration metrics with no opportunity report coverage 0, not credit |
| Leakage audit | `test_v25_observations_enforce_seat_visibility`, `test_all_fact_masks_never_read_hidden_values`, `test_intake_plan_is_value_blind_and_no_oracle_values_exposed` |
| Replay | `python -m aeread_families.refund.v2_5_release --panel all --seed 301` on 2026-10-13: 816 of 816 completed, 0 paid calls, 0 operational exclusions; every receipt replayed and audited independently through the kernel |

Blockers to `passed`:

1. **The interface accepts what the verifier fails (RF-D-03, carried by
   RF-D-06).** The policy schema types `refund_method` as string or null. The
   environment turns a null into `"none"` when it builds the payment ticket, so
   the right money moves, but scoring compares the raw null with `"none"`:
   `payment` 0.5, `contract` 0, `end_to_end` 0. That needs a ruling, then a new
   identity.
2. **The `operational` leaf is the constant 1.0** and is one of the four
   admission leaves. It cannot fail, so it guards nothing. Measured: every
   control scores 1.0 on it, including `refuse_empty`, which returns `{}` on
   every placement of every seat.
3. **No guard has a mutation record.** Planted counterexamples exist (Gate 1,
   second evidence item). No guard has been reverted and seen to kill its test, which the
   standard requires before a check counts as evidence.
4. An infrastructure failure becoming typed missingness belongs to the kernel
   and is not exercised by any Refund golden.

## 3. Construct validity and baselines

**Status: failed.** The gate now fails on a measurement. Lower controls exist
for every seat, and the beatability rule below was declared and pushed
(`1ededca5`) before any control ran. The reference fails that rule on every
public cohort in the policy, customer and payments seats. RF-D-05 also still
stands: the `payment` leaf checks binding to the proposal, not the money that
moved. That alone is a Gate 3 stop condition, whatever the controls show.

| Control the standard asks for | Refund V2.5 |
|---|---|
| no-op or feasible lower anchor | `refuse_empty` (every seat); `noop_null_resolution` (policy) |
| seeded random or weak control | `random_legal` at seeds 0, 1 and 2 (policy), legal-only and checked |
| simple comparison baseline | `naive_full_refund` (policy), `naive_overdisclose` and `naive_first_record` (customer), `naive_first_sorted` (intake), `naive_no_mutation` (payments) |
| informed or adaptive policy | the deterministic reference profiles, one per seat |
| oracle-informed ceiling | the same reference; it is the answer key |

Until 2026-10-13 there was no lower control and no beatability rule (RF-D-04,
open since V2.1 and carried into V2.5 by RF-D-06).

### Beatability rule `refund_v25_beatability/1`

Declared and committed on 2026-10-13 **before any control was executed on any
case**, in `src/aeread_families/refund/v2_5_controls.py` (`RULE`,
`evaluate_rule`). For each screened seat, each public cohort at seed 301 and
each declared lower control K, with the release's reference profile in the
active seat as the comparison and every other seat scripted:

| Clause | Requirement |
|---|---|
| B1 | mean reference `end_to_end` − mean K `end_to_end` ≥ **0.50** |
| B2 | mean reference `policy_semantic` − mean K `policy_semantic` ≥ **0.25**, policy seat only (elsewhere `policy_semantic` is the scripted policy counterpart's) |
| B3 | share of cases where K's `end_to_end` reaches the reference's ≤ **0.10**; under ten cases that allows none |

A cohort passes for a seat only if every clause holds for every control. A
failing cohort is reported as a finding (the cohort is trivial for that seat:
a control without the judgment reaches the reference), not fixed by retuning:
a changed threshold or clause is a new rule identity, and this verdict stays.
The margins are set from the leaves' units: a floor that completes half the
strict trajectories leaves half the cohort unable to separate judgment from its
absence; 0.25 is one of `policy_semantic`'s four fields, the most a constant
answer should get by base rate.

Declared controls (`CONTROLS`, `refund_v25_lower_controls/1`):

| Seat | Controls |
|---|---|
| policy | `refuse_empty`, `noop_null_resolution`, `naive_full_refund`, `random_legal` at seeds 0, 1, 2 |
| customer | `refuse_empty`, `naive_overdisclose`, `naive_first_record` |
| intake | `refuse_empty`, `naive_first_sorted` |
| payments | `refuse_empty`, `naive_no_mutation` |

`CONTROL_DESCRIPTIONS` in the module defines each one. A random draw is keyed
by its seed and the canonical observation, so it depends only on what the seat
sees.

### Screen result

`python -m aeread_families.refund.v2_5_controls --output FRESH_PATH --record cases/refund_v25/qc/lower_controls.json`
plays the reference and every control through the real environment for each
seat and each of the 11 cohorts at seed 301. Each trajectory goes through
kernel finalization, replay and independent audit. That is 3,468 trajectories
and 0 paid calls. The record holds every leaf for every case, the per-cohort
means, illegal-move counts and the verdict. It is bound to the controls'
source digest, and a test regenerates one cohort byte for byte. The reference
scores 1.0 on every leaf of every placement. `random_legal` made 0 illegal
moves in 612 trajectories.

| Cohort | n | Policy | Customer | Intake | Payments |
|---|---:|---|---|---|---|
| `core` | 24 | fail: full refund reaches 5 (B3) | fail: first record reaches 24 (B1+B3) | pass (2 reached) | fail: no-mutation reaches 10 (B3) |
| `policy` | 76 | fail: full refund reaches 14 (B3) | fail: first record reaches 76 (B1+B3) | pass (2 reached) | fail: no-mutation reaches 32 (B3) |
| `v3_common` | 8 | fail: full refund reaches 2 (B3) | fail: first record reaches 8 (B1+B3) | pass (0 reached) | fail: no-mutation reaches 4 (B3) |
| `v3_intake` | 24 | fail: full refund reaches 3 (B3) | fail: first record reaches 24 (B1+B3) | pass (0 reached) | fail: no-mutation reaches 15 (B1+B3) |
| `v3_payments` | 18 | fail: full refund reaches 10 (B1+B3) | fail: first record reaches 18 (B1+B3) | pass (0 reached) | fail: no-mutation reaches 5 (B3) |
| `v3_customer` | 16 | fail: full refund reaches 3 (B3) | fail: first record reaches 16 (B1+B3) | pass (0 reached) | fail: no-mutation reaches 7 (B3) |
| `v4_payments` | 8 | fail: full refund reaches 4, semantic gap 0.19 (B2+B3) | fail: first record reaches 8 (B1+B3) | pass (0 reached) | fail: no-mutation reaches 3 (B3) |
| `v4_customer` | 4 | fail: full refund reaches 1 (B3) | fail: first record reaches 2 (B3) | pass (0 reached) | fail: no-mutation reaches 2 (B3) |
| `v5_intake` | 8 | fail: null resolution, semantic gap 0.00 (B2) | fail: first record reaches 8 (B1+B3) | pass (0 reached) | fail: no-mutation reaches 8 (B1+B3) |
| `v51_payments` | 12 | fail: full refund, semantic gap 0.00 (B2) | fail: first record reaches 12 (B1+B3) | pass (0 reached) | fail: no-mutation reaches 2 (B3) |
| `v5_customer` | 6 | fail: full refund reaches 1 (B3) | fail: first record reaches 4 (B1+B3) | pass (0 reached) | fail: no-mutation reaches 2 (B3) |

"Reaches k" counts the cases where that control's strict `end_to_end` equals
the reference's. Only the failing control is named in each cell; every
other control passed every clause there.

What the screen establishes:

1. **The policy seat has trivial cases (RV25-D-03).** `naive_full_refund`
   grants a full refund on the first turn and collects nothing. It is
   illegal on any case that still has a pending fact, yet it passes the strict
   composite on 38 of the 180 case IDs. On those cases intake has already
   disclosed every fact the branch needs, and the answer is a full refund. On
   `v5_intake` every reference resolution is a hold, and on `v51_payments`
   every one is a full refund. There a constant is semantically exact. No
   other control ever reaches the reference: `refuse_empty`,
   `noop_null_resolution` and the three `random_legal` seeds have strict
   `end_to_end` 0 on all 204 placements. Random `policy_semantic` ranges from
   0.17 to 0.50 per cohort.
2. **`evidence` measures legality, not collection (RV25-D-04).** Requests are
   legal only inside the public pending set, and submitting is illegal until
   that set is empty. So every legal path scores 1.0, and `random_legal` does
   on all 612 of its trajectories.
3. **Customer and payments measure copying and base rate (RV25-D-05,
   RV25-D-06).** This confirms by measurement what this profile argued from
   the legality rules. A customer that takes the first listed record equals
   the reference wherever the observation is a flat fact map (9 cohorts). A
   payments seat that always emits `no_mutation` is right on every no-op
   ticket, which is 17% to 100% of each cohort. Intake passes, but only against
   a sorted-order control. On `v5_intake` its legal set is a single batch, so a
   random legal intake would be the reference.
4. **Correction (RV25-J-02).** This profile earlier predicted that a constant
   payments action matches at least four of the twelve `v51_payments` cases.
   The measured number is 2. Ten of the twelve execute on first delivery and
   reach `no_mutation` only at redelivery.

A post-hoc hypothesis, not a verdict: score minimal pairs instead of cases.
The full-refund constant passes both members of 0 of the 38 `policy` pairs,
which include `core`'s 12. Across all 102 pair placements it passes both
members of 7, all in the two payments cohorts. A pair-level rule would be a
new identity (`refund_v25_beatability/2`), declared before it is evaluated,
and this verdict stays recorded.

Two structural findings still narrow the construct:

1. **Most seats have no judgment to measure.** The customer, payments and V5
   intake seats each have exactly one legal action per phase: the claim must
   equal the public claim, a disclosure must equal exactly the requested facts
   and values, a confirmation must name the current proposal, a payment must
   match the ticket, and a V5 intake batch must equal the reference set. The
   screen above measures the consequence. More than one legal action exists
   only in the policy seat and the pre-V5 intake seat, and comparison campaigns
   are restricted to the policy seat.
2. **`payment` measures binding, not money (RF-D-05, still open).** The leaf
   compares the payments seat's execution with the environment's own ticket,
   which is built from the policy proposal, not with the reference resolution.
   Write `payment_mutation: "refund"` and the alias scores as `execute`, but
   the environment builds a no-op ticket from the raw string. No money moves
   where the reference refunds, yet `payment` scores 1.0; only `contract` and
   `end_to_end` fall to 0.
   `test_v25_unambiguous_v24_aliases_only_affect_attribution` asserts that 1.0
   as intended. This hides a component failure behind its own name, which is a
   Gate 3 stop condition. `end_to_end` remains a strict composite, not a
   universal model utility.

**Closure requires** a policy-seat panel or scoring unit that passes a
beatability rule declared before it is evaluated, which rules out admitting
cases a constant answer solves. It also requires the floored and saturated
grounds measured with a model control, a better-informed-policy contrast on a
declared nontrivial slice, an `evidence` leaf that scores collection rather
than legality, and a `payment` leaf that compares executed transactions with
the reference.

## 4. Attribution and experimental controls

**Status: partial.**

Declared block: one focal subject seat with three deterministic scripted
counterparts. Controlled mode refuses anything but exactly one active seat
(`build_refund_v25_run`, and the V5 builder separately). Comparison campaigns
must be controlled, with `active_agents == ("policy",)`. Plan-level contract
tests: `test_v25_controlled_plan_replaces_exactly_one_seat`,
`test_v25_extra_implementation_pins_bind_run_plan_identity`,
`test_v25_comparison_contract_requires_boolean_and_controlled_policy`,
`test_public_run_cannot_be_restarted`.

Blockers to `passed`:

1. **No profile has been admitted.** The public entrypoint refuses a paid
   provider before any credential or client loads
   (`test_paid_entrypoint_fails_before_credentials_or_client`). The kernel
   Arena adapter rejects completed invalid JSON before family scoring and does
   not honour all profile controls (RV25-T-01,
   [#267](https://github.com/aeread-org/AERead/issues/267)). No
   `full_trajectory` gate exists.
2. **The human-QC approval still binds itself (RF-T-01, carried by RF-D-06).**
   The V2.5 record names a reviewer and a date, has scope
   `developmental_design` and says `normative_benchmark_promotion: false`, and
   the V2.1 approval is now rejected (RV25-D-02). But `_contribution()` sets the
   approval's `contribution_sha256` to the digest of the contribution it has
   just built, and `qc/provider_free.json` is written by hand rather than bound
   to a run digest.
3. **Closed-schema admission passes vacuously (RV25-T-06, logged with this
   profile).** The contribution declares empty object schemas for action and
   observation. All four real seat output schemas fail the kernel's
   `_strict_schema`: customer and policy leave properties out of `required`,
   and intake and payments have an untyped `decision`.
4. The independent cluster is undeclared (Gate 1, blocker 2), so repeats, seats and
   cohorts have no declared correlation structure.

## 5. Confirmatory reliability and publication

**Status: not_run.**

V2.5 has no model campaign, variance pilot or freeze, and no paid call has
been made under it. The V2.1 bundles are not confirmatory evidence. Their
model evidence is six cases at temperature 0, each repeated under 20 seeds, and
was reported at n = 120 per model (RF-D-01). Their policy-compliance rate folds
three different failures into one zero (RF-D-02). The guarded-metric
falsifiability check (item 7 of the standard) has not been attempted for any
Refund metric.

Blocker: everything upstream. A pilot needs a policy-seat panel that passes a
declared beatability rule, a declared cluster, an admitted profile and a
full-trajectory gate first.

## Current implementation coverage

| Gate | Status | Main blocker to `passed` |
|---|---|---|
| Profile admission | `passed` | none |
| Task-distribution admission | `partial` | 38 of 180 case IDs trivial for the policy seat, floored and saturated grounds unmeasured, undeclared independent unit, no executed holdout |
| Environment and verifier | `partial` | null refund method accepted by schema and failed by verifier (RF-D-03); constant `operational` leaf; no mutation records |
| Construct validity and baselines | `failed` | the reference fails `refund_v25_beatability/1` on all 11 cohorts in the policy, customer and payments seats (RV25-D-03, D-05, D-06); `evidence` scores legality (RV25-D-04); `payment` scores a refund that never happened (RF-D-05) |
| Attribution and controls | `partial` | no admitted profile or adapter (#267); self-binding QC approval (RF-T-01); vacuous closed-schema admission (RV25-T-06) |
| Confirmatory reliability | `not_run` | every gate above |

## What may be claimed today

V2.5 is a **provider-free developmental environment**. Its four-seat protocol,
admission checks, visibility rules and replay are conformant: the deterministic
reference reproduces itself, at full score, on 816 trajectories covering 180
cases. Against provider-free lower controls it is beatable only in the intake
seat; in the policy seat a constant full refund passes the strict composite on
38 of the 180 case IDs. V2.1 results describe six cases per model, and their
policy-compliance rates are not policy judgment (RF-D-02).

Not permitted, and not claimed in the release: any statement about LLM
ability, a model ranking, paid-equivalence with the historical Arena runs,
reading `payment` as correct money movement, reading `evidence` as collection
judgment, or treating 816, 204 or 180 as independent observations.

## Registers

- **Tier 1:** none. A Refund failure register is owed.
- **Tier 2,** in [the incident log](../../operations/incident_log.md):
  RV25-D-01..06, RV25-T-01..06 and RV25-J-01..02 are on this branch. RF-D-01..04, RF-T-01 and
  RF-J-01 are on branch `codex/refund-gap-analysis`, with the V2.1 gap analysis
  `evidence/refund/refund_v2_1_gap/`. RF-D-05 and RF-D-06 are on branch
  `docs/paper-case-studies-qc`. None of those branches is merged, so the rows
  cited here are not yet all in one file.
- **Errata:** none. V2.5 has published no numbers. A ruling on RF-D-03 that
  changes V2.1's published rates would need one.
