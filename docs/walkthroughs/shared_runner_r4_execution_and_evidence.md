# Walkthrough: Shared-runner R4 model execution and evidence

R4 is the first stage that may call an external model. It implements the R3 asynchronous
response-source boundary with explicit logical actions, action attempts, provider calls, tool
invocations, retry ownership, typed failures, cost accounting, canonical events, and
content-addressed artifacts.

The generic implementation is `src/aeread/shared_runner/execution.py`. The native one-action
smoke family and CLI are in `src/aeread/shared_runner/smoke.py`. Executable contracts are in
`tests/test_shared_runner_execution.py` and `tests/test_shared_runner_smoke.py`.

## Complete R1-R4 path

```text
R1 authoring records and registered family plugin
  -> R2 resolved, canonical, hashed RunPlan and PlanCell
  -> write exact run_plan.json before external work
  -> resolve one cell, case, family, profiles, prompts, pricing, and plugin
  -> create one EpisodeAttempt and append-only EvidenceStore
  -> R3 phase scheduler emits one DecisionRequest per logical action
  -> R4 minimal_chat creates explicit ActionAttempt and ProviderCall
  -> durably append provider_call_started before invoking the client
  -> canonicalize provider response, usage, cost, and failure status
  -> R3 family parser, legality, transition, termination, and outcome
  -> append their canonical boundary events and verify the evidence chain
```

The generic kernel never imports the smoke family or branches on a family ID. The smoke family
is a small native plugin with one private value and one non-negative integer offer. It exists to
prove instrumentation and integration, not to support a scientific economic claim.

## Evidence ordering

A successful one-action `minimal_chat/1.0` attempt produces this causal event order:

```text
phase_instance_started
logical_action_started
action_attempt_started
provider_call_started
provider_call_succeeded
action_attempt_succeeded
action_parsed
action_legality_checked
logical_action_succeeded
transition_applied
phase_instance_succeeded
episode_terminated
family_outcome_recorded
```

Every event is flushed before control returns. Its payload is stored under a SHA-256 artifact
path; the event records that path and digest. Events carry a total sequence, prior event hash,
and their own hash. `verify_chain()` validates sequence, links, event content, and every payload
artifact. `audit_reconciliation()` requires exactly one start and exactly one terminal success,
failure, agent-action failure, or `outcome_unknown` event for every started logical action,
action attempt, provider call, and tool invocation.

## Retry and failure ownership

The profile must declare `max_action_attempts`, retryable conditions, session behavior, and
`sdk_retries: 0`. One provider invocation creates one `ProviderCall`. A declared retry creates a
new `ActionAttempt` and a new `ProviderCall`; a provider client never retries invisibly.

Provider cancellation, timeout, transport loss, or an unexpected interruption after
`provider_call_started` is recorded as `provider_call_outcome_unknown`: the runner cannot prove
that the remote service performed no billable work. Its parent attempt is then operationally
failed for an explicitly declared retry, or closed as `outcome_unknown` when execution stops. A
known provider rejection is recorded as failure and is retried only when both the adapter
classifies it as retryable and the profile explicitly lists its condition. Usage-based cost is
recorded before a cost-budget excess terminates the action, so incurred cost cannot disappear.
Profile cost limits are enforced independently while the receipt also retains the run-wide
total.

`ToolExecutor` applies the same write-before-side-effect and terminal-or-unknown rule. The
`minimal_chat/1.0` harness itself forbids tools and persistent memory; tool records support later
tool-aware harnesses without pretending a tool call is an action retry.

## OpenAI Responses adapter

The adapter follows the official [Create a model response](https://developers.openai.com/api/reference/resources/responses/methods/create/)
contract, sends `store: false`, disables SDK retries, records the resolved model and usage, and
binds the request to the base URL declared in the agent profile. The live smoke path pins
`https://api.openai.com/v1`; an environment variable cannot silently redirect it.

As checked on 2026-08-26, the official [GPT-5 nano model page](https://developers.openai.com/api/docs/models/gpt-5-nano)
identifies `gpt-5-nano-2025-08-07` as the pinned snapshot, supports the Responses API, and lists
standard prices of $0.05 per million input tokens, $0.005 per million cached input tokens, and
$0.40 per million output tokens. Those values are a versioned input to the smoke plan rather
than a hidden global assumption: the profile records both the pricing identifier and the
SHA-256 digest of the exact canonical pricing record, and execution verifies both before a
call. Recheck and repin pricing before later experiments.

## OpenRouter DeepSeek adapter

`OpenRouterChatClient` uses OpenRouter's OpenAI-compatible Chat Completions endpoint but does
not treat a marketplace model name as a sufficient model pin. The DeepSeek diagnostic path
requests `deepseek/deepseek-v4-flash-0731` and seals the canonical endpoint revision
`deepseek/deepseek-v4-flash-20260731`, provider `DeepInfra`, and `fp8` quantization. It permits
only that provider, disables fallbacks and SDK retries, requires every requested parameter,
and rejects the response unless OpenRouter's opt-in routing metadata identifies exactly one
successful attempt on the sealed provider and canonical model.

The profile also seals temperature `0`, top-p `1`, seed `71001`, a 512-token output ceiling,
low reasoning effort, and a strict JSON action schema. The adapter requires response usage and
OpenRouter's reported cost; the evidence retains the raw response so the reported charge can
be reconciled independently against the pinned route prices. The 2026-08-26 DeepInfra endpoint
snapshot lists $0.08 per million prompt tokens, $0.016 per million cached prompt tokens, and
$0.18 per million completion tokens. Recheck the live endpoint and repin both its identity and
prices before a later experimental run.

## Claude Code diagnostic adapter

`ClaudeCodePrintClient` permits an authenticated Claude Code installation to exercise the same
R4 provider boundary without serializing a subscription credential. It resolves and hashes the
actual executable, seals its version and digest into the request, and rechecks the digest before
every call. The command uses safe mode, one print turn, an exact model snapshot, no tools, no
session persistence, no fallback model, a JSON schema, and a provider-enforced dollar ceiling.
The adapter rejects a missing schema, runtime drift, non-JSON result, hidden multi-model usage,
or a missing structured output.

Claude Code print mode does not expose temperature, top-p, seed, or a configurable output-token
limit. The plan therefore declares those limitations, the transport records temperature and
top-p as unavailable, and `max_output_tokens` records the resolved model default rather than a
control the CLI did not apply. This path is suitable for R4 instrumentation admission, but its
provider-owned prompt/runtime envelope is not equivalent to a direct API paper run.
The pinned $1/M input, $0.10/M cache-read input, and $5/M output rates were checked against
Anthropic's official [Claude pricing](https://platform.claude.com/docs/en/about-claude/pricing)
page on 2026-08-26.

## Commands

Zero-cost integration proof from a source checkout:

```bash
PYTHONPATH=src python -m aeread.shared_runner.smoke \
  --provider fake \
  --output /tmp/aeread-shared-runner-smoke
```

One live call with the pinned cheapest GPT-5 model:

```bash
export OPENAI_API_KEY=...  # do not commit or print this value
PYTHONPATH=src python -m aeread.shared_runner.smoke \
  --provider openai \
  --model gpt-5-nano-2025-08-07 \
  --revision gpt-5-nano-2025-08-07 \
  --output /tmp/aeread-shared-runner-openai-smoke
```

One live call with the pinned DeepSeek/OpenRouter route:

```bash
export OPENROUTER_API_KEY=...  # set locally; do not commit or print this value
PYTHONPATH=src python -m aeread.shared_runner.smoke \
  --provider openrouter \
  --model deepseek/deepseek-v4-flash-0731 \
  --revision deepseek/deepseek-v4-flash-20260731 \
  --output /tmp/aeread-shared-runner-openrouter-deepseek-smoke
```

One live call through an authenticated Claude Code installation using the pinned Haiku snapshot:

```bash
PYTHONPATH=src python -m aeread.shared_runner.smoke \
  --provider claude_code \
  --model claude-haiku-4-5-20251001 \
  --revision claude-haiku-4-5-20251001 \
  --output /tmp/aeread-shared-runner-claude-smoke
```

After installing the package, the equivalent entry point is `aeread-shared-smoke`; the
`PYTHONPATH=src python -m ...` form above is for an uninstalled source checkout.

The CLI prints only run/cell/attempt identities, the family outcome, recorded cost, and evidence
directory. Provider requests and raw responses remain content-addressed local artifacts; no API
key is serialized.

## Verified live admission

On 2026-08-26 the exact Claude command above completed one sealed cell through R1-R4. The
resolved model `claude-haiku-4-5-20251001` submitted offer `8`; parsing, legality, transition,
termination, and outcome all succeeded. The runner recorded 2,000 input tokens, 795 output
tokens, and $0.005975 cost under a $0.01 ceiling. Recomputing the cost from the pinned $1/M input
and $5/M output prices produces the same $0.005975. All 13 event links and payload artifacts
verified and every started entity reconciled exactly once. The non-secret durable admission
summary is [`../evidence/shared_runner_r4_claude_smoke_2026-08-26.json`](../evidence/shared_runner_r4_claude_smoke_2026-08-26.json).

The pinned OpenRouter command also completed one sealed cell on 2026-08-26. OpenRouter selected
DeepInfra on the canonical `deepseek/deepseek-v4-flash-20260731` endpoint with routing attempt
`1`; the model submitted valid offer `5`. The runner recorded 66 input tokens, no cached input,
165 completion tokens, and a charged cost of $0.0000346302. The nominal pinned-price
recomputation is $0.00003498, equal to OpenRouter's reported upstream inference cost; the
charged cost is exactly 99% of that amount, so the admission retains both rather than claiming
equality. All 13 event links and payload artifacts verified and every started entity reconciled
exactly once. The non-secret durable admission summary is
[`../evidence/shared_runner_r4_openrouter_deepseek_smoke_2026-08-26.json`](../evidence/shared_runner_r4_openrouter_deepseek_smoke_2026-08-26.json).

OpenRouter reported 172 reasoning tokens while reporting 165 completion tokens. Because those
fields are internally inconsistent, reasoning usage is retained only as provider diagnostic
metadata; actions and outcomes remain the primary evidence. The full raw response, including
provider-returned reasoning text, remains in the local content-addressed evidence and is not
committed.

## Exact R4 boundary

R4 proves that the runner can call a model without hiding retries, side effects, outcomes, or
cost. It does not yet provide an `EvaluationReceipt`, crash resume, deterministic replay,
scoring, coverage reconciliation, Exchange compatibility, or Housing semantics. Those remain
R5-R7. The smoke result is an instrumentation admission result, not a paper measurement.
