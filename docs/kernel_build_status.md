# Kernel build status

**Branch:** `zeyu/kernel-r1` (from `c8176ad`) · **Writer:** one at a time · **Not pushed yet**

Ordered work, one commit per block, focused tests per block, full suite at a milestone.
Update this file in place; it is a status board, not a plan generator.

| Block | Work | State | Commit |
|---|---|---|---|
| 1 | Remove self-referential process guards (SHA pins, plan-heading guards, AST/export-shape tests) | done | `2c79bd6` |
| 2 | R3 episode scheduler: phase schedule, frozen observations, typed verdicts, evidence | done | `6250ce6` |
| 3 | Housing vertical slice: the real plugin driven by the real scheduler | done | `1e8ef26` |
| 3b | Close the gaps an independent review found in the scheduler | done | `afefe16` |
| 4 | Contract-decision comment for PR #7 (not blocking code) | done | `f977b7a` |
| 5 | `ToolInvocation` evidence records (tau3 blocker) | done | `7d38c75` |
| 6 | `reasoning_condition`, ID grammar, exportable-id rule | done | (this commit) |
| 7 | R6 `exchange_v1` old/new parity (offline; seats not slot-mediated) | done | (this commit) |
| 8 | Split into reviewable PRs (R1 / R2 / R4-5 / R3) | next | |

## Standing rules

- The kernel imports no family and branches on no `family_id`.
- Records are added when a real consumer needs them, never speculatively. The
  authoring surface stays as small as the runner and the paper actually use.
- Deleted process scaffolding does not come back: no git-SHA pins in tests, no
  plan-document heading guards, no AST/alias/export-count shape tests.
- Every block: self-review, focused tests, an independent read-only review of
  the diff, then one commit whose message states what changed and why.

## Deferred deliberately

- `SamplingPlan` / `AnalysisPlan` public façade — collapse the 59
  `_PlannedIdentityRecord` micro-specs behind two records once the analysis
  layer has a real consumer.
- Analysis DAG language (graph/node/port/edge, Holm families) — no consumer in
  the current experiment plan; keep internal or drop.
- Open rulings for Chenyu: `user_simulator` as a seat kind vs a counterpart
  profile; `CallAttempt*` additive-compatibility path vs rename; whether
  housing's `contract_status` should stop listing the action-failure
  disposition as unresolved now that the runner owns that vocabulary and
  housing carries the ruled disposition.

## Known risks carried

- Housing's strategic content is unverified under binding-hold semantics
  (naive 0.852 vs adaptive 0.849); the deviation audit must be rerun before
  any paid model run on that case.
- Canonical JSON determinism is currently a property of the implementation
  (CPython float repr, no unicode normalization), not a written spec with
  golden vectors.
- `PhaseSpec.mode` is recorded and logged but does not change scheduling: a
  phase declaring `single` may still return many slots. Either the runner
  enforces it or the field is documented as descriptive.
- Adapters are awaited one seat at a time even in a simultaneous phase.
  Correct, but a real provider will make a wide phase N times slower than it
  needs to be.
- Seats cannot be enumerated before an episode runs: a plugin only reveals a
  phase's slots once the state is in that phase. A resolver that needs every
  seat up front must read them from the case.
- Exchange seats are not slot-mediated: the compatibility wrapper runs the
  legacy transcript whole, so exchange parity is proven provider-free only.
  Live exchange seats need the engine restructured, which is a decision rather
  than a task.
