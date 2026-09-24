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

## 8. Repeated sourcing (`interaction.periods`): campaigns and status

**Design:** [repeated-sourcing extension](relationship_design.md), built
2026-09-21 from §4 of the
[economic primitives design](../../research/economic_primitives_extension_design.md).
A new construct on the same family: the award is a period transition, supplier
standing moves quote, floor and capacity, and the reference is an exact
four-period dynamic programme with myopic, loyal and shopping references beside
it. Nothing here reopens the family's construct gate (§3), which stays `failed`.

**Task distribution, in the Gate 1 form.** The independent unit is the
economic world. Six worlds in `cases/procurement_allocation_v1/relationship_v1/`,
one per stratum (loyalty investment, qualification investment, demand ramp,
incumbent capacity, retaliation trap, unreliable incumbent), generated by
`relationship_case_matrix.py` and **authored, not selected by rule**: their
numbers were tuned by hand until `headroom_screen.classify_relationship_world`
admitted them (optimum beats myopic and loyal by 5% of the bound). Seeds bind
the inference seed and the world's `delivery_seed`; on these worlds
verification is perfect, so the seed never reaches the first prompt and the
seeds of a world are repeats on a deterministic route, exactly the §7 rule
(incident P-D-01). Two generated packs replace that for the next campaigns:
`relationship_dev_v2` (seed domain 2420000+, 36 scanned, 12 admitted, 67%) and
`relationship_holdout_v1` (2430000+, 42 scanned, 12 admitted, 52%), selected by
the rule their `pack.json` states, every refusal recorded with its verdict, every
world declaring binomial sample noise so campaign seeds are replicates, and each
manifest carrying the four public-observation policies' outcome per world. The
domains are disjoint; the holdout has not been read by any live cell. Measured
headroom against the live control is what the two campaigns below record, not
what admitted the worlds.

| Campaign | Route | Cells | Cost | Mean regret (95% world bootstrap) | vs myopic | Status |
|---|---|---:|---:|---|---|---|
| `procurement_allocation_relationship_gemini38_flash_variance_v1` | Gemini 3.8 Flash, Google AI Studio | 18/18 | $0.80 | 35.81 (27.24–44.06) | −11.68 (−20.14 to −2.40) | published, `development_qualification` |
| `procurement_allocation_relationship_glm53_flash_variance_v3` | GLM 5.3 Flash, Parasail | 18/18 | $0.20 | 109.02 (73.38–144.48) | −84.88 (−120.50 to −49.67) | published, `development_qualification` |
| `procurement_allocation_relationship_dev2_gemini38_flash_variance_v2` | Gemini 3.8 Flash, Google AI Studio, T=1.0, `stable_prefix_v1` | 60/60 | $2.82 | 33.72 (27.47–40.11) | −7.74 (−15.08 to −0.23) | published, `development_qualification` |
| `procurement_allocation_relationship_dev2_glm53_flash_variance_v2` | GLM 5.3 Flash, Parasail, same controls | 59/60 | $0.64 | 86.11 (68.31–104.52) | −60.13 | published, `development_qualification` |

Paired on identical worlds and seeds, Gemini's regret is 73.20 below GLM's
(−106.53 to −40.66), lower on six of six worlds; descriptive, no ranking. Two
spent GLM identities (v1, v2) are recorded in the incident log (P-O-01, P-O-02)
and never resumed.

**Gate status for this construct.** Gate 1 `passed`: the variance pilot and
the confirmatory ran on rule-selected packs with disjoint seed domains, and the
declared unit is the world (declared sample noise does not make seeds
replicates on a deterministic route, P-D-03, so seeds add information only
where the model's own sampling varies). Gate 2 `passed`: every cell replayed
live and re-audited from disk, the bound is attained by replaying its own plan
through the environment, and a brute-force enumeration agrees with it. Gate 3
`passed`: no-op (`defer`), the four pinned public policies and the competent
`deadline_aware` rule are published per world in the pack manifests, beside
the myopic, loyal and shopping references and an attainable ceiling; admission
requires `deadline_aware` to beat `defer` (P-D-07). Gate 4 `passed`: the paired
plans differ only in route, verified key by key (P-D-02 records the earlier
pair that did not). Gate 5 `passed`: a rule-selected variance pilot, a
confirmatory pre-registered and frozen before any cell ran, and a holdout no
live cell had read.

**Confirmatory result.** On `relationship_holdout_v1`, 12 worlds x 5 seeds, 60
of 60 cells per route, all three pre-registered outcomes are supported (95%
world-bootstrap intervals exclude zero). O1: Gemini breaches in 0 of 60 cells,
GLM in 8 of 60; paired difference -0.133 (-0.233 to -0.050). O2: on valid
orders Gemini's regret is 14.16 lower (8.96 to 19.21). O3: both beat the
`deadline_aware` baseline on the same episodes, Gemini by 137.4 (108.2 to
168.1) on 12 of 12 worlds and GLM by 104.2 (62.6 to 145.0) on 11 of 12. The
claim is these three statements for these two routes, this prompt and the
generator's worlds; nothing about the models in general. Against the dev pilot
the direction of every comparison held and GLM's margins improved (breach rate
13% against 29%). Bundles:
`procurement_allocation_relationship_holdout_{gemini38,glm53}_flash_confirmatory_v1`.

**Controls for the next identity, and what the dev_v2 pilot changed.** The
both-route variance pilot on `relationship_dev_v2` (12 worlds x 5 seeds) halted
on provider credit after 28 Gemini and 16 GLM cells (P-O-03) and is recorded,
not published. What it settled: both routes beat every observation-only policy
on every world they reached, Gemini sits on the myopic reference and GLM well
below it, and GLM breaches minimum service in 8 of 16 cells against 0 of 28. It
also showed three defects in the design this section described: declared sample
noise does not make seeds replicates (P-D-03), `retaliation_trap` has no
informative observation-only baseline (P-D-04), and the plan's temperature was
never applied (P-D-05). New plans therefore default to `temperature: 1.0` on
every route and to the `stable_prefix_v1` observation layout (P-D-06), which
holds the same fields grouped so the provider can cache the prefix (on
Gemini the calls are too short for its ~4k-token cache blocks, so the saving
there is nil; it is for routes with fine-grained prefix caching). Both are
frozen in the plan; campaigns run under them are not pooled with the
temperature-0, flat-layout campaigns in the table above.

**The first symmetric pair, and the baseline it is read against.** The two
`dev2 ..._variance_v2` identities ran the 12 `relationship_dev_v2` worlds at
five seeds under plans that differ only in route. Paired on 59 cells, Gemini's
regret is 52.39 below GLM's (34.05–71.83), lower on 12 of 12 worlds; the gap is
mostly breaches (17 of 59 GLM cells against 1 of 60 Gemini cells; on the cells
where neither breached it is about 20). At temperature 1 Gemini still returns
five identical cells on 6 of 12 worlds, so the world, not the seed, is the unit
that carries information for it. The pack's pinned public policies forfeit
period 1 on 10 of 12 worlds (P-D-07), so "beats every public policy" is true
and says little. The packs now also record `deadline_aware`, an
observation-only rule that stops qualifying while it can still deliver and
orders the target quantity; it beats `defer` on every world of both packs, with
mean regret 121.8 (dev) and 111.7 (holdout), and admission requires it. Read
against it, Gemini (33.7) is well clear of a competent simple rule and GLM
(86.1) only modestly: GLM's mean regret is worse than the rule's on 3 of 12
worlds and Gemini's on 1 (`qualification_investment_2420007`, 36.9 against
19.8). That comparison, per world,
is the construct check for the confirmatory.

**Confirmatory, frozen before any cell ran.** Pre-registration
`procurement_relationship_confirmatory_v1` in `relationship_confirmatory.py`
(commit 4842974e): O1 breach rate, O2 regret on valid orders, O3 advantage over
`deadline_aware` on the same episode; paired per world, 95% world bootstrap, a
direction supported only when its interval excludes zero. Pack
`relationship_holdout_v1` (never read by a live cell), seeds 76001-76005,
temperature 1.0, `stable_prefix_v1`. Plans:
`procurement_allocation_relationship_holdout_gemini38_flash_confirmatory_v1`
`0f35817c526d35400abb72a3c1fd01a2bc8c11e6ef200449ca4e92ed94c33c44` and
`procurement_allocation_relationship_holdout_glm53_flash_confirmatory_v1`
`c3a2dd144c6120967018942f3638f8739eddee8aa9cfd25353e1901f6f85bae8`, differing
only in route.
