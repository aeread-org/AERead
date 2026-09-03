# Concepts

AERead's shared vocabulary, in dependency order. Benchmark families own their economic or
task semantics; the shared runner owns reproducible planning, execution, evidence, and receipts.

## Family

A versioned benchmark environment with its own state, observations, valid actions, transition
rules, terminal conditions, and measurement semantics. Exchange, Housing, procurement,
data-center development, commercial-state calibration, and Tau3 retail are distinct families;
they share runner contracts, not one economic model or headline score.

## World

A reproducible decision environment containing the actors, initial state, rules, hidden
information, and available actions for one family. When a world is stochastic, its declared
world seed and pinned implementation reproduce the same initial conditions. Evaluator-only
state must not leak into an agent's observation.

In `exchange_v1`, the world is a seeded exchange economy with resource endowments and private
utilities. Other families instantiate different worlds: housing assignments, supplier awards,
commercial records, or policy-constrained database state.

## Case

A versioned declaration of one world or world generator plus its family-owned payload. A case
identifies the capability being measured and pins the content needed to reconstruct it. Its
shape is family-specific: an Exchange case can declare visibility, settlement, and consent
rules, while a retail case can declare an initial database and policy constraints.

Cases are organized by family under [`cases/`](../../cases/README.md). The current coverage map
is [CAPABILITIES.md](../../CAPABILITIES.md).

## Profiles and roles

An `AgentProfile` declares how a participant is invoked: model or policy identity, prompts,
sampling controls, budgets, retry policy, and harness. A family maps profiles to its own roles
or seats. Controlled evaluations hold declared counterparts and execution controls fixed so a
comparison can be attributed to the treatment under test.

Exchange commonly uses these family-owned roles:

- **under_test** — the candidate agent;
- **panel** — frozen model or scripted counterparty seats;
- **compiler** — converts dialogue into proposed settlement rows;
- **verifier** — checks feasibility and authorization.

Other families need not use this role set or a compiler-mediated negotiation.

## RunPlan, task, episode, and attempt

A `RunSpec` is authored experimental intent. Before external work begins, the resolver expands
and seals it as an immutable `RunPlan` with explicit implementation pins and `PlanCell` records.

- A **task** is one planned cell: case, profiles, controls, seeds, and replicate.
- An **episode** is the family-state trajectory defined for that cell.
- An **episode attempt** is one retained execution of the episode. Operational retries create
  new attempt identities; they are not new independent experimental samples.

This distinction keeps planned-but-unstarted tasks, failed attempts, and valid poor outcomes
separate.

## Phases, actions, and calls

The shared scheduler advances a family's declared phase graph. A `LogicalAction` is one
economically meaningful decision requested from an actor. It can have multiple `ActionAttempt`
records only under the sealed retry policy. One action attempt may contain several
`ProviderCall` and `ToolInvocation` records during multi-turn tool use; those calls are not
themselves action retries.

For simultaneous phases, every participant observes the same frozen pre-phase state. The
family plugin parses actions, checks legality, applies transitions, and determines termination.

## Evidence and receipts

Execution produces an append-only event log and content-addressed artifacts. Every external
side effect receives a durable start event before dispatch and exactly one terminal success,
failure, or `outcome_unknown` event. Missing or corrupt operational evidence is not converted
into a zero-quality task outcome.

An `EvaluationReceipt` binds the sealed plan and attempt identity to evidence roots, validity,
typed scores, replay status, and inclusion or exclusion decisions. Research tables and
publications are projections derived from plans and receipts, not independent sources of truth.

## Measurement is family-native

Each family defines typed verifier outputs and reference providers appropriate to its construct.
Deterministic validity, economic or task quality, operational reliability, latency, tokens, and
cost remain separate measurements unless an analysis plan explicitly defends a transformation.
AERead does not define one universal cross-family scalar.

### Exchange example: negotiation funnel and AER

An Exchange episode can progress through communication, proposals, responses, finalization,
private acceptance, compilation, verification, and settlement. Value is realized only when a
deal survives the applicable gates.

The Exchange scorer records `w_real`, realized welfare gain, and a `denominator`, attainable
welfare gain under the case's declared reference tier. Its Attainable-welfare Efficiency Ratio
(AER) aggregates `ΣW_real / ΣD` within a compatible tier and reports seeded uncertainty.

- Negative outcomes are preserved, and valid values may exceed 1.
- A clipped companion such as `aer_clip` is presentation-only.
- Exchange feasibility or authorization failures affect `w_real` according to the pinned
  Exchange scoring contract while retaining the denominator.
- Reference tiers are not silently pooled, and degenerate denominators retain a typed reason.

AER is an Exchange-family measurement, not the definition of success for Housing, procurement,
retail, or other families.

## Baselines and qualification

Families declare baselines and admission tests appropriate to their construct. Exchange uses
provider-free no-op, random, greedy, and ceiling comparisons to reject cases that do not
separate meaningful action from inaction. Other families can require different deterministic
validity, reference, non-triviality, or bounded-objective checks. Passing an execution test does
not by itself qualify a case for a scientific campaign.

## Replay and recovery

The shared runner seals provider and tool boundaries in evidence, supports deterministic
family-state replay, and audits event-chain integrity. A completed replay must reproduce the
declared state and score contract without making candidate calls. An interrupted external call
whose result cannot be proven is retained as `outcome_unknown`, not silently retried or erased.

Legacy `exchange_v1` commands still use their older transcript and inference-cache replay path
until the Exchange compatibility plugin completes the shared-runner migration.

## Seeds and experimental units

World, environment, inference, and counterfactual randomness are distinct controls when a
family uses them. Public development seeds may ship with a case; confirmatory or held-out seeds
can remain private. Repeated attempts or trajectories within one independently sampled world
remain correlated and do not become additional independent samples merely because they have
different execution IDs.
