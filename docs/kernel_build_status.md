# Kernel build status

**Branch:** `zeyu/kernel-r1` (from `c8176ad`) · **Writer:** one at a time · **Not pushed yet**

Ordered work, one commit per block, focused tests per block, full suite at a milestone.
Update this file in place; it is a status board, not a plan generator.

| Block | Work | State | Commit |
|---|---|---|---|
| 1 | Remove self-referential process guards (SHA pins, plan-heading guards, AST/export-shape tests) | done | `2c79bd6` |
| 2 | R3 episode scheduler: phase schedule, frozen observations, typed verdicts, evidence | done | `6250ce6` |
| 3 | Housing vertical slice through the kernel (shape risk) | next | |
| 4 | Contract-decision comment for PR #7 (not blocking code) | | |
| 5 | `ToolInvocation` evidence records (tau3 blocker) | | |
| 6 | `reasoning_condition`, ID grammar, locked vocabularies | | |
| 7 | R6 `exchange_v1` old/new parity | | |
| 8 | Split into reviewable PRs (R1 / R2 / R4-5 / R3) | | |

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
  profile; `CallAttempt*` additive-compatibility path vs rename.

## Known risks carried

- Housing's strategic content is unverified under binding-hold semantics
  (naive 0.852 vs adaptive 0.849); the deviation audit must be rerun before
  any paid model run on that case.
- Canonical JSON determinism is currently a property of the implementation
  (CPython float repr, no unicode normalization), not a written spec with
  golden vectors.
