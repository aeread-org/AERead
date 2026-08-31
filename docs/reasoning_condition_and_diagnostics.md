# Reasoning condition and diagnostic taxonomy

**Status:** shared-runner measurement contract

**Decision:** reasoning is a declared experimental condition and a secondary diagnostic
surface; actions and outcomes remain primary

**Non-goal:** scoring private chain-of-thought or treating reasoning-token volume as quality

## 1. Why this is a condition, not a model label

"Reasoning model" is not a stable experimental description. The same provider/model can be
served with provider-default reasoning, an explicit effort level, a bounded reasoning
budget, no exposed control, or a prompt that requests a visible explanation. These settings
can change the policy, latency, cost, output availability, and comparability of a run.

Every evaluated cell therefore binds a versioned `reasoning_condition_id` through its
`AgentProfile` and resolved `RunPlan`. Reports compare complete agent configurations, not a
bare model name and not an informal reasoning on/off label.

## 2. Required declaration

The reasoning condition records at least:

```yaml
reasoning_condition_id: provider_reasoning_low_v1
mode: provider_default | enabled | disabled | unsupported_control
reasoning_effort: low | medium | high | provider_specific | null
reasoning_token_budget: integer | null
output_token_budget: integer
total_completion_budget: integer | null
provider_parameters: canonical mapping
rationale_visibility: none | provider_summary | task_visible_decision_record
rationale_protocol_id: string | null
reasoning_content_retained: false
```

The resolved provider request, parameter support, and budget semantics are stored with the
condition. `provider_default` is not called "off." A provider that exposes no disable switch
is `unsupported_control`, not a control arm. Prompt-elicited visible explanation is a
separate intervention because it changes the prompt and may change the policy.

AERead does not require or retain private chain-of-thought. A provider reasoning summary or
task-visible decision record is retained only when permitted and declared. It remains an
observed output, not privileged access to the model's causal computation.

## 3. Experimental comparison

A causal reasoning-condition comparison holds constant:

- resolved model snapshot and provider route;
- family, case, role, policy text, tools, and memory/compaction configuration;
- temperature, sampling parameters, and non-reasoning budgets where the API permits;
- counterpart or user-simulator version; and
- the same paired task/user seed and case block.

The comparison varies one predeclared reasoning condition. If changing reasoning necessarily
changes another parameter, that bundle is named and the claim is about the bundled agent
configuration. Cross-model comparisons, retrospective splits by reasoning-token count, and
one model's provider-default setting versus another model's explicit effort setting do not
identify a reasoning effect.

Primary analysis remains paired on the case/task cluster. Repeated stochastic samples are
nested replicates. Reports include the condition effect on the primary behavioral estimand,
its cluster-level interval, cost, latency, empty/truncated rates, and coverage.

## 4. Primary versus diagnostic evidence

The scientific ordering is:

1. **Primary:** legal actions, tool calls, state transitions, terminal outcomes, and the
   family-declared score vector.
2. **Secondary deterministic diagnostics:** constraint violations, parse/tool failures,
   missing commits, counterfactual action checks, and other event-derived labels.
3. **Secondary interpretive diagnostics:** structured decision records, human annotations,
   or LLM-judged explanations, each with provenance and uncertainty.

A persuasive explanation cannot rescue an invalid action, and an optimal action does not
require a persuasive explanation. Reasoning length is never added to an economic score.

## 5. Failure-mechanism taxonomy

Do not reduce a result to reasoning on/off. Diagnostic labels identify where the observable
decision pipeline failed:

| Code | Question | Preferred evidence |
|---|---|---|
| `objective_selection` | Did the agent optimize the estimand actually assigned—for example, private utility, policy entitlement, or social welfare—rather than a nearby but different objective? | Declared task objective plus action/outcome counterfactuals; a structured self-report is supporting evidence only. |
| `strategic_modeling` | Did it represent relevant counterpart behavior, competition, information, timing, or future state well enough to choose an action? | Paired information interventions, response predictions, and action counterfactuals. |
| `constraint_tracking` | Did it preserve budgets, policy rules, consent, feasibility, privacy, and state-dependent prohibitions across the trajectory? | Deterministic event/transition predicates wherever possible. |
| `execution` | Given an otherwise adequate choice, did it emit a legal schema, invoke the right tool, provide required arguments, and complete the intended mutation or commitment? | Parser, legality, tool-result, state-diff, and commit evidence. |
| `undetermined` | Does the available evidence fail to distinguish two or more mechanisms? | Report ambiguity; do not force a single explanation. |

Labels are multi-valued: a trajectory may fail constraint tracking and execution. Each label
records its evidence source and confidence:

```yaml
diagnostic_code: constraint_tracking
status: present | absent | undetermined
evidence_kind: deterministic_rule | counterfactual | structured_self_report | human_annotation | llm_judge
evidence_refs: [event_or_artifact_id]
annotator_or_scorer_version: string
judge_dependent: boolean
confidence: number | null
```

`deterministic_rule` and controlled counterfactual evidence take precedence. A visible
rationale can reveal what the model says it considered, but it may be an incomplete or
post-hoc rationalization. LLM-coded rationales remain `judge_dependent=true` and cannot
become the primary capability score.

## 6. Reasoning-budget starvation is measurement failure

Every provider attempt records:

- input, output, and `reasoning_tokens` when exposed;
- the reasoning, output, and total budget semantics sent to the provider;
- `finish_reason`, empty, truncated, latency, and cost;
- whether a declared higher-budget retry fired; and
- whether usable action content was ever emitted.

An empty response with `finish_reason=length` and positive reasoning usage is reasoning-budget
starvation. It must not be scored as an economic no-op, refusal, bid, or failure to consent.
The explicit retry policy applies; if it is exhausted, the affected action or episode receives
the appropriate typed missing/invalid-measurement status. Reports publish this rate per
model x case x reasoning condition so serving differences cannot masquerade as capability.

## 7. Optional visible decision record

When a study needs more diagnostic resolution, it may ask every compared arm for the same
short, structured decision record:

```yaml
selected_objective: string
key_state_beliefs: [string]
binding_constraints: [string]
anticipated_counterparty_or_environment_response: [string]
chosen_action: structured reference
rejected_alternative: structured reference | null
```

This is an experimental measurement instrument, not hidden chain-of-thought. Its schema,
prompt, parser, visibility to other agents, token budget, and scoring rules are versioned in
`rationale_protocol_id`. If the record is requested in only one arm, the treatment is
"reasoning configuration plus rationale elicitation," not reasoning configuration alone.

## 8. Receipt and reporting additions

Each receipt binds:

```yaml
reasoning_condition_id: string
reasoning_condition_sha256: string
provider_reasoning_parameters: canonical mapping
rationale_visibility: string
rationale_protocol_id: string | null
reasoning_attempt_summary:
  total_reasoning_tokens: integer | null
  empty_after_reasoning_count: integer
  reasoning_length_retry_count: integer
  truncated_count: integer
diagnostic_labels: [typed diagnostic record]
```

Paper tables and leaderboards report the resolved reasoning condition beside the model,
primary outcome, cost, and mute/truncation diagnostics. A claim such as "reasoning improves
strategy" requires the paired intervention above. Otherwise use descriptive wording such as
"under the declared reasoning-enabled configuration."

## 9. Interpretation rules

The defensible conclusion template is:

> Reasoning is a declared experimental condition and a secondary diagnostic surface, while
> actions and outcomes remain primary. Diagnostic evidence distinguishes objective
> selection, strategic modeling, constraint tracking, and execution when the trace supports
> that distinction.

The following claims are prohibited without additional evidence:

- more reasoning tokens imply better reasoning;
- a visible rationale is the model's faithful causal chain-of-thought;
- a cross-model difference identifies the effect of reasoning;
- an empty, reasoning-starved turn is an economic decision; or
- one forced diagnostic label is preferable to `undetermined` when mechanisms cannot be
  separated.

This contract lets reasoning explain behavioral results without allowing explanation quality,
provider telemetry, or harness starvation to replace the behavior being measured.
