# agenticpay.bilateral adapter — status

Branch `zeyu/agenticpay-adapter`. Last verified 2026-09-02.

## What the adapter claims

For the pinned bilateral topology (`single_buyer_product_seller`) of SafeRL-Lab/AgenticPay
(commit `1ff4e1a2686eac6a07ff559df6d50329c6fd9f69`), it reproduces upstream's deterministic
`step()`/scoring result exactly, by delegating every price/contract extraction, legality
check, and scoring formula to the pinned upstream checkout across a subprocess bridge —
never reimplementing any of it. It publishes four separately-labelled measurement leaves
rather than one blended number, plus upstream's own `GlobalScore`/`BuyerScore`/`SellerScore`
carried forward verbatim as a labeled compatibility artifact (spec section 2):

| Leaf | Verifier family | Evaluation class | Declared when |
|---|---|---|---|
| `agenticpay_deal_reached` | `rule_constraint` | `deterministic` | always |
| `agenticpay_buyer_surplus_share` | `objective_reference` | `deterministic` | always (`invalid_measurement` when the ZOPA denominator is degenerate) |
| `agenticpay_seller_surplus_share` | `objective_reference` | `deterministic` | always (same degeneracy rule) |
| `agenticpay_contract_legality` | `rule_constraint` | `deterministic` | only for contract-mode (realistic-split) cases |

This milestone (3 of 3) adds the scripted harness, an end-to-end run through the real
kernel scheduler with sealed evidence, and an offline replayer:

- `harness.py`'s `ScriptedAgenticpayBilateralHarness` serves a fixed, ordered script of
  buyer/seller negotiation messages through the real `run_episode` scheduler — the same
  code path a live run would use, not a hand-wired call into `environment.py`'s hooks.
  This family declares no tool-call surface at all (`tools.py`: none — both seats emit one
  plain message string per turn), so unlike `tau3_retail.harness.ScriptedTau3RetailHarness`
  (which delegates to a `ToolRuntime` for its own evidence), this harness seals one
  `agenticpay_bilateral_decision_served` event per served decision directly through
  `EvidenceStore.append_event` — the same primitive `aeread.shared_runner.family_evaluation`
  already uses for its own non-tool evidence.
- `replay.py` mirrors `tau3_retail.replay`'s `RecordedEpisode`/`RecordedDecision`/
  `RecordedResponseSource`/`replay_episode`/`compare_episode_results` shape. A recorded
  episode replays with **zero further scripted-policy calls**: every seller-phase round
  still independently re-invokes the real upstream bridge (`AgenticpayBridge.replay_round`,
  which reconstructs upstream's environment from scratch and replays its own history), so a
  genuine domain divergence would surface in the replayed terminal/outcome, not be silently
  skipped.

## Evidence

**Two full episodes verified end to end with sealed evidence and byte-identical replay:**

1. A two-round, price-only negotiation (`agenticpay.bilateral.basic.task1`) that converges
   to `$100` and agrees.
2. A one-round, contract-mode negotiation (`agenticpay.bilateral.realistic.s01_beauty_product`)
   that agrees on a full `<contract>` payload.

Both were run through the real `PluginRegistry`/`run_episode` path with a live
`EvidenceStore`: every served decision is sealed (4 events for episode 1, 2 for episode 2 —
one per logical action, matching `EpisodeResult.logical_action_count` exactly), and
`evidence.audit_reconciliation()` succeeds after `evidence.seal()`.

Episode 1 was then replayed from a **JSON-round-tripped** `RecordedEpisode` (forcing the
replay to depend only on plain, serialized text, never on reusing the original run's
in-memory objects), through a **second, independent** `AgenticpayBridge`/plugin instance.
The result matches the original run's `canonical_json_bytes(final_state)`
**byte-for-byte**, not merely content-equal:

```python
assert canonical_json_bytes(replayed.final_state) == canonical_json_bytes(original.final_state)
```

This is a genuine strengthening over `tau3_retail.replay`'s own guarantee, not just a
different assertion: tau3.retail's upstream re-stamps a fresh wall-clock `timestamp` on
every message it replays, forcing that adapter's replay to compare message *content* only
(`replay._strip_message_timestamps`). This adapter's pinned upstream checkout and bridge
driver introduce no wall-clock time, randomness, or other per-call nondeterminism anywhere
in the replayed path (verified directly: no `datetime`/`time.time`/`random`/`uuid` in
`agenticpay/core.py`, the pinned `single_buyer_product_seller` env files, or this adapter's
own `agenticpay_bridge.py`/`agenticpay_bridge_driver.py`), so raw state equality holds
without stripping anything.

All four declared leaves were also recomputed from the replayed episode and matched the
originally-computed values (`agenticpay_deal_reached=1.0`; both surplus-share leaves equal
to the original run's; `agenticpay_contract_legality=1.0` for the contract-mode episode).
Unlike tau3.retail's DB-equivalence leaf (which needs a fresh `Tau2Bridge.evaluate_env` call
against the replayed database), every leaf here is a pure function of
`EpisodeResult.terminal`/`round_trace`, so `score_replayed_episode` makes no bridge call of
its own.

**Suite: 787 passed, 31 skipped, 1 xfailed** for the full repository, with
`AEREAD_AGENTICPAY_BRIDGE_PYTHON` pointed at the provisioned bridge venv. The 31 skips are
other families' bridges not provisioned in this session (tau2/tau3-bench, and similar) —
unrelated to this family, and none of them mention `agenticpay`.

This family's own five test files plus the required smoke-regression check:

| File | Passed |
|---|---|
| `tests/test_agenticpay_bilateral_cases.py` | 20 |
| `tests/test_agenticpay_bilateral_environment.py` | 9 |
| `tests/test_agenticpay_bilateral_measurement.py` | 20 |
| `tests/test_agenticpay_bilateral_replay.py` (new this milestone) | 12 |
| `tests/test_shared_runner_smoke.py` (required regression check) | 10 |
| **Total** | **71, 0 failed** |

Run with:

```bash
export AEREAD_AGENTICPAY_BRIDGE_PYTHON="/Users/sunzeyu/Documents/econ benchmark/bridges/agenticpay-venv/bin/python"
python -m pytest tests/test_agenticpay_bilateral_cases.py tests/test_agenticpay_bilateral_environment.py \
  tests/test_agenticpay_bilateral_measurement.py tests/test_agenticpay_bilateral_replay.py \
  tests/test_shared_runner_smoke.py -q
```

## Why the bridge needs provisioning

AERead's own venv deliberately does not carry `agenticpay`'s runtime dependencies
(`loguru`, `numpy` — see `docs/agenticpay_adapter_spec.md`'s governing facts). Without a
provisioned bridge interpreter, every bridge-gated test in this family **skips rather than
fails** — a green run then means "the fidelity tests didn't run," not "the adapter matches
upstream." A pre-provisioned venv already exists at
`/Users/sunzeyu/Documents/econ benchmark/bridges/agenticpay-venv`; provision a fresh one with:

```bash
tools/agenticpay_bridge/provision.sh
export AEREAD_AGENTICPAY_BRIDGE_PYTHON=<printed path>
AEREAD_AGENTICPAY_BRIDGE_REQUIRED=1 pytest   # fails if a fidelity test skips
```

## Known limits, stated rather than implied

- **No `parity.py` / `test_agenticpay_bilateral_parity.py` yet.** Spec section 5 also
  describes a component-level "reproducibility under re-execution" parity harness (run the
  identical scripted trajectory twice through independent bridge subprocess invocations,
  require byte-identical `info`/`state.metadata`), mirroring `tau3_retail.parity`'s module.
  This milestone's scope was scripted harness + end-to-end + replay; parity is not built.
  Note that `replay.py`'s own live-vs-replay comparison already demonstrates a related but
  distinct property (a *recorded* trajectory reproduces byte-identically when re-executed
  through the scheduler) — it does not substitute for parity's "same script, run twice fresh,
  independent subprocesses, no recording in between" determinism check.
- **Only 2 of the 28 pinned bilateral cases were run end to end this milestone** (one basic,
  one realistic/contract-mode), chosen to exercise both scoring branches
  (`is_contract_mode` true/false) and the contract-legality leaf. The remaining 26 cases were
  validated at the payload/importer level in Milestones 1–2
  (`tests/test_agenticpay_bilateral_cases.py`) but not driven through a full scripted episode
  here.
- **Replay's byte-identical guarantee rests on an absence, not a proof by construction.**
  This adapter's pinned upstream and bridge code were checked directly for
  `datetime`/`time.time`/`random`/`uuid` and found to have none reachable from the replayed
  path (see "Evidence" above); this is an empirical fact about the current pinned commit, not
  a structural guarantee that would catch a future upstream change reintroducing
  nondeterminism. `compare_episode_results` would surface such a regression as
  `final_state_matches=False` the next time these tests run.
- **Mode C (multi-party topologies) remains entirely deferred**, as declared in the spec
  (section 6) since Milestone 1 — unchanged this milestone.
- **`docs/benchmark_qc.md` still does not exist on this branch/`main`**, already logged in
  `ledger_entries/agenticpay.md` from Milestone 1; re-checked this session (still absent), no
  new ledger entry needed.

## No new kernel/runner defects found this milestone

`EvidenceStore.append_event`, `run_episode`, and `PluginRegistry` all behaved exactly as
documented for a family with no tool-call surface; nothing required a workaround. The one
pre-existing ledger entry (the missing `docs/benchmark_qc.md`) was re-verified, not
re-derived, and needed no update.
