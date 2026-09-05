# negarena adapter — status

Branch `zeyu/negarena-adapter`. Last verified 2026-09-02.

## What the adapter claims

For each pinned NegotiationArena scenario (`buy_sell_game` or `ultimatum`), the
adapter drives a scripted, provider-free transcript through the real
shared-runner scheduler (`aeread.shared_runner.scheduler.run_episode`) and
reproduces upstream's own deterministic settlement, never reimplementing it.
Every parse/legality/settlement call inside `NegarenaPlugin`'s hooks delegates
to `NegarenaBridge`, a subprocess bridge into the pinned upstream checkout —
the adapter computes no trade/valuation/split arithmetic of its own. It
publishes two separately-labelled measurement leaves:

| Leaf | Verifier family | Evaluation class | Reported |
|---|---|---|---|
| `negarena_seat_outcome` (primary) | `comparative` | `deterministic` | once per seat (RED, BLUE) |
| `negarena_agreement_reached` (diagnostic) | `rule_constraint` | `deterministic` | once per episode |

Both leaves check termination first: a `malformed_action`/`invalid_measurement`
terminal reason yields `status="invalid_measurement"`, `primary=None` for
*both* leaves — never a computed zero payoff, never a silent "no agreement".

Milestone 3 adds the scripted harness (`harness.py`) and offline replayer
(`replay.py`) on top of the milestones 1-2 environment/scorer/goldens:

- `ScriptedNegarenaHarness` serves one recorded raw response per
  `(phase_id, seat_id)` request from the real scheduler and records one
  `negarena_decision_served` event per served decision into a genuine
  `EvidenceStore`. Unlike `tau3_retail`'s harness, it drives no `ToolRuntime`
  — negarena's Mode B phase graph declares `needs_tools: False`
  (`environment.py`'s `family_manifest`); the only artifact to script is the
  raw text response itself.
- `run_scripted_negarena_episode` (`harness.py`) is the one production entry
  point for driving a scripted episode toward `finalize_family_execution`:
  it drives `run_episode` with `ScriptedNegarenaHarness`, then always seals
  the complete generic evidence lifecycle
  (`record_full_evidence_lifecycle` — phase/transition/terminal/outcome
  events, matching what the shared kernel's own `MinimalChatExecutor` would
  append live) before returning, so a caller cannot reach a terminated
  episode's evidence with only `negarena_decision_served` events sealed
  (docs/negarena_codex_triage.md Finding 3, closed for real in
  docs/negarena_fix_verification.md — the sealing call used to be made only
  by a test module's own helper, not by any production code path).
- `replay.py` extracts the ordered decision log (`record_episode`), round-trips
  it through plain JSON (`RecordedEpisode.to_json`/`from_json`), and replays it
  through `run_episode` again with a fresh `NegarenaBridge`/`NegarenaPlugin`
  instance and zero model/provider calls (`RecordedResponseSource` makes no
  call of its own). It then compares every phase-instance state hash, the
  terminal record, the outcome, and the final state, and independently
  recomputes both measurement leaves from the replayed episode.

## Evidence

**89 of 89 negarena-family tests pass with the bridge genuinely wired in — not
skipped.** Running the entire family test file set
(`test_negarena_environment.py`, `test_negarena_cases.py`,
`test_negarena_harness.py`, `test_negarena_parity.py`,
`test_negarena_measurement.py`, `test_negarena_kernel_finalizer.py`,
`test_negarena_provisioning.py`) plus `test_shared_runner_smoke.py` with
`AEREAD_NEGARENA_BRIDGE_PYTHON` unset collects 46 pass / 43 skip (every skip
is the same "upstream NegotiationArena Python interpreter unavailable"
reason — bridge tests skip cleanly when unprovisioned, `test_negarena_provisioning.py`'s
5 tests never need the bridge at all and always run); with the bridge
interpreter exported, the same 89 tests collect as **89 passed, 0 skipped, 0
failed**. Per-file collection: environment 21, cases 22, harness 11, parity 3,
measurement 14, kernel_finalizer 3, provisioning 5, shared-runner smoke 10.

```bash
export AEREAD_NEGARENA_BRIDGE_PYTHON="/Users/sunzeyu/Documents/econ benchmark/bridges/negarena-venv/bin/python"
PY="/Users/sunzeyu/Documents/econ benchmark/AERead/.venv/bin/python"
"$PY" -m pytest tests/test_negarena_environment.py tests/test_negarena_cases.py \
  tests/test_negarena_harness.py tests/test_negarena_parity.py \
  tests/test_negarena_measurement.py tests/test_negarena_kernel_finalizer.py \
  tests/test_negarena_provisioning.py tests/test_shared_runner_smoke.py -q
```

**Two full episodes driven through the real scheduler, both sealed.**
`test_negarena_harness.py` runs golden-1 of `buy_sell` (8 logical actions,
terminal reason `accepted`, RED realizes 0.0 / BLUE realizes 20.0, agreement
1.0) and golden-1 of `ultimatum` (2 logical actions, terminal reason
`accepted`, RED realizes 60.0 / BLUE realizes 40.0) purely through
`ScriptedNegarenaHarness` + `run_episode` — never a hand-wired plugin loop.
Each episode's `EvidenceStore` is sealed (`seal().event_count` equals the
episode's `logical_action_count`), closed, reopened with `resume=True`, and
`verify_chain()`/`verify_seal()` both confirm the seal survives a reopen.

**Replay reproduces state and score byte-identically, with zero further
provider calls.** For both goldens, the completed episode's decision log is
extracted, round-tripped through plain JSON text (proving replay never reuses
the original run's in-memory objects), and replayed through `run_episode`
again with an independent bridge/plugin instance. `compare_episode_results`
confirms every phase-instance pre/post state hash, the terminal record, the
outcome, and the final state match byte-for-byte
(`canonical_json_bytes(original.X) == canonical_json_bytes(replayed.X)` for
`final_state`/`terminal`/`outcome`), and both measurement leaves recomputed
from the replayed episode match the original run's leaves exactly. Negative
tests confirm a reordered/truncated recording is rejected rather than silently
replayed: `RecordedResponseSource` raises `ReplayError` directly, and the same
mismatch surfacing through the real scheduler is wrapped in
`SchedulerContractError` without losing the underlying message.

**Component parity (milestone 2, re-verified here).** `test_negarena_parity.py`
runs golden-1 of each family twice — once through the adapter
(`NegarenaPlugin.parse_action`/`legal`/`step`), once as a direct bridge call to
upstream's own `after_game_ends()` via `NegarenaBridge.replay_transcript`,
which never touches the adapter's environment module — and both agree
byte-identically on `player_outcome`.

## What it costs to run

The full 89-test bridge-backed run took 315.28s on a heavily shared, 10-core
machine at load average ~10-12 (many concurrent unrelated test runs). Each
bridge call spawns a fresh subprocess that imports the pinned upstream
checkout (and transitively `openai`/`anthropic`) from scratch, so this number
is dominated by import cost under contention, not settlement work; treat it as
an upper bound rather than a clean per-call baseline (tau3's own status doc
notes the same effect at ~1.95s/call under lower contention).

## Known limits, stated rather than implied

- **Tonight's corpus is 6 scenarios (3 `buy_sell` + 3 `ultimatum`)** — an
  integration gate, same posture as tau3's 18-task pilot, not a population
  coverage claim (spec section 6).
- **`trading_game` is out of scope.** Its `game_objects` reuse is expected to
  be direct, but its interface/prompt code is unread (spec section 6).
- **The bridge venv is required even for "pure" arithmetic modules** — there
  is no zero-dependency import path into any upstream negarena code at this
  pin (see `ledger_entries/negarena.md`'s poisoned-import-chain entry).
- **Replay still calls the bridge, not only "zero provider calls."** Spec
  section 5's Replay bullet describes "zero network, zero bridge-venv call";
  this is not what is implemented or achievable without contradicting spec
  section 3's "settlement computation ... executed via the bridge, never
  reimplemented" rule, which was already locked in at milestone 2.
  `NegarenaPlugin.parse_action`/`legal`/`build_scorer` delegate to
  `NegarenaBridge` identically whether the episode is live or replayed, so a
  replay still spawns bridge subprocesses. What *is* proved, and is the
  guarantee `docs/shared_runner_portability_contract.md` §5.4 actually names
  ("a provider-free replay must pass all deterministic fields before paid
  model runs"), is zero further *model/LLM* calls — `RecordedResponseSource`
  makes no call of its own, and negarena's family plugin never had a model
  provider in it to begin with. Flagging this as a spec-wording deviation
  rather than a defect: the narrower guarantee is the one both the portability
  contract and this milestone's own task description ("zero provider calls")
  actually require.
- **No judge-dependent leaf exists.** Both leaves are fully deterministic
  given a transcript; no judge-provenance fields are needed in either
  `VerifierSpec` (spec section 6).
- **`is_exportable_id`'s legal `visibility_policy`/`SeatSpec.role` vocabulary**
  for a two-seat adversarial dialogue is unconfirmed — the same open question
  tau3 already raised (its UNRESOLVED Q3), not re-litigated here.
- **Upstream's ultimatum outcome reduction is asymmetric between seats**
  (RED reports absolute final holdings, BLUE reports a delta from its own
  initial holdings) — numerically coincidental for this corpus because every
  ultimatum case gives the responder seat a zero initial endowment. See
  `ledger_entries/negarena.md` for the full upstream-code citation. Fixed in
  the review pass (docs/negarena_review_claude.md WARNING-2):
  `validate_payload` now rejects any ultimatum case whose BLUE seat starts
  with a nonzero `money_token` balance, so a future scenario-grid edit that
  would silently reintroduce the asymmetry fails at Gate-1 admission instead
  of scoring two incomparable numbers under the same `head_to_head` estimand.
- **Malformed-response detection now covers every required tag, not only
  the trade tag.** `negarena_bridge_driver.py`'s `parse_response` op checks
  upstream's own `get_tag_indices` for every tag the pinned parser
  unconditionally extracts, before calling `parser.parse()` — closing a gap
  where a response missing e.g. `<player answer>` used to parse "clean"
  with a garbage value instead of surfacing as `malformed_action`
  (docs/negarena_review_claude.md CRITICAL-1).
- **`NegarenaScorer.__call__` (the shared kernel's generic
  `build_scorer(family_case)(outcome, evidence_refs=...)` call site,
  `finalize_family_execution` et al.) surfaces neither declared leaf as a
  real score — this is a stated limit, not a claimed working path.** The
  kernel expects exactly one `ScoreEnvelope` per call
  (`runner_defect_ledger.md` D-15: "the only production call site that
  invokes `build_scorer` assumes a single-`ScoreEnvelope`-per-family
  contract that no real family plugin satisfies"), while negarena publishes
  two typed leaves (`negarena_seat_outcome`, `negarena_agreement_reached`).
  Per D-15's ruling ("no adapter may add a `__call__` that silently picks
  one leaf as primary... satisfying the kernel by contradicting the
  measurement design is not a fix"), `__call__` does not compute a real
  per-seat/agreement score at all: it always reports the primary leaf
  (`negarena_seat_outcome`) as a typed `invalid_measurement`
  ("`negarena_kernel_finalizer_lacks_seat_pairing_context`") because the
  generic call site carries no seat/opponent-pairing context real per-seat
  scoring needs, and it never returns anything for the second leaf
  (`negarena_agreement_reached`) at all — that leaf is simply absent from
  this path, not fabricated. So a caller reaching `finalize_family_execution`
  through this call site alone sees 0 of 2 leaves scored; the real per-seat
  and agreement scores are only ever produced by calling
  `score_seat_outcome`/`score_agreement_reached` directly (as
  `tests/test_negarena_harness.py` and `replay.py::score_replayed_episode`
  already do), which is what every negarena test that asserts a real score
  value uses. Whether `finalize_family_execution` should instead seal a leaf
  *vector* is the kernel-owner decision D-15 defers; not this branch's to
  resolve.
- **`RecordedEpisode` binds a replay to case/cell *content* identity, not to
  the implementation that produced it.** `record_episode`/`replay_episode`
  (`replay.py`) now reject a mismatched case or cell by content hash
  (`case_sha256`/`cell_sha256`) and by `case_id`/`cell_id`
  (docs/negarena_fix_verification.md's remaining Finding-2 gap, closed).
  What is still not sealed into a `RecordedEpisode` is which
  `ImplementationPin`s (family plugin/scorer/harness/runtime versions) were
  live in the `RunPlan` at record time: `PlanCell` itself carries no pins
  field at all — pins exist only on `RunPlan`
  (`aeread.shared_runner.resolver.RunPlan.implementation_pins`) — and
  `record_episode`/`replay_episode`'s signatures take a `cell`/`case`, never
  a `RunPlan`. Binding a recording to the implementation pins that produced
  it would mean threading a `RunPlan` (or its pin tuple) through both
  functions, a signature change with no precedent anywhere in this
  repository: `tau3_retail`'s own `RecordedEpisode` binds neither content
  hashes nor pins. Deciding whether replay-record provenance should include
  implementation pins (and, if so, at what layer) is a shared
  evidence/replay-contract question, not a negarena-only choice — flagging
  it here rather than silently narrowing what "replay reproduces the
  original execution" is proven to mean.
