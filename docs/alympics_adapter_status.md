# alympics.wac adapter — status

Branch `zeyu/alympics-adapter`. Last verified 2026-09-02. Milestone 3 of 3
(scripted harness + end-to-end + replay); milestones 1-2 (cases,
environment, measurement) landed earlier on this branch.

## What the adapter claims

For the pinned Water Allocation Challenge (`microsoft/Alympics`, commit
`caed7c8c3b8f9de9ac8be1ba54407a51087affc5`), a complete episode — every
round's salary credit, bid legality gate, greedy winner admission,
settlement, and elimination check — can be driven **entirely through the
real kernel scheduler path** (`run_episode`/`AlympicsWacPlugin`, Mode C
simultaneous phase graph), with **zero network calls, zero API keys, zero
LLM calls**: every seat's bid comes from one of four named, deterministic
scripted policies (`proportional`, `aggressive`, `conservative`,
`myopic_need` — `harness.py`), never from a live model, and upstream's own
`_get_salary`/`_check_winner`/`_round_settlement`/`success_bid`/
`unsuccess_bid` execute unmodified via `environment._delegate_round`.

A completed episode's decision log can be **serialized to plain JSON,
reloaded, and replayed offline with zero further provider calls**, and the
replayed run's final state is required to be **byte-identical** to the
original live run's — not merely content-equivalent modulo a documented
non-deterministic field (unlike `tau3_retail`, whose per-message wall-clock
`timestamp` never survives two independent runs identically; this family's
state carries no such field, and the test suite pins exact equality as a
checked fact, not an assumption). All four declared leaves
(`alympics_wac_terminal_wealth`, `alympics_wac_survival`,
`alympics_wac_bid_legality`, `alympics_wac_settlement_exactness`) can be
recomputed purely from a replayed episode plus a replayed baseline episode
— never by re-deriving a baseline through a hand-written formula.

Every bid a scripted harness serves is sealed as one durable,
hash-chained evidence event (`EvidenceStore.append_event`/`.seal()`), the
same append-only mechanism `tau3_retail`'s tool executions use — this
family has no tools to delegate through (`family_manifest`'s
`needs_tools: False`), so a served bid decision is the analogous
"externally observable thing a live provider would have produced."

## Evidence

**Two full episodes driven end-to-end through the harness, each with its
own sealed evidence generation** (`tests/test_alympics_wac_harness.py`):

| Case | Policy assignment | Termination | Round-1 bids (verified) |
|---|---|---|---|
| `reference_baseline` | all `proportional` | `rounds_exhausted` at round 20 | `{alex:24, bob:27, cindy:30, david:33, eric:36}` — matches spec section 4 golden 1 exactly |
| `mixed_policies_a` | `alex:aggressive, bob:conservative, cindy:proportional, david:myopic_need, eric:proportional` | `rounds_exhausted` at round 15, `alex` the sole survivor | `{alex:40, bob:9, cindy:30, david:22, eric:36}`, round-1 winner `alex` |

`mixed_policies_a` exercises all four named policies in one episode. Both
runs are checked for `len(harness.requests) == result.logical_action_count
== evidence.seal().event_count` — the harness never under- or
over-records relative to what the scheduler actually asked for — plus
`evidence.verify_chain()`, `evidence.verify_seal()`, and that
`append_event` after `seal()` raises `EvidenceSealedError`. A third test
runs both cases back-to-back into two independent `EvidenceStore`
generations and confirms neither leaks identity into the other
(`episode_id`, `event_root_sha256` both differ).

**Replay reproduces state byte-identically, not just semantically**
(`tests/test_alympics_wac_replay.py`): both the full 20-round
`reference_baseline` run and the mid-game-elimination `mixed_policies_a`
run are recorded, round-tripped through `RecordedEpisode.to_json`/
`from_json` (a genuine plain-JSON record, not a reused in-memory object),
replayed through a **second, independent** `AlympicsWacPlugin`, and
compared field-by-field: `phase_instance_count_matches`,
`state_hashes_match` (every phase instance's `pre_state_sha256`/
`post_state_sha256`), `terminal_matches`, `outcome_matches`, and
`final_state_matches` are all `True` — confirmed additionally by a direct
`canonical_json_bytes(replayed.final_state) ==
canonical_json_bytes(original.final_state)` byte comparison.

**All four leaves recomputed from replay alone**
(`test_replayed_episode_recomputes_all_four_leaves_using_a_replayed_baseline`,
`test_replay_and_verify_end_to_end_returns_a_matching_report`): the actual
`mixed_policies_a` episode and a second, derived baseline episode (focal
seat `alex` swapped to `proportional` via `harness.baseline_policy_assignment`,
opponent panel held fixed) are each recorded and replayed independently,
and `score_replayed_episode` reproduces `terminal_wealth`, `survival`,
`bid_legality`, and `settlement_exactness` all as `status="ok"` — the
`settlement_exactness` leaf's own shadow-recompute (a second, independent
call into `_delegate_round`) passes against the replayed round log alone,
with no live upstream run in the loop beyond that recompute. For
`reference_baseline` (already all-`proportional`), the baseline policy
assignment for its own focal seat is identical to the actual one, so the
comparative wealth/survival deltas are exactly `0.0` — checked, not
assumed.

**Full family test suite + kernel smoke: 99 passed, 0 failed.**

```
cases        27 passed
environment  21 passed
harness      13 passed   (new, milestone 3)
measurement  15 passed
parity        2 passed
replay       11 passed   (new, milestone 3)
smoke        10 passed   (tests/test_shared_runner_smoke.py)
```

**Full repository suite (all families): 815 passed, 31 skipped, 1 xfailed,
0 failed.** The skips are pre-existing bridge-gated tests belonging to
other families (e.g. tau2/tau3, rLLM integration) whose provisioned
interpreters are not present in this environment; none belong to this
family, and none were introduced or affected by this milestone.

Reproduce:

```bash
cd AERead/.worktrees/alympics
PYTHONPATH=src ../../.venv/bin/python -m pytest \
  tests/test_alympics_wac_cases.py \
  tests/test_alympics_wac_environment.py \
  tests/test_alympics_wac_harness.py \
  tests/test_alympics_wac_measurement.py \
  tests/test_alympics_wac_parity.py \
  tests/test_alympics_wac_replay.py \
  tests/test_shared_runner_smoke.py -q
```

## The four scripted policies (spec section 6: constants finalized here)

Each is a pure, deterministic function of *only* the seat's own
observation — never another seat's state, never this harness's own past
responses (the same leakage boundary spec section 2 leaf 4 requires of
the environment itself, restated from the harness side):

| Policy | Formula | Note |
|---|---|---|
| `proportional` | `3 * requirement` | Fixed every round; verified against spec section 4 golden 1's own bid vector. |
| `conservative` | `1 * requirement` | Fixed every round; spec section 4 golden 2's "valid but poor" policy. |
| `aggressive` | `5 * requirement` | Fixed every round; over-bids `proportional` on a fixed multiplier. |
| `myopic_need` | `requirement * (1 + no_drink)` | Reacts only to this seat's own, already-escalating drought penalty (`no_drink` — upstream's own literal "need" counter). |

`aggressive` and `myopic_need` are this adapter's own choice; spec section
6 explicitly defers their exact constants to implementation time, and no
earlier milestone locks in a different value. **`myopic_need` deliberately
never reads `observation["balance"]`**, which sidesteps an already-ledgered
limitation (`ledger_entries/alympics.md`): `observe()`'s reported balance
lags upstream's own live, salary-credited balance by one round's
`daily_salary`, for every seat, every round. `proportional`/`aggressive`/
`conservative` are balance-independent by construction and are likewise
unaffected.

## Known limits, stated rather than implied

- **Tampering detection at replay time is comparison-based only, not an
  inline oracle.** Unlike `tau3_retail` (whose `step()` independently
  re-executes and cross-checks every recorded tool call against the
  upstream bridge during replay itself), `replay_episode` here has no
  second oracle to compare a recorded bid against — it faithfully replays
  whatever the record says and settles it exactly like a live run would.
  A tampered recorded bid is only caught by explicitly calling
  `compare_episode_results(original, replayed)` against the original run;
  `replay_episode` alone succeeds and produces a different, but internally
  consistent, outcome. Verified directly:
  `test_replay_detects_a_tampered_bid_only_via_comparison_against_the_original`.
- **Baseline comparisons are not auto-derived, but they are now verified.**
  `score_replayed_episode` still requires the caller to already have run
  and replayed a second, baseline episode (`harness.
  baseline_policy_assignment` + a second `ScriptedAlympicsWacHarness`/
  `run_episode`/`replay_episode` pass); this module does not generate,
  cache, or memoize that baseline itself. What changed
  (docs/alympics_fix_verification.md finding 2): `AlympicsWacScorer.
  score_terminal_wealth`/`score_survival` now independently recompute the
  declared baseline episode from the case's own frozen supply schedule/
  personas/starting state and reject a supplied baseline that does not
  reconcile with it exactly — a caller can no longer submit a fabricated
  `baseline_final_players`/`baseline_round_log` and have it accepted merely
  because its `baseline_policy_id` label matches. The bare
  `measurement.score_terminal_wealth`/`score_survival` functions (used
  directly by this family's own unit tests to isolate other gates) still
  only check the label; only the case-bound `AlympicsWacScorer` path — the
  one every production caller actually uses — performs the recompute.
- **A routine CI run does not, by itself, prove this family's
  upstream-fidelity tests ran.** Every environment/measurement/harness/
  parity/replay test module here skips, module-level, when the pinned
  upstream Alympics checkout is absent, and `.github/workflows/ci.yml` runs
  plain `pytest tests/ -q` with neither the checkout provisioned nor
  `AEREAD_ALYMPICS_UPSTREAM_REQUIRED` set (docs/alympics_fix_verification.md
  finding 9). `conftest.py`'s `pytest_terminal_summary` hook can turn a
  matching skip into a failed run, but only when that env var is
  explicitly set — off by default, mirroring the project's own existing
  tau2/tau3 convention, and left that way deliberately: wiring it into
  default CI would mean provisioning a third-party checkout over the
  network, which this family's own provider-free/no-network posture rules
  out. A green default CI run therefore certifies only that
  `test_alympics_wac_cases.py`'s upstream-free tests ran; certifying the
  rest requires explicitly setting `AEREAD_ALYMPICS_UPSTREAM_REQUIRED=1`
  (locally, or in a dedicated CI job that does provision the checkout) —
  the same posture tau2/tau3 already have, not a new inconsistency
  introduced here.
- **Milestone 3 exercises 2 of the 7 grid cells end-to-end**
  (`reference_baseline`, `mixed_policies_a`, plus one derived baseline
  variant of each) — the same pilot-scope posture as tau3's 18-task pilot
  and negarena's 6 scenarios, not a claim of full 7-cell coverage.
- **No provider or model call anywhere in this milestone.** Every "full
  episode" claim is against scripted policies; per P01's audit verdict
  (`docs/problem_bound_case_audit.md`) the family stays `baseline_only` —
  none of this demonstrates anything about live agent behavior or a
  solved policy optimum.
- **Kernel exception-wrapping (ledgered, generic, not alympics-specific):**
  the scheduler wraps any `response_source` exception raised mid-episode
  into `SchedulerContractError`, so `replay.ReplayError` only surfaces
  directly for pre-flight checks (e.g. case-id mismatch, checked before
  `run_episode` is ever called); an exhaustion/ordering error raised from
  inside a live scheduler turn surfaces as `SchedulerContractError` instead
  (the original type is still recoverable via `.__cause__`). See
  `ledger_entries/alympics.md` for the full write-up; this is core kernel
  behavior and was not changed here.

## Open questions for the kernel/spec owner

None new from this milestone. The two open items already on record
(`docs/benchmark_qc.md` unmerged to `main`; `observe()`'s balance-credit
lag) are unchanged and are tracked in `ledger_entries/alympics.md`, not
repeated here.
