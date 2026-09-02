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
- `replay.py` extracts the ordered decision log (`record_episode`), round-trips
  it through plain JSON (`RecordedEpisode.to_json`/`from_json`), and replays it
  through `run_episode` again with a fresh `NegarenaBridge`/`NegarenaPlugin`
  instance and zero model/provider calls (`RecordedResponseSource` makes no
  call of its own). It then compares every phase-instance state hash, the
  terminal record, the outcome, and the final state, and independently
  recomputes both measurement leaves from the replayed episode.

## Evidence

**74 of 74 negarena-family tests pass with the bridge genuinely wired in — not
skipped.** Running the entire family test file set
(`test_negarena_environment.py`, `test_negarena_cases.py`,
`test_negarena_harness.py`, `test_negarena_parity.py`,
`test_negarena_measurement.py`) plus `test_shared_runner_smoke.py` with
`AEREAD_NEGARENA_BRIDGE_PYTHON` unset collects 40 pass / 34 skip (bridge tests
skip cleanly when unprovisioned); with the bridge interpreter exported, the
same 74 tests collect as **74 passed, 0 skipped, 0 failed**. Per-file
collection: environment 18, cases 22, harness 7, parity 3, measurement 14,
shared-runner smoke 10.

```bash
export AEREAD_NEGARENA_BRIDGE_PYTHON="/Users/sunzeyu/Documents/econ benchmark/bridges/negarena-venv/bin/python"
PY="/Users/sunzeyu/Documents/econ benchmark/AERead/.venv/bin/python"
"$PY" -m pytest tests/test_negarena_environment.py tests/test_negarena_cases.py \
  tests/test_negarena_harness.py tests/test_negarena_parity.py \
  tests/test_negarena_measurement.py tests/test_shared_runner_smoke.py -q
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

The full 74-test bridge-backed run took 278.5s on a heavily shared, 10-core
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
  ultimatum case gives the responder seat a zero initial endowment, but would
  diverge for a future scenario that does not. See
  `ledger_entries/negarena.md` for the full upstream-code citation; no
  AERead-side fix is needed for tonight's corpus.
