# termsbench adapter — review disposition

Fix pass against the second-reviewer read in `docs/termsbench_review_codex.md`
(missing — that reviewer did not produce a report; nothing to reconcile
against it) and `docs/termsbench_review_claude.md` (present, 4 findings: 2
MAJOR, 2 MINOR). Every finding below was independently re-verified against
the code before any fix was made. All 4 are about the termsbench adapter's
own code (`src/aeread_families/termsbench/`), not about the kernel/runner
(`src/aeread/shared_runner/`), so none required a
`ledger_entries/termsbench.md` entry — no ledger file was created.

## MAJOR

### 1. `termsbench_protocol_compliance`'s reference hash omits `agent.r_a`

**Disposition: fixed.**

Verified directly: `_case_constants_sha256` (`measurement.py`) hashed only
`price_bounds`, `agent["role"]`, and `horizon`, never `agent["r_a"]` — the
individual-rationality anchor `environment.py`'s `_step_agent` actually tests
Accept/Offer actions against. Two payloads sharing the hashed fields but
differing in `r_a` produced an identical `source_sha256`, confirmed by
direct computation before the fix.

Fix: `src/aeread_families/termsbench/measurement.py` — `_case_constants_sha256`
now includes `"agent_r_a": float(payload["agent"]["r_a"])` in the hashed
`rule_payload`.

Test: `tests/test_termsbench_measurement.py::test_protocol_compliance_reference_hash_changes_with_the_agent_ir_anchor`
builds leaf 4 for two payloads identical except `r_a` and asserts their
`verifier.reference.source_sha256` now differ (it failed before the fix,
matching the review's own before/after computation).

### 2. Golden 3 ("no protected state is touched") is never asserted

**Disposition: fixed.**

Verified directly: both golden-3 tests
(`tests/test_termsbench_measurement.py::test_golden3_invalid_unauthorized_accept_earns_no_credit_but_stays_valid`
and
`tests/test_termsbench_environment.py::test_golden3_accept_without_counterpart_offer_is_agreement_violation`)
only inspected `result.terminal`, never `result.final_state`, so the
"no protected state (price, DB) is touched" invariant both docstrings
restate was not locked in by either test. Confirmed the underlying behavior
was already correct (`_step_agent`'s invalid-action branch returns before
appending to `agent_offers`/`counterpart_offers`/`transcript`, and `round`
is never incremented on that path).

Fix: added assertions to both existing golden-3 tests —
`result.final_state["round"] == 1`,
`result.final_state["agent_offers"] == ()`,
`result.final_state["counterpart_offers"] == ()`,
`result.final_state["transcript"] == ()` — rather than writing new tests,
since the existing tests are the golden-3 regression tests the invariant
belongs in.

## MINOR

### 3. `select_pilot_cell_seed`'s docstring overstates what it returns

**Disposition: fixed.**

Verified directly: the implementation returns the seed at the first rank
(lowest `difficulty_score`) whose bin matches, not the numerically smallest
seed among every candidate landing in that bin. These coincide on the
committed 30-case pilot (per the review's own finding) but are not the same
guarantee.

Fix: reworded the docstring in `src/aeread_families/termsbench/cases.py` to
describe the actual first-rank-wins semantics.

Test:
`tests/test_termsbench_cases.py::test_select_pilot_cell_seed_picks_first_rank_not_smallest_seed_within_a_bin`
monkeypatches `_difficulty_score_only` so two candidates share a bin but the
lower-scored one is the larger seed, and asserts the function returns the
first-rank (lower-scored) seed, not the smallest seed in the bin — a
regression to the old (incorrect) "smallest seed in bin" reading would fail
this test.

### 4. `FamilyManifest.measurement.primary_estimand` names a leaf half the corpus never declares

**Disposition: fixed (documentation only).**

Verified directly: `resolver.py`'s `missing_estimands` check only requires
the suite's `AnalysisPlan` to know about the family's declared
`primary_estimand` id, never that every case emits it — confirmed by
reading `resolve_run_plan`'s check (`src/aeread/shared_runner/resolver.py`).
No functional defect; the review itself found no evidence this breaks
anything today, only that nothing in `FamilyManifest` documents the
Overlap/No-deal split.

Fix: added a comment above `primary_estimand` in
`family_manifest()` (`environment.py`) stating the split explicitly and
noting the resolver's actual (weaker) check, so a future suite-level
report keyed on this id is not silently surprised by an empty No-deal half.
No new test: the behavior this documents (No-deal cases never emit
`termsbench_surplus_efficiency`) is already regression-tested by the
pre-existing `test_nodeal_case_declares_no_deal_agreement_and_protocol_compliance_only`.

## Refuted

None — all 4 findings in `docs/termsbench_review_claude.md` were confirmed
by independent re-verification before fixing.

## Deferred to ledger

None — no finding was about `src/aeread/shared_runner/` (the kernel/runner)
rather than this adapter.

## Verification

`tests/test_termsbench_*.py` + `tests/test_shared_runner_smoke.py`: 92
passed, 0 failed. Full repo suite: 808 passed, 31 skipped, 1 xfailed (the
skips/xfail are `tau3_retail`'s bridge-gated fidelity tests and one
pre-existing xfail, unchanged from before this pass).
