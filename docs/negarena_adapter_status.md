# negarena adapter — status

Branch `zeyu/negarena-contract-migration`, stacked on
`zeyu/kernel-r12-seat-context` (ruling R12). Last verified 2026-09-06.

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

## Leaf policy (kernel_scoring_contract_spec.md, migration milestone 2 of 3)

`family_manifest()`'s `measurement` block now declares this family's leaf
policy explicitly (spec section 3), and `NegarenaScorer.__call__` takes a
`FamilyScoringInput` and returns a `FamilyScoreSet` carrying both declared
leaves — the shim that previously always reported `negarena_seat_outcome` as
`invalid_measurement("negarena_kernel_finalizer_lacks_seat_pairing_context")`
and never returned `negarena_agreement_reached` at all (see the retired
"Known limits" entry below, previously citing ledger D-15) is gone. Ruling
R12 (found by this exact family during this migration, per the spec's own
round-3 rulings) supplies what that shim was missing: `FamilyScoringInput`
now carries `seat_context` (`subject_seats`, `profile_by_seat`), populated by
the kernel from the plan's evaluation block and the resolved cell, never
from the live episode (R2 still holds).

| Leaf | Scope | Seat scope | Primary | Admission |
|---|---|---|---|---|
| `negarena_seat_outcome_leaf` | `finalize_time` | `subject_seat` | **yes** | **yes** |
| `negarena_agreement_reached_leaf` | `finalize_time` | `cell` (default) | no | no |

**Why `negarena_seat_outcome` is primary.** It is this family's own
already-declared `primary_estimand` (`family_manifest()`'s `measurement`
block, present since before this milestone) and the adapter's own stated
headline number: this module's docstring opens with it as leaf 1, and both
this status doc's original leaf table and `measurement.py` label leaf 2
explicitly "diagnostic". It is not the leaf that was easiest to reach through
the pre-migration seam — if anything the opposite is true: leaf 2
(`negarena_agreement_reached`) needs only `scoring_input.outcome`'s
termination reason and no bridge call at all, while leaf 1 needs a real
settlement call (`NegarenaBridge.settle`, upstream's own `after_game_ends()`)
plus the seat-context machinery ruling R12 added — the choice tracks the
family's own declared estimand ("what did *this* seat realize under its own
valuation, against the specific opponent it was paired with" — this module's
own docstring), not convenience.

**Why it alone gates admission.** `negarena_agreement_reached` is a
`rule_constraint` diagnostic, already labelled as such in this module's own
docstring before this milestone, and its reason for existing separately
predates this migration too: "so a degenerate no-agreement episode is never
silently averaged into the payoff leaderboard as a 'loss'"
(`docs/verifier_taxonomy.md` section 9). Whether an episode ended in
agreement is a measured (`status="ok"`) fact regardless of which way it
went — a `REJECT`/iteration-cap termination is not grounds to exclude the
receipt, only to record the fact honestly. Only an
`invalid_measurement`/`malformed_action` termination invalidates both
leaves at once (both scorers share that one check), so in practice
admission today tracks whether the episode could be measured at all, never
which way the negotiation went.

**Why `negarena_seat_outcome_leaf` is `seat_scope="subject_seat"`, and
`negarena_agreement_reached_leaf` is not.** Leaf 1's estimand is inherently
per seat — "what did *this* seat realize", one value for RED, a different
one for BLUE, never a summed/blended two-seat number (this module's own
docstring, and ruling R12's own problem statement, which names this exact
family: "found by the negarena migration, 2026-09-06"). Under R12 rule 2,
for the ordinary case (one seat is the tested model, the other a fixed
scripted/pinned opponent — every case in today's six-scenario corpus,
`cases.py`), `seat_context.subject_seats` has exactly one entry, so
`__call__` scores that one subject seat via the existing
`score_seat_outcome` method and reports its own value as `primary`; the
kernel's `_enforce_subject_seat_primaries` then verifies `primary ==
utility_by_seat[subject]` directly (`tests/test_negarena_measurement.py`'s
`test_call_returns_both_declared_leaves_for_a_single_subject_seat` asserts
this identity itself, not merely trusts the kernel to catch a violation).
Zero subject seats or several with no declared `subject_reduction` are
`invalid_measurement("no_subject_seat")`/`invalid_measurement
("ambiguous_subject_seat")` respectively — no case in today's corpus pairs
the tested seat against itself, so no `subject_reduction` is declared; a
future self-play negarena case would need that decision made explicitly,
which is out of this migration's scope. `negarena_agreement_reached_leaf`'s
estimand ("did the episode end via an in-band `ACCEPT`") is a single fact
about the whole episode, not a function of which seat is the tested
subject — both seats experience the same termination — so it stays the
default `seat_scope="cell"`.

**Opponent identity: an agent profile id is not an upstream policy id.**
`score_seat_outcome`'s `opponent_policy_id` parameter is score-time metadata
only (`primary.metadata["opponent_policy_id"]`), never consumed by
`bridge.settle`'s arithmetic — but it still must name a real upstream policy
identity, never the kernel's own profile id
(`seat_context.profile_by_seat[opponent_seat]`). `measurement.py`'s
`OPPONENT_PROFILE_TO_POLICY_ID` is a small, pinned, deterministic mapping
(today: `{"negarena_scripted_v1": "scripted"}`, matching every existing call
site's hardcoded `opponent_policy_id="scripted"` — `replay.py`, `parity.py`,
`tests/test_negarena_harness.py` — and the one `AgentProfile.profile_id`
`tests/test_negarena_kernel_finalizer.py` actually registers). An opponent
profile id absent from this mapping is
`invalid_measurement("unknown_opponent_profile")`, never a guessed policy id.

**Deferred leaves: none.** Both leaves are `evaluation_class="deterministic"`
with no judge, rater, or other not-yet-existing artifact anywhere in their
verifier declarations (`measurement.py`'s `build_*_leaf` functions); neither
waits on an artifact that "may not exist yet" (spec section 4), so both are
declared `scope="finalize_time"` and neither is `scope="deferred"`.

**What this milestone does not touch.** `tests/test_shared_runner_scoring_contract.py`'s
closed-world enrollment (`_NOT_YET_MIGRATED_TRUSTED_KEYS`,
`FAMILY_SCORING_FIXTURES`) needs sealed evidence produced through
`finalize_family_execution`, which is currently blocked by the
finalizer-wiring gap recorded below (`docs/negarena_migration_plan.md`'s
"Baseline failures to fix in milestone 3") — per spec section 5's own
ordering (item 4, wiring to the finalizer, comes after item 2/3, leaf
policy and `__call__`), enrollment is milestone 3's job, not this one.
`tests/test_shared_runner_scoring_contract.py` was not edited in this
migration.

## Evidence

**Updated for this milestone (2026-09-06): 96 collected, 94 passed, 2 failed,
0 skipped with the bridge genuinely wired in — not stale.** The "89 of 89" figure
below this paragraph predates both the kernel path reorg
(`src/aeread/shared_runner/execution.py` -> `.../task/execution.py`) and a
second, unrelated baseline defect this migration found but did not fix (see
`docs/negarena_migration_plan.md`'s "Baseline: not clean before the fix");
neither is reproducible on this base without accounting for both. Running
the entire family test file set (`test_negarena_environment.py`,
`test_negarena_cases.py`, `test_negarena_harness.py`,
`test_negarena_parity.py`, `test_negarena_measurement.py`,
`test_negarena_kernel_finalizer.py`, `test_negarena_provisioning.py`) plus
`test_shared_runner_smoke.py`, with both bridge env vars unset, collects
**47 passed, 49 skipped, 0 failed** — every skip carries the identical,
documented "upstream NegotiationArena Python interpreter unavailable"
reason (checked directly, not assumed: no skip masks an old calling
convention, the exact trap the reference migration's worked example warns
about). With the bridge genuinely exported, the same suite collects **96
collected, 94 passed, 2 failed, 0 skipped**: the 2 failures are
`test_negarena_kernel_finalizer.py::test_finalize_family_execution_does_not_crash_and_seals_a_typed_receipt`
and `::test_finalize_family_execution_seals_the_complete_evidence_lifecycle`,
both pre-existing, both unrelated to this milestone's leaf-policy/`__call__`
work (they fail identically before and after this milestone's changes, with
`ValueError: family replay action lacks one successful attempt` raised
*before* `NegarenaScorer.__call__` is ever reached — see
`docs/negarena_migration_plan.md`'s "Baseline failures to fix in milestone 3
(finalizer wiring)" for the full cause and the two test ids). This milestone
added 7 new tests (1 manifest leaf-policy test, 6 `NegarenaScorer.__call__`
tests covering both leaves, the single/other/zero/several-subject-seat
cases, and the unmapped-opponent-profile case), all passing; 89 + 7 = 96.

```bash
export AEREAD_NEGARENA_UPSTREAM_ROOT="/Users/sunzeyu/Documents/econ benchmark/upstream-negarena"
export AEREAD_NEGARENA_BRIDGE_PYTHON="/Users/sunzeyu/Documents/econ benchmark/bridges/negarena-venv/bin/python"
PY="/Users/sunzeyu/Documents/econ benchmark/AERead/.venv/bin/python"
"$PY" -m pytest tests/test_negarena_environment.py tests/test_negarena_cases.py \
  tests/test_negarena_harness.py tests/test_negarena_parity.py \
  tests/test_negarena_measurement.py tests/test_negarena_kernel_finalizer.py \
  tests/test_negarena_provisioning.py tests/test_shared_runner_smoke.py -q
```

**Below this point, the original milestone-1/pre-reorg claim, kept for
history.** "89 of 89 negarena-family tests pass with the bridge genuinely
wired in — not skipped." Running the entire family test file set
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
- **RESOLVED by the scoring-contract migration (see "Leaf policy" above).**
  This entry previously read: "`NegarenaScorer.__call__` (the shared
  kernel's generic `build_scorer(family_case)(outcome, evidence_refs=...)`
  call site, `finalize_family_execution` et al.) surfaces neither declared
  leaf as a real score" — the kernel used to expect exactly one
  `ScoreEnvelope` per call (`runner_defect_ledger.md` D-15), while negarena
  publishes two typed leaves, so `__call__` always reported the primary leaf
  as a typed `invalid_measurement`
  (`"negarena_kernel_finalizer_lacks_seat_pairing_context"`) and never
  returned the second leaf at all. `kernel_scoring_contract_spec.md`
  replaces that single-envelope call site with
  `plugin.build_scorer(family_case)(scoring_input,
  evidence_refs=scoring_input.evidence_refs)` returning a `FamilyScoreSet`,
  and ruling R12 supplies the seat/opponent-pairing context D-15's ruling
  said the kernel — not the adapter — must carry. `NegarenaScorer.__call__`
  now returns both declared leaves for real through this exact call site;
  `score_seat_outcome`/`score_agreement_reached` remain the single source of
  truth `__call__` composes (spec section 5), and are still exercised
  directly by every negarena golden test.
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
