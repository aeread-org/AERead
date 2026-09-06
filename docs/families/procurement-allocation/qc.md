# Procurement allocation V1 QC profile

**Standard:** [AERead benchmark QC](../../operations/benchmark_qc.md)

**Campaign procedure:** [experiment campaign SOP](../../operations/experiment_campaign_sop.md)

**Design review:** [procurement design review](design_review.md)

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

Admitted panels:

| Panel | Worlds | Surfaces | Purpose |
|---|---:|---|---|
| `dev/` | 7 | labeled | development qualification |
| `blinded_v3/` | 6 | opaque mirror of `dev` | presentation-invariance control |
| `confirmatory_v1/` | 12 | labeled + opaque | held-out panel for the V4 scaffold |
| `risk_gates_v1/` | 6 | labeled + opaque | sample-schedule and landed-cash factorial |
| `qwen_holdout_v1/` | 6 | opaque | targeted residual-capability holdout |
| `confirmatory_v2/` | 12 | labeled + opaque | held-out panel for the pre-award check; **inadmissible**, control saturates 7 of 12 worlds |
| `information_v1/` | 8 | labeled + opaque | information worlds; **inadmissible**, control saturates 7 of 7 and the biased channel is unread |
| `duediligence_v1/` | 6 | labeled + opaque | verification-scarce worlds; **admitted** on a measured control failure rate of 3 of 6 |

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
4. A rejected counter names no field, so negotiation limits cannot be learned
   inside one episode.
6. Replaying every prefix of the fifteen pre-award deferrals shows no point at
   which a feasible award was constructible, so the family measures irreversible
   early commitment without giving feedback until the end.

Until defects 1 through 4 are exercised on a live panel, procurement results
describe **award feasibility under declared constraints**. They do not describe
information acquisition, negotiation, or buyer competence in general, and no
status report may translate the narrower claim into the broader one.
