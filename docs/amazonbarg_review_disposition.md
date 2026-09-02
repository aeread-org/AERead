# amazonbarg adapter — review disposition

Source reviews: `docs/amazonbarg_review_claude.md` (present). `docs/amazonbarg_review_codex.md`
does not exist in this worktree (the codex reviewer did not produce a report, or died before
writing one) — handled as absent rather than blocking this pass.

Each finding below was independently re-verified against the code (and, where the finding
concerned upstream behavior, against the pinned upstream checkout at
`/Users/sunzeyu/Documents/econ benchmark/upstream-amazonbarg`) before any fix was made.

## W1 — the invalid/malformed-action golden (golden 4) never gets the sealed-evidence/replay treatment

**Disposition: FIXED.**

**Confirmed independently.** `GOLDEN_1_SCRIPT`/`GOLDEN_5_SCRIPT` were the only two scripts wired
into `tests/test_amazonbarg_harness.py` and `tests/test_amazonbarg_replay.py` before this pass —
goldens 2, 3, and 4 (including golden 4, the malformed-action case whose whole point is "no
protected state changed on invalid input") never went through `ScriptedAmazonbargHarness`'s
hash-chained `EvidenceStore` or `replay.py`'s `replay_and_verify` path, only the plain, in-memory
`run_episode` call in `test_amazonbarg_environment.py`/`test_amazonbarg_measurement.py`. Read
`environment.py::AmazonbargPlugin.step()`'s `BUYER_PHASE` branch and confirmed a malformed reply
(no `Action:` line) is classified `action_error` and terminates the episode after exactly one
served decision, with the decision itself still recorded as a normal `LogicalActionRecord`
(parse/legality both succeed at the kernel level; only `step()`'s own `_classify_action` raises
internally and catches it) — so nothing about the harness/replay mechanics would need to change
to cover it, only the missing test wiring.

**Fix.** Added `GOLDEN_2_SCRIPT`, `GOLDEN_3_SCRIPT`, and `GOLDEN_4_SCRIPT` (matching the exact
scripted trajectories already verified against delegated `eval.py:Metrics` in
`test_amazonbarg_measurement.py`) to both `tests/test_amazonbarg_harness.py` and
`tests/test_amazonbarg_replay.py`, closing the gap for all five QC Gate-2 goldens rather than
only golden 4 (the review's "ideally 2, 3" suggestion). `docs/amazonbarg_adapter_status.md` and
`docs/amazonbarg_adapter_spec.md`'s golden 3 entry were updated to state the new, wider coverage
plainly instead of only disclosing the gap at the aggregate level.

**Test added.**
- `tests/test_amazonbarg_harness.py::test_golden_2_runs_end_to_end_through_the_real_scheduler_and_seals_evidence`,
  `::test_golden_3_...`, `::test_golden_4_...` — each drives the golden through the real
  `run_episode`/`AmazonbargPlugin`/`PluginRegistry` path via `ScriptedAmazonbargHarness` and
  verifies the sealed, hash-chained `EvidenceStore` (`verify_chain()`/`verify_seal()`, exact
  event-payload round-trip). Golden 4's test additionally asserts exactly one event was sealed
  (the malformed buyer turn) and nothing after it — no seller-phase turn ever ran, no phantom deal
  was ever recorded.
- `tests/test_amazonbarg_replay.py::test_golden_2_replay_reproduces_state_byte_identically`,
  `::test_golden_3_...`, `::test_golden_4_...` — each records the live sealed episode, round-trips
  it through plain JSON, and replays it through a second, independent `AmazonbargPlugin`, asserting
  byte-identical final state.
  `::test_golden_4_replay_recomputes_an_invalid_measurement_score_identically` additionally
  recomputes the score from the replayed history and asserts every leaf (including the
  `invalid_measurement` seals gated by `wrongAction=1`) reproduces identically between the original
  and replayed runs — the same evidentiary bar goldens 1 and 5 already met.

All eight new tests fail if reverted (each depends on the newly-wired `GOLDEN_2/3/4_SCRIPT`
constants and test functions that did not exist before this pass).

## W2 — latent `AttributeError` in the golden test helper for a future conflicting-interest-but-deal-closes case

**Disposition: FIXED.**

**Confirmed independently.** Reproduced live: scripted `toys-games_22` (the pilot's one
conflicting-interest session, `cost=$959.00 > budget=$864.93`) through `BUY $900 -> DEAL $900`
instead of the shipped golden 5 script (`BUY $850 -> REJECT -> QUIT`); `compute_upstream_metrics`
returned `D=900.0`, `buyer_bargained_ratio=-0.373` (upstream's own `eval.py:Metrics.evaluate` sets
these fields whenever a `DEAL` closes, with no check against `cost`/`budget` at all), while
`measurement.py::_measurement_gate` still correctly sealed `zopa`/`lower`/`upper`/`ratio_*` as
`invalid_measurement` (`primary=None`) because `derived.interest == "conflicting"` — independent
of whether `D`/`buyer_bargained_ratio` are present in `metrics_output`. Calling
`envelopes["lower"].primary.value` (exactly what `_score_and_check_parity` did unconditionally
whenever `"D" in metrics_output`) raised `AttributeError: 'NoneType' object has no attribute
'value'`, confirming the finding exactly as described. None of the five shipped goldens combine
"conflicting interest" with "deal closes" (golden 5's own CI session quits), so this was latent,
not currently triggered by the 106/106 green run.

**Fix.** `tests/test_amazonbarg_measurement.py::_score_and_check_parity`'s component-parity block
now guards the `lower`/`upper`/`ratio_buyer`/`ratio_seller` assertions the same way the `zopa`
assertion already was (`if envelopes[...].status == "ok": ...`), instead of gating only on
`metrics_output` field presence.

**Test added.**
`tests/test_amazonbarg_measurement.py::test_conflicting_interest_session_whose_scripted_trajectory_still_closes_a_deal`
scripts the exact reproduction above (`toys-games_22`, `BUY $900 -> DEAL $900`) and asserts the
parity check completes cleanly with every non-authenticity leaf sealed `invalid_measurement`.
Confirmed this test fails with the pre-fix helper (`AttributeError: 'NoneType' object has no
attribute 'value'` at the `lower` assertion) and passes after the fix.

## M1 — golden 3's category label ("invalid-unauthorized") reads as if the illegal deal were blocked; it is deliberately not

**Disposition: FIXED (documentation clarification, not a code change).**

**Confirmed independently.** Read `environment.py::AmazonbargPlugin.legal()` directly: there is no
cost/budget check anywhere in the live phase graph, only the scheduling-level seat/phase-binding
check — matching the adapter's own "Governing facts" statement that "a DEAL below cost or above
budget is not blocked at generation time". Golden 3's terminal state genuinely changes
(`termination_reason="deal"`, a real below-cost deal price recorded); nothing is protected from
this mutation at the state layer, only caught afterward by `amazonbarg_zopa_membership`. The label
"invalid-unauthorized" (shared with `aucarena`/`negarena`'s taxonomy) does invite the opposite
reading from golden 4's actual state-layer prevention, exactly as the finding describes.

**Fix.** `docs/amazonbarg_adapter_spec.md` section 4's golden 3 entry now states explicitly:
"This golden proves scoring-layer detection of an environment-permitted illegal deal, not
state-layer prevention ... See golden 4 for the adapter's actual 'no protected state changed on
invalid input' proof." `docs/amazonbarg_adapter_status.md`'s golden-3 cross-reference was updated
to match. No code change; no test applicable (a spec-text-only clarification with no observable
runtime behavior to assert against).

## Summary

| Finding | Severity | Disposition |
|---|---|---|
| W1 — golden 4 (and 2, 3) never sealed/replayed | WARNING | Fixed |
| W2 — latent `AttributeError` in parity-check helper | WARNING | Fixed |
| M1 — golden 3 label invites the opposite reading | MINOR | Fixed |

Nothing was refuted — every finding in `docs/amazonbarg_review_claude.md` reproduced or confirmed
exactly as described. Nothing was deferred to the ledger from this review: all three findings are
adapter-code or adapter-doc gaps owned outright by this adapter, not the shared kernel/runner.

Full family test suite (`test_amazonbarg_{cases,environment,harness,measurement,replay,shim}.py`)
plus `tests/test_shared_runner_smoke.py`: **114/114 passed, 0 skipped, 0 failed** — 106
pre-existing plus 8 new regression tests (3 for W1's harness coverage, 4 for W1's replay coverage,
1 for W2). Full repo suite: **830 passed, 31 skipped, 1 xfailed** — no regression (822 passed
before this pass, same 31 skips/1 xfail, all pre-existing and unrelated to amazonbarg).
