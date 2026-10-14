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
profile. The family has no policy below its reference: every non-model policy
is the deterministic reference profile, which scores at the ceiling by
construction (the release raises if any score is not 1). "Qualified" therefore
means the reference reproduces itself, not that the panel tells a better
refund handler from a worse one. Until a lower control exists, a model's score
on this family has nothing below it to be read against.

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

1. **Headroom is unmeasured.** No control has been run on any case. The only
   policy ever executed is the reference, at the ceiling by construction, so no
   case has been shown to be non-trivial, non-floored or non-saturated.
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
   admission leaves. It cannot fail, so it guards nothing.
3. **No guard has a mutation record.** Planted counterexamples exist (Gate 1,
   second evidence item). No guard has been reverted and seen to kill its test, which the
   standard requires before a check counts as evidence.
4. An infrastructure failure becoming typed missingness belongs to the kernel
   and is not exercised by any Refund golden.

## 3. Construct validity and baselines

**Status: failed.**

| Control the standard asks for | Refund V2.5 |
|---|---|
| no-op or feasible lower anchor | none |
| seeded random or weak control | none |
| simple comparison baseline | none |
| informed or adaptive policy | the deterministic reference profiles, one per seat |
| oracle-informed ceiling | the same reference; it is the answer key |

There is no beatability rule. This is RF-D-04, open since V2.1 and carried into
V2.5 by RF-D-06.

What the reference run shows instead: each of the 180 case IDs yields exactly
one action sequence, whichever seat is nominally active and whichever cohort
places it. So the 816 trajectories are 180 per-case sequences, and by action
payload digest only 174 are distinct. On the V5.1 payments cohort, four of the
twelve cases share one byte-identical reference trajectory that ends in
`no_mutation`, and two more groups of two and three cases also coincide. A
constant payments action that never reads the ledger would therefore match the
reference on at least four of those twelve. No such control has been run.

Three findings narrow the construct before any control is added:

1. **Most seats have no judgment to measure.** The customer, payments and V5
   intake seats each have exactly one legal action per phase: the claim must
   equal the public claim, a disclosure must equal exactly the requested facts
   and values, a confirmation must name the current proposal, a payment must
   match the ticket, and a V5 intake batch must equal the reference set. For
   those seats a leaf can only separate "emitted the unique legal action" from
   "invalid". What they measure is reading and binding, not refund judgment.
   More than one legal action exists only in the policy seat and the pre-V5
   intake seat, and comparison campaigns are restricted to the policy seat.
2. **`payment` measures binding, not money (RF-D-05).** The leaf compares the
   payments seat's execution with the environment's own ticket, which is built
   from the policy proposal, not with the reference resolution. Write
   `payment_mutation: "refund"` and the alias scores as `execute`, but the
   environment builds a no-op ticket from the raw string: no money moves where
   the reference refunds, and `payment` scores 1.0. Only `contract` and
   `end_to_end` fall to 0. `test_v25_unambiguous_v24_aliases_only_affect_attribution`
   asserts that 1.0 as intended. This hides a component failure behind its own
   name, which is a Gate 3 stop condition.
3. `end_to_end` is a strict composite. The release document says it is not a
   universal model utility, and no other leaf is declared as the construct.

**Closure requires** at least a no-op/invalid policy and a constant or
public-observation policy per active seat, scored on every public case. It also
requires a beatability rule declared before any model result, a
better-informed-policy contrast on a declared nontrivial slice, and a `payment`
leaf that compares executed transactions with the reference.

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

Blocker: everything upstream. A pilot needs a lower control, a declared
cluster, an admitted profile and a full-trajectory gate first.

## Current implementation coverage

| Gate | Status | Main blocker to `passed` |
|---|---|---|
| Profile admission | `passed` | none |
| Task-distribution admission | `partial` | no measured headroom, undeclared independent unit, no executed holdout |
| Environment and verifier | `partial` | null refund method accepted by schema and failed by verifier (RF-D-03); constant `operational` leaf; no mutation records |
| Construct validity and baselines | `failed` | no lower control or beatability rule (RF-D-04); `payment` scores a refund that never happened (RF-D-05) |
| Attribution and controls | `partial` | no admitted profile or adapter (#267); self-binding QC approval (RF-T-01); vacuous closed-schema admission (RV25-T-06) |
| Confirmatory reliability | `not_run` | every gate above |

## What may be claimed today

V2.5 is a **provider-free developmental environment**. Its four-seat protocol,
admission checks, visibility rules and replay are conformant: the deterministic
reference reproduces itself, at full score, on 816 trajectories covering 180
cases. V2.1 results describe six cases per model, and their policy-compliance
rates are not policy judgment (RF-D-02).

Not permitted, and not claimed in the release: any statement about LLM
ability, a model ranking, paid-equivalence with the historical Arena runs,
reading `payment` as correct money movement, or treating 816, 204 or 180 as
independent observations.

## Registers

- **Tier 1:** none. A Refund failure register is owed.
- **Tier 2,** in [the incident log](../../operations/incident_log.md):
  RV25-D-01..02 and RV25-T-01..06 are on this branch. RF-D-01..04, RF-T-01 and
  RF-J-01 are on branch `codex/refund-gap-analysis`, with the V2.1 gap analysis
  `evidence/refund/refund_v2_1_gap/`. RF-D-05 and RF-D-06 are on branch
  `docs/paper-case-studies-qc`. None of those branches is merged, so the rows
  cited here are not yet all in one file.
- **Errata:** none. V2.5 has published no numbers. A ruling on RF-D-03 that
  changes V2.1's published rates would need one.
