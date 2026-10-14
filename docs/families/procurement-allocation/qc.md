# Procurement allocation V1 QC profile

**Standard:** [AERead benchmark QC](../../operations/benchmark_qc.md)

**Campaign procedure:** [experiment campaign SOP](../../operations/experiment_campaign_sop.md)

**Design review:** [procurement design review](design_review.md)

**Continuous replacement:** [unified run plan](unified_run_plan.md); a new campaign identity, with provider-free admission and conditional live gates.

**Status:** case-specific profile;
`development_case_qualification=passed` and
`environment_and_verifier_qc=passed`, while
`construct_validity=failed` and `normative_procurement_profile=partial`.

The construct gate is **failed**, not partial, and that is the single most
important line in this profile. Deterministic public-observation policies beat
the qualified model on the development panel by $28.50 per world on labeled
cases and $54.92 on opaque ones, with six-world intervals excluding zero. A
family whose trivial baseline outscores its subject is not yet measuring the
construct it declares. The [design review](design_review.md) identifies why:
four of the five economic dimensions the objective names carry no measurable
weight in the V1 worlds.

This profile binds the shared gates to procurement allocation V1. Requirements
inherited from the standard are not repeated unless procurement supplies a
specific implementation, threshold, policy, or artifact.

## 0. Profile admission

`passed` as of 2026-09-06: this document is the profile, and it records a typed
status for the family and for each of Gates 1 through 5, with a stated blocker
for every gate that is not `passed`. Before it existed, procurement was `failed`
at this gate for the whole life of the family, which is why its construct
failure went unrecorded.

## 1. Task-distribution admission

The independent unit is the **economic world**: one BOM, objective, and supplier
panel. Presentation surfaces (`labeled`, `opaque`, `blinded_v3`) are paired
mirrors of the same world and are never independent observations of it.

Panel inventory (admission status is stated separately from generation):

| Panel | Worlds | Surfaces | Purpose |
|---|---:|---|---|
| `dev/` | 7 | labeled | development qualification |
| `blinded_v3/` | 6 | opaque mirror of `dev` | presentation-invariance control |
| `confirmatory_v1/` | 12 | labeled + opaque | held-out panel for the V4 scaffold |
| `risk_gates_v1/` | 6 | labeled + opaque | sample-schedule and landed-cash factorial |
| `qwen_holdout_v1/` | 6 | opaque | targeted residual-capability holdout |
| `confirmatory_v2/` | 12 | labeled + opaque | held-out panel for the pre-award check; **inadmissible**, control saturates 7 of 12 worlds |
| `duediligence_v1/` | 6 | labeled + opaque | first information panel; **inadmissible**, 1 of 6 worlds can express a difference. Retained as the screen's regression fixture |
| due-diligence recalibration | 6 | not committed | one trap per component so a single recovery fits the budget; **inadmissible**, control saturates 6 of 6 at four seeds while all baselines lose. Not written to `cases/`; its measurement is defect 17 |
| `information_v1/` | 8 | labeled + opaque | information worlds; **inadmissible**, control saturates 7 of 7 measured worlds and the biased channel is unread |

Admission is decided by `headroom_screen.classify_world`, which rejects a world
on three separate grounds -- trivial, floored, saturated -- measured over at
least three seeds. No panel has yet passed it. That is the current state of the
family and is reported as such rather than worked around.

Validate for every world:

- exact case-content digest, stable under regeneration;
- an `economic_world_sha256` distinct from every prior panel, and a world seed
  drawn from a domain disjoint from every prior panel;
- a strictly positive full-information bound, so the case has a beneficial
  feasible award and deferring is not trivially optimal;
- a bound reachable within the declared ten-action budget;
- a paired surface whose world seed and economic-world digest match exactly.

Generation refuses a world whose supplier-by-quantity enumeration exceeds
`UPPER_BOUND_ENUMERATION_LIMIT`, naming the coarsening required. Before that
bound existed the generator appeared to hang, which silently made fine-grained
quantity worlds unauthorable; see design-review defect 7.

**Not yet enforced, and it has now cost a full run.** The standard requires
admitted instances to be *informative*, and procurement checks nothing about
headroom. Two consequences are measured:

- `negotiated_moq` shipped with the only real MOQ headroom in a corpus of 147
  supplier records, while other worlds advertised negotiation worth cents.
- `confirmatory_v2` passed every Gate 1 check and is still uninformative: the V4
  control scores 97% feasible awards on its labeled surface against 56% on the
  development panel, and wins every completed row in 7 of its 12 worlds. A
  144-row run was spent discovering this.

Two admission criteria are therefore owed, and neither exists yet:

1. **Dimension headroom.** A world claiming to exercise a dimension must show
   that dimension is worth a declared minimum share of its bound.
2. **Control headroom.** A panel must be admitted against a *measured* control
   rate, not an authored intuition about difficulty. Run the frozen control or
   the deterministic policy baselines across candidate worlds and admit a world
   only when the control fails a declared minimum share of rows; publish the
   measured rate per world in the panel manifest.

Until criterion 2 exists, `confirmatory_v2` is recorded here as **inadmissible**:
it is a validly generated panel that cannot measure the treatment it was built
for. See design-review defect 14.

## 2. Environment and verifier

Procurement goldens, all in `tests/test_procurement_allocation_case.py`:

| Golden | Test |
|---|---|
| Successful | `test_optimal_interactive_script_matches_reference_and_replays` |
| Valid but poor | `test_return_window_changes_expected_recovery_and_margin` |
| Invalid or unauthorized | `test_verbal_confirmation_is_visible_but_not_award_eligible` |
| Rejected negotiation leaves state unchanged | `test_counter_outside_supplier_limits_is_rejected_without_new_offer` |
| Malformed output | `test_parser_projects_superset_schema_onto_selected_action` |
| Non-terminating projection | `test_check_award_projection_matches_the_award_it_precedes` |
| Leakage audit | `test_observation_hides_private_terms_and_marks_listings_unverified` |

The oracle is exhaustive enumeration over supplier, negotiation mode, and
admissible quantity, so it has **no independent second implementation**. The
standard permits exhaustive enumeration on small instances in place of an
independent oracle, and that is the route taken; the compensating control is
that `evaluate_award` is the single scorer used by the bound, the terminal
score, the pre-award check, and the offline replay, so a defect in it moves all
four together rather than producing a disagreement. This is a known weakness of
the profile, not a strength.

Replay is stronger here than the standard requires. The regret decomposition
re-drives **every published action trace** through the environment and requires
the recomputed feasibility, margin, regret, and completed kits to match the
sealed row within $0.000001. 216 rows across eight bundles currently pass. Any
environment change is therefore checked against the whole published corpus, not
against a fixture set.

## 3. Construct validity and baselines

**Status: failed.**

Declared baselines, all deterministic and provider-free, in
`policy_baselines.py`:

| Policy | Interpretation |
|---|---|
| `defer` | the explicit outside option; a lower anchor |
| `displayed_price_greedy` | qualify the cheapest visible listing first |
| `listing_claim_fit` | prioritize overlap with the required variant claim |
| `semantic_hint` | additionally read suggestive supplier identifiers |

Each policy sees only the public observation serialized into the provider
request, never `private_terms` or the case object.

The measured result is the gate failure. Over the six development worlds, after
averaging three inference seeds within each world:

| Surface | `displayed_price_greedy` minus GLM, contribution margin | Six-world interval |
|---|---:|---|
| labeled | +$28.50 | [$2.32, $55.91] |
| opaque | +$54.92 | excludes zero |

Both displayed-price and listing-claim policies were feasible in 6 of 6 worlds
on each surface. A subject that loses to a policy which reads only the displayed
price is not demonstrating the construct the objective describes.

Two further construct results belong here rather than in a campaign document:

- **Presentation dependence.** `semantic_hint` improved by $4.01 when supplier
  names became opaque, so suggestive names are not uniformly helpful; but the
  worksheet V2 campaign showed the model's payment-terms win depended on reading
  `terms_flexible` from a labeled identifier, capturing the saving on 3 of 3
  labeled seeds and 1 of 3 opaque ones. Labeled surfaces measure name-reading in
  part, so opaque should be the primary reported surface.
- **Ceiling saturation.** 23 of 53 feasible awards in the pre-award-check run sat
  exactly at the full-information bound. A panel where the subject frequently
  attains the ceiling exactly has no headroom left to measure.

**Closure requires** the `information_v1` panel to show that a subject can
separate from these baselines on worlds where verification, information cost,
and negotiation headroom carry weight. Until a live result on that panel exists,
this gate stays failed and no procurement campaign result may be described as
measuring buyer competence in general.

## 4. Attribution and experimental controls

Procurement is a single-seat family: one buyer against a deterministic
environment. There is no opponent profile, seat rotation, or self-play block, so
the standard's cross-play requirements are `not_applicable`.

| Declared treatment factor | Controls bound |
|---|---|
| Buyer prompt | route, revision, harness, action schema, verifier, retry policy, budget, cases, seeds |
| Model or provider route | prompt, harness, schema, verifier, retry policy, cases, seeds |
| Presentation surface | economics, world seed, objective, private terms, upper bound |
| Environment interface (`check_award`) | prompt held to the frozen procedure plus one declared step |

Pairing is by exact case identifier and inference seed. Every campaign binds its
parent evidence manifest by file digest before any live request, and a route or
prompt change takes a new campaign identity.

**Route substitution is prohibited.** An operational failure is typed
missingness and is never replaced by another provider, seed, or retry into an
existing row.

## 5. Confirmatory reliability and publication

The guarded metric is **`feasible_award`**, true only for a submitted award that
passed every gate. It is not terminal feasibility, which `outcome` reports as
true for an explicit deferral. That distinction is not cosmetic: the pre-award
development run passed a terminal-feasibility guardrail at +0.389 while
producing fifteen deferrals worth nothing, which is design-review defect 5. A
synthetic all-deferral arm must fail the confirmation rule, and
`test_procurement_qc_invariants.py` asserts exactly that, mutation-verified
against the previous guard.

Missingness policy: a typed operational failure seals that row as missingness
and the panel continues. A world-seed pair enters the estimate only when both
arms completed it, dropped pairs are counted and published, a world left with no
usable pair is an error rather than a silent omission, and eligibility requires
the missing fraction to stay under a declared ceiling. The earlier
abort-on-first-failure policy left every remaining cell neither a receipt nor
typed missingness, which the standard already forbids; see design-review
defect 11.

## 6. Current implementation coverage

| Gate | Current coverage | Main blocker to `passed` |
|---|---|---|
| Task-distribution admission | Seven panels with distinct world seeds and economic-world digests, positive reachable bounds, and a bounded generator | No per-dimension headroom check, so a world can claim to exercise negotiation while it is worth cents |
| Environment and verifier | Seven goldens, leakage audit, and full-corpus replay of 216 published rows | No independent oracle implementation; exhaustive enumeration is the oracle |
| Construct validity and baselines | Four deterministic policies across both surfaces, 48 rows, zero provider cost | **Failed:** the greedy baseline beats the subject by $28.50 labeled and $54.92 opaque |
| Attribution and controls | Single-seat pairing by case and seed, digest-bound parents, prohibited substitution | No blocker; cross-play requirements are `not_applicable` |
| Confirmatory reliability | `confirmatory_v2` frozen with `feasible_award` guarded and a declared missingness ceiling; 144 rows executed | The panel is inadmissible: its control saturates, so no confirmatory claim is available from it in either direction. A replacement panel admitted against a measured control rate is required |

## 7. Known construct limits

The [design review](design_review.md) records eleven defects with recomputed
evidence. Those that bound what this family can currently claim:

1. Verbal claims were always true, so verification had no economic content. Fixed
   by `verbal_bias`; unexercised until an `information_v1` result exists.
2. Buying every piece of information costs 1.76% of gross revenue on average, so
   the information trade-off never binds and the real scarce resource is the
   ten-action budget.
3. Two of 147 supplier records have any MOQ headroom and price floors sit 3.10%
   below quote, so four of five counterable terms are decorative.
4. Historical counters named no rejected field. New cases can declare
   `counter_feedback=field_specific`; replies identify failed terms without
   revealing private limits. Legacy receipt behavior remains unchanged.
6. Replaying every prefix of the fifteen pre-award deferrals shows no point at
   which a feasible award was constructible, so the family measures irreversible
   early commitment without giving feedback until the end.
7. `validate_payload` rejects a world whose full-information optimum does not
   beat deferring, and computes that optimum under the action budget, so the rule
   admitting a world is the rule making it hard. A budget sweep found every world
   at 0/3 or 3/3 with no fractional cell, so the panel-level 50% award rate at
   budget 6 is a mixture of deterministic worlds rather than headroom.
8. Within-world seed variance is zero on every world measured, across two
   independent runs. Seeds are repeats, not replicates: the effective sample
   size of a panel is its world count, and any interval computed across rows is
   narrower than the truth by construction.

Defects 7 and 8 bound this family harder than 1 through 4, because they say no
panel built on the current environment can express a treatment effect on award
feasibility within a world, however it is tuned. The unblocking change is noisy
sampling, which turns a one-draw settlement into an accumulation and creates both
the interior band defect 7 says is missing and the variance defect 8 says is
absent.

Until then, procurement results describe **award feasibility under declared
constraints**. They do not describe information acquisition, negotiation, or
buyer competence in general, and no status report may translate the narrower
claim into the broader one. Seed count must not be used to buy precision on this
family, and the variance pilot must refuse to proceed on zero within-world
variance rather than reading it as a tight measurement.

## 8. Pack profile: `pay_or_test_v1`

**Status as of 2026-10-13:** Gate 0 `passed`, Gate 1 `failed`, Gate 2
`passed`, Gate 3 `failed`, Gate 4 `partial`, Gate 5 `not_run`.

The pack is one decision: pay the premium to the one supplier with a record, or
spend money and days testing a cheaper newcomer whose odds the listing states.
It has an exact answer, and that is what both failures are about. A rule that
compares each untested newcomer with paying, one test ahead, reaches the best
policy's value to within $0.06 a world. The design rule for these cases is that
when the one-step rule matches the best policy the case is arithmetic and is not
run (written first for the data-center agreement case, in its
`agreement_case.md` on branch `codex/datacenter-agreement`, not yet on `main`).
So the construct gate is `failed` whatever any subject scores on it, and the
flash-model panels below are evidence of headroom between model tiers, not of
the construct.

| Gate | Status | Evidence | Blocker |
|---|---|---|---|
| 0. Profile admission | `passed` | this section: a typed status and a blocker for every gate of the pack | none |
| 1. Task-distribution admission | `failed` | six cells (`pay_money`, `pay_time`, `test_cheapest` and `test_other` on a tight and a loose clock) of four worlds each, regenerated byte for byte (`test_committed_pack_is_reproduced_byte_for_byte`); admitted on what the buyer sees, prices, fees, days and stated odds, with the newcomers' types drawn afterwards on their own stream, so admission cannot select on luck (`test_the_cell_does_not_depend_on_how_the_newcomers_turned_out`, `test_a_listing_is_the_same_whatever_type_its_seller_is`); every cell's claim tested against the exact reference; `natural_mix` in `pack.json` records how the generator's draws fall | the *trivial* ground of measured headroom. The one-step rule is a deterministic policy that reads only public observations, and it matches the best policy in 23 of 24 worlds to within a cent (largest gap $1.43). Admission screened worlds against the fixed rules, not against it. Same finding as Gate 3, seen from admission |
| 2. Environment and verifier | `passed` | no pinned module changed; the best informed policy's value equals the environment's own average over all 27 type profiles in all 24 worlds, for the best policy and for every scripted rule (`test_expected_values_equal_the_average_over_every_way_the_newcomers_could_turn_out`, extended from 6 worlds to 24 on 2026-10-13, 25 s with the pack build); each rule the prompt states is checked against the environment (`test_the_order_is_counted_as_the_prompt_says`, `test_version_two_adds_only_two_stated_rules_and_both_are_true`); only a quote shows lateness and only a sample shows yield (`test_only_a_quote_shows_lateness_and_only_a_sample_shows_yield`); every v2 flash-model receipt replays to state and score offline (50 of 50, gates included), and the report re-drives every trace to the recorded margin within $0.000001 | none for this pack. P-D-17 (the pre-award check is an oracle under sample noise) does not apply: no world declares `sample_noise` and a test holds it to that (`test_a_listing_states_the_price_lead_time_and_sample_terms_the_supplier_holds`); a check after a quote and before a sample reports `sample_not_verified` and 0 kits, identical for a good and a poor newcomer in 288 of 288 checks (every newcomer of the 24 worlds, four quantities); after a sample the yield is already exact. P-D-23 (schema admits a null message the parser rejects) was a transport defect, handled as the standard requires (typed `malformed_procurement_action`, scored as walking away) and closed for new runs by the OpenRouter driver's v2 schema, which `tests/test_pay_or_test_openrouter.py` holds to the parser field by field. P-T-14 and P-T-15 (report crashes on a one-world gate and on a rejected action) are fixed with tests in `tests/test_pay_or_test_report.py` |
| 3. Construct validity and baselines | `failed` | exact expected loss against the best informed policy over the 24 worlds (`pack.json`): best-odds-first-once $45.7, always pay $75.2, cheapest-first-once $81.4, cheapest-until-found $146.1, one-step comparison $0.06. Brief v2 states that a quote is final and that the buyer is judged on its average, closing P-D-19 and P-D-21. The frontier CLI agents are saturated under it (P-D-22): Codex Sol 6.1 gives up $1.0 a world [0.2, 2.1], Opus 5.5 $5.4 [1.2, 10.6] | a shortcut reaches the best score: the one-step rule. A pack that measures this decision needs worlds where the one-step rule falls measurably short of the best policy, for example where the order of two tests or when to stop after a failed one matters, or noisy samples, which first need the opt-in environment control P-D-17 asks for |
| 4. Attribution and experimental controls | `partial` | single seat, so cross-play is `not_applicable`; pairing by world; a schema change and a route change each took a new identity (`..._gate_v2`, `..._v2`), and the v1 gate cells are kept as they are; the flash subjects share route policy, harness, schema, seed and every sealed limit, so Gemini against Luna is a model contrast | the contrast between the flash models and the CLI agents is not a model contrast: the CLI agents played as tool-less CLI sessions without a schema, the flash models as one strict structured call an action, so model and harness are confounded. GLM 5.3 Flash is not run: its Housing v14 route is gone (P-O-05) and the procurement family's earlier Morph route was refused by the catalog check on 2026-10-13 because Morph now lists $0.063 and $1.00 per million tokens against the pin's $0.13 and $0.45 (incident row pending) |
| 5. Confirmatory reliability and publication | `not_run` | development runs only, one play a world; run roots are local and gitignored, nothing is published | no variance pilot, no frozen confirmatory identity; not worth running while Gate 3 is failed |

Flash-model panels, prompt v2 (`finalquotes`), action schema v2, 24 worlds, one
play a world, scored by `tools/cli_subjects/pay_or_test_report.py`. Intervals
resample worlds.

| Subject (identity suffix `_v2`) | Given up a world | Share of best value | Worlds with nothing given up | Paid without testing (test worlds) | Requests / award timing / award terms / strays / walk away | Invalid actions | Cost |
|---|---:|---:|---:|---:|---|---:|---:|
| Gemini 3.8 Flash, Google AI Studio | $75.2 [48.7, 101.4] | 83.3% | 8 of 24 | 16 of 16 | $27.0 / $48.2 / $0 / $0 / $0 | 0 | $0.18 |
| GPT-6 Luna, OpenAI | $74.4 [46.7, 102.7] | 83.5% | 7 of 24 | 14 of 16 | $27.6 / $44.3 / $2.4 / $0 / $0 | 0 | $0.03 |

Both models pay the premium nearly everywhere. Gemini never tested a newcomer
and its loss is the always-pay rule's exact expected loss, $75.2; Luna tested in
two worlds. Neither lost anything to speak of in a pay world ($0.0 and $1.0); in a test
world they lost $112.8 and $111.0. The loss of paying when a test was worth more
falls on three actions: the recorded supplier's quote and sample (requests) and
the award (award timing). Paired by world, Gemini minus Luna is +$0.8
[-3.7, 6.3]. The gap to the frontier CLI agents is $69 to $74 a world, and the
one-step rule closes all of it.

### 8.1 Version 2: `pay_or_test_v2`

**Status as of 2026-10-14:** Gate 0 `passed`, Gate 1 `partial`, Gate 2
`passed`, Gate 3 `passed`, Gate 4 `not_run`, Gate 5 `not_run`. No model or
provider has been called on this pack.

Version 1 failed because a test was worth only what it showed about the
listing tested, so looking one test ahead was enough. Version 2 adds one stated
fact: new listings of one seller kind share a source with a chance the case
states (0.8, 0.9 or 0.95), and sharing one they are all sound, all late or all
failing inspection; each listing's own odds are still its cohort record. A cheap
sample can then be worth taking for what it says about another listing. In
`myopic_pays__tight__1`, three trading-company newcomers are each 20% likely to
be sound; one is 36% cheaper than the recorded supplier but its sample costs
$160, another is 4% cheaper with a $20 sample. Testing the cheap one for $22
tells the buyer, nine times in ten, whether the dear one is sound: if it passes,
the dear one is 92% likely sound and worth its $160, with the cheap one as the
fallback. The one-step rule pays the premium and gives up $55.51.

Mechanisms considered. (A) the shared source, chosen: it needs no environment
change (types are pack properties the environment applies as before), and the
shortfall it creates is attributable, because on the same listings with the
source never shared the one-step rule is within $0.33 of the best policy in
every world ($0.03 on average). On version 1's own ranges it was not enough
(P-D-24); it works once sample fees and discounts are drawn on their own over
wide ranges. (B) odds read from cohort records rather than stated: with
independent types a one-step rule reads the same records and computes the same
odds, so nothing changes; with an unknown kind-level rate it is (A) again,
with a prior the brief would have to state as a distribution. Rejected. (C) a
cheaper-but-slower and a dearer-but-faster test of one supplier: the
environment has one sample per supplier with one fee and one duration, so it
needs an environment change. Rejected. A variant the environment does support,
per-listing sample days on a clock that leaves no time to return to the recorded
supplier, also defeats the one-step rule (up to $121 a world), but through the
clock, not through information; it is left out so the shortfall has one cause.

| Gate | Status | Evidence | Blocker |
|---|---|---|---|
| 0. Profile admission | `passed` | this subsection | none |
| 1. Task-distribution admission | `partial` | 24 worlds, four cells of six (`myopic_pays` and `myopic_tests`, named by where the one-step rule's first request goes, each on a tight and a loose clock). Each world is the first seed of its own 5,000-seed block that `admit` accepts; 5,798 seeds were scanned (1,957 and 2,634 for the two `myopic_pays` cells, 674 and 533 for `myopic_tests`), so admission keeps 0.2% to 1.1% of draws. Every world is rebuilt byte for byte and every earlier seed of its block is rejected again (`test_each_world_is_the_first_admitted_seed_of_its_block_reproduced_byte_for_byte`, about 570 CPU-seconds, 95 s on 8 workers), and the manifest is rebuilt from the worlds (`test_the_manifest_is_rebuilt_from_its_worlds_byte_for_byte`). Admission (declared in `pay_or_test_v2_case_matrix.admit`) reads the listings, the clock and the stated law only; types are drawn afterwards on their own stream (`test_admission_does_not_depend_on_how_the_newcomers_turned_out`, `test_a_listing_is_the_same_whatever_type_its_seller_is`). The *trivial* ground: every world defeats the one-step rule, version 1's one-step comparison, the four fixed rules and the kind-blind shortcut by at least $10 (`test_every_world_defeats_the_one_step_rules_and_every_fixed_rule_by_the_margin`), the one-step rule's mean loss is $30.09 against a declared $15 (`test_the_one_step_rule_loses_the_declared_mean_and_the_manifest_says_so`), and information is worth at least $24.0 in every world against a declared $10 (`test_information_has_headroom_in_every_world`). Seeds 8,950,000 to 9,070,000, disjoint from version 1 and the inference packs (`test_the_pack_does_not_overlap_version_one_seeds`) | the grounds that need the control itself. Measured headroom asks for the frozen control's scores at several seeds a world to reject *degenerate* worlds, and no subject has played version 2. The variance pilot in the [confirmatory plan](pay_or_test_v2_confirmatory_plan.md) is that measurement |
| 2. Environment and verifier | `passed` | no pinned module changed: version 2 lives in three new modules, and its reference subclasses version 1's without editing it. In all 24 worlds the best policy's value and every one of the ten rules' values equal the environment's own average over the 27 type profiles weighted by the stated law, each policy played through the environment (`test_expected_values_equal_the_environments_average_over_every_way_the_newcomers_could_turn_out`); the reference's joint prior equals the stated law computed independently from the listings (`test_the_reference_prior_is_the_stated_law_exactly`); the generator's draws follow the stated shares and the stated chance of a shared source over 4,000 seeds, for pairs of one kind and of two kinds (`test_types_follow_the_stated_shares_and_the_stated_chance_of_a_shared_source`); every rule the brief states is checked against the environment as in version 1 (order counting, a void award, the deadline, what a quote and a sample show, a quote is final) | none for the scripted scope. Receipt replay is checked on the first panel with the driver's `--verify`, as for version 1 |
| 3. Construct validity and baselines | `passed` | declared before any model result: the margins above and the rules they apply to. Controls: walking away ($600 short), always pay, test the cheapest once, test the best odds once, work up the price list, the one-step rule with and without the shared source, the kind-blind shortcut, and the evaluator-only full-information value. A better-informed policy improves the outcome on every world by at least $10 against every one of them. The controlled perturbation removes the effect: with the source never shared the one-step rule is within $0.33 of the best policy (`test_without_a_shared_source_the_one_step_rule_is_close_to_the_best_policy`). Shortcut tests: starting a test with the sample instead of the quote does not help the one-step rule ($30.14); sampling the cheapest sample first without reading kinds gives up $32.07 and is screened (P-D-25); a listing and the policy block are identical whatever the types; the prompt names no procedure. Diagnostics: a two-test lookahead gives up $5.89 (3 of 24 worlds at $10 or more), and a habit that writes the inference down, sample the cheapest of a kind that has a dearer one first, $7.11 (10 of 24) | none for the policy-level checks. Whether the pack separates subjects is Gate 4 and 5's question; a subject that matches the two-test lookahead would saturate it, which the pilot measures |
| 4. Attribution and experimental controls | `not_run` | single seat; pairing by world; prompt identity `procurement_allocation_pay_or_test_shared_source_v1` | no campaign. The plan declares its contrasts |
| 5. Confirmatory reliability and publication | `not_run` | the [confirmatory plan](pay_or_test_v2_confirmatory_plan.md), not run | no variance pilot, no frozen identity |

Exact expected loss against the best informed policy, dollars a world, from
`pack.json` for version 2 and from the version 2 reference on version 1's 24
worlds with the source never shared (version 1's own `pack.json` agrees on its
five rules). The top seven rules are screened; the last three are diagnostics.

| Rule | v1 | v1 worlds at $10+ | v2 | v2 smallest | v2 worlds at $10+ |
|---|---:|---:|---:|---:|---:|
| Pay the premium | 75.19 | 16 | 64.43 | 10.06 | 24 |
| Test the cheapest once | 81.38 | 19 | 71.62 | 29.35 | 24 |
| Test the best odds once | 45.72 | 14 | 56.94 | 12.94 | 24 |
| Work up the price list | 146.11 | 21 | 349.22 | 20.94 | 24 |
| One step ahead, updating its odds | 0.06 | 0 | 30.09 | 10.06 | 24 |
| One step ahead, version 1's (stated odds only) | 0.06 | 0 | 30.51 | 10.06 | 24 |
| Cheapest sample first, kinds ignored | 78.90 | 14 | 32.07 | 10.00 | 24 |
| One step ahead, either order inside a test | 0.06 | 0 | 30.14 | 10.06 | 24 |
| Two tests ahead | 0.00 | 0 | 5.89 | 0.00 | 3 |
| Cheapest sample of a kind with a dearer one first | 81.19 | 16 | 7.11 | 0.01 | 10 |

Mutation record (2026-10-14, rerun from clean bytecode after P-T-16): the prior
check dies when the reference ignores the shared source; the posterior check
dies on the same mutant; the environment-average check dies in 24 of 24 worlds
when a quote reads the poor share as the late share; the draw-law check dies
when the generator never shares a source; the listing-invariance check dies when
a listing carries its type; the attribution and margin checks die when their
thresholds are moved past the pack's values; and the scan check dies in 5 of 6
worlds tried when admission stops screening the kind-blind shortcut.

## 9. Pack profile: `inference_v2`

**Status as of 2026-10-13:** Gate 0 `passed`, Gate 1 `failed`, Gate 2
`failed`, Gate 3 `failed`, Gate 4 `not_run`, Gate 5 `not_run`.

| Gate | Status | Evidence | Blocker |
|---|---|---|---|
| 0 | `passed` | this section | none |
| 1 | `failed` | eighteen worlds; a public record on one component's listings and none on the other; the cheapest unrecorded listing is good in nine worlds and bad in nine, so the prompt's ranking cannot decide the hard half (the P-D-15 fix); a fixed listing rule alone solves 4 to 8 of 18 and the record plus a fixed rule 8 to 10 (`reference_worlds_solved` in `pack.json`) | the *trivial* ground: the record has no overlap between good and bad suppliers, and a rule that picks the unrecorded listing looking more like the good group than the bad one solves 18 of 18 without naming an attribute (P-D-16) |
| 2 | `failed` | the environment's goldens and replay as in Section 2 | the pack declares sample noise, so the pre-award check prints the margin the true yield gives after one noisy batch (P-D-17, open; no published number moves). Needs the opt-in control in `environment.py` that projects from the buyer's own evidence, under a new identity |
| 3 | `failed` | Opus 5.5 solves 18 of 18 at $1 regret a world, Codex Sol 6.1 16 of 18 (P-D-16) | saturated at the top, and the similarity rule above is a shortcut to the best score |
| 4 | `not_run` | no declared treatment comparison has been run on it | none until Gate 3 can pass |
| 5 | `not_run` | development runs only | no variance pilot or freeze |
