# Verifier-class to case mapping

**Status:** shared-runner routing crosswalk for the 23-paper audit, five AERead
pilot-v0 families, and measurement-paper integration targets

**Depends on:** [`verifier_taxonomy.md`](verifier_taxonomy.md) and
[`problem_bound_case_audit.md`](problem_bound_case_audit.md)

**Decision:** every declared estimand selects one of five semantic verifier families;
`stochastic_estimator` and `measurement_validity` are recorded as cross-cutting layers

## 1. Mapping rule

The primary mapping unit is the estimand, not the paper, domain label, environment, or
metric column. A paper receives a single row here only as an ingestion default. When one
paper contains substantively different estimands, the row is marked `split_required` and
the adapter must create separate `VerifierSpec` leaves below paper level.

The five semantic families answer what evidence supports the claim:

1. `canonical_reference`: accepted answer, outcome, or equivalence class;
2. `rule_constraint`: rule, invariant, axiom, or temporal-property satisfaction;
3. `objective_reference`: native objective value, exact optimum, or certified bound;
4. `comparative`: effect relative to a named policy, opponent, system, or human sample;
5. `rater_judge`: assessment under a versioned human or model rubric.

`stochastic_estimator` describes how repeated cases, users, opponents, or judges are
aggregated. `measurement_validity` decides whether the evidence is admissible before any
capability measurement. Neither cross-cutting layer is a primary semantic family.

A primary family does not erase secondary leaves. For example, AucArena is comparative
for strategic performance but still needs deterministic rule checks for budgets and bid
legality. The runner retains that vector and its composition rule. No row authorizes a cross-family scalar.

## 2. Verifier class to case index

This inverse index is the quick routing view. Parenthetical entries are sub-estimands or
secondary leaves; the detailed tables below are controlling.

| Verifier class | Direct primary cases | Split or secondary routes |
|---|---|---|
| `canonical_reference` | P11 FinanceBench; P22 STEER; M03 tau3 terminal database; M04 tau3 required communication | P10 exact-answer downstream tasks; deterministic terminal-state leaves in M05-M06 |
| `rule_constraint` | P09 GARP compliance; M02 Housing protocol/IR diagnostics; M07 SAGE workflow adherence where determinizable | P13-P15 equilibrium/property routes; P21 auction legality; A01-A05 feasibility, IR, consent, discovery, and settlement diagnostics; M06 STATE temporal predicates |
| `objective_reference` | P01 Alympics; P02 AERead welfare; P04 Collusion; P06 GovSim; P08 EconEvals; P19 Market-Bench; P23 Vending-Bench; A01-A05 welfare; M01 Housing welfare | P05 finite simulated tasks; solved P13-P15 game routes; P07 extra-information bound; P16/P20 terminal outcome geometry |
| `comparative` | P03 AgenticPay; P07 TERMS-Bench; P16 Strategic Dialogue; P17 NegotiationArena; P18 MERIT/AGORABench; P20 Bargaining Abilities; P21 AucArena | P05 web shopping; P10 benchmark-only downstream tasks; P12 pairwise structure; opponent/policy baselines for P01-P07, P19, P23, A01-A05, and M01 |
| `rater_judge` | P12 GDPval; M05 tau3 natural-language assertion component | P11 full manually adjudicated evaluation; P18 human-derived weighting; non-determinizable M06 STATE and M07 SAGE requirements |
| `stochastic_estimator` | all suite-level estimates with sampled task clusters | especially required for simulated users, opponents, markets, and judges; never substitutes for the semantic family |
| `measurement_validity` | every admitted case and estimand | schema, observation, action, retry, state, hash, replay, and scorer checks; never a capability score |

## 3. The 23-paper routing table

`direct` means the named primary claim has a stable paper-level default while secondary
leaves remain separate. `split_required` means no paper-level primary result is allowed;
the listed subcases must receive their own estimands and verifier specs.

| ID | Deployable workflow | Routing | Primary semantic route | Required secondary leaves and claim boundary | Cross-cutting layers |
|---|---|---|---|---|---|
| P01 | Alympics water allocation under repeated scarcity | `direct` | `objective_reference` / `objective_value_only` for survival and resource outcomes | `comparative` opponent-panel results; `rule_constraint` for resource/action legality. Survival support is not a solved policy optimum. | `stochastic_estimator` over worlds/opponents; `measurement_validity` |
| P02 | AERead exchange families | `direct` for social welfare; split private diagnostics | `objective_reference` / `bound_certificate`: executable lower-bound witness and full-information planner upper bound | `comparative` fixed-panel baseline; `rule_constraint` for IR, consent, and settlement. The planner is not a same-information policy oracle. | paired `stochastic_estimator` over case clusters; `measurement_validity` |
| P03 | AgenticPay bilateral and multiparty commerce | `direct` | `comparative` / `paired_comparison` for the published negotiation/matching performance | `objective_reference` for valid ex-post utility/support components; `rule_constraint` for matching and IR. GlobalScore weights do not define an optimum. | task/opponent `stochastic_estimator`; `measurement_validity` |
| P04 | repeated Bertrand pricing and auction extension | `direct` | `objective_reference` / `objective_value_only` for joint profit, with analytic stage references retained as diagnostics | `comparative` opponent-conditioned dynamics. Nash or monopoly stage values do not solve the long-run policy game. | seed/opponent `stochastic_estimator`; `measurement_validity` |
| P05 | Bayesian Teaching simulated recommendation and web shopping | `split_required` | finite simulated tasks: `objective_reference` / `exact_optimum`; web shopping: `comparative` against the named learned/reference system | Do not transfer exact Bayesian status from the finite simulator to open-web shopping. | route-specific `stochastic_estimator`; `measurement_validity` |
| P06 | GovSim common-pool fishery, pasture, and pollution management | `direct` | `objective_reference` / `objective_value_only` for survival, efficiency, and equality vector | `comparative` population/policy reference; rule diagnostics for resource constraints. Natural endpoint maxima are not certified policy bounds. | world/opponent `stochastic_estimator`; `measurement_validity` |
| P07 | TERMS-Bench buyer-supplier negotiation | `direct` | `comparative` / `paired_comparison` against a pinned counterpart | `objective_reference` / `bound_certificate` for the separately labeled extra-information dynamic-program upper bound. It is simulator-relative, not a same-information optimum. | paired case/simulator-seed `stochastic_estimator`; `measurement_validity` |
| P08 | EconEvals procurement, scheduling/matching, and pricing | `direct` | `objective_reference` / `exact_optimum` for the declared instance objective | executable greedy/reference policies remain `comparative` baselines, even when they also witness a lower bound. | deterministic leaf, cluster-level `stochastic_estimator`; `measurement_validity` |
| P09 | budget and risk choices tested for GARP consistency | `direct` | `rule_constraint` / `axiom_relation`, lower-is-better violation count | zero violation is a property target, not a policy optimum; preserve direction and the predicate/residual vector. | deterministic leaf, cluster-level `stochastic_estimator`; `measurement_validity` |
| P10 | Economy of Minds coordination on math, finance, and software work | `split_required` | exact-answer downstream tasks: `canonical_reference`; optimizable downstream tasks: `objective_reference`; benchmark/rubric tasks: `comparative` or `rater_judge` | The economic coordination mechanism is case structure, not a verifier class and not itself an economic-decision estimand. | task-specific estimation; `measurement_validity` |
| P11 | FinanceBench numerical questions from real filings | `direct` only for a structured subset | `canonical_reference` / `canonical_point` or `canonical_set` after unit, period, currency, and evidence normalization | The published manually adjudicated full evaluation is a separate `rater_judge` result; do not relabel it deterministic. | deterministic leaf or rater sampling; `measurement_validity` |
| P12 | GDPval professional work products | `direct` | `rater_judge` / blinded `human_rubric` or pairwise preference | `comparative` encodes the named reference system and pairwise design. A moving expert/reference comparison has no fixed capability optimum. | rater/task `stochastic_estimator`; `measurement_validity` |
| P13 | GTBench heterogeneous canonical games | `split_required` | equilibrium/property tasks: `rule_constraint`; exactly solved values: `objective_reference`; relative-advantage tasks: `comparative` | Bind every leaf to game form, information structure, horizon, and solution concept. | game-specific estimation; `measurement_validity` |
| P14 | normal-form, sequential, and incomplete-information game workflows | `split_required` | finite solution/property checks: `rule_constraint` or `objective_reference`; incomplete-information negotiation: `comparative` | Never inherit complete-information exactness into an information-relative negotiation policy. | game/opponent `stochastic_estimator`; `measurement_validity` |
| P15 | GAMA-Bench public goods, auctions, coordination, and bargaining | `split_required` | game-specific equilibrium/axiom targets: `rule_constraint`; solved outcome objectives: `objective_reference`; opponent-relative games: `comparative` | Retain the per-game result vector; distance-to-ideal values are not one common scale. | game/opponent `stochastic_estimator`; `measurement_validity` |
| P16 | Deal-or-No-Deal item-split dialogue | `direct` | `comparative` / `head_to_head` against the declared learned opponent | `objective_reference` for terminal allocation value/support only. Enumerating deals does not solve the opponent-conditioned dialogue policy. | dialogue/opponent `stochastic_estimator`; `measurement_validity` |
| P17 | NegotiationArena resource, ultimatum, and price negotiation | `direct` | `comparative` / `head_to_head` with role and opponent in the estimand | `objective_reference` may preserve native utility and feasible outcome geometry, but not claim a policy optimum. | paired matchup `stochastic_estimator`; `measurement_validity` |
| P18 | MERIT/AGORABench bargaining regimes | `direct` | `comparative` for opponent-conditioned negotiation performance | `rater_judge` provenance for human-derived normative weighting; preserve consumer surplus, negotiation power, and acquisition components before any defended composite. | task/opponent/human `stochastic_estimator`; `measurement_validity` |
| P19 | Market-Bench procurement, pricing, inventory, and balance sheet | `direct` | `objective_reference` / `objective_value_only` in native profit or net-worth units | `comparative` named-policy deltas. No published policy upper bound means saturation is undecidable. | market-seed `stochastic_estimator`; `measurement_validity` |
| P20 | Amazon-product bilateral bargaining | `direct` | `comparative` / `paired_comparison` or `head_to_head` | `objective_reference` for separately typed ZOPA and terminal outcome-support geometry. These do not solve the hidden-information policy against an LLM opponent. | paired case/opponent `stochastic_estimator`; `measurement_validity` |
| P21 | AucArena multi-item ascending auctions | `direct` | `comparative` / `field_rating` or `head_to_head` with bidder field fixed | `rule_constraint` for budgets, bid increments, legality, and acquisition requirements; native profit remains descriptive without a policy bound. | auction/field `stochastic_estimator`; `measurement_validity` |
| P22 | STEER generated rational-choice questions | `direct` | `canonical_reference` / `canonical_point` or accepted rational-answer set | generation-time rationality rules may be retained as `rule_constraint` provenance. This measures answer/property correctness, not interactive policy optimality. | deterministic leaf, cluster-level `stochastic_estimator`; `measurement_validity` |
| P23 | Vending-Bench long-horizon inventory and pricing | `direct` | `objective_reference` / `objective_value_only` for terminal net worth and risk | `comparative` human or named-agent baselines. Repeated simulation estimates a distribution but does not supply the missing policy upper bound. | simulator/task `stochastic_estimator`; `measurement_validity` |

## 4. Five AERead pilot-v0 family mappings

The primary row below is the declared social-welfare estimand. Distributional capture,
individual rationality, consent, discovery, and trust remain separate leaves. The same
executable policy may be both comparison baseline `B` and feasible lower-bound witness
`V_LB`, but those are distinct reference roles.

| ID | Native family | Routing | Primary semantic route | Required secondary leaves and claim boundary | Cross-cutting layers |
|---|---|---|---|---|---|
| A01 | visible bilateral IR | `direct` | `objective_reference` / `bound_certificate` for welfare between scripted `V_LB` and full-information `V_UB` | `comparative` fixed-panel delta; `rule_constraint` for feasibility and IR; observed seat gains remain a vector. | paired case/panel `stochastic_estimator`; `measurement_validity` |
| A02 | multiparty clearing | `direct` | `objective_reference` / `bound_certificate` for welfare | `rule_constraint` for bundle, settlement-row, and allocation feasibility; `comparative` baseline; core/Shapley waits for coalition values. | paired case/panel `stochastic_estimator`; `measurement_validity` |
| A03 | hidden discovery | `direct` | `objective_reference` / `bound_certificate`, explicitly retaining the information wedge | `comparative` feasible discovery policy; `rule_constraint` for contact limits and legal disclosure; discovery and inaction diagnostics stay separate. | paired case/panel `stochastic_estimator`; `measurement_validity` |
| A04 | consent under hidden information | `direct` | `objective_reference` / `bound_certificate` for welfare | `rule_constraint` / `temporal_property` for sign-off before transfer plus IR; `comparative` fixed panel; any Nash reference declares feasible set and disagreement values. | paired case/panel `stochastic_estimator`; `measurement_validity` |
| A05 | deferred settlement | `direct` | `objective_reference` / `bound_certificate` for terminal welfare | `rule_constraint` / `temporal_property` for pay-first credit and settlement rows; `comparative` fixed panel; gains, harm, defection, and trust remain a vector. | paired case/panel `stochastic_estimator`; `measurement_validity` |

## 5. Measurement-paper and refund integration targets

These are implementation targets rather than additional papers in the 23-row corpus.
They show how a single environment can emit multiple typed verifier leaves.

| ID | Case/estimand | Routing | Primary semantic route | Required secondary leaves and claim boundary | Cross-cutting layers |
|---|---|---|---|---|---|
| M01 | `housing_v1` realized social welfare | `direct` | `objective_reference` / `bound_certificate`: `L = 0`, naive executable `B`, and exact full-information assignment `U` | `comparative` paired policy delta. `U` is exact for the terminal allocation objective, not an attainable same-information strategic-policy oracle. | paired world-seed `stochastic_estimator`; `measurement_validity` |
| M02 | Housing phases, real offers, immutable holds, capacity, payoffs, and IR | `direct` | `rule_constraint`: phase invariants, reference integrity, capacity predicates, terminal accounting, and IR vector | Negative-payoff agreements remain valid measured outcomes; IR is not an admission gate unless the estimand declares it one. | deterministic replay; `measurement_validity` |
| M03 | pinned tau3 retail terminal database | `direct` | `canonical_reference` / `terminal_state_equivalence` | Alternative legal trajectories pass when the versioned canonical terminal state is equivalent. Do not invent a welfare objective. | task-cluster/user-seed `stochastic_estimator`; `measurement_validity` |
| M04 | pinned tau3 required communication | `direct` diagnostic | `canonical_reference` / `canonical_set` for pinned substring checks or a separately versioned structured validator | It is not the v1.0.1 headline because `COMMUNICATE` does not gate pinned retail reward. | nested user runs where applicable; `measurement_validity` |
| M05 | pinned tau3 upstream aggregate reward | `split_required` | deterministic DB component: `canonical_reference`; non-empty NL assertions: `rater_judge` | Preserve upstream component aggregation only as compatibility output; never relabel the mixed aggregate judge-free. | judge/user `stochastic_estimator`; `measurement_validity` |
| M06 | STATE-Bench final-state and process requirements | `split_required` | final state: `canonical_reference`; checkable process requirements: `rule_constraint` / `temporal_property`; residual UX/semantic requirements: `rater_judge` | Pin source artifacts and retain all leaves; do not multiply deterministic and judged components into an AERead headline scalar. | task/user/judge `stochastic_estimator`; `measurement_validity` |
| M07 | SAGE service-flow adherence | `split_required` pending pin/schema audit | machine-observable workflow graph order: `rule_constraint` / `temporal_property`; residual semantic dialogue quality: `rater_judge` | SAGE remains a candidate adapter until its graph nodes, transitions, evidence surface, release, and scoring protocol are pinned. It is not a refund-state gold set. | task/user/judge `stochastic_estimator`; `measurement_validity` |

## 6. Runner encoding

At ingestion, each direct row resolves to at least one `EstimandSpec` plus one primary
`VerifierSpec`. Each `split_required` row resolves to multiple estimands before a run plan
is frozen. The paper ID or family ID remains provenance; it is not accepted as the
`verifier_family` value.

Minimum routing fields are:

```yaml
source_case_id: M03
estimand_id: tau3_retail_db_state
verifier_family: canonical_reference
reference_kind: terminal_state_equivalence
input_scope: terminal_state
composition: leaf
evaluation_mode: stochastic_estimator
integrity_layer: measurement_validity
cluster_mapping: task_instance
```

Hybrid cases retain their leaf vector. A deterministic gate may exclude inadmissible
evidence, but a rule failure, poor welfare, opponent loss, and judge preference are not
silently interchangeable. Aggregation and saturation language continue to follow each
leaf's own validity domain and cluster definition.
