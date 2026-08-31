# Walkthrough: Shared-runner R3 provider-free phase scheduling

R3 consumes one sealed `PlanCell` and its `CaseManifest`, then executes a family plugin's
declarative phase graph without importing a provider or a concrete family. The implementation
is `src/aeread/shared_runner/scheduler.py`; the conformance fixtures are in
`tests/test_shared_runner_scheduler.py`.

```text
PlanCell + CaseManifest + exact family plugin + async response source
  -> verify sealed cell/case identity and logical-action budget
  -> validate family payload and the complete reachable PhaseSpec graph
  -> construct deterministic Episode and PhaseInstance identities
  -> resolve eligible actors and role-specific schemas
  -> isolate observations, responses, parser inputs, legality inputs, and transition state
  -> enforce phase and case logical-action budgets
  -> apply typed TransitionResult records and declared next-phase edges
  -> call terminal and outcome hooks
  -> return immutable EpisodeResult
```

## Simultaneous and sequential phases

For `simultaneous`, R3 computes and freezes every participant's observation from independent
copies of the same pre-phase state before requesting any action. Responses are then requested
in deterministic actor order, peer actions remain hidden, and the complete action mapping is
passed to exactly one family `step` call. A malicious or accidental mutation inside one
`observe` hook cannot change a peer's view or the transition state.

For `sequential`, each actor observes the state produced by the prior actor's transition. Each
action therefore has its own family `step` boundary. A transition may end the episode or select
a declared next phase before all currently eligible actors act.

`single` is the one-actor bundled form and rejects any eligibility result other than one seat.

## Typed action boundary

The family parser must return `ParseResult`; legality must return `LegalityResult`. A valid
action becomes an `ActionEnvelope`. A malformed or illegal action follows the declared policy:

- `reject` stops execution with a `SchedulerContractError` before `step`;
- `family_defined` passes a typed invalid envelope to `step`, allowing the family to implement
  its declared no-op, penalty, or forfeit semantics without adding a family branch to the kernel.

## Pre-provider failures

R3 rejects changed case content, mismatched cell identities, incomplete seat assignments,
duplicate or unknown actors, missing role schemas, duplicate/unreachable/missing phases,
undeclared transitions, noncanonical states or observations, and exhausted action budgets.
Those checks occur through a provider-free response source, so R4 can preflight the same path
with a fake adapter before a paid call.

## Exact boundary

R3's response source is an asynchronous dependency injection point, not a model adapter. R3
does not create `ActionAttempt`, `ProviderCall`, tool, event, artifact, retry, cost, or timing
records. R4 must reconcile those side effects and return a canonical response through this
interface. A direct provider function passed to R3 would bypass the evidence contract and is
not a valid shared-runner model execution.

