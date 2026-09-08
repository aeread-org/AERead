# agenticpay.bilateral adapter — second-reviewer findings (Claude)

Scope: read-only adversarial review of `origin/main...HEAD` on
`zeyu/agenticpay-adapter` (the `agenticpay.bilateral` adapter). Spec read in full
(`docs/agenticpay_adapter_spec.md`), diff read file-by-file, and the real bridge/
upstream checkout (`bridges/agenticpay-venv`, `/Users/sunzeyu/Documents/econ
benchmark/upstream-agenticpay`, pinned at `1ff4e1a2686eac6a07ff559df6d50329c6fd9f69`)
were exercised directly — all 61 bridge-gated tests across
`test_agenticpay_bilateral_{cases,environment,measurement,replay}.py` pass for real
(not skipped) in this environment.

## CRITICAL

### C1. Every case's logical-action budget undercounts by 2x — non-converging negotiations crash the scheduler instead of reaching upstream's own `timeout`

- `src/aeread_families/agenticpay_bilateral/cases.py:589` (basic) and `:661`
  (realistic): `"max_logical_actions": int(extraction.constructor_kwargs["max_rounds"])`
- `src/aeread_families/agenticpay_bilateral/environment.py:299`:
  `max_actions = int(family_case["constructor_kwargs"]["max_rounds"])`, used as
  `PhaseSpec.max_logical_actions` for **both** `BUYER_PHASE` and `SELLER_PHASE`.

`environment.py`'s own docstring (lines 1-8) states the design: the kernel
schedules "one buyer turn and one seller turn at a time, alternating," and only
the seller phase's `step()` actually calls the bridge and can complete one
upstream negotiation round. That means **one upstream round == two kernel
logical actions** (one buyer + one seller). Upstream's own `max_rounds`
(20 for every one of the 28 imported cases — confirmed directly from the
checked-in JSON: `constructor_kwargs.max_rounds == 20` and
`episode.max_logical_actions == 20` for every case) is the number of *rounds*
before upstream's own truncation fires (`"timeout"`, one of exactly two
declared `TERMINATION_REASONS`).

But `case.episode.max_logical_actions` (and therefore
`cell.case_max_logical_actions`, which `scheduler.py:355` requires to equal it
exactly) is set to `max_rounds` itself, not `2 * max_rounds`. The scheduler
(`scheduler.py:749`/`:805`) enforces this as a **hard total-action ceiling
across the whole episode**:

```python
if logical_action_count > cell.case_max_logical_actions:
    raise SchedulerContractError("case logical-action budget exceeded before termination")
```

So a negotiation that has not converged by round `max_rounds / 2` (round 10,
for every current case) crashes the entire episode with an unhandled
`SchedulerContractError` — never reaching upstream's own round 20 and never
producing the declared `"timeout"` termination reason at all.

**Verified empirically** (not just read from source): I drove
`agenticpay.bilateral.basic.task1` through the real scheduler + real bridge
with a scripted buyer/seller that never converges:

```
max_logical_actions (episode): 20
SchedulerContractError raised: case logical-action budget exceeded before termination
rounds completed before crash: 10
```

Exactly 10 of the intended 20 rounds run before the hard crash. Compare with
`housing.py:1335` (`max_logical_actions=2 * num_tenants * rounds`), which
already establishes the correct convention in this same codebase for a
multi-seat-per-round phase graph — this adapter did not apply it.

**Why this is CRITICAL, not a corner case:** `max_rounds=20` is upstream's own
default specifically to tolerate slow/inefficient real-agent negotiations —
the primary use case this benchmark exists for. Any live-policy run (not the
1-2 round scripted goldens this PR ships) that takes more than 10 rounds to
either agree or genuinely time out will abort with an infrastructure-level
`SchedulerContractError`, indistinguishable from a kernel bug, instead of
scoring a legitimate (if poor) outcome. `"timeout"` is declared in every
case's `episode.termination` and in `TERMINATION_REASONS`
(`cases.py:79`) but is **not reachable** through the real kernel path as
currently wired.

**Not caught by any test in this PR:** neither
`tests/test_agenticpay_bilateral_environment.py` nor
`tests/test_agenticpay_bilateral_measurement.py` nor
`tests/test_agenticpay_bilateral_replay.py` contains the string `timeout` or
drives a negotiation past 2 rounds — the entire timeout/truncation path is
untested, and the bug is invisible in a green test run.

**Suggested direction (not a prescription, since I was asked not to edit):**
`cases.py`'s `"max_logical_actions"` for both `build_basic_case` and
`build_realistic_case` should be `2 * int(extraction.constructor_kwargs["max_rounds"])`;
`environment.py:299`'s `phases()` can keep `max_actions = max_rounds` as the
**per-phase** cap (each seat only ever acts `max_rounds` times), since the
per-phase check and the case-level check are independent budgets in
`scheduler.py`.

## WARNING

### W1. The contract-mode "component parity" test is tautological, and its docstring overclaims independence from the basic-mode sibling it's modeled on

- `tests/test_agenticpay_bilateral_measurement.py:592-600`
  (`test_surplus_share_leaves_recombine_to_upstream_recorded_global_score_contract_mode`)
- `src/aeread_families/agenticpay_bilateral/measurement.py:490-499`
  (`_score_surplus_share`, contract-mode branch: `share = utility / z_max`)
- Verified against upstream source directly:
  `upstream-agenticpay/agenticpay/envs/single_buyer_product_seller/Task1_basic_price_negotiation.py:1051-1060`
  (`_get_contract_score_terms`): `r_b = u_b / self.z_max`, `r_s = u_s / self.z_max`,
  `q_value = 4.0 * r_b * r_s` — the exact values later multiplied into
  `GlobalScore` at `:1116` (`quality_score = self.quality_score_weight * score_terms["q"] * discount`).

For **contract-mode** cases, `agenticpay_buyer_surplus_share`'s primary value
(`terminal["buyer_utility"] / terminal["z_max"]`) is not independently
recomputed — it is upstream's own `r_b`, read back verbatim off
`state.metadata` (via `_overlay_contract_utilities` in
`agenticpay_bridge_driver.py`). The "component parity" test then multiplies
this same number back through the disclosed `Q = 4*r_b*r_s` formula and
asserts it reproduces `info["global_score"]`. Since `r_b`/`r_s` are the exact
inputs upstream itself just used to compute that `GlobalScore`, equality holds
by construction — it cannot catch an error in upstream's own MAUT utility
calculation (`u_b`, `u_s`, `z_max`), only a typo in *this adapter's* copy of the
weights/discount/`Q` formula.

This is materially different from its **basic-mode** sibling
(`test_surplus_share_leaves_recombine_to_upstream_recorded_global_score_basic_mode`,
line 568), where `measurement.py`'s `_score_surplus_share` computes
`u_b = (buyer_max_price - agreed_price) / zopa` **independently** from
`agreed_price` (upstream never stores `buyer_utility`/`seller_utility` for
price-only mode — confirmed in upstream source: those metadata fields stay
`None` unless `_get_contract_score_terms()` runs, which early-returns `None`
when `not self.use_contract_mode`). The basic-mode check is a genuine
cross-check; the contract-mode one is not, but both tests carry an identical
docstring claiming parity with "the same class of check
`test_tau3_retail_measurement.py` performs against
`tau2.evaluator.evaluator_env.EnvironmentEvaluator`" (module docstring, lines
17-22) — which is true for tau3's genuinely separate evaluator, but overstated
for this contract-mode test specifically.

**Failure scenario this could mask:** if a future upstream pin bump changes
how `buyer_utility`/`seller_utility` are computed or stored (e.g., a stale
value from a prior round leaks through `_get_contract_score_terms`'s
`agreed_contract` fallback branch), this "parity" test would still pass
undisturbed, because both sides of the equality read the same (possibly
wrong) stored value — giving false confidence that contract-mode scoring was
independently verified when it was not. This is already disclosed at the spec
level (`docs/agenticpay_adapter_spec.md` §5/§9: "no separate gold oracle
exists… replay parity here is the correctness oracle"), so the risk is
narrow — but the test's own docstring should say so explicitly rather than
imply equal strength to the basic-mode check and to tau3's independent
oracle.

## SUGGESTION

### S1. Golden 3 (invalid contract offer) proves "no state mutation" only indirectly

`tests/test_agenticpay_bilateral_measurement.py:485-516`
(`test_golden_3_invalid_or_unauthorized_contract_offer`) asserts
`legality.metrics["round_1_seller_contract_legal"].value == 0.0`, which is
true iff `round_trace[0]["seller_contract_before"] ==
round_trace[0]["seller_contract_after"]` by
`measurement.score_contract_legality`'s own definition
(`measurement.py:350`). That does correctly prove no mutation occurred (I
verified upstream's actual behavior — `_validate_contract` rejection leaves
`state.metadata["seller_contract"]` untouched), but the test never asserts the
`round_trace` fields directly, so a future refactor of
`score_contract_legality`'s "accepted" definition could silently change what
this golden is actually proving without any assertion in the golden itself
changing. Asserting
`result.terminal["round_trace"][0]["seller_contract_after"] is None` (or
`== round_trace[0]["seller_contract_before"]`) directly in the golden, in
addition to the derived leaf check, would make the "no protected state
changed" claim self-evident from the test body rather than inherited from
`measurement.py`'s implementation.

## What checked out clean

- **Gate 1 (corpus admission):** `cases.py`'s `import_all_cases` dedups on
  `case_id` (raises on collision), every case round-trips through
  `CaseManifest.from_dict` and re-hashes stably (`_finish_case`), and
  `test_checked_in_cases_match_a_fresh_import`/
  `test_importer_is_byte_identical_across_two_runs` close the loop between the
  checked-in `cases/agenticpay_bilateral/*.json` and a fresh, from-source
  import — no silent resampling or hand-edited case file was found (verified
  by re-running the importer against the real pinned upstream checkout;
  output matched byte-for-byte).
- **Verifier declarations vs. `docs/research/verifier_taxonomy.md`:** all four leaves
  (`agenticpay_deal_reached`, `agenticpay_contract_legality`,
  `agenticpay_buyer_surplus_share`, `agenticpay_seller_surplus_share`) are
  genuinely deterministic (`rule_constraint`/`objective_reference`,
  `evaluation_class="deterministic"`) — no LLM judge exists anywhere in
  upstream's negotiation-scoring path, and none is smuggled in here.
  `GlobalScore`/`BuyerScore`/`SellerScore` are correctly withheld from
  `MeasurementLeafSpec` status (no declared normative weights) and carried
  only as a labeled compatibility artifact, matching taxonomy §10's
  `weighted`-composite gate.
- **Replay honesty:** `replay.py`'s `replay_episode` re-feeds only the raw
  recorded `{"message": ...}` strings through the real scheduler; the seller
  phase's `step()` still makes a genuine, independent
  `AgenticpayBridge.replay_round` subprocess call against a **second** bridge
  instance for every replayed round (verified in
  `tests/test_agenticpay_bilateral_replay.py:305-343`, which explicitly builds
  a second `AgenticpayBridge`/plugin and round-trips the record through plain
  JSON text first). This is real re-execution, not a re-read of cached
  final state.
