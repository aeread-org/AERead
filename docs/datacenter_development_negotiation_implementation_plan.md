# Data-center development negotiation implementation plan

**Status:** V0/V1/V2 provider-free development fixtures are executable; no live-model benchmark results exist yet

**Decision:** build an AERead-native `datacenter_development_v1` family on the
shared runner. Start with a customer service agreement followed by a construction
loan. Keep land, power, and construction facts fixed in V0, then make those
agreements negotiable in later versions.

**Case type:** sequential multi-party negotiation with deterministic contract,
constraint, temporal, cash-flow, and comparative verifier leaves. This is not a
classifier and should not be scored as document similarity.

## 1. Objective

Measure whether a developer agent can negotiate agreements whose written terms
jointly produce a financeable, timely, and economically viable data-center
project while preserving hard constraints and the distinction between verbal
discussion and binding commitments.

The family should test four coupled capabilities:

1. reason across agreements rather than optimize each document independently;
2. maintain commitments and conditions across several negotiation rounds;
3. understand how agreed terms change monthly cash flow, debt capacity, covenant
   compliance, and commercial operation date (`COD`); and
4. produce a written agreement that faithfully contains the accepted structured
   terms.

The benchmark is synthetic and executable. Public agreements may inform the
term vocabulary and plausible ranges, but the benchmark does not decide real
legal enforceability and does not copy a public contract into a gold answer.

## 2. Scope ladder

| Version | Negotiated agreements | Fixed project facts | Purpose |
|---|---|---|---|
| V0 | customer service agreement, construction loan | site control, power availability, EPC cost/schedule | Prove the coupled commercial-to-financing mechanism with a tractable state space. |
| V1 | customer service agreement, construction loan, power agreement, EPC agreement | land/site control | Add COD and cost-risk coupling without making every variable endogenous at once. |
| V2 | customer service agreement, construction loan, power agreement, EPC agreement, land agreement | only macro scenario assumptions | Exercise the complete development stack after V0/V1 replay and measurement are stable. |

V0 is the first implementation target. A five-agreement first release would
make failures hard to attribute and would greatly enlarge the counterpart-policy
and exact-reference state space before the runner integration is proven.

## 3. Fit with the current infrastructure

The clean boundary is a new package under `src/aeread_families`. Exchange V1,
Housing V1, procurement grounding, and tau3 retail supply patterns, but none is
the right semantic parent for this family.

| Existing component | Reuse | Data-center binding |
|---|---|---|
| `CaseManifest` and `FamilyManifest` | Direct | Pin the family version, world seed, seats, action budget, visibility policy, generator, and scoring identities. |
| `PluginRegistry` | Direct | Register the exact `(datacenter_development_v1, 1.0.0)` implementation and all required family hooks. |
| `PhaseSpec` scheduler | Direct | Express developer/customer and developer/lender negotiation as explicit phases with phase-specific observation and action schemas. |
| `AgentProfile`, `RunSpec`, and resolver | Direct | Pair the same cases, counterpart policies, inference seeds, budgets, and model route across harness conditions. |
| evidence store and scheduler lifecycle events | Direct | Record every offer, response, acceptance, transition, terminal state, and provider attempt. |
| `EvaluationReceipt` and replay | Direct after R0 below | Seal multiple independent measurement leaves and replay them without a provider call. |
| paired analysis and harness bake-off protocol | Direct after family admission | Compare quality, reliability, speed, calls, tokens, retries, and cost within this family. |
| Housing V1 | Pattern only | Reuse private observations, controlled counterpart seats, immutable offer IDs, explicit commit actions, and deterministic replay. |
| Exchange procurement | Concepts only | Reuse typed cost, capacity, deadline, authorization, and feasibility checks; do not inherit its award problem or score. |
| tau3 retail | Measurement pattern | Keep deterministic, temporal, comparative, and any judged claims as separate leaves. |
| procurement grounding | Source discipline only | Preserve evidence provenance and denominators; do not reuse its one-shot report classifier. |

### R0 infrastructure prerequisite: multi-leaf family finalization

`EvaluationReceipt` already accepts a tuple of `ScoreEnvelope` values, but the
generic path in `shared_runner/family_evaluation.py` currently calls one scorer,
records one `score_recorded` event, and seals `scores=(score,)`. This family
must not hide contract integrity, temporal validity, and economics inside that
single envelope.

Before the new family is admitted, extend the generic family scoring contract:

- `build_scorer(case)(outcome, evidence_refs=...)` may return a
  `FamilyScoreSet` containing a non-empty tuple of `ScoreEnvelope` values;
- the score set declares one `primary_leaf_id` and its admission leaves;
- finalization records one deterministic score-set payload and pins the union of
  all predicate, reference, and scorer implementations;
- a receipt is included only when the primary leaf is valid and every
  designated admission leaf is valid;
- diagnostic leaf failure must not silently invalidate an otherwise valid
  primary result unless the family declares it as an admission leaf; and
- replay reconstructs and byte-compares the complete ordered score tuple.

For compatibility, the adapter may normalize the current one-envelope scorers
to a one-element tuple. Housing and procurement grounding should retain
byte-equivalent receipt meaning after this change.

## 4. V0 benchmark contract

### 4.1 Seats and information

| Seat | Tested? | Information |
|---|---:|---|
| `developer` | yes | Public project facts, its own objectives and constraints, public negotiation history, and the latest written offers. |
| `customer` | no, controlled policy | Public facts, customer-private demand/value/risk parameters, and the service negotiation history. |
| `lender` | no, controlled policy | Public facts, lender-private risk tolerances/pricing rules, the executed service agreement, and the loan negotiation history. |

The developer must never observe raw customer reservation values, lender
acceptance thresholds, policy branches, simulator draws, or full-information
reference solutions. The event store may retain evaluator-private inputs, but
the family `observe` hook is the only path to a seat observation.

### 4.2 Binding hierarchy

The environment, not a language model, defines what is binding:

1. messages are non-binding communications that can reveal or imply positions;
2. an `offer` contains a human-readable message and a complete structured term
   object;
3. only an exact offer ID accepted by the required parties becomes an executed
   written agreement;
4. the executed structured terms, not prose extraction, drive project state and
   cash flow;
5. a later executed amendment supersedes only the fields identified by its
   explicit precedence metadata; and
6. a contradiction or omission between message text and structured written
   terms is recorded as a communication diagnostic, not guessed into the
   binding state.

This makes “verbal versus written” testable without claiming that the benchmark
can infer real-world contract law.

### 4.3 V0 service agreement terms

The first schema should keep the grid finite and interpretable:

- committed capacity in MW;
- service commencement month relative to the project schedule;
- ramp schedule;
- monthly capacity charge per kW;
- energy pass-through rule;
- minimum take-or-pay percentage;
- initial term and renewal option;
- service-level credit cap;
- customer termination right and fee;
- developer delay damages and cap;
- credit support amount; and
- conditions precedent tied to power, construction, and financing.

Every numeric term uses a declared unit and integer precision. Money is stored
as integer cents, rates as integer basis points, power as integer kW, and time
as integer months. Floating-point values are produced only at the reporting
boundary.

### 4.4 V0 construction-loan terms

- maximum commitment;
- advance rate against eligible cost;
- base-rate curve identifier and spread in basis points;
- unused commitment fee;
- origination fee;
- interest reserve;
- draw start and draw-stop conditions;
- minimum contracted-capacity threshold;
- minimum take-or-pay threshold;
- minimum debt-service coverage ratio (`DSCR`);
- loan-to-cost and loan-to-value limits;
- maturity month and extension option;
- completion guarantee or recourse cap; and
- default and cure rules.

The lender observes the executed service agreement before loan negotiation.
This is the core causal link in V0: the agent must recognize that a seemingly
attractive customer agreement may still be unfinanceable.

### 4.5 Fixed V0 project facts

- development and construction costs by month;
- EPC completion distribution or deterministic scenario path;
- contracted utility capacity and energization month;
- site-control cost and expiry;
- operating cost per delivered kW;
- tax and insurance schedule;
- developer equity budget;
- discount rate and terminal value rule; and
- deterministic scenario path or a finite, declared scenario distribution.

Use a deterministic path in the first scripted/replay gate. Add stochastic
scenario replicates only after exact single-path accounting identities pass.

## 5. Phase graph

Use six model-facing phases. Project realization is computed by `terminal` and
`outcome`; it does not need an actorless scheduler phase.

```text
service_developer_offer
        -> service_customer_response
        -> service_developer_offer       (counter or next round)
        -> service_developer_commit      (customer has accepted an offer)
        -> loan_developer_offer
        -> loan_lender_response
        -> loan_developer_offer           (counter or next round)
        -> loan_developer_commit          (lender has accepted an offer)
        -> terminal project realization
```

Each counterparty-response phase uses a controlled policy assigned through an
ordinary seat profile, so it remains visible in the same request/evidence
machinery as the tested developer. `step` selects the next phase from explicit
response state and round budgets. Walking away, exhausting a negotiation
deadline, or rejecting a final written offer is terminal and receives a real
outside-option outcome, not an infrastructure failure.

Initial phase definitions:

| Phase | Mode | Eligible actor | Action schema |
|---|---|---|---|
| `service_developer_offer` | `single` | developer | offer, request clarification, accept counter, or walk |
| `service_customer_response` | `single` | customer | accept, counter, reject, or disclose a permitted signal |
| `service_developer_commit` | `single` | developer | sign exact accepted offer ID or walk |
| `loan_developer_offer` | `single` | developer | offer, request clarification, accept counter, or walk |
| `loan_lender_response` | `single` | lender | accept, counter, reject, or disclose a permitted signal |
| `loan_developer_commit` | `single` | developer | sign exact accepted offer ID or walk |

The action schema must require both `message` and structured `terms` for an
offer/counter. An acceptance references an immutable offer ID and carries no
replacement terms. Phase-specific JSON schemas are bound through each
profile's `output_schema_by_action_schema`; one global schema is insufficient.

## 6. State and cash-flow engine

### 6.1 Canonical state

The family state should contain only canonically serializable records:

```text
case identity and current phase
public project facts
round counters and negotiation deadlines
public message/offer ledger with immutable IDs
executed service agreement or null
executed loan agreement or null
counterparty-policy cursor and private-state references
termination reason
```

Do not store Python objects, derived caches, or provider responses directly in
the state. Derive stable offer IDs from the case identity, agreement type,
round, proposer, and canonical term bytes.

### 6.2 Deterministic monthly ledger

`cashflow.py` should compile the executed agreements and fixed project facts
into a monthly ledger over a pinned horizon. At minimum it computes:

- construction spend, eligible cost, debt draws, fees, accrued interest, and
  equity contributions;
- power availability, completed capacity, serviceable capacity, and billed
  capacity;
- service revenue, take-or-pay revenue, operating expense, SLA/delay credits,
  termination payments, and taxes;
- debt service, outstanding principal, cash balance, minimum DSCR, covenant
  breaches, defaults, and cure effects; and
- COD, developer equity NPV, lender NPV, customer NPV, and total project NPV.

Required accounting identities include sources equal uses at every draw,
principal roll-forward, no billing before service commencement, no delivered
capacity above the minimum of built and energized capacity, and no loan draw
before all declared conditions precedent are satisfied.

Use integer arithmetic for contract inputs and cash ledger values. Discounting
may use `Decimal` with a pinned precision and rounding rule. The implementation
must reject non-finite outputs rather than substituting zeros.

## 7. Measurement design

There is no unique “gold contract.” Several agreements can be legal and
economically rational. Therefore, canonical verification checks that the
executed instrument matches the mutually accepted structured offer; it does not
compare the negotiated economics to one gold term sheet.

Keep these leaves separate in every receipt:

| Leaf | Verifier family / reference kind | Primary value | Admission role |
|---|---|---|---|
| `binding_contract_integrity` | `canonical_reference` / `terminal_state_equivalence` | pass | Required: executed terms equal the exact mutually accepted offer IDs and precedence rules. |
| `project_constraint_satisfaction` | `rule_constraint` / `constraint_satisfaction` | pass | Required: capacity, conditions precedent, loan limits, and accounting invariants hold. |
| `negotiation_temporal_compliance` | `rule_constraint` / `temporal_property` | pass | Required: no acceptance of unknown offers, no signature before acceptance, no draw or billing before prerequisites. |
| `developer_equity_npv` | `objective_reference` / `comparison_baseline` | USD NPV | **Primary outcome:** risk-adjusted developer equity NPV under the declared scenario condition and controlled counterpart policies. |
| `total_project_npv` | `objective_reference` / `comparison_baseline` | USD NPV | Secondary economic outcome guarding against pure value transfer. |
| `counterparty_outcomes` | descriptive seat utilities on the economic envelopes | customer and lender NPV | Report individual rationality and distribution; do not blend into an arbitrary universal scalar. |
| `paired_negotiation_delta` | `comparative` / `paired_comparison` | paired NPV or success delta | Analysis-time comparison against a declared scripted developer or another harness on the same world and counterpart seed. |
| `verbal_written_mismatch` | deterministic diagnostic metric initially | count and severity | Records omissions and contradictions; it does not alter binding terms. Promote to a semantic leaf only after a fully specified validator exists. |

The primary family manifest declares `developer_equity_npv` as an
`optimizable_outcome`, with a versioned scripted-developer comparison baseline.
Do not declare an exact optimum or upper bound in V0 unless an exhaustive or
dynamic-programming solver is implemented and its information set is explicit.
A full-information solution, if later added, must be labelled as a relaxation,
not as an attainable same-information policy.

Walking away may be the correct action. It yields the case's declared outside
option and should remain a valid economic measurement. Illegal transitions,
broken accounting, hidden-state leakage, or incomplete evidence are admission
failures rather than low economic scores.

## 8. Case design and pilot panel

Create 24 curated V0 worlds: six mechanism strata with four variants each.
The variants differ in term ranges and hidden counterpart parameters, not in
post-result difficulty labels.

| Stratum | Mechanism under test |
|---|---|
| revenue without bankability | Customer pricing looks attractive, but take-or-pay or credit support is too weak for the lender. |
| delayed revenue | A viable contract begins too late relative to fixed construction spending and site-control expiry. |
| loan proceeds with restrictive draws | The headline commitment is sufficient, but draw conditions create an equity shortfall. |
| covenant cliff | Small changes in price, ramp, or leverage cause a DSCR or loan-to-cost breach. |
| liability transfer | High service revenue is offset by SLA credits, delay damages, or termination exposure. |
| verbal/written divergence | A favorable message omits or contradicts a material structured term in the actual offer. |

For every world, retain at least:

- one feasible agreement path;
- one superficially attractive but unfinanceable path;
- one rational walk-away condition;
- deterministic scripted counterpart behavior for a fixed seed;
- a scripted-developer baseline trajectory; and
- a hand-reviewed explanation of the dominant mechanism, stored outside the
  tested agent's observation.

The first executable gate uses two worlds from different strata. The 24-world
panel is not run until both replay exactly and the cash-flow metamorphic tests
pass.

## 9. Proposed repository layout

```text
cases/datacenter_development_v1/
  README.md
  family_manifest.json
  pilot_manifest.json
  v0/
    *.json

src/aeread_families/datacenter_development/
  __init__.py
  contracts.py
  cashflow.py
  counterparts.py
  environment.py
  measurement.py
  generator.py
  runner.py
  harness_bakeoff.py
  leaderboard.py

tests/
  test_datacenter_contracts.py
  test_datacenter_cashflow.py
  test_datacenter_environment.py
  test_datacenter_measurement.py
  test_datacenter_replay.py
  test_datacenter_cases.py
  test_datacenter_harness_bakeoff.py
  test_family_evaluation_multi_leaf.py
```

Do not add the family to `cases/README.md` until at least one case validates,
executes with scripted providers, seals, and replays. A catalog entry should
describe an executable family, not a design document.

## 10. Ordered implementation plan

### R0: extend generic family scoring

- Normalize plugin scorer output to a non-empty score tuple.
- Add explicit primary and admission leaf declarations.
- Seal, audit, and replay the complete score tuple.
- Prove one-leaf Housing and procurement-grounding compatibility.
- Add tamper, duplicate-leaf, invalid-primary, and diagnostic-leaf tests.

**Exit gate:** existing family receipt tests pass unchanged in meaning, and a
synthetic two-leaf fixture seals and replays exactly.

### R1: contract schemas and deterministic finance kernel

- Implement strict V0 payload and term validation.
- Implement immutable offer IDs and binding compilation.
- Implement the integer/Decimal monthly ledger.
- Add unit and metamorphic tests before any model-facing runner code.

**Exit gate:** accounting identities, conditions precedent, COD propagation,
and all hand-computed fixtures pass deterministically.

### R2: family plugin and controlled counterpart policies

- Implement every required plugin hook.
- Add private role observations and the six-phase graph.
- Add one conservative customer policy and one lender policy, each versioned
  and deterministic for a case seed.
- Execute two cases with scripted developer responses.

**Exit gate:** scripted execution, finalization, sealing, state replay, and
multi-leaf score replay pass with no evaluator-private fields in observations.

### R3: case generator and curated pilot

- Generate finite term grids from a pinned master seed.
- Curate four variants for each of the six mechanism strata.
- Compute source hashes, case hashes, baseline trajectories, and mechanism
  annotations.
- Review boundary cases near financing and covenant thresholds.

**Exit gate:** all 24 cases validate; each declared path has verified outcomes;
the case manifest and generator are reproducible from a clean checkout.

### R4: live model qualification

- Freeze the provider route, model revision, prompt, phase schemas, reasoning
  setting, token/action/cost budgets, and retry policy.
- Run three single-action schema probes, then one complete trajectory.
- Preserve failures as typed missingness and verify cost telemetry.

**Exit gate:** one complete live trajectory has a verified route, sealed
receipt, deterministic replay, and no hidden retry or missing billing field.

### R5: paired harness panel

- Reuse the staged protocol in `docs/open_harness_testing.md`.
- Pair all harnesses on case, world seed, inference seed, counterpart policy,
  and execution budgets.
- Rotate execution order and report cluster-level paired intervals by case.
- Rank only complete admitted harnesses within this family.

**Exit gate:** family-native leaderboard reports primary NPV, constraint and
temporal validity, agreement/walk-away rate, reliability, latency, calls,
tokens, cost, retries, and failures as separate columns.

### R6: V1 and V2 expansion

- V1 adds power and EPC negotiations plus schedule/liquidated-damages coupling.
- V2 adds land/site-control negotiations and amendment precedence.
- Every new agreement adds its own schemas, counterpart policy, contract
  compiler, cash-flow effects, fixtures, and replay tests before joining a
  scored panel.

**Implemented development gate:** V1 is pinned as family version `1.1.0` with
12 scripted actions. V2 is pinned as family version `2.0.0` with 18 scripted
actions, including an explicit land amendment that identifies the superseded
offer, exact amended fields, and precedence index. Both fixtures use the shared
runner, seal five leaves, and replay without provider calls. This does not
satisfy the live qualification or paired-panel gates above.

## 11. Required regression tests

At minimum, cover:

- accepted written terms compile byte-for-byte into executed agreements;
- verbal claims never mutate binding terms;
- accepting or signing an unknown, expired, or superseded offer is illegal;
- counterpart private state and reference solutions never enter observations;
- no service revenue occurs before the later of contractual commencement,
  energized capacity, and completed capacity;
- no loan draw occurs before all conditions precedent;
- maximum commitment, advance rate, loan-to-cost, and loan-to-value limits hold;
- principal, interest, fee, cash, and equity roll-forwards reconcile monthly;
- walk-away produces the declared outside option and remains score-valid;
- deterministic case and inference seeds reproduce offers and outcomes;
- changing one material term changes the expected ledger rows and hashes;
- score leaves remain separate and their implementation pins are complete;
- sealed evidence reproduces the state, outcome, and every score envelope;
- provider or harness failure is missingness, not zero NPV; and
- a tampered offer, transition, outcome, score, or receipt is rejected.

## 12. Risks and controls

| Risk | Control |
|---|---|
| Legal realism is mistaken for legal advice. | Define synthetic binding rules and label public documents as vocabulary/range grounding only. |
| Free-form prose becomes an unreliable source of truth. | Require complete structured terms beside the message; score the structured instrument and diagnose prose mismatch separately. |
| Controlled counterpart is exploitable. | Use several versioned policies, hidden policy parameters, paired seeds, holdout worlds, and policy-specific reporting. |
| One score hides why an agent failed. | Preserve independent integrity, constraint, temporal, economic, and comparative leaves. |
| The benchmark rewards predatory value transfer. | Report developer, lender, customer, and total-project outcomes plus individual-rationality violations. |
| Cash-flow bugs dominate model differences. | Hand-computed fixtures, accounting identities, metamorphic tests, Decimal rounding rules, and provider-free replay precede live runs. |
| Five agreements create attribution ambiguity. | Stage V0, V1, and V2 and never pool their results without a declared analysis plan. |
| A full-information solver is misreported as attainable. | Declare its information set and label it a relaxation; omit the upper-bound claim until the solver exists. |

## 13. V0 definition of done

V0 is complete only when:

1. the generic family path supports and replays multiple independent leaves;
2. the service and loan schemas, phase graph, binding hierarchy, and monthly
   finance kernel have deterministic tests;
3. two scripted cases and the full 24-world manifest execute, seal, and replay;
4. private counterpart state is absent from every tested observation;
5. one live full trajectory passes route, schema, cost, and receipt audit; and
6. the family can enter a paired harness bake-off without changing its cases,
   measurement definitions, prompts, or execution contract after results are
   observed.

Until those gates pass, the family should be described as “under
implementation,” not as a benchmark result.
