# aucarena adapter — status

Branch `zeyu/aucarena-adapter`. Last verified 2026-09-02. Milestone 3 of 3 (scripted
harness + end-to-end + replay); milestones 1-2 (cases/environment/scorer/goldens) landed
earlier on this branch.

## What the adapter claims

For each of the five QC Gate-2 goldens (`docs/aucarena_adapter_spec.md` section 5), a
scripted, all-`"rule"`-or-`"scripted"`-bidder auction runs deterministically end to end
through the real kernel phase scheduler (`aeread.shared_runner.scheduler.run_episode`), with
every bid-legality, bid-recording, and hammer-determination rule delegated to hand-vendored,
provenance-headed copies of upstream `jiangjiechen/auction-arena`'s own pure functions
(`_vendored_upstream.py`) — never reimplemented from spec prose. It declares four
measurement leaves, never one blended number (`docs/aucarena_adapter_spec.md` section 2):

| Leaf | Verifier family | Reference kind | Scope | Declared |
|---|---|---|---|---|
| `aucarena_budget_invariant` | `rule_constraint` | `state_invariant` | trajectory | always |
| `aucarena_bid_legality` | `rule_constraint` | `constraint_satisfaction` | trajectory | always |
| `aucarena_hammer_rule` | `rule_constraint` | `temporal_property` | trajectory | always |
| `aucarena_profit_vs_field` | `comparative` | `head_to_head` | terminal_state | always; `invalid_measurement` when the roster's field is empty (golden 5) |

No `objective_reference` leaf is declared: per the P21 row in both
`docs/verifier_taxonomy.md` §13 and `docs/problem_bound_case_audit.md`, profit and TrueSkill
do not solve the auction policy game, so `aucarena_profit_vs_field` stays a head-to-head
comparison against a *named, declared* frozen rule-bidder field — never a universal
auction-skill score.

Milestone 3 adds two more claims, both new this milestone:

1. **Sealed evidence.** The shipped `ScriptedAucArenaHarness` (`src/aeread_families/
   aucarena/harness.py`) optionally records every served bid decision into a real
   `EvidenceStore` — a hash-chained, tamper-evident `bid_decision_served` event per decision,
   keyed by the scheduler's own `phase_instance_id`/`logical_action_id`. Two full episodes
   (goldens `successful` and `invalid_unauthorized`) each produce their own independently
   sealed evidence generation, verified with `verify_chain()`, `seal()`, and a fresh
   `EvidenceStore.audit_existing(...).verify_seal()` — not merely an in-memory claim.
2. **Offline replay, byte-identical.** `src/aeread_families/aucarena/replay.py` records an
   episode's raw decision log, JSON-round-trips it, and replays it through a second,
   independent `AucArenaPlugin` instance with zero further policy calls. Because this family
   has no bridge process and no wall-clock content anywhere in its state, the replayed final
   state matches the original **byte-for-byte** (`canonical_json_bytes` equal), not merely in
   content — stronger than `tau3_retail`'s own replay guarantee, which must specifically
   strip per-message timestamps to compare content only.

## Evidence

**Full aucarena suite: 100 passed, 0 failed, 0 skipped** across the six family test files
(`test_aucarena_cases.py` 19, `test_aucarena_vendored_upstream.py` 24,
`test_aucarena_environment.py` 13, `test_aucarena_measurement.py` 16,
`test_aucarena_parity.py` 12, `test_aucarena_replay.py` 16). Zero skips anywhere in this
family — unlike `tau3_retail`, there is no upstream bridge interpreter to be missing: the
pinned item pool is resolved once, at import time (`cases.py`), and nothing at runtime ever
imports upstream or touches the network.

```bash
PYTHONPATH=src pytest tests/test_aucarena_*.py -q
# 100 passed
```

**Full repo suite: 826 passed, 31 skipped, 1 xfailed, 0 failed.** The 31 skips are
pre-existing and unrelated to this family: `rllm` integration tests (`No module named
'rllm'`) and `tau3_retail` tests gated on a pinned upstream tau2-bench Python interpreter
(`$AEREAD_TAU2_BRIDGE_PYTHON`). Re-ran with and without this branch's changes to confirm the
skip set is unchanged by this work.

```bash
PYTHONPATH=src pytest tests/test_shared_runner_smoke.py -q
# 10 passed
```

**Every one of the five goldens replays byte-identically, state and score.**
`tests/test_aucarena_replay.py::test_replay_reproduces_every_golden_byte_identically` is
parametrized over all five (`successful`, `valid_but_poor`, `invalid_unauthorized`,
`malformed_operational`, `degenerate_reference`); for each, `canonical_json_bytes(final_state)`
and every one of the four leaves' recomputed `ScoreEnvelope`s are asserted byte-equal between
the live run and its offline replay — including golden 5's `aucarena_profit_vs_field`
surviving replay as `invalid_measurement`, not silently re-scored as an economic zero
(`test_replay_and_verify_reproduces_the_invalid_measurement_status`).

**Mutation tested, and the result was not what was first assumed.** The original plan was
"tamper one recorded bid, expect `compare_episode_results` to report a soft, typed
mismatch." That is not what happens: because this family's `"simultaneous"` phase mode makes
eligibility for the *next* round state-derived (the current highest bidder and each seat's
withdraw flag, both set by the very bid value under test), corrupting even one well-formed,
still-legal bid from the one seat whose response actually carries information (`"agent"`;
`"rule"` seats' raw responses are accepted but never inspected) changes which seat the
scheduler must request next. `RecordedResponseSource` catches that immediately — surfaced as
`SchedulerContractError` by the kernel scheduler's own response-source exception wrapping —
before the replayed episode can complete at all, let alone reach a state comparison. This is
verified, not assumed (`test_tampering_a_mid_trajectory_bid_is_caught_immediately_not_
silently_replayed`), and is a stronger, earlier-failing integrity property than a
post-hoc state diff would give. `compare_episode_results`'s own comparison logic is proven
separately not to be vacuous with a synthetic, scheduler-free fixture
(`test_compare_episode_results_reports_specific_mismatches_not_one_boolean`) and with two
independently-produced live runs of different goldens
(`test_compare_episode_results_would_report_a_genuine_divergence`).

**Sealed evidence is durable and independently re-verifiable, not just an in-memory claim.**
`test_two_full_episodes_each_produce_independently_sealed_evidence` seals two full episodes'
evidence generations, calls `seal()` twice (idempotent, same seal both times), and opens each
one through `EvidenceStore.audit_existing()` — a fresh, read-only handle, not the writer that
produced it — confirming `verify_seal()` agrees.
`test_sealed_evidence_rejects_further_writes` confirms a sealed generation cannot silently
accept another event.

## Why there is no bridge to provision

Unlike `tau3_retail` (which needs a live, `langchain`/`torch`-loaded upstream `Environment`
to reproduce a policy game the vendored functions alone cannot settle), this family's
scripted-`"rule"`-bidder path is deterministic bookkeeping with no LLM call reachable on it
(`docs/aucarena_adapter_spec.md` section 1, "Governing facts"). The four rules this adapter
must reproduce exactly — bid legality, bid recording/tie-break, hammer determination, and
profit/budget bookkeeping — are vendored as free functions with per-function provenance
headers (`_vendored_upstream.py`), covered directly by hand-computed-trace unit tests
(`tests/test_aucarena_vendored_upstream.py`) and cross-checked against the environment's own
recorded trajectory by an independent recompute (`tests/test_aucarena_parity.py`). There is
nothing left to delegate to a subprocess, and nothing to provision.

## Known limits, stated rather than implied

- **Scripted `"rule"`/`"scripted"` bidders only.** LLM-driven bidders (`plan_strategy` beyond
  `"none"`/`"static"`, belief tracking, learning-from-prior-auction) are not wrapped; they
  require the `langchain`-chained prompt/parse path this adapter deliberately never imports
  (`docs/aucarena_adapter_spec.md` section 7).
- **`aucarena_profit_vs_field` is a head-to-head comparison, not a policy optimum.** Per the
  P21 row in both `docs/verifier_taxonomy.md` and `docs/problem_bound_case_audit.md`, this
  route is `not_demonstrated` for saturation and must stay that way in any paper claim.
- **The scenario corpus is AERead-authored, not an upstream-published task list** — upstream
  ships only a raw 26-item pool and a generator, not an enumerable task set
  (`docs/aucarena_adapter_spec.md` section 1). Growing coverage means authoring more scenario
  records against the same pinned pool, not importing more upstream tasks.
- **`enable_discount` (price cuts after failed-to-sell rounds) and the human-bidder path are
  unvendored.** Every case this adapter admits fixes `enable_discount=False`;
  `validate_payload` rejects any payload that sets it otherwise.
- **No tool-call layer.** Bids are plain typed actions, not `ToolDefinition`-bound calls, so
  the shared-runner tool/state-evidence machinery `tau3_retail` exercises is not exercised by
  this family — sealed evidence here covers the raw decision itself, not a delegated tool
  result.
- **`parity.py` was never built, on purpose (unchanged since milestone 1).**
  `tests/test_aucarena_parity.py` already runs the same two-independent-code-paths comparison
  a shipped module would; a third module would add indirection, not additional coverage.
- **Content-tamper mutation testing on the *hammer/legality path itself* (as opposed to the
  bid values under test) was not separately attempted this milestone** — the discovery above
  (any bid-value tamper cascades into a decision-order mismatch) made the originally-planned
  "tamper and observe a soft state mismatch" test path unreachable for this family's own
  goldens; the comparator's non-vacuity is instead established with synthetic fixtures and
  two genuinely different live runs (see Evidence, above).

## Ledger

No new kernel/runner defect found this milestone. Three pre-existing entries from earlier
milestones remain open in `ledger_entries/aucarena.md` (missing `docs/benchmark_qc.md`;
`build_scorer` receiving no seed-bearing object, worked around by this family persisting
`world_seed` in its own state) — unchanged by this work, not re-litigated here.
