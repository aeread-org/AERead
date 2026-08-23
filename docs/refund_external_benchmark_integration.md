# Refund external-benchmark integration plan

**Status:** design decision; implementation follows the shared-runner kernel and its
`exchange_v1`/`housing_v1` conformance gates

**Decision:** adapt a pinned upstream customer-service environment before considering an
AERead-native refund family

**Paper role:** use housing and refund to demonstrate two different measurement routes, not
to construct a universal cross-family score

## 1. Research decision

AERead will use a thin adapter over the current tau benchmark implementation (branded
**tau3-bench** upstream) as the first external refund/return environment. It will not copy
the task corpus into AERead or reimplement the upstream policy, tools, database, user
simulator, or evaluator.

The measurement-layer paper uses the pair for structural coverage:

| Demonstration | Primary measurement route | What it establishes |
|---|---|---|
| `housing_v1` | `optimizable_outcome` with a feasible witness and typed upper bound | The runner can preserve bounded optimization claims without confusing a full-information relaxation with an attainable same-information oracle. |
| pinned tau3 retail | `property_or_answer`, with deterministic final-database equivalence as the primary estimand | The same runner can preserve exact state/property validation when a policy optimum and per-seat payoff are not the right objects. |

The upstream aggregate reward remains available as an interoperability result, but it is
not silently relabeled judge-free and is not pooled with housing. There is no default
cross-family scalar.

## 2. Frozen upstream source

The first implementation pins the following source before any baseline is run:

| Field | Frozen value |
|---|---|
| repository | [`sierra-research/tau2-bench`](https://github.com/sierra-research/tau2-bench) |
| release | `v1.0.1` |
| dereferenced commit | `fc0055dc4e0a316c3f83133267fbd6faaa770992` |
| domain/split | `retail/base` |
| pinned task count | 114 |
| upstream license | MIT |

Do not use the legacy [`sierra-research/tau-bench`](https://github.com/sierra-research/tau-bench)
repository: its own README directs evaluation users to the maintained tau3 code and warns
that its tasks are outdated. A newer tau3 revision may replace this pin only through a
reviewed manifest change with a new commit, artifact hashes, parity run, and an explicit
statement about score comparability.

### 2.1 The pinned evaluator surface is mixed

The release must be read from its task records rather than inferred from the evaluator's
default documentation. At the frozen commit:

- `retail/base` contains 114 task IDs;
- 112 of 114 task records declare `DB + NL_ASSERTION` as `reward_basis`; the other two
  declare `DB`;
- 40 of 114 contain at least one non-empty natural-language assertion and therefore have
  an actual LLM-judge surface;
- 36 contain non-empty `communicate_info`, but zero pinned retail tasks gate the upstream
  reward on `COMMUNICATE`;
- 31 reference a return tool, 29 an exchange tool, and 18 a cancellation tool. These sets
  overlap and are descriptive corpus tags, not independent samples.

Consequently, the full upstream reward is not a universally deterministic refund label.
AERead separates the deterministic database property from the upstream judge-dependent
component instead of changing upstream semantics.

## 3. Measurement declarations

The adapter emits a vector with provenance rather than one replacement score.

| Estimand | Kind and status | Role |
|---|---|---|
| `tau3_retail_db_state` | `property_or_answer`; `property_verified` when the final canonical database equals the upstream gold state | **Paper-primary external estimand.** Preserve the upstream rule that alternative tool trajectories pass when they produce the same target state. |
| `tau3_required_communication` | `property_or_answer`; exact upstream substring checks or an explicitly versioned structured validator | Diagnostic at the v1.0.1 pin because `COMMUNICATE` does not gate the retail reward. Never claim it is the pinned headline score. |
| `tau3_upstream_reward` | `comparative_or_human_judged`; `judge_dependent=true` whenever non-empty NL assertions participate | Compatibility result produced by the pinned upstream evaluator. Record every component and never present this value as a deterministic oracle. |
| tool errors, redundant calls, turns, latency, tokens, and cost | descriptive diagnostics | Explain execution burden without altering task correctness. |

No artificial `payoff`, social-welfare optimum, bargaining solution, or universal score is
created for refund entitlement. If a later native environment measures economic loss, it
must keep customer shortfall and unauthorized firm concession in their native units unless
a defended aggregation rule is supplied.

## 4. Adapter boundary and event mapping

Upstream remains authoritative for:

- policy text and task definitions;
- initial database and tool semantics;
- the user simulator and its stopping behavior;
- gold-state construction and upstream evaluator components.

AERead owns:

- resolution of the pinned source into an immutable `RunPlan`;
- provider calls, explicit attempts/retries, budgets, and costs;
- canonical events, visibility, evidence, replay, and receipts;
- typed measurement declarations and cluster-aware analysis.

The adapter maps the half-duplex interaction into a repeatable phase graph rather than a
hard-coded refund script:

```text
user turn -> agent response -> zero or more tool calls -> tool results
          -> user turn or terminal evaluation
```

Read-only and mutating tools remain distinct events. A logical agent action may have more
than one recorded provider attempt, but hidden SDK retries are prohibited. The adapter must
not collapse multiple tool calls into one opaque action or treat an empty, truncated, or
malformed response as a customer-service decision.

## 5. First pilot: 18 pinned tasks

The first parity and instrumentation run uses this 18-task pilot, all from the frozen
`retail/base` split. The strata exercise different state and dialogue risks; they are not
post-outcome difficulty bins.

| Stratum | Task IDs | Coverage intent |
|---|---|---|
| direct return/state transition | `14`, `53`, `73`, `108` | ordinary eligible returns, damaged goods, exclusions, and exact item selection |
| payment method, refusal, and fallback | `10`, `11`, `82`, `83` | unsupported refund destination, original-payment fallback, gift-card fallback, and human handoff |
| confirmation, changed mind, and non-mutation | `5`, `48`, `84`, `91` | authorization timing, inquiry without unintended mutation, and changed requests |
| compound and multi-order state | `16`, `28`, `103`, `104` | cancellation plus return, refund calculation, multiple orders, and nearby-state disambiguation |
| lookup and conditional fallback | `30`, `46` | damaged-item exchange/return cascade, ambiguous identifiers, and required communication |

The pilot is an integration gate, not a population estimate. Changing an ID, stratum, or
task definition changes the pilot manifest hash and requires the change to be recorded
before results are viewed.

## 6. Component-level parity gate

For each pilot task, first produce or ingest a canonical upstream trajectory. Replay the
same ordered messages and tool calls through the adapter and require **component-level
parity**:

1. identical canonical initial database;
2. identical ordered tool calls and tool results after normalization;
3. identical final database and state diff;
4. identical upstream DB reward;
5. identical `COMMUNICATE` result whenever that component is evaluated;
6. identical NL-assertion inputs, judge configuration, and recorded judge result whenever
   that component is evaluated;
7. identical upstream aggregate reward from the same recorded component values.

Deterministic components require exact equality. Judge parity is established by replaying
the same recorded judge artifact or invoking the same pinned judge configuration once and
feeding that result to both aggregation paths; two fresh stochastic judge calls do not
constitute a parity test.

Required fixtures include a successful mutation, a correct refusal/no-op, a different valid
tool trajectory reaching the same gold state, a malformed tool call, an unexpected state
mutation, and an empty `finish_reason=length` attempt followed by the declared retry. The
adapter may expand beyond the pilot only after all deterministic fixtures and pilot DB
components agree exactly.

## 7. Receipt and replay requirements

Every episode receipt binds at least:

```yaml
upstream_repository: sierra-research/tau2-bench
upstream_release: v1.0.1
upstream_commit: fc0055dc4e0a316c3f83133267fbd6faaa770992
domain: retail
split: base
task_id: string
task_sha256: string
task_list_sha256: string
policy_sha256: string
database_sha256: string
tool_schema_sha256: string

user_simulator_model: resolved provider/model/version
user_simulator_prompt_sha256: string
user_seed: integer
tested_agent: resolved AgentProfile

event_root_sha256: string
tool_calls: ordered event references
state_before_sha256: string
state_after_sha256: string
state_diff_artifact: reference
attempt_ids: [string]
retry_count: integer
finish_reason: string
input_tokens: integer
output_tokens: integer
reasoning_tokens: integer

evaluation_type: pinned upstream enum/value
reward_basis: [string]
scorer_version: resolved implementation reference
judge_dependent: boolean
judge_model: resolved value or null
judge_prompt_sha256: string or null
component_scores: mapping
upstream_reward: number or null
```

The task, policy, database, simulator prompt, tools, and scorer are hashed independently so
a matching repository commit cannot hide a runtime override. Replay must reconstruct the
state transition and deterministic score without a provider call. A paper row is admitted
only from validated receipts.

## 8. Expansion and STATE-Bench

After the 18-task pilot passes, expand adapter conformance to all 114 pinned `retail/base`
tasks. Report the full retail domain and any predeclared refund/return slice separately;
supporting the whole adapter does not turn every retail task into a refund observation.

STATE-Bench is the next external corpus, not a source of silently merged labels:

1. pin its repository release/commit and task artifacts before selection;
2. retain deterministic final-state requirements as a primary vector component;
3. translate process requirements into typed temporal predicates where the transcript and
   event log make them checkable—for example, required read before write, confirmation
   before mutation, forbidden mutation, exact amount/method/reason, and no unexpected state
   change;
4. retain requirements that cannot be determinized, plus UX judgments, as separately named
   `judge_dependent` secondary measurements with judge model, prompt, version, and artifacts;
5. never multiply the deterministic state vector and residual judge scores into a new AERead
   headline scalar.

## 9. Cluster, pairing, and saturation language

For the fixed task-distribution estimand, the independently sampled unit is the **task instance**.
Turns, messages, tool calls, and state mutations are observations within that
cluster. Repeated user simulations are stochastic **nested replicates**, not additional
independent task draws. Models and interventions are paired on the same task ID and user
seed; analysis resamples task clusters or uses the corresponding paired/block design.

`pass@1` estimates success for one declared simulator draw. A pass-all-runs measure such as
`pass^k` estimates robustness across the declared nested runs. Near-perfect `pass@1` alone
cannot support a saturation statement.

Only **fixed-suite ceiling exhaustion** may be claimed, and only when all of the following
are preregistered and satisfied for `tau3_retail_db_state`:

- the exact pinned task panel and coverage strata are reported;
- the property maximum of one is applicable to every admitted task;
- the pass-all-runs estimate and cluster-level interval are within a declared epsilon of
  that maximum;
- missing, invalid, judge-dependent, and retried cells are reported rather than converted
  to failures or successes;
- no declared stratum retains material headroom under its cluster-level interval.

This wording describes exhaustion of the pinned suite under the declared simulator and
run conditions. It is not evidence of **universal refund capability**, and it does not
license claims about unseen policies, stores, languages, adversarial users, or future
benchmark versions.

## 10. Ordered implementation gates

1. Pin tau3 `v1.0.1` at commit `fc0055dc4e0a316c3f83133267fbd6faaa770992`
   and resolve `retail/base`; reject the legacy repository.
2. Freeze the 18-task pilot manifest and its independent artifact hashes.
3. Implement trajectory ingestion/replay and pass the component-level parity gate.
4. Emit complete evidence and receipts, including simulator, state, retry, and scorer
   provenance.
5. Expand conformance to all 114 pinned retail tasks and preserve separately reported
   deterministic and judge-dependent components.
6. Add the pinned STATE-Bench adapter, determinizing process requirements only where the
   event evidence supports exact predicates.
7. Consider a native `refund_v1` only if the adapters expose a named, unresolved measurement
   question with a falsifiable estimand.

Examples that could justify `refund_v1` include counterfactual policy deviations,
customer-shortfall versus unauthorized-concession decomposition, or causal separation of
information failure from execution failure. Merely reproducing tool-use completion or a
service-flow score does not pass this admission gate.

## 11. Completion criteria

The external refund integration is paper-ready only when:

- the exact upstream pin and all source/runtime hashes appear in every receipt;
- the pilot and full-domain deterministic components reproduce upstream results exactly;
- upstream judge-dependent results remain labeled and reproducible from recorded artifacts;
- replay reconstructs final state and score without network inference;
- missing actions and reasoning-budget exhaustion are typed evidence, not implicit no-ops;
- task-cluster pairing and nested simulator runs are preserved in analysis;
- saturation language remains confined to the pinned suite; and
- housing and refund appear as two typed measurement demonstrations, never as a universal
  scalar leaderboard.
