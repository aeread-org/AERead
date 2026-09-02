# agenticpay.bilateral adapter — review disposition

Branch `zeyu/agenticpay-adapter`. Reviewer inputs: `docs/agenticpay_review_claude.md`
(present). `docs/agenticpay_review_codex.md` was not present in this worktree at fix-pass
time — no findings from that reviewer to disposition here.

Each finding below was independently re-verified against the code (and, where the finding
concerned bridge-dependent behavior, against the real pinned upstream checkout through the
provisioned bridge venv) before any fix was written.

## CRITICAL

### C1. Case-level `max_logical_actions` undercounts, crashing non-converging negotiations before upstream's own `"timeout"` — **fixed, and the reviewer's suggested magnitude was itself insufficient**

**Verification:** confirmed by reading `cases.py:589`/`:661` (`max_logical_actions =
max_rounds`) and `environment.py:299` (`phases()`'s per-phase cap, same value), and by
empirically driving `agenticpay.bilateral.basic.task1` through the real scheduler + real
bridge with a scripted, never-converging buyer/seller pair. Reproduced the reviewer's
reported crash exactly: `SchedulerContractError` after 10 of the intended 20 rounds.

**Correction to the reviewer's suggested fix:** the review proposed `2 * max_rounds`
(mirroring `housing.py`'s `2 * num_tenants * rounds` convention) and asserted this would let
the negotiation "reach upstream's own round 20." Empirically driving the real bridge with a
budget of `2 * max_rounds` (40) still crashed the scheduler with the same error, one round
short. Root cause: `Task1BasicPriceNegotiation.step`'s own truncation check
(`elif self.current_round >= self.max_rounds`) reads `current_round` *before* that round's
own increment, so with `max_rounds=20`, upstream's own `"timeout"` termination reason does
not appear until `info["round"] == 21` — upstream actually plays `max_rounds + 1` real
rounds, not `max_rounds`, before truncating. Verified directly against the pinned checkout
(commit `1ff4e1a2686eac6a07ff559df6d50329c6fd9f69`) with a scripted 21-round negotiation and
manually widened budgets: `terminal["reason"] == "timeout"` and `terminal["rounds"] == 21`
only once both the case-level budget and each phase's per-seat cap allow a 21st round.
`Task2ClosePriceNegotiation`/`Task3CloseToMarketPriceNegotiation` (the other two basic-split
classes) both subclass `Task1BasicPriceNegotiation` and do not override `step`, so this
applies uniformly to all 28 cases (3 basic + 25 realistic/contract-mode, which also all use
`Task1BasicPriceNegotiation` as their base env class).

**Fix:**
- `cases.py`: `episode.max_logical_actions` is now `2 * (max_rounds + 1)` for both
  `build_basic_case` and `build_realistic_case`, with a comment explaining the `+ 1` and
  citing the empirical verification.
- `environment.py`: `phases()`'s per-phase `max_actions` (both `BUYER_PHASE` and
  `SELLER_PHASE`) is now `max_rounds + 1`, for the same reason.
- `docs/agenticpay_adapter_spec.md`: added this as a third documented upstream quirk
  (alongside the two already recorded for `agenticpay_bridge_driver.py`), so a future reader
  of the `+ 1` in the budget formula is not left to re-derive it.
- Regenerated all 28 checked-in case files under `cases/agenticpay_bilateral/` via
  `cases.run_import` against the pinned upstream checkout, so
  `test_checked_in_cases_match_a_fresh_import` and
  `test_importer_is_byte_identical_across_two_runs` stay green (`pins.json` is unchanged;
  only each case's `episode.max_logical_actions` and its consequent `content_sha256`
  changed).

**Test added:** `tests/test_agenticpay_bilateral_environment.py::
test_golden_non_converging_negotiation_reaches_real_timeout_not_a_scheduler_crash` — drives a
real, never-converging ($90 buyer / $130 seller, $0 tolerance) negotiation for
`max_rounds + 1` rounds through the real scheduler + real bridge and asserts
`terminal["reason"] == "timeout"`, `terminal["rounds"] == max_rounds + 1`, and
`logical_action_count == 2 * (max_rounds + 1)`. Confirmed this test fails
(`SchedulerContractError`) against the pre-fix code before the fix, and passes after.

## WARNING

### W1. Contract-mode "component parity" test is tautological; module/test docstrings overclaimed parity with the basic-mode sibling — **fixed (documentation only, no code defect)**

**Verification:** confirmed by reading `measurement.py:490-499`'s `_score_surplus_share`
contract-mode branch (`share = utility / z_max` where `utility` is read verbatim from
`terminal[f"{side}_utility"]`, itself sourced from upstream's own `state.metadata` via
`_overlay_contract_utilities`) against the basic-mode branch immediately below it (which
independently derives `u_b`/`u_s` from `agreed_price` and never reads upstream's stored
utility fields), and against upstream's own
`Task1_basic_price_negotiation.py:1051-1060`/`:1116` (`_get_contract_score_terms`,
`GlobalScore`). The contract-mode test does read the same numbers upstream itself just used
to compute `GlobalScore`, so its equality assertion holds by construction; it does not
independently verify upstream's MAUT utility calculation, only this adapter's own
weights/discount/`Q`-formula copy. This is a real difference in test strength, not a
scoring/behavior defect — both leaves are still correctly declared, and the spec (`docs/
agenticpay_adapter_spec.md` §5/§9) already discloses that no separate gold oracle exists for
contract-mode utilities.

**Fix:** no code change (measurement.py's scoring itself is correct and intentional — it
must read upstream's own contract utilities rather than reimplementing MAUT scoring, per the
spec's "never reimplement" governing principle). Documentation-only:
- `tests/test_agenticpay_bilateral_measurement.py`'s module docstring now distinguishes the
  two modes' parity strength explicitly instead of claiming one undifferentiated "same class
  of check" as tau3_retail's independent oracle.
- Added a docstring directly on
  `test_surplus_share_leaves_recombine_to_upstream_recorded_global_score_contract_mode`
  stating plainly that it proves this adapter's own formula, not upstream's utility
  calculation, and pointing at replay parity as the actual correctness oracle for
  contract-mode utilities (per spec §5/§9).

No new test needed/possible for this finding's class (it is a claim-strength/documentation
issue, not a behavior a test assertion could newly catch without first pinning an independent
oracle for contract-mode utilities, which is explicitly out of scope per the spec).

## SUGGESTION

### S1. Golden 3 proves "no state mutation" only indirectly through `score_contract_legality`'s own definition — **fixed**

**Verification:** confirmed `tests/test_agenticpay_bilateral_measurement.py`'s
`test_golden_3_invalid_or_unauthorized_contract_offer` asserted only the derived leaf metric
(`legality.metrics["round_1_seller_contract_legal"].value == 0.0`), never the underlying
`round_trace` fields (`seller_contract_before`/`seller_contract_after`) that
`measurement.py:350`'s `score_contract_legality` reads to compute that metric. A future
refactor of that function's "accepted" definition could change what the golden proves without
any assertion in the golden's own body changing.

**Fix:** added a direct assertion in the golden itself:
`round_trace[0]["seller_contract_after"] is None` and
`round_trace[0]["seller_contract_after"] == round_trace[0]["seller_contract_before"]`,
alongside a comment explaining why this is asserted in addition to (not instead of) the
derived leaf check.

## Findings not independently reproduced

None — both non-"what checked out clean" review items (C1, W1) and the one suggestion (S1)
were independently reproduced/confirmed against the code (and, for C1, against the real
bridge) before fixing; no finding was refuted.

## Items the review marked "checked out clean" — re-confirmed, not re-derived

Gate 1 corpus admission, verifier-taxonomy declarations, and replay honesty were all
re-verified to still hold after this fix pass's changes (regenerating the 28 checked-in case
files did not touch any provenance/import-determinism invariant those checks cover — the
full `test_agenticpay_bilateral_cases.py` and `test_agenticpay_bilateral_replay.py` suites
stayed green throughout).

## Test run (post-fix)

```bash
export AEREAD_AGENTICPAY_BRIDGE_PYTHON="/Users/sunzeyu/Documents/econ benchmark/bridges/agenticpay-venv/bin/python"
python -m pytest tests/test_agenticpay_bilateral_cases.py tests/test_agenticpay_bilateral_environment.py \
  tests/test_agenticpay_bilateral_measurement.py tests/test_agenticpay_bilateral_replay.py \
  tests/test_shared_runner_smoke.py -q
```

Result: 72 passed, 0 failed (61 pre-existing + 1 new regression test for C1 + 10 smoke).

## Kernel/runner defects found this pass

None. `scheduler.py`'s case-level and phase-level logical-action budget enforcement behaved
exactly as documented throughout; the defect was entirely in this adapter's own
`cases.py`/`environment.py` budget computation, not in the shared kernel. No new
`ledger_entries/agenticpay.md` entry was needed.

## Second-review findings

Second reviewer: Codex (adversarial pass), recovered as `docs/agenticpay_review_codex.md`
and triaged in `docs/agenticpay_codex_triage.md` (4 confirmed, 2 refuted, 1 kernel; see that
file for the reviewer's own evidence). Each CONFIRMED finding was fixed with a regression
test that reproduces the reviewer's exact concrete failure scenario through the real
scheduler + real bridge (never a hand-built `terminal`/`round_trace` fixture alone) and was
confirmed to fail before the fix, then pass after. Findings the review marked REFUTED were
not touched; the one KERNEL finding was appended to the runner defect ledger, not fixed here.

### [HIGH] Finding 2 (out-of-range agreements publish invalid shares) — **fixed**

`measurement.py`'s `_score_surplus_share` basic-mode branch checked only that the ZOPA
denominator was positive, never that `agreed_price` actually fell within
`[seller_min_price, buyer_max_price]` — the same `valid_range` condition upstream's own
`_calculate_global_score` requires before treating a deal as a success
(`Task1_basic_price_negotiation.py:1188-1195`). Driven through the real scheduler + real
bridge (task1, buyer_max=150/seller_min=80, both parties submit $200): upstream reaches
`"agreed"` at $200, and pre-fix this published `status="ok"` with buyer share -50/70 and
seller share 120/70 — outside the leaf's own declared `[0, 1]` support.
**Fix:** `_score_surplus_share` now rejects an out-of-range `agreed_price` as
`invalid_measurement` with reason `"agreed_price_out_of_declared_range"`, before computing a
share.
**Test:**
`tests/test_agenticpay_bilateral_measurement.py::test_surplus_share_rejects_an_agreed_price_outside_the_declared_zopa_bounds`.

### [HIGH] Finding 3 (unbound replay reports "match" without comparison) — **fixed**

Two independent defects in `replay.py`: (1) `RecordedEpisode` bound only to a case's
`case_id` string, never its content — a record could be replayed against a freshly hashed
`CaseManifest` sharing the original's `case_id` but with tampered reservation prices (and a
matching new `PlanCell`), and nothing rejected it; (2) `ReplayReport.status` returned
`"match"` whenever there was no *mismatching* comparison, including when `comparison is
None` (no comparison was ever made — a genuinely offline replay with no `original` supplied).
**Fix:** `RecordedEpisode` gains `case_sha256` (stamped by `record_episode`, which now takes
`case: CaseManifest`); `replay_episode` rejects a case whose `content_sha256` doesn't match
the record's, even when `case_id` matches. `ReplayReport.status` now returns
`"not_comparable"` when `comparison is None`, `"match"`/`"mismatch"` only for an actual,
checked comparison.
**Tests:**
`tests/test_agenticpay_bilateral_replay.py::test_replay_rejects_a_case_with_the_same_id_but_different_content`
(new — tampered-content rejection);
`tests/test_agenticpay_bilateral_replay.py::test_replay_without_an_original_run_still_replays_and_scores`
(updated assertion: `report.status == "not_comparable"`, not `"match"`, when
`comparison is None`).

### [MEDIUM] Finding 4 (repeated legal contracts are marked illegal) — **fixed**

`measurement.py`'s `score_contract_legality` inferred "accepted" from
`contract_before != contract_after`. Upstream assigns every parsed, validated contract to
state unconditionally, even when it exactly repeats the previous value
(`Task1_basic_price_negotiation.py:408-410`) — so a seat repeating an already-accepted legal
contract is indistinguishable, by a before/after state comparison alone, from a rejected
submission (both leave the stored value unchanged). Reproduced through the real bridge
(s01_beauty_product: round 1 buyer submits legal contract C, seller submits a different,
individually legal but incompatible contract D — no agreement yet; round 2 buyer repeats C
verbatim, seller submits C — agreement reached): pre-fix, round 2's buyer resubmission was
scored illegal (`round_2_buyer_contract_legal = 0.0`).
**Fix:** rather than reimplement upstream's bounds-checking, `agenticpay_bridge_driver.py`'s
new `_overlay_contract_validity` calls upstream's own `_extract_contract`/`_validate_contract`
methods again, on the exact same raw text `step()` itself just used (both pure, no side
effects) — reproducing upstream's own verdict exactly, never a re-derivation of it. That
verdict is threaded through as `round_trace[i]["{seat}_contract_valid"]`
(`environment.py`), and `score_contract_legality` now reads it directly instead of comparing
state before/after.
**Tests:**
`tests/test_agenticpay_bilateral_measurement.py::test_repeating_an_already_accepted_legal_contract_is_not_marked_illegal`
(bridge-driven, reproduces the reviewer's exact scenario);
`tests/test_agenticpay_bilateral_measurement.py::test_score_contract_legality_uses_upstreams_valid_verdict_not_a_before_after_diff`
(pure-fixture sibling). The pre-existing
`test_score_contract_legality_flags_only_the_rejected_round` fixture was updated to include
the new `*_contract_valid` field (its assertions are unchanged; this only supplies the data
shape production code now reads).

### [MEDIUM] Finding 5 (sealed evidence omits execution results) — **classified KERNEL, not fixed here**

Deciding whether a family-owned, non-scheduler harness (`harness.py`'s
`ScriptedAgenticpayBilateralHarness`, which seals only served responses, never bridge
results/state hashes/terminal/score) must also satisfy a minimum evidence-sealing contract
is a shared evidence-contract policy question, not something this family can unilaterally
decide — the production, scheduler-driven path already seals the complete `TransitionResult`,
terminal/outcome, and finalized score correctly (`execution.py`/`family_evaluation.py`).
Recorded as `D-16` in `runner_defect_ledger.md` per this fix pass's instructions;
`src/aeread/shared_runner/` was not modified.

### [MEDIUM] Finding 6 (fidelity tests become successful skips unless an opt-in variable is set) — **fixed**

`conftest.py`'s `pytest_terminal_summary` hook (already correct and already verified
end-to-end: setting `AEREAD_AGENTICPAY_BRIDGE_REQUIRED=1` against a missing bridge does turn
a skip into a nonzero exit code) is opt-in and off by default by design — but nothing ever
turned it on for this family. `.github/workflows/ci.yml` ran `pytest tests/ -q` with no
bridge-required variable set at all and no upstream checkout provisioned, so a plain CI run
could go green while every agenticpay upstream-fidelity test silently skipped.
**Fix:** added a separate `agenticpay-fidelity` CI job that checks out the pinned upstream
commit, provisions the bridge venv via the existing `tools/agenticpay_bridge/provision.sh`,
sets `AEREAD_AGENTICPAY_BRIDGE_REQUIRED=1`, and runs this family's four fidelity test files.
Kept as its own job (not folded into the existing `test` job) so a bridge/provisioning
failure here cannot block the provider-free suite every other family's PR relies on.
**Test:** `tests/test_agenticpay_bilateral_ci_bridge_requirement.py` (new) — pure text
inspection of the checked-in workflow (never a real GitHub Actions run; this suite is
offline/provider-free and there is no local runner for it), asserting the opt-in switch is
wired on and that the job actually invokes all four fidelity test files, so this protection
cannot silently regress again without this test failing first.
**Open concern for review:** the new CI job itself could not be executed in this sandboxed
session (no network/GitHub Actions access here); its YAML was hand-verified to parse
(`yaml.safe_load`) and its steps were validated locally by running the exact fidelity
`pytest` invocation with the equivalent environment variables set (exit code 0, 66 passed),
but the job's `actions/checkout`-of-a-second-repository step and `provision.sh`'s network
`pip install` have not been observed to succeed inside an actual GitHub Actions runner.
Recommend watching the first real CI run on this branch/PR before relying on it.

### [LOW] Finding 1 / Finding 7 — **REFUTED, not touched**

Finding 1 (negotiation budget too small) and Finding 7 (replay scoring expectations
circular) were independently re-verified against the code and confirmed refuted, per
`docs/agenticpay_codex_triage.md`'s own evidence (budget already accounts for the `+1` round
milestone-1 fix already applied; measurement.py's own independent hand-derived goldens would
catch the proposed shared-formula-error scenario even though the replay-specific comparison
alone would not). No code or test changes were made for either.

## Second-review test run (post-fix)

```bash
export AEREAD_AGENTICPAY_BRIDGE_PYTHON="/Users/sunzeyu/Documents/econ benchmark/bridges/agenticpay-venv/bin/python"
python -m pytest tests/test_agenticpay_bilateral_cases.py tests/test_agenticpay_bilateral_environment.py \
  tests/test_agenticpay_bilateral_measurement.py tests/test_agenticpay_bilateral_replay.py \
  tests/test_agenticpay_bilateral_ci_bridge_requirement.py tests/test_shared_runner_smoke.py -q
```

Result: 78 passed, 0 failed (72 pre-existing (first review pass) + 4 new regression tests for
findings 2/3/4 + 2 new CI-wiring tests for finding 6).
