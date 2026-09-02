# econagent adapter — status

Branch `zeyu/econagent-adapter`. Last verified 2026-09-02.

## What the adapter claims

For three pinned, reduced-scale EconAgent (ACL 2024; `tsinghua-fib-lab/ACL24-EconAgent`,
commit `bfada09`) scenarios, it drives upstream's real, non-LLM `complex` scripted policy
end to end — through the REAL AERead shared-runner path
(`aeread.shared_runner.scheduler.run_episode`, not a hand-wired plugin-hook loop — see
"What milestone 3 added" below) — and publishes a **vector** of three separately-labelled
measurement leaves, never one blended number, with **no `objective_reference` and no
optimum claim of any kind**:

| Leaf | Verifier family | Reference kind | Claim |
|---|---|---|---|
| `econagent_budget_identity` | `rule_constraint` | `state_invariant` | Per-agent, per-month, the six-term budget identity (income, tax, lump-sum redistribution, consumption, saving interest, inventory) holds exactly — every term read from upstream's own executed state, never recomputed independently. |
| `econagent_tax_bracket_arithmetic` | `rule_constraint` | `constraint_satisfaction` | Every recorded `tax_paid` matches upstream's own `PeriodicBracketTax` bracket computation, re-invoked live — never a reimplemented piecewise formula. |
| `econagent_macro_trajectory` | `comparative` | `baseline_delta` (mode: descriptive/baseline-only) | GDP-proxy, price level, unemployment-proxy time series. Diagnostic only — no comparator, no optimum, no pass/fail meaning. |

EconAgent itself defines no reward and no task-success criterion (`simulate.py` only dumps
a dense log); this spec deliberately never manufactures one. See
`docs/econagent_adapter_spec.md` section 2 for the full verifier declaration and section 6
for the stated scope limits.

## What milestone 3 added

Milestones 1-2 (cases, environment, measurement, goldens, parity) all exercised
`EconAgentV1Plugin` by calling its hooks directly in a hand-wired loop — never through the
real scheduler. Milestone 3 built:

- **`harness.py`** — `ScriptedEconAgentHarness`, a provider-free `ResponseSource`. Every
  `agent_i` seat submits the same acknowledgment every month regardless of observation (per
  milestone-1 correction 4, the real `[labor, consumption]` decision is computed once per
  month inside the persistent bridge session), so unlike `tau3_retail`'s harness there is no
  tool/action content to script at all.
- **`tests/test_econagent_e2e.py`** — both `econagent.pilot.small10x12.seed0` and `.seed1`
  driven end to end through `run_episode`/`PluginRegistry.resolve_manifest`, plus an
  importer-determinism check (running the importer twice, and against the committed case
  files, produces byte-identical output for all three scenario ids).
- **`replay.py`/`tests/test_econagent_replay.py`** — offline replay with the real upstream
  bridge subprocess never spawned. See "Evidence" and "Known limits" below for what this
  actually proves and where its one real caveat is.
- **A real defect this pass's own first scheduler-driven run exposed and fixed**: `cases.py`
  and `environment.py` had set the per-episode logical-action budget to `episode_length`
  (months) rather than `n_agents * episode_length` (one logical action per agent seat per
  month, for this family's `mode="simultaneous"` phase) — undercounting by a factor of
  `n_agents` and undetected through two milestones of hand-wired tests. Fixed in the same
  commit as this milestone, following this spec's own established "reality forces a
  deviation" convention (see the spec's "Milestone 3 correction" section); the three on-disk
  case files were regenerated (`content_sha256` changed as a direct, sole consequence).

## Evidence

**Two full pilot episodes run end to end through the real scheduler**
(`test_econagent_e2e.py`): `small10x12.seed0` and `.seed1`, 10 agents x 12 months each — one
simultaneous phase instance per month, all 10 seats acting in each, 120 logical actions per
episode, terminal reason `episode_length_reached` both times, with genuinely different final
agent states (different `world_seed`).

**Replay reproduces state and score with the real bridge subprocess never spawned**
(`test_econagent_replay.py`, 12 tests). A live 4-agent x 6-month episode's bridge call log
(`start_episode`, `agent_snapshot`, then `(step_month, agent_snapshot)` x 6, then
`dense_log`, `close` — 16 calls) is recorded, round-tripped through plain JSON text, and
replayed through the real scheduler with `EconAgentBridge._spawn` monkeypatched to raise if
ever called — the replay still completes, proving no subprocess is spawned. The replayed
episode's terminal record, outcome, and final-state *content* match the live run's exactly;
all three measurement leaves recomputed from the replay (including
`econagent_tax_bracket_arithmetic`, itself replayed from a separately recorded
`recompute_tax` call log) equal the live run's `ScoreEnvelope`s exactly. A mutation test
(tampering one recorded `step_month` response's `actions` field before replay) confirms the
comparator genuinely detects divergence rather than being vacuously true.

**Suite: 96 econagent-family + smoke tests passed, 0 failed**, with a provisioned bridge
(`bridges/econagent-venv`) and the pinned upstream checkout present:

```
tests/test_econagent_cases.py tests/test_econagent_environment.py
tests/test_econagent_measurement.py tests/test_econagent_goldens.py
tests/test_econagent_parity.py tests/test_econagent_e2e.py
tests/test_econagent_replay.py tests/test_shared_runner_smoke.py
96 passed in 60.60s
```

**Full repository regression check: 812 passed, 31 skipped, 1 xfailed, 0 failed**
(`pytest tests/` from the worktree root) — the 31 skips are other adapters' own
bridge-gated tests for upstream checkouts/interpreters not relevant to this change (tau2,
etc.); nothing econagent-owned skipped.

**Parity** (`test_econagent_parity.py`, built in milestone 2, re-verified here): for each of
the three pilot scenarios, the adapter's per-agent terminal `inventory["Coin"]`, cumulative
`tax_paid`, and dense-log length match an independently-invoked oracle call into the same
pinned upstream engine exactly — never the driver agreeing with itself. A mutation test
(two runs with different `world_seed`s) confirms the comparison detects real divergence.

**Goldens** (`test_econagent_goldens.py`, built in milestone 2, re-verified here): all five
QC Gate 2 instances (successful, valid-but-poor, invalid-or-unauthorized,
malformed-or-operational-failure, degenerate-reference) pass against the real bridge.

## Known limits, stated rather than implied

- **A live episode's raw, byte-exact state never matches its own replay.**
  `EconAgentV1Plugin.initial_state` mints a fresh `uuid.uuid4().hex` `bridge_session_id`
  bookkeeping key on every call — never surfaced through `terminal()`/`outcome()`, never
  causally relevant to any accounting leaf, but part of the full state the scheduler hashes
  and freezes. `replay.py`'s `StateComparison` reports this honestly: raw fields
  (`state_hashes_match`, `final_state_matches`) are `False` by construction on every replay,
  always; only the session-id-stripped content comparison
  (`final_state_content_matches`) — the actual replay guarantee — is asserted as the pass/
  fail signal. Same shape of finding as `tau3_retail/replay.py`'s message-timestamp
  non-determinism, unrelated cause.
- **Seat action is an acknowledgment, not a decision.** Per milestone-1 correction 4, this
  pass's `PhaseSpec`/seat plumbing does not exercise a genuine per-seat decision surface —
  the real `complex_actions` computation happens once per month inside the bridge, not
  through any seat's parsed action. A non-scripted (e.g. LLM) policy seat is out of scope
  here and unaddressed by any test.
- **Only two shapes gated: 10 agents x 12 months and 4 agents x 6 months.** The paper's
  100-agent x 240-month configuration is declared in the manifest but explicitly `not_run`;
  no claim about that scale's behavior is made, including whether 100 simultaneous seats
  work at all through the scheduler (unverified by any test in this family).
- **No optimality or benchmark score, by design.** EconAgent defines no reward or baseline
  policy comparison upstream; `econagent_macro_trajectory` is descriptive-only and supports
  no capability or saturation claim.
- **Gate 2 hard-gate not wired.** The two `rule_constraint` leaves are declared
  `hybrid_gate`-eligible but no invalidating gate currently blocks a budget-identity
  violation from reaching the diagnostic leaves.
- **License posture.** No LICENSE file exists at the upstream repo root; this adapter never
  vendors any upstream file (import-only via bridge `sys.path`), which means zero
  availability guarantee if the upstream repository disappears.

## Open items noted in the ledger, not fixed here

- No static Gate-1/Gate-2 check in the shared kernel cross-validates a case's declared
  `episode.max_logical_actions` against its phases' actual seat cardinality before an
  episode is really run through `run_episode` — the exact gap that let the
  `n_agents`-undercounted budget above survive two milestones of hand-wired tests
  undetected. See `ledger_entries/econagent.md` for the reproduction and a suggested static
  preflight check.
- `AEREAD_ECONAGENT_BRIDGE_REQUIRED` has no enforcement hook generalized beyond tau2 in the
  shared root `conftest.py` — a missing bridge still skips silently rather than failing CI.
  See `ledger_entries/econagent.md`.

## What it costs to run

Unlike `tau2_bridge` (one fresh subprocess per call), this bridge is one persistent
subprocess per episode (spec milestone-1 correction 3, since `complex_actions` needs the
live upstream `env` object's shared RNG stream across the whole episode) — the full
96-test econagent + smoke suite, including every bridge-gated test (goldens, parity,
e2e, replay), runs in about a minute on this machine. There is no multi-hour corpus sweep
here: the entire declared, run corpus is three small scenarios (10x12, 10x12, 4x6), by
design (spec section 1) — the 100x240 paper configuration is declared but never executed.
