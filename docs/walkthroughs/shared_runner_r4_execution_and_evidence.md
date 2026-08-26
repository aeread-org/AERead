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

After installing the package, the equivalent entry point is `aeread-shared-smoke`; the
`PYTHONPATH=src python -m ...` form above is for an uninstalled source checkout.

The CLI prints only run/cell/attempt identities, the family outcome, recorded cost, and evidence
directory. Provider requests and raw responses remain content-addressed local artifacts; no API
key is serialized.

## Exact R4 boundary

R4 proves that the runner can call a model without hiding retries, side effects, outcomes, or
cost. It does not yet provide an `EvaluationReceipt`, crash resume, deterministic replay,
scoring, coverage reconciliation, Exchange compatibility, or Housing semantics. Those remain
R5-R7. The smoke result is an instrumentation admission result, not a paper measurement.
