# negarena adapter — review disposition

Source reviews: `docs/negarena_review_claude.md` (present). `docs/negarena_review_codex.md`
does not exist in this worktree (the codex reviewer did not produce a report, or died before
writing one) — handled as absent rather than blocking this pass.

Each finding below was independently re-verified against the code (and, where the finding
concerned upstream behavior, against the pinned upstream checkout at
`/Users/sunzeyu/Documents/econ benchmark/upstream-negarena`,
commit `c447fafd439a20b84cdedeb2f8a85c4fad764745`) before any fix was made.

## CRITICAL-1 — malformed-response detection bypassable for non-trade tags

**Disposition: FIXED.**

**Confirmed independently.** Re-ran the review's exact reproduction script against the real
bridge (`NegarenaBridge.discover`) and the pre-fix adapter code: a `buy_sell` response with a
well-formed `<message>`/`<newly proposed trade>`/`<my resources>` but no `<player answer>` tag
parsed with `parsed.ok == True`, `parsed.action["public"]["player answer"]` populated with a
garbage substring of the surrounding response text, and `NegarenaPlugin.legal(...)` reporting
`legality.legal == True`. Read upstream's `negotiationarena/utils.py::get_tag_indices` directly
and confirmed it returns `(-1, -1, len(tag))` for an absent tag rather than raising, and that
every upstream parser (`BuySellGameDefaultParser.parse`, `UltimatumGameDefaultParser.parse`)
unconditionally extracts every one of its tags regardless of whether extraction "found" anything
— so `environment.py`'s existing `"message" not in public or "player answer" not in public or ...`
check could never fire for any tag except the trade tag.

**Fix.** `src/aeread_families/negarena/negarena_bridge_driver.py::_op_parse_response` now calls
upstream's own `negotiationarena.utils.get_tag_indices` for every tag the pinned parser
unconditionally extracts for the given `game_kind` (`_required_tags_for`, enumerated call-for-call
from `BuySellGameDefaultParser.parse` / `UltimatumGameDefaultParser.parse` at the pinned commit)
*before* invoking `parser.parse()`. A missing tag now returns an in-band
`{"parsed": False, "parse_error_type": "missing_required_tag", ...}`, which
`NegarenaPlugin.parse_action` already turns into `malformed_action` via its existing
"upstream parser raised" branch. This delegates to upstream's own tag-boundary function rather
than reimplementing any tag grammar (spec section 3's non-negotiable).

**Re-verified after the fix:** the same reproduction script now returns `parsed.ok == False`,
`error_code == "malformed_action"`; a well-formed control response (all tags present) still
parses clean.

**Test added.** `tests/test_negarena_environment.py::test_golden_4_missing_player_answer_tag_is_caught_not_a_crash`
(buy_sell, mirrors the review's exact repro, also drives `step()`/`terminal()` through to confirm
the episode terminates rather than silently continuing) and
`::test_golden_4_missing_player_answer_tag_is_caught_for_ultimatum_too` (same gap, other family
split). Both fail against the pre-fix driver and pass after.

## WARNING-2 — ultimatum per-seat outcome asymmetry has no runtime guard

**Disposition: FIXED (adapter-owned guard); upstream defect itself remains documented in the
ledger, not fixed (upstream is read-only).**

**Confirmed independently.** Read `games/ultimatum/game.py::after_game_ends()` at the pinned
commit directly: `outcome = [(final - initial) for initial, final in zip(...)]` followed by
`outcome[0] = final_resources[0]` — RED's reported outcome is overwritten to an absolute value,
BLUE's stays a delta. Confirmed `environment.py::validate_payload` (pre-fix) accepted any
non-negative-integer BLUE starting balance for an ultimatum case, and that every currently
authored `negarena.ultimatum.*` case (`cases.py::_ultimatum_payload` call sites) happens to give
BLUE a zero starting `Dollars` balance, making the gap latent rather than currently triggered.
This finding is about the adapter's own missing validation (not a kernel/runner defect), so it was
fixed directly rather than deferred to the ledger; the underlying upstream asymmetry itself was
already recorded in `ledger_entries/negarena.md` as an upstream informational entry and is left
as-is (upstream is read-only).

**Fix.** `src/aeread_families/negarena/environment.py::validate_payload`'s ultimatum branch now
rejects any payload whose BLUE seat's starting `money_token` balance is nonzero, with a
`ValueError` explaining why (delta vs. absolute outcomes become incomparable under the same
`head_to_head` estimand otherwise). This converts a previously-silent future-corpus risk into a
Gate-1 admission failure.

**Test added.**
`tests/test_negarena_environment.py::test_validate_payload_rejects_a_nonzero_blue_ultimatum_endowment`
mutates a real authored ultimatum case's payload to give BLUE a nonzero balance and asserts
`validate_payload` raises. `test_validate_payload_accepts_every_authored_case` (pre-existing)
continues to confirm every shipped case still validates (all give BLUE a zero balance).

**Status doc updated.** `docs/negarena_adapter_status.md`'s "Known limits" section's ultimatum
bullet no longer says "no AERead-side fix is needed" — it now describes the guard.

## SUGGESTION-3 — dangling cross-reference to a nonexistent spec heading

**Disposition: FIXED.**

**Confirmed independently.** `grep -n "Deviations from the original spec text" docs/*.md` returns
nothing; the real explanation lives under `docs/negarena_adapter_spec.md` section 1's
"**Correction (found during implementation):**" bullet (the literal heading text the comment
claimed to exist does not).

**Fix.** `src/aeread_families/negarena/cases.py`'s comment now points at
"`docs/negarena_adapter_spec.md` section 1's 'Correction (found during implementation)' note"
instead of the nonexistent heading. No test added (a comment-text fix has no observable behavior
to assert against); verified by `grep` that the new cross-reference text is now literally present
in the spec doc.

## SUGGESTION-4 — measurement_validity spec text claims more than is implemented

**Disposition: FIXED (documentation correction, not a code change).**

**Confirmed independently.** `docs/negarena_adapter_spec.md` section 2 claimed
`measurement_validity` "additionally checks ... iteration-count/turn-alternation replay
consistency" as one of its named checks. Read `measurement.py` in full: it only ever emits
`ValidityReport("invalid", ...)` for the two termination reasons (`malformed_action` /
`invalid_measurement`) already produced by `parse_action`/`legal`; there is no separate,
independently-reported iteration-count/turn-alternation check. The invariant does hold, but only
implicitly, via the phase graph's `next_phases` wiring (`environment.py`) and the scheduler's own
bookkeeping — never as its own pass/fail signal a receipt consumer could inspect. Confirmed this
is not a scoring bug: no test or golden actually depends on a standalone
iteration-count/turn-alternation validity signal existing.

**Fix.** `docs/negarena_adapter_spec.md` section 2's `measurement_validity` paragraph now states
plainly what is and is not implemented, with an explicit "Correction (found during review,
docs/negarena_review_claude.md SUGGESTION-4)" note, matching the honest-correction convention
already used elsewhere in this spec and in `docs/negarena_adapter_status.md`'s "Known limits"
section. No code change; no test applicable (a spec-text-only gap).

## Summary

| Finding | Severity | Disposition |
|---|---|---|
| 1 — malformed-action detection bypassable for non-trade tags | CRITICAL | Fixed |
| 2 — ultimatum outcome-reduction asymmetry has no runtime guard | WARNING | Fixed |
| 3 — dangling cross-reference to a nonexistent spec heading | SUGGESTION | Fixed |
| 4 — measurement_validity claim broader than implementation | SUGGESTION | Fixed |

Nothing was refuted — every finding in `docs/negarena_review_claude.md` reproduced or confirmed as
described. Nothing was deferred to the ledger from this review: findings 1, 3, 4 are adapter-code
or adapter-doc gaps we own outright, and finding 2's adapter-owned half (missing runtime guard) was
likewise fixed directly; its upstream-defect half (the asymmetric `after_game_ends()` reduction
itself) was already ledgered in `ledger_entries/negarena.md` before this pass and needs no new
entry, since upstream is read-only and the ledger entry already documents it accurately.

Full family test suite + `tests/test_shared_runner_smoke.py`, bridge-backed
(`AEREAD_NEGARENA_BRIDGE_PYTHON` exported): **77 passed, 0 skipped, 0 failed** (304.35s) — 74
pre-existing plus 3 new regression tests (2 for CRITICAL-1, 1 for WARNING-2). Same set with the
bridge interpreter unset: **40 passed, 37 skipped, 0 failed** (bridge-dependent tests, including
the 3 new ones, skip cleanly).
