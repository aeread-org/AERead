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

## Scoring-contract migration (kernel_scoring_contract_spec.md, migration milestone 2 of 3)

Branch `zeyu/agenticpay-contract-migration`. Follows
`docs/agenticpay_migration_plan.md`, whose "Seat scope" and "Case conditionality"
sections argue the design below in full; this section records the reasoning
spec section 5.5 requires a human to check, not a repeat of that argument.

### Leaf policy declared in `family_manifest()`

| Leaf id | Scope | `seat_scope` | `case_conditional` |
|---|---|---|---|
| `agenticpay_deal_reached_leaf` | `finalize_time` | `cell` | `False` |
| `agenticpay_surplus_share_leaf` (**primary**, **admission**) | `finalize_time` | `subject_seat` | `False` |
| `agenticpay_contract_legality_leaf` | `finalize_time` | `cell` | `True` |

No leaf is `deferred`: every scorer in `measurement.py` is
`evaluation_class="deterministic"` arithmetic over the verified re-executed
episode's own terminal state / round trace, or a bridge call that only
re-validates *this* episode's own already-submitted contract text (never a
separate run, never a judge/rater verdict). There is no artifact any leaf is
waiting on, so no `deferred_artifact` field is ever populated.

### Why `agenticpay_surplus_share` is primary

The manifest's coarse, family-level `primary_estimand` was already
`"agenticpay_bilateral_surplus_share"` — a singular, role-neutral label, never
`"...buyer_surplus_share"` or `"...seller_surplus_share"`. Only a surplus-share
leaf is the `maximize`d, bounded `[0, 1]` quantity that wording, and the
manifest's `optimum_lower_bound`/`optimum_upper_bound`, describe.
`agenticpay_deal_reached` and `agenticpay_contract_legality` are rule/constraint
gates over the negotiation's mechanics (did it conclude; did every attempted
submission satisfy its declared bounds), not the substantive outcome quality
the family's headline number is meant to report — and `agenticpay_deal_reached`
is in fact the *simplest* of the three to compute (one boolean read off
`terminal["reason"]`), so choosing surplus-share as primary is deliberately
not "the one that was easiest" (the forbidden reasoning spec section 3 names).

Before this milestone, "surplus share" was two always-on, role-specific leaves
(`agenticpay_buyer_surplus_share`/`agenticpay_seller_surplus_share`), each
published on every case regardless of which seat a real evaluation cell
actually tests. Both `buyer` and `seller` are independently `testable` in this
manifest's `roles` block, so neither leaf id was ever a safe stand-in for "the"
primary: a cell testing the seller would have its real result sitting in
`agenticpay_seller_surplus_share`, an admission leaf that was never declared as
admission, while `agenticpay_buyer_surplus_share` silently reported the
scripted opponent's own share instead. Ruling R12 names this precisely: "one
value exists for each seat, and a summed or blended two-seat number is not the
estimand." The fix collapses both into the one leaf actually declared —
`agenticpay_surplus_share`, `seat_scope="subject_seat"` — scored for whichever
seat the plan's `SeatContext.subject_seats` singleton actually names, via the
exact same, unchanged `_score_surplus_share` formula/degeneracy rules
(`measurement.py`'s `score_surplus_share`). `agenticpay_buyer_surplus_share`/
`agenticpay_seller_surplus_share` themselves are **not removed**: they remain
exactly as they scored before, kept for `replay.py`'s own pre-existing,
independent `ReplayScoreResult` diagnostic (out of this migration's scope,
spec section 5) and for the golden/fixture tests that already exercise their
formula directly — they are simply no longer declared in the manifest, so
`__call__` never emits them as finalize-time leaves.

Ruling R12 rule 3 (an agent profile id may need mapping to an upstream policy
id) does not apply to this leaf: unlike negarena's bridge-settled
`score_seat_outcome` (which needs an `opponent_policy_id` to call
`NegarenaBridge.settle`), neither side's surplus share depends on which policy
sits in the opponent's seat — `_score_surplus_share` reads only
`family_case`/`terminal`. No profile-id-to-policy-id mapping is declared, and
`__call__` correctly never reads `seat_context.profile_by_seat` for this leaf.

### Why these leaves gate admission

`admission_leaf_ids = (agenticpay_surplus_share_leaf,)` — the primary alone,
matching both reference migrations' own convention (govsim: primary alone;
collusion: primary alone):

- `agenticpay_deal_reached` is a diagnostic, not a gate: a `"timeout"`
  negotiation is a genuine, meaningful failure the family wants to *report*,
  not a case whose receipt should be excluded outright — and a `"timeout"`
  already routes `agenticpay_surplus_share` itself to `invalid_measurement`
  (reason `"no_agreement_reached"`), so gating on `agenticpay_deal_reached`
  separately would be redundant with the primary's own admission behavior.
- `agenticpay_contract_legality` is likewise a diagnostic, and is
  independently *required* to be excluded from admission by ruling R13 rule 1
  (a `case_conditional` leaf may not be `primary_leaf_id` or in
  `admission_leaf_ids`, since both must exist for every execution admitted
  under one static manifest, which a case-conditional leaf by definition does
  not). A rejected submission is informative (per-round detail already
  retained in `metrics`), not grounds by itself to exclude a receipt whose
  surplus-share leaf still scored `ok`.

### Case conditionality (ruling R13)

`agenticpay_contract_legality` is declared `case_conditional=True`; the other
two are not. `measurement.py::build_contract_legality_leaf` already returns
`None` whenever `not is_contract_mode(family_case)` (the 3 basic price-only
cases; present for the 25 contract-mode cases) — `AgenticpayBilateralPlugin
.inapplicable_leaf_ids` is a direct restatement of that identical predicate,
never a second, independently-maintained decision. A basic-case receipt
carries `inapplicable_leaf_ids=("agenticpay_contract_legality_leaf",)` and is
still `included` when `agenticpay_surplus_share` scores `ok` (R13 rule 4: an
omitted diagnostic is a disposition, not a cell exclusion).

### Deferred leaves: none

Covered above under "Leaf policy" — no leaf waits on any not-yet-existing
artifact.

## Conformance enrollment (kernel_scoring_contract_spec.md, migration milestone 3 of 3)

Branch `zeyu/agenticpay-contract-migration`. `("agenticpay.bilateral",
"0.1.0")` is removed from `_NOT_YET_MIGRATED_TRUSTED_KEYS` in
`tests/test_shared_runner_scoring_contract.py` and added to that module's
`_BRIDGE_GATED_ENROLLED_FAMILY_VERSIONS` instead — this family's fixtures
require the real, provisioned upstream bridge (like govsim's), so they run
in their own per-test-skippable `test_agenticpay_obeys_the_scoring_contract`
rather than inside the always-on
`test_every_registered_family_obeys_the_scoring_contract`. Two separate
same-case paired-history pairs are supplied (one contract-mode, one basic),
not one four-fixture list: `agenticpay_surplus_share`'s own declared
reference legitimately varies its `source_sha256` by case (the ZOPA bound
vs. the contract config), so mixing case kinds in one protocol-test call
would fail the kernel's leaf-identity-stability check for a reason that has
nothing to do with ruling R13's case-conditional behavior it is meant to
prove. Both pairs, and the sensitivity-witness round-trace pair for
`agenticpay_contract_legality`, were verified constructible against the
real bridge directly before being wired into the test.

Also fixed as part of reaching this milestone (all case-independent, none
change scoring arithmetic):

- `family_manifest()` now declares `trajectory_outcome_paths=("/round_trace",)`
  (ruling R9) and `scoring.reference_provider_ids` (derived from
  `measurement.py`'s own leaf builders via a new
  `_measurement_reference_provider_ids()` helper, mirroring
  `negarena.environment`'s identical convention) — without the latter,
  `resolve_run_plan` never reserves an `ImplementationPin` for any of this
  family's leaf validity-domain predicates, reference implementations, or
  scorers, and `EvaluationReceipt`'s own pin/implementation cross-check
  rejects every sealed receipt outright. A latent gap from Milestone 1/2;
  this family had never been driven through a real `RunPlan`/finalizer
  before this milestone, so nothing had ever exercised it.
- A kernel bug in `task/evaluation.py`'s `_replay_family_trajectory`:
  `plugin.initial_state(family_case, run=None)` called the hook by keyword,
  raising `TypeError` for any family (this one among them) whose second
  parameter is named `cell` instead of `run` — every other hook call in
  that function is already positional, matching `scheduler.py`'s own live
  call. This blocked replay (and so finalize) for every "cell"-named family
  on this base; none had reached this code path before this migration.
- `ScriptedAgenticpayBilateralHarness` seals only its own convenience event
  and had never produced evidence `replay_family_scoring_input` can
  replay. `EvidenceRecordingAgenticpayHarness`
  (`tests/test_agenticpay_bilateral_replay.py`) reproduces
  `AttemptExecutor`'s own generic event vocabulary around the same scripted
  script, mirroring govsim's identically-purposed
  `EvidenceRecordingGovsimHarness`, and is what makes replay — and so both
  the finalizer test below and the protocol test's fixtures — reachable for
  this family at all.

### A receipt now comes back

`tests/test_agenticpay_bilateral_replay.py::test_finalize_wires_agenticpay_to_the_shared_family_finalizer`
drives one real, bridge-backed, contract-mode episode
(`agenticpay.bilateral.realistic.s01_beauty_product`) through
`task.evaluation.finalize_family_execution` and asserts the returned
`EvaluationReceipt` carries `status="ok"`, `inclusion_status="included"`,
and exactly the three declared finalize-time leaf ids
(`agenticpay_deal_reached_leaf`, `agenticpay_surplus_share_leaf`,
`agenticpay_contract_legality_leaf`) with `primary_leaf_id` equal to the
declared `agenticpay_surplus_share_leaf` — this family had never produced
an `EvaluationReceipt` before this milestone.
