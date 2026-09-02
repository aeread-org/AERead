# alympics.wac adapter — review disposition

Two review reports were expected (`docs/alympics_review_codex.md`,
`docs/alympics_review_claude.md`); only the Claude report exists in this
checkout (`git status`/`find` show no `alympics_review_codex.md` on disk —
the other reviewer produced nothing to process). Every finding below is from
`docs/alympics_review_claude.md`, each independently re-verified against the
code before any fix, per this pass's own ground rules (reviews can contain
false positives; nothing here was fixed on the review's word alone).

CRITICAL: 0 · MAJOR: 2 · MINOR: 3 (all as reported by the reviewer).

## MAJOR

### M1 — Golden 3 (invalid/unauthorized bid) is never driven end-to-end through `run_episode`/the Mode C phase graph

**Verified:** confirmed independently. `tests/test_alympics_wac_environment.py`'s
`test_delegate_round_flags_an_over_balance_bid_as_illegal_but_still_settles`
and `test_legal_hook_never_rejects_an_over_balance_bid_action`, plus
`tests/test_alympics_wac_measurement.py`'s
`test_golden_3_over_balance_bid_becomes_invalid_measurement_never_a_legal_loss`,
all call `_delegate_round`/`legal()` directly or hand-construct the
`round_log` dict fed to the measurement scorers — none of them go through
`observe`/`parse_action`/`legal`/`step` via `run_episode` the way goldens 1,
2, and 5 do.

**Disposition: fixed.**
1. Added
   `test_over_balance_bid_is_flagged_illegal_through_a_real_run_episode_step`
   (`tests/test_alympics_wac_environment.py`) — drives a full
   `reference_baseline` episode through `run_episode` with alex always
   bidding `999_999` (unreachable by any balance alex could accrue this
   episode) and every other seat bidding `proportional`; asserts every round
   `step()` itself logs shows `bid_legal["alex"] is False`, alex never wins,
   every other still-alive seat's legality is untouched, and alex ends up
   genuinely eliminated (an ordinary loss trajectory, never a special
   "illegal-but-rewarded" outcome).
2. Added
   `test_golden_3_over_balance_bid_end_to_end_through_run_episode_becomes_invalid_measurement`
   (`tests/test_alympics_wac_measurement.py`) — same real `run_episode`
   trajectory, fed into `score_bid_legality`/`score_terminal_wealth`/
   `score_survival` as the *actual* recorded `round_log` (never a
   hand-constructed stand-in), asserting all three go `invalid_measurement`
   for alex while `bob`'s own leaf stays `ok`.

Both new tests pass; the pre-existing unit-level tests are left in place
(they still cover the isolated-helper claims, which remain true and useful).

### M2 — Golden 4 (malformed/operational failure) is structurally unreachable through any real production code path

**Verified:** confirmed independently by tracing `environment.py`'s
production call site. `step()` (`environment.py:600-608`) always calls
`_delegate_round(...)` without `force_malformed`, which defaults to `None`;
in that branch, `wa.llm.call` is always bound to a closure that returns
`json.dumps({p.name: p.bidding for p in survivors})` — valid, complete JSON
by construction, since every alive seat's bid is already known before
`step()` runs. The `KeyError`/`TypeError` catch inside `_delegate_round`
(lines 318-329) can therefore never actually fire from `step()`'s own call
site or any of the four named scripted policies; it is reachable only via
`_delegate_round`'s private, test-only `force_malformed` parameter. This
matches `cases.py`'s own existing inline comment on `TERMINATION_REASONS`
almost verbatim — the code was already honest about this internally, but
`docs/alympics_adapter_spec.md`'s golden-4 table row and its e2e test-plan
bullet did not carry the same disclosure, so a QC auditor reading only the
spec could reasonably believe golden 4 is a real, live-reachable scenario.

**Disposition: fixed (documentation), not a code defect.** This is an
intentional consequence of the adapter's own design (per-instance `LLM.call`
replacement that "never sniffs or reconstructs bids from prompt text" —
`environment.py`'s module docstring) — rearchitecting `step()` to route
through upstream's real freeform-text parser so this branch could fire for
real would reintroduce exactly the prompt-content-sniffing risk the design
deliberately avoids, and is out of scope for a fix pass. Instead:
1. `docs/alympics_adapter_spec.md` §4's golden-4 row now explicitly states
   the branch is reachable only via `_delegate_round`'s test-only
   `force_malformed` hook, never through `step()`'s real call site.
2. §5's e2e bullet now names goldens 1/2/3/5 as `run_episode`-driven and
   golden 4 as unit-level-only, with the reason.
3. §6's stated limits gained a new bullet stating this plainly, matching
   `cases.py`'s existing candor.

No test was added for M2 itself (the finding class is "the spec
overclaims," not "the code has a bug reachable by a scripted trajectory" —
the existing `test_delegate_round_missing_key_raises_keyerror_caught_as_malformed`/
`test_delegate_round_unparseable_raises_typeerror_caught_as_malformed`/
`test_step_records_malformed_action_termination_without_crashing` already
cover the reachable, hand-invoked half of this claim).

## MINOR

### N1 — `cases.py` embeds the shared, mutable `PERSONAS` dict by reference into every case payload

**Verified:** confirmed independently. `build_case`'s
`data["payload"]["personas"] = PERSONAS` aliased the same module-level dict
into all 7 generated case payloads.

**Disposition: fixed.** Changed to `copy.deepcopy(PERSONAS)`
(`src/aeread_families/alympics_wac/cases.py`). Added
`test_each_cases_personas_payload_is_an_independent_object_not_a_shared_alias`
(`tests/test_alympics_wac_cases.py`), which builds its own fresh cases
(never the shared module-scoped `built` fixture, to avoid polluting other
tests in the file with an in-place mutation), mutates one case's
`payload["personas"]["alex"]["requirement"]`, and asserts neither another
case's payload nor the module-level `PERSONAS` constant changed.
Mutation-verified: reverting the fix locally (`"personas": PERSONAS`)
reproduces the failure this test now catches, then restored via `cp` from a
`/tmp` backup (never `git checkout`, per this pass's own ground rules).

### N2 — No programmatic near-duplicate detection across the 7 grid cells

**Verified:** confirmed independently. `build_all_cases()` only rejected an
exact `case_id` collision; nothing checked whether two cells shared the same
`(supply_regime, rounds, seed, policy_assignment)` tuple under different
names.

**Disposition: fixed.** Added `_grid_cell_dedup_key()` and a check in
`build_all_cases()` that raises `GridValidationError` on a repeated
`(supply_regime, rounds, seed, policy_assignment)` tuple across cells;
`build_all_cases()` now takes an optional `grid` parameter (defaulting to
the real module `GRID`) so tests can exercise this against a synthetic grid
without touching production data. Added
`test_build_all_cases_rejects_near_duplicate_grid_cells` and
`test_build_all_cases_allows_disjoint_seed_cells_that_otherwise_match` (the
latter guards against a regression that would wrongly flag the real grid's
own `mixed_policies_a`/`_seed2` disjoint-seed pairing). Confirmed the real
7-cell `GRID` still builds cleanly under the new check.

### N3 — Spec §3's bid-legality-gate wording is looser than §2's and than the implementation

**Verified:** confirmed independently by reading `environment.py`'s
`_check_winner_wrapper` (`environment.py:280-296`): the gate runs *during*
the call to `run_single_round` (before the real, delegated `_check_winner`
executes), not as a separate check "before `run_single_round` is invoked"
as §3 literally said.

**Disposition: fixed.** Reworded §3's bullet in
`docs/alympics_adapter_spec.md` to match §2's more precise "checked before
delegating to `_check_winner`, during the same call to `run_single_round`."
No behavior changed; documentation-only.

## Summary

| Finding | Severity | Disposition |
|---|---|---|
| M1 | major | fixed |
| M2 | major | fixed (documentation; not a code defect) |
| N1 | minor | fixed |
| N2 | minor | fixed |
| N3 | minor | fixed |
