# AERead: Verifiable Environments for Evaluating Economic Agents

**Working paper draft — 2026-09-06**

This manuscript is a rehearsal draft, not a submitted paper. Throughout the draft,
**implemented** refers to behavior present in the repository, **observed** refers to a
claim backed by a named evidence artifact, and **planned** refers to a design without an
executable qualification artifact. The draft intentionally withholds model-ranking
claims that the current evidence does not support.

The environment-paper structure and proposed main-text compression are explained in
[the companion literature review](environment_paper_structure_review.md). The working
draft below retains more implementation detail than an eventual 8–10 page paper.
Quantitative observations were checked against saved reports on 2026-09-06; this
drafting pass did not rerun their campaigns. The evidence appendix identifies each
source and the remaining qualifications.

## Abstract

Economic-agent outcomes depend on private information, interacting policies, market
rules, and execution reliability. An allocation can be efficient while leaving a
participant worse off; an absent outcome can reflect provider failure rather than a
policy decision. We present **AERead**, an environment and evaluation framework that
makes these distinctions explicit. Versioned families define economic state,
role-specific observations, actions, transitions, utilities, and reference solutions.
A common execution layer binds those semantics to declared experiments, recorded
attempts, replayable evidence, and typed verifiers. The evaluation protocol identifies
the focal policy, opponent population, sampling unit, and admissible measurements.

We describe a multi-round Housing market and report development evidence from a
provider-free sweep of 288 configuration–seed instances and an eight-world pilot with
189 replay-verified completions out of 192 attempts. The pilot supports exploratory
analysis; its mixed interaction aggregate and incomplete world pairs limit attribution.
As a separate portability check, the pinned retail adapter matches upstream
deterministic results on 114 gold-action tasks. A curated Procurement intervention
provides a further case study of reporting economic quality alongside feasibility.
These studies support concrete implementation and measurement claims. Independent
construct validation, a cleaner focal-policy study, and comparative tests of the
protocol's diagnostic value remain necessary for broader conclusions.

## 1. Introduction

Language-model agents increasingly make decisions through tools, interact over long
horizons, and affect shared state. Existing interactive benchmarks have made important
progress by placing agents in executable terminals, browsers, operating systems, and
workplace simulations [1–7]. These settings expose failures hidden by prompt-only tests:
agents may select the wrong tool, lose track of state, violate a policy, or fail to
verify their work.

Economic interactions add three measurement problems.

First, **outcomes are jointly produced**. A transaction, allocation, or negotiation
depends on the focal agent, counterparties, roles, private information, and the mechanism.
A self-play outcome is therefore not an intrinsic property of one model.

Second, **validity and value are different**. An allocation can have high apparent
welfare while violating capacity, consent, individual-rationality, or policy constraints.
Conversely, a legal outcome may be economically poor. A scalar reward that mixes the two
can hide the failure mode or create a gameable proxy.

Third, **execution is part of the measurement**. Provider errors, hidden retries,
truncation, tool faults, and harness drift can change which trajectory is observed. An
operational failure is missing measurement evidence, not automatically evidence that the
policy has zero economic ability.

AERead addresses these problems by treating an agent benchmark as a governed measurement
instrument. Its central design rule is:

> Standardize experimental control, evidence, and measurement declarations; keep
> economic semantics inside versioned environment families.

This paper develops three contributions:

1. A family-extensible environment contract for private state, role-specific
   observations and actions, deterministic transitions, and case-native outcomes.
2. A typed verification model connecting each reported metric to the claim and evidence
   it can support, without imposing a universal cross-family score.
3. An evaluation and evidence protocol that declares counterparties, roles, pairing,
   sampling units, attempts, failures, and qualification gates. The protocol can express
   separate focal-policy and population studies; the current Housing pilot's more
   limited estimand is disclosed in Section 8.

The empirical question is whether these distinctions change conclusions about agent
behavior or identify useful interventions that task completion alone would miss.
The present draft combines existing implementation evidence with a proposed study
of that question. Section 8.8 identifies the experiments still required; the existence
of the framework is not itself evidence that it improves diagnostic accuracy.

Our purpose is not to claim that the current suite measures general economic intelligence.
AERead instead provides a common measurement layer for a declared set of economic and
stateful decision problems, with explicit coverage and maturity boundaries.

## 2. Design objectives and related environments

### 2.1 Design objectives

AERead is designed around seven objectives:

1. **Outcome grounding.** Prefer terminal state, constraints, objective values, and
   recorded actions over matching one textual answer or one reference trajectory.
2. **Information integrity.** Separate evaluator-only world state from the observations
   available to each role.
3. **Multi-agent attribution.** Treat counterparties, roles, and interaction populations
   as experimental conditions rather than background noise.
4. **Typed verification.** State whether evidence establishes correctness, legality,
   objective quality, comparison, or a judge-dependent assessment.
5. **Operational observability.** Retain provider calls, attempts, retries, timeouts,
   costs, and tool effects so harness failures are not mislabeled as policy failures.
6. **Reproducibility.** Resolve seeds, profiles, limits, implementations, and analysis
   identities before execution and preserve replayable evidence.
7. **Claim governance.** Promote experiments through explicit qualification gates and
   bind published claims to sanitized evidence artifacts.

### 2.2 Relationship to adjacent work

Harbor provides a portable framework for running agent evaluations and generating RL
rollouts in container environments [1]. Terminal-Bench 2.0 uses Harbor to compare agents
on difficult, outcome-driven terminal tasks with executable verifiers [2]. AERead is
complementary: it focuses on economic world semantics, multiple adaptive seats,
case-native objectives and constraints, statistical attribution, and campaign evidence.
Harbor/ATIF is a planned export boundary; Harbor does not define AERead's benchmark truth.

τ-bench evaluates tool-using conversational agents by comparing terminal database state
with an annotated goal and introduces pass^k for repeated-trial reliability [3]. τ²-bench
extends this idea to a dual-control Dec-POMDP in which both the agent and user act through
tools, uses compositional task generation, and separates reasoning from coordination
failures [4]. This is the closest conceptual precedent for AERead's multi-party control
and outcome verification. AERead differs by supporting heterogeneous economic families,
typed objective and constraint evidence, explicit opponent-population estimands, and a
campaign-level qualification lifecycle.

WorkArena/BrowserGym, OSWorld, and TheAgentCompany construct realistic, executable
software or workplace worlds [5–7]. They motivate explicit observation/action spaces,
controlled initialization, execution-based evaluation, and task-creation QC. AgentBench
provides a common package over multiple interactive environments [8]. AERead similarly
supports heterogeneous families, but disables default scalar pooling when their
estimands and units are not comparable.

AppWorld explicitly separates its controllable application engine from its task suite
and evaluation procedures [10]. We adopt that organizational distinction: AERead's
execution framework, the Housing benchmark instance, and any later learning experiment
are separate artifacts. AgentGym likewise separates environment infrastructure,
benchmark tasks, trajectory data, and its proposed learning method [11].

SidConArena is a particularly close economic comparator [12]. It combines partially
observed multi-agent negotiation, production, and auctions with executable outcomes
and evaluates homogeneous and mixed-model populations. Consequently, multi-agent
economic simulation and verifiable outcomes are established ingredients. AERead's
candidate contribution lies in combining explicit economic measurement contracts,
family portability, and controlled evidence protocols, and must be evaluated at that
specific level.

The Harbor-Index release also describes task audits, human review, verifier repair,
and infrastructure-failure analysis [13]. These methods are relevant precedents;
AERead does not claim to originate benchmark quality control.

SOTOPIA evaluates open-ended social interaction through a holistic evaluator calibrated
against human judgments [9]. AERead uses judge-dependent evaluation only for properties
that cannot be reduced to deterministic state, rule, or objective checks. Deterministic
economic evidence remains visible even when a semantic rubric is added.

## 3. Environment and execution model

### 3.1 Economic interaction as a partially observed game

We use a finite-horizon partially observable stochastic game as explanatory notation
for multi-agent families. This is a mathematical description of the family contract,
not an additional implemented universal solver. A case supplies a sampled world
`w ~ D_theta`, participants `N`, state `s_t`, active phase `q_t`, observation functions
`O_i`, role/phase action sets `A_i`, a transition rule `T`, horizon `H`, and utility
functions `u_i`. Each participant receives only `o_i,t = O_i(s_t, q_t)` and chooses
an action according to its policy and visible history. A joint phase transition is

`s_(t+1) = T(s_t, q_t, {a_i,t : i active}, xi_t)`.

Randomness `xi_t`, where used, belongs to a declared environment seed. Housing's
transitions are deterministic given the generated world and phase actions; stochastic
model outputs do not make its state-update rules stochastic. A phase may activate one
seat, a sequence of seats, or a simultaneous batch.

Utilities can differ across participants. Cooperative special cases may share an
objective, but the framework does not assume the common reward required by a
cooperative Dec-POMDP. Terminal welfare, individual payoff, and rule satisfaction are
separate measurements of the same realized trajectory.

A focal-policy estimand must declare the world distribution `D`, counterparty
distribution or panel `Q`, role assignment `r`, and fixed execution controls `c`:

`J_i(pi; D, Q, r, c) = E[m_i(tau) | pi in role r, opponents from Q, worlds from D, controls c]`.

Here `m_i` is a declared economic measurement defined on admissible evidence. When
execution evidence is missing, the observed complete-case mean need not identify this
target without a missingness assumption or sensitivity bound. A paired policy
comparison holds `D`, `Q`, `r`, and `c` fixed. If the opponent changes with the subject,
the result is a joint-population contrast rather than that focal-policy comparison.

### 3.2 Separation of shared control from family semantics

AERead has three conceptual layers:

```text
Research protocol
  suites, sampling, evaluation blocks, estimands, analysis

Shared runner
  resolution, scheduling, model/tool calls, retries, evidence, replay, receipts

Environment family
  state, private observations, legal actions, transitions, outcomes, references
```

The shared runner does not contain family-specific branches. A versioned family plugin
defines state and interaction semantics. The runner owns the aspects that must remain
comparable and observable across families.

### 3.3 Core records

The principal records are:

| Record | Meaning |
|---|---|
| `FamilyManifest` | Roles, phases, capabilities, measurements, generators, and implementations. |
| `CaseManifest` | One content-bound world, independent of the model assigned to it. |
| `SuiteManifest` | A declared collection or distribution of cases. |
| `AgentProfile` | Model, harness, prompt, sampling, tools, memory, limits, and retry policy. |
| `EvaluationBlock` | Controlled, population, cross-play, self-play, or reference comparison. |
| `RunPlan` | Immutable expansion of cases, seats, profiles, seeds, controls, and analysis identities. |
| `EpisodeEventLog` | Append-only observations, actions, attempts, calls, transitions, and failures. |
| `EvaluationReceipt` | Evidence hashes, replay level, measurement validity, typed results, and inclusion decision. |

This vocabulary prevents a common analytical error: treating campaigns, runs, worlds,
tasks, attempts, and model calls as interchangeable observations.

### 3.4 Role-specific interaction

A family exposes a phase graph. Each phase declares eligible actors, whether actions are
sequential or simultaneous, role-specific observation and action schemas, limits,
invalid-action policy, and possible successor phases.

For a simultaneous phase, the runner freezes each participant's observation from the
same pre-action state and hides peer actions until the action bundle closes. The family
then applies one deterministic transition. This prevents dispatch order from leaking
another agent's action.

Evaluator-only state may include private values, latent preferences, reference solutions,
or policy constraints. It must not appear in agent observations, parser errors, debug
messages, or agent-visible receipts. The recorded visibility contract makes this boundary
testable.

### 3.5 Attempts, calls, and side effects

AERead separates a logical action from its execution attempts. An attempt can contain one
or more model-provider calls and tool invocations. Additional attempts are allowed only
under the resolved profile's retry policy. Each provider or tool side effect is recorded
before and after execution.

This matters because an SDK-level retry, a replayed tool call, or a restarted model
session can change the behavior being measured. AERead does not permit these changes to
remain implicit.

### 3.6 Evidence, replay, and publication

Raw execution records live under an ignored run root. Sanitized, selected evidence is
published separately with content digests. A publication cannot replace the source run;
it is a traceable projection from it.

The implemented runner records a resolved plan before external calls, append-only events
during execution, and a final receipt after verification. Replay guarantees are declared
rather than implied. Depending on the family and harness, a receipt may support score
reproduction or full state-and-score replay.

## 4. Verification and measurement

### 4.1 Claim-to-evidence contract

AERead represents verification as:

```text
case -> estimand -> verifier -> reference/evidence -> typed result -> receipt
```

The framework currently distinguishes five semantic verifier families:

| Family | Claim supported | Example |
|---|---|---|
| Canonical reference | Agreement with an accepted point, set, or equivalence class | Correct final refund database state |
| Rule/constraint | Satisfaction of predicates, invariants, or temporal rules | Consent precedes a state mutation |
| Objective reference | Quality under a declared objective and feasible domain | Housing welfare or regret to a certified reference |
| Comparative | Difference from a named policy, system, or population | Paired model contrast on identical worlds |
| Rater/judge | Assessment under a versioned human or model rubric | Quality of a free-form explanation |

Statistical estimation and evidence admissibility are orthogonal layers. A deterministic
verifier applied to a stochastic episode makes the realized episode's score reproducible;
it does not make the population estimand deterministic.

### 4.2 Validity gates and retained vectors

Logical prerequisites such as legal action shape, capacity, or required consent may act
as hard validity gates. Admitted outcomes retain their component measurements. AERead
does not hide compliance, welfare, distributional capture, reliability, and cost inside
one arbitrary weighted score.

Three uses of validity must remain distinct. **Action legality** determines the
environment's response to a submitted action. In Housing an illegal proposal may
become a native pass, leaving a fully observed trajectory that can legitimately score
zero or later recover. **Measurement validity** determines whether recorded evidence
supports a score; an interrupted provider call can instead leave a missing outcome.
**Economic acceptability** concerns properties such as individual rationality (IR).
Housing permits some loss-making choices to measure them, so an IR violation is not
automatically an invalid measurement. The family and estimand declare which predicates
block which claim.

When an exact optimum is unavailable, the framework distinguishes executable baselines,
certified lower or upper bounds, and descriptive objective values. A baseline is not
silently relabeled as a global floor, and an apparent violation of a claimed bound
invalidates the comparison until reconciled rather than being clipped away.

### 4.3 Task and verifier QC

Task qualification is broader than unit testing. Depending on the family, AERead applies:

- schema and range validation;
- deterministic generation and duplicate/degeneracy checks;
- oracle, invariant, and terminal-accounting tests;
- known-valid, valid-but-poor, and invalid golden trajectories;
- replay and evidence-integrity checks;
- hidden-state and visibility tests;
- adversarial mutations targeting parser or verifier shortcuts;
- scripted, random, naive, adaptive, and oracle-informed baselines; and
- explicit human review for construct validity and production promotion.

Passing automated checks establishes the declared mechanical properties. It does not by
itself establish that the task distribution represents the intended real-world construct.

## 5. Multi-agent evaluation protocol

AERead separates four questions:

| Evaluation block | What varies | Permitted interpretation |
|---|---|---|
| Controlled focal agent | One subject seat; other seats fixed | Performance against a declared opponent condition |
| Controlled population | One profile fills a declared role population | Behavior of that homogeneous population |
| Cross-play | Ordered subject-opponent pairings and role rotations | Matchup sensitivity and robustness over a declared panel |
| Self-play | The same profile controls multiple adaptive seats | Joint-system behavior under homogeneous self-play |

The profile under test includes the model, harness, prompt, tools, memory, sampling,
limits, and retry behavior. Comparing model names while changing these fields is a system
comparison, not an isolated model effect.

Worlds are paired across conditions when possible. The independently sampled world or
task cluster, not each trajectory or tool call, is the unit used for uncertainty.
Replicates within a world estimate conditional stochasticity. Incomplete opponent panels
remain visible and cannot silently enter a rank.

AERead reports role-level outcomes, validity and constraint violations, joint welfare,
and compatibility separately. A single observed deal or allocation cannot identify which
participant caused the result.

These are protocol capabilities and recommended study controls, not a claim that every
existing campaign implements the full design. Housing's development primary aggregate
includes self-play, and its model-sensitivity line omitted the earlier scripted anchor.
The incident register records these as D-13 and D-9. Separate reported slices mitigate
the first issue; they do not retroactively turn the aggregate into an isolated
focal-policy effect. Section 8 preserves that interpretation.

## 6. Case families

The current repository contains the following families at different maturity levels:

| Family | Interaction | Primary evidence | Current role in the suite |
|---|---|---|---|
| Exchange | Bilateral and multiparty trade/clearing | Feasibility, individual rationality, welfare references | Scored baseline and diagnostic cases |
| Housing | Multi-round search and assignment under private preferences | Capacity, allocation validity, case-native outcome and references | Main generated-world and campaign case study |
| Procurement grounding | Evidence-grounded sourcing decision | Canonical decision and evidence/rule constraints | Development benchmark |
| Procurement allocation | Qualification, negotiation, and award | Rule constraints and objective-reference evidence | Development plus held-out design |
| Pinned τ2 retail adapter (`tau3_retail`) | Tool-mediated customer-service state mutation | Terminal DB equivalence; separately retained judged assertions | Gold-action parity on 114 upstream tasks; judge-input parity only |
| Consent/IR | Multi-party cycle construction | Consent, feasibility, individual rationality, exact same-information optimum | Development diagnostic |
| Commercial-state reconstruction | Evidence and authority reconstruction | Deterministic state and source-authority checks | Calibration pilot |
| Data-center development | Financing, EPC, utility, and service amendment negotiation | Deterministic cash-flow and contract-state checks | Development design |

These families share execution and evidence contracts, not a universal task score.
The table is an inventory of family work, not evidence that every listed family has
completed shared-runner migration or benchmark qualification. Housing and the pinned
retail adapter supply the principal portability evidence here. Coverage and maturity
should be reported alongside any result.

## 7. Campaign governance

### 7.1 Ordered promotion gates

AERead campaigns progress through:

```text
design contract
  -> provider-free validation
  -> profile admission
  -> full-trajectory qualification
  -> variance pilot
  -> confirmatory freeze
  -> confirmatory execution
  -> publication
```

Each gate has explicit evidence. Passing a runnable integration test does not imply that a
multi-world comparison is statistically qualified. A failed profile-admission probe can
correctly block downstream model trajectories without producing a model score.

### 7.2 Failures, retries, and invalidation

Operational failures are typed missingness. They remain in the attempt record and are
reported by condition. A failed cell is not selectively rerun to complete an otherwise
favorable matrix.

Changing a frozen model route, prompt, budget, timeout, or retry policy creates a new
campaign identity. Before confirmatory freeze, an append-only invalidation reopens the
affected suffix of gates. After freeze, any control change requires a new campaign.

AERead maintains a machine-derived failure register for committed campaign evidence and a
separate human judgment log for design, operational, tooling, and judgment incidents.
Neither is retroactively cleaned once the cause becomes known.

Content hashes bind recorded bytes and versions; they do not authenticate a reviewer
or establish that a report's claims are true. The current contribution pipeline still
has three promotion blockers: trusted execution/semantic validation of contributed
conformance reports, complete runtime enforcement of contributed resource ceilings,
and authenticated human approval. Built-in development evidence must not be described
as production admission for arbitrary third-party families. These open boundaries are
documented in [QC/SOP open items](../operations/qc_sop_open_items.md).

## 8. Empirical studies and evidence boundaries

### 8.1 Environment

Housing is a multi-round market with tenants `i`, listings `j`, private tenant
willingness to pay `v_ij`, private landlord costs `c_j`, and rent `p_ij`. Binary
assignment variables `x_ij` permit at most one listing per tenant and one tenant per
listing. Unmatched participants have zero trade payoff. For a signed match:

`tenant payoff = v_ij - p_ij`,

`landlord payoff = p_ij - c_j`,

`joint surplus = v_ij - c_j`.

Rent redistributes surplus. For example, `v = 100`, `c = 60`, and `p = 110` yield
surplus 40 while the tenant loses 10. The efficient matching can therefore coexist
with an IR violation. The paper reports allocation efficiency, individual payoffs,
and IR diagnostics as distinct measurements.

The welfare reference is

`U(w) = max_x sum_(i,j) x_ij (v_ij - c_j)`

subject to one-to-one assignment and dropping nonpositive-surplus matches. This is
a full-information allocation upper bound. It is not a proven attainable optimum
for decentralized agents with private information, limited contacts, and a finite
round budget. On worlds with `U > 0`, realized welfare `R` gives the ratio `R/U`;
zero-upper-bound worlds require separate treatment. That ratio does not certify
truthful pricing, equilibrium behavior, or compliance with every participant's IR.

Each round runs three phases:

1. **Contact:** an unmatched tenant sends a listing and rent offer. Each tenant has
   one contact opportunity per round.
2. **Respond:** the landlord sees its own inbox and can accept or counter one offer,
   creating an immutable hold that reserves listing capacity.
3. **Commit:** the tenant signs or walks from a named hold. The signed terms come
   from that hold; unused holds expire at the round boundary.

Tenants observe their own preferences and the public board. Landlords observe their
own costs and inboxes. Private evaluator data remain outside those observations.
Generated worlds vary market tightness, common versus private utility weight, and
interaction budget. Deterministic policies provide no-op, random, naive, adaptive,
and oracle-informed controls. The exact environment version and phase semantics
must accompany every experiment.

The case study demonstrates qualification, economic measurement, and the remaining
limits of attribution under the implemented campaign.

### 8.2 Provider-free case admission

The first case-configuration sweep crossed 18 configurations with 16 paired development
seeds, producing 288 configuration–seed instances without provider calls. This is not
288 independently sampled worlds: seeds are paired across configurations. Predeclared gates excluded duplicate
or degenerate worlds, generator/oracle failures, insufficient baseline beatability, and
uninformative score envelopes. Fourteen configurations passed. A three-configuration
panel was selected by declared distance from target baseline difficulty across mild,
moderate, and severe market strata.

This stage qualifies the environment distribution. It is not evidence about model
performance.

### 8.3 Route qualification and operational evidence

Successive development campaigns exposed rate limits, timeouts, empty provider responses,
and one driver-owned budget-classification defect. AERead retained these events rather
than replacing them with zero outcome scores or silently retrying selected cells.

As of 2026-09-06, the published Housing failure register contains 59 typed failures from
11 campaign bundles: 45 rate limits, nine timeouts, three provider rejections, one
execution error, and one transport failure. This count describes the accumulated
operational evidence; it is not a provider-quality estimate because the campaigns had
different designs and exposure.

### 8.4 Exploratory variance pilot

Campaign `housing_model_sensitivity_openrouter_parasail_v26` fixed two model profiles,
one harness, route snapshots, prompts, tools, memory, reasoning, sampling, timeouts,
retry policy, action schema, and case/world assignments. It planned and attempted 192
model-to-model cells across eight independently sampled worlds. Of these, 189 completed
with verified replay and three remained typed operational missingness.

Only six of the eight worlds contained the complete subject pair required by the analysis.
Across those six, the exploratory paired contrast (GLM minus DeepSeek under the declared
aggregation) was -0.0241 with a paired-world sample standard deviation of 0.0286. The
minimum meaningful effect was predeclared as 0.05. The analysis uses these facts to size
a later experiment; it does not rank the models. The contrast aggregates specified
live-opponent conditions including self-play. Opponent compatibility, endogenous
self-play, and the omitted scripted anchor limit its interpretation even on complete
worlds. Additional trajectories alone would not resolve that estimand issue.

### 8.5 Confirmatory freeze

The resulting confirmatory design is separately identified as
`housing_confirmatory_parasail_v2`. Before inspecting a holdout outcome, the freeze binds:

- 30 independently sampled holdout world seeds;
- three unseen configuration strata;
- two stochastic replicates;
- fixed subject/opponent conditions and routes;
- 720 planned trajectories;
- a paired-world primary contrast and interval procedure;
- a maximum five-percent operational-failure fraction;
- no selective retries; and
- an eight-dollar campaign cost ceiling.

The confirmatory outcome is not reported in this draft. The methodological claim is that
the analysis and execution identity were frozen before an eligible outcome could be used
to choose the design.

There is an important protocol caveat. A predecessor campaign,
`housing_confirmatory_parasail_v1`, attempted and completed 280 trajectories before its
campaign cost reserve stopped execution. The V2 freeze records that those outcomes were
not inspected before the new identity and corrected ceiling were sealed. This is weaker
than a pristine freeze made before any holdout call. The paper should therefore describe
V2 as a recorded **pre-outcome-inspection** freeze, not as an untouched holdout, and the
acceptability of that boundary requires external review. A future confirmatory campaign
should freeze a validated cost ceiling before its first holdout call.

### 8.6 Portability: pinned retail parity

The pinned τ2 retail adapter supplies a second, different validation surface. Its
saved corpus parity receipt reports 114 matched tasks, zero mismatches, zero skips,
and zero errors. The comparison executes each task's gold actions through both the
upstream path and the adapter and compares initial/final database state, tool effects,
deterministic reward components, and the inputs to judged assertions.

This is evidence about imported execution and measurement semantics on those
trajectories. It is not a model-performance result, exhaustive path equivalence,
or agreement between actual LLM judge outputs. The implementation emits a judged
assertion leaf only when the assertion content is nonempty, which holds for 40 of
114 tasks. Temporal-policy verification is not an additional proven leaf of this
adapter. Source: [adapter status](../families/tau3-retail/adapter_status.md) and
[corpus parity receipt](../families/tau3-retail/receipts/corpus_parity.json).

### 8.7 Diagnosis and intervention: procurement strategy scaffold

A separate saved Procurement campaign reports a prompt-treatment comparison over
12 curated economic worlds, two naming surfaces (labeled and opaque), and three
replicates per world per surface/arm: 144 trajectories in total. The saved report
marks its predeclared joint confirmation rule supported. The overall treatment-minus-
control contrast in regret to the declared upper bound is -26.04 in the case's USD
units, with a 95% world-cluster bootstrap interval of [-46.10, -7.41]. The feasibility
contrast is +0.25, with interval [0.069, 0.444].

The labeled-surface regret interval crosses zero, and some individual worlds regress.
The pooled finding therefore does not imply uniform benefits. It applies to the
declared case panel, prompt intervention, and pinned model/route; it is neither a
model ranking nor an RL training result. The report declares world-level pairing
and a frozen rule. Its row-level provenance, reference-bound validity, and execution
chronology should be independently audited before publication. This draft reports
the saved artifact's finding, not a fresh replication.

Source: [frozen comparison report](../../evidence/procurement_allocation_glm53_flash_parasail_strategy_confirmatory_v2/reports/confirmatory_effects.json)
and the [campaign plan](../../evidence/procurement_allocation_glm53_flash_parasail_strategy_confirmatory_v2/tables/frozen_plan.json).

### 8.8 Proposed validation experiments, not yet reported results

To convert the implementation contribution into an empirical measurement paper, we
propose four bounded studies:

| Question | Controlled comparison | Required evidence |
|---|---|---|
| Do the verifiers detect the defects they claim to detect? | Freeze known-valid alternatives and deliberate state, reference, privacy, and accounting mutations; test with and without the relevant guard on copied artifacts | Detection and false-rejection rates by defect type; mutation denominators and coverage |
| Does the protocol change conclusions? | Re-analyze identical development traces under score-zero operational failures, silent exclusions, trajectory-level independence, and the declared world-paired analysis | Changes in estimates and intervals, sensitivity to missing outcomes, and any claim that becomes unsupported; no result is presumed |
| How much is focal-policy performance opponent-dependent? | Scripted anchor and a frozen live panel; balanced roles; paired worlds and nested repeats; self-play treated as a separate block | Role-specific utilities, feasible outcomes, cross-play interaction effects, paired uncertainty, and missingness by condition |
| Do the cases represent the intended economic construct? | Independent expert review of a declared sample, oracle feasibility checks, baseline calibration, and held-out generator perturbations | Review agreement/disagreements, accepted/excluded counts, baseline separation, and generalization limits |

These studies should be predeclared before their evaluation traces are used to
choose controls or acceptance criteria. Development evidence can refine the design;
it cannot substitute for its held-out validation.

## 9. From evaluation to intervention

AERead failure labels are intended to change what data or training intervention follows.
State and action traces support observations about behavior. Labels such as planning
or belief error are hypotheses unless supported by a controlled probe: reasoning text
alone does not establish the model's internal cause. A targeted intervention should
test the hypothesis, with the world and other relevant controls held fixed.

| Evidence pattern | Diagnosis | Candidate intervention |
|---|---|---|
| Incorrect belief before a reasonable action | State comprehension or inference | Belief probes and evidence-grounded trajectories |
| Correct belief, poor sequence | Planning | Counterfactual plans or action-preference pairs |
| Correct plan, malformed/illegal action | Execution | Typed tool-use examples and action validation |
| Valid result never checked | Verification | Verification-required tasks or verifier-shaped reward |
| Repeated failure after corrective evidence | Recovery | Revision and recoverable-error trajectories |
| Missing or corrupted trajectory | Harness/provider | Infrastructure repair; no policy-gradient signal |
| More solicitation without valid clearing | Reward-proxy exploitation | Outcome-grounded reward, oracle examples, or structured solver access |

The last distinction is particularly important for RL. A verifier that rewards an
affordance such as contacting more parties can be optimized without constructing a valid
multi-party outcome. Diagnostic leaves should remain visible so higher reward does not
hide worse validity.

## 10. Interoperability

AERead's native records define its benchmark truth. External frameworks are adapters or
export targets:

- Harbor/ATIF for portable task execution and rollout interchange;
- rLLM-compatible trajectory representations;
- RL environments and verifier integrations; and
- provider- or harness-specific agent adapters behind one canonical response boundary.

Interoperability should preserve case, profile, seed, attempt, verifier, and evidence
identity. An exporter must not collapse typed failures into reward zero, expose hidden
state, or change the experimental unit. Harbor/ATIF export is currently a planned
boundary, not an implemented claim in this manuscript.

## 11. Limitations and threats to validity

### Construct validity

Executable checks establish that a declared rule or objective was evaluated correctly;
they do not establish that the task distribution represents economically important work.
Several families still need independent domain-expert review, reviewer-agreement
measurement, and broader baseline calibration.

### Generator coverage

Deterministic generators can make experiments reproducible while still omitting important
market structures or leaving exploitable artifacts. Held-out parameter combinations,
surface perturbations, metamorphic tests, and external cases are required.

### Opponent-population dependence

Multi-agent results depend on the opponent panel and role distribution. A frozen panel
supports reproducibility but may not represent deployment. Results should therefore
state the target population and report sensitivity across opponent policies.

### Provider and harness drift

Hosted model routes can change without a model-name change. Endpoint snapshots, provider
identity, prices, and harness versions reduce ambiguity but cannot make external systems
permanent. Reproduction may require replay against sealed responses rather than fresh
provider calls.

### Missingness and effective sample size

Operational missingness may be related to trajectory length, model, or condition. Merely
reporting it separately does not eliminate selection bias. Confirmatory analyses need
predeclared tolerances and sensitivity analyses. Repeated trajectories within a world do
not create new independent task evidence.

### No universal cross-family score

AERead intentionally does not define one scalar over welfare, refund correctness,
procurement evidence, and judged communication. This limits simple leaderboard display
but preserves the meaning of each measurement. Any future composite requires a declared
decision context, normalization, weighting, and sensitivity analysis.

## 12. Discussion and conclusion

The central challenge in evaluating economic agents is not merely making a simulation
interactive. It is preserving the chain from economic construct to observable behavior,
task distribution, controlled execution, admissible evidence, verifier, statistical
claim, diagnosed failure, and subsequent intervention.

AERead contributes an environment architecture and evidence lifecycle for this chain.
Its families can express private information, interacting incentives, coupled actions,
stateful outcomes, and multiple kinds of verification without forcing every result into
the same score. Its campaign protocol treats replay, operational failure, pairing, and
freezing as part of measurement rather than post-hoc experiment management.

The Housing pilot supplies development variance and operational evidence with explicit
missingness and an imperfect attribution design. Retail parity supports portability
over pinned gold trajectories. Procurement supplies a bounded example of an intervention
reported with both quality and feasibility. Together these establish a starting point
for studying economic-agent measurement. Further work must validate constructs with
independent experts, compare the diagnostic value of the protocol, complete controlled
opponent-panel experiments, and test intervention generalization on held-out worlds.

## Evidence appendix: manuscript claims and source artifacts

These are saved-artifact observations inspected during drafting, not newly executed
tests. Source paths permit another reviewer to audit the claim. The presence of a hash
inside a report does not imply that this drafting pass independently recomputed every
transitive digest.

| Manuscript claim | Source | Permitted use |
|---|---|---|
| Family/phase scheduling and frozen simultaneous observations | [scheduler implementation](../../src/aeread/shared_runner/task/scheduler.py), [scheduler tests](../../tests/test_shared_runner_scheduler.py) | Implemented contract; exact test execution remains associated with its original run |
| Typed verifier/reference compatibility | [measurement implementation](../../src/aeread/shared_runner/measurement.py) | Implemented measurement semantics, not proof of task construct validity |
| Six Housing golden scenarios passed | [QC bundle](../../evidence/housing_qc_goldens_v1/reports/qc_bundle.json) | Narrow mechanics, replay, and classification coverage |
| 18 configurations × 16 paired seeds; 14 configurations admitted | [sweep summary](../../evidence/housing_case_config_sweep_v1/reports/sweep_summary.json) | Development case admission; 288 instances are not 288 independent samples |
| 189 of 192 Housing attempts completed; six complete paired worlds | [V26 qualification and analysis](../../evidence/housing_model_sensitivity_openrouter_parasail_v26/reports/qualification.json) | Exploratory contrast/variance with declared interaction mixture and missingness |
| 59 typed failures across 11 bundles | [failure summary](../../evidence/housing/failure_register/reports/summary.json) | Incident corpus; heterogeneous exposure does not support comparative provider rates |
| 114-task deterministic retail parity | [corpus parity](../families/tau3-retail/receipts/corpus_parity.json), [scope and limitations](../families/tau3-retail/adapter_status.md) | Gold-action and judge-input equivalence, not exhaustive or judge-output equivalence |
| Procurement prompt-treatment benefit with feasibility guardrail | [confirmation report](../../evidence/procurement_allocation_glm53_flash_parasail_strategy_confirmatory_v2/reports/confirmatory_effects.json) | Saved result on 12 curated worlds and one model/route; independent provenance/replication review pending |
| Housing V2 declares 30 worlds and 720 trajectories | [freeze artifact](../../evidence/housing_confirmatory_parasail_v2/reports/confirmatory_freeze.json), [incident log](../operations/incident_log.md) | Planned design with predecessor execution disclosed; no completed V2 effect reported |
| Remaining contributed-family admission limits | [open items](../operations/qc_sop_open_items.md) | Explicit production-contribution blockers, not a claim all families are qualified |

### Manuscript figures to produce

1. **Environment figure:** private preferences/costs, public board, and the
   contact/respond/commit cycle; show what each actor can observe.
2. **Measurement figure:** a valid efficient match, a high-welfare IR violation,
   a legal poor outcome, and a missing operational outcome with their distinct leaves.
3. **Evidence figure:** planned/attempted/completed/paired units for the Housing pilot,
   preserving world versus trajectory denominators.
4. **Experiment figure:** paired world effects for the selected intervention and
   a separate cross-play matrix when that study is actually qualified.

The final paper should render these from declared equations and saved artifacts;
the figure descriptions are not placeholders for invented experimental results.

## Rehearsal appendix: questions this draft should survive

1. Why is AERead an environment framework rather than a collection of economic games?
2. What does AERead add beyond Harbor's task and rollout abstraction?
3. How do AppWorld, τ²-bench, and SidConArena each overlap with the contribution?
4. How do you know a generated Housing world measures the intended construct?
5. Which properties are deterministic, and which still require human validation?
6. What is the unit under test: a model, an agent profile, a population, or a joint system?
7. Why are operational failures missingness rather than score zero?
8. What prevents hidden retries or provider drift from changing the result?
9. Why did 189 completed trajectories not justify a model ranking?
10. What evidence justifies 30 confirmatory worlds?
11. Why can the current paired contrast not be called a winner result?
12. What would falsify the paper's principal methodological claim?
13. How could a weak policy game each verifier family?
14. Which failure diagnoses imply different post-training interventions?
15. What would an executable Harbor/ATIF adapter need to preserve?
16. Why can Housing welfare improve while a participant becomes worse off?
17. Is the Housing oracle a feasible decentralized policy or a full-information upper bound?
18. What did the 114-task adapter parity study actually compare?
19. What does the current mixed self-play aggregate fail to identify?
20. Which proposed experiment would show that the evidence protocol adds no diagnostic value?

## References

1. Harbor Framework Team. [Harbor: a framework for evaluating and optimizing agents and models in container environments](https://github.com/harbor-framework/harbor), 2026.
2. [Terminal-Bench: Benchmarking Agents on Hard, Realistic Tasks in Command Line Interfaces](https://arxiv.org/abs/2601.11868), 2026.
3. Yao et al. [τ-bench: A Benchmark for Tool-Agent-User Interaction in Real-World Domains](https://arxiv.org/abs/2406.12045), 2024.
4. Barres et al. [τ²-bench: Evaluating Conversational Agents in a Dual-Control Environment](https://arxiv.org/abs/2506.07982), 2025.
5. Drouin et al. [WorkArena: How Capable Are Web Agents at Solving Common Knowledge Work Tasks?](https://arxiv.org/abs/2403.07718), 2024.
6. Xie et al. [OSWorld: Benchmarking Multimodal Agents for Open-Ended Tasks in Real Computer Environments](https://arxiv.org/abs/2404.07972), 2024.
7. Xu et al. [TheAgentCompany: Benchmarking LLM Agents on Consequential Real World Tasks](https://arxiv.org/abs/2412.14161), 2024.
8. Liu et al. [AgentBench: Evaluating LLMs as Agents](https://arxiv.org/abs/2308.03688), 2023.
9. Zhou et al. [SOTOPIA: Interactive Evaluation for Social Intelligence in Language Agents](https://arxiv.org/abs/2310.11667), 2023.
10. Trivedi et al. [AppWorld: A Controllable World of Apps and People for Benchmarking Interactive Coding Agents](https://arxiv.org/html/2407.18901v1), 2024.
11. [AgentGym: Evolving Large Language Model-based Agents across Diverse Environments](https://arxiv.org/html/2406.04151v1), 2024.
12. [SidConArena](https://arxiv.org/html/2606.27397v1), 2026.
13. Harbor team. [Introducing Harbor-Index](https://harbor-index.org/), 2026. Release article.
