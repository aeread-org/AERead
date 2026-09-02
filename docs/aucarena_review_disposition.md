# aucarena adapter — review disposition

Reviews consulted: `docs/aucarena_review_claude.md` (present).
`docs/aucarena_review_codex.md` does not exist in this worktree — handled
gracefully, no codex findings to disposition.

Each finding below was independently re-verified against the code (not just
re-read from the review) before any fix was applied.

## WARNING 1 — `aucarena_hammer_rule`'s accept/reject partition read
`record.envelope.valid` instead of independently recomputing it

**Disposition: fixed.**

Verified: `score_hammer_rule` (`src/aeread_families/aucarena/measurement.py`,
pre-fix lines ~522-526) built `round_bids` by filtering
`phase_instance.actions` on `record.envelope.valid`, and `envelope.valid` is
computed by `environment.py`'s own `legal()`/`parse_action()` gate
(`scheduler.py:570`), not re-derived independently by this leaf. Confirmed
the module docstring's "independently reproduced ... never from
`environment.py`'s own live state" claim held for the hammer/tie-break
arithmetic but not for which bids were even considered.

Fix: added `_independently_accepted_bid` (`measurement.py`), which
recomputes acceptance from each action's own recorded `record.parse` plus a
fresh `vendored.bid_sanity_check` call against the action's frozen pre-round
observation — the same recompute `score_bid_legality` already performs,
reused here so `score_hammer_rule`'s independence claim no longer rests on
`environment.py`'s legality gate having already run correctly.
`score_hammer_rule` now builds `round_bids` from
`_independently_accepted_bid(record)` instead of `record.envelope.valid`,
and reads the bid price from `record.parse.action["bid_price"]` instead of
`record.envelope.action["bid_price"]`.

Test added:
`tests/test_aucarena_parity.py::test_hammer_rule_does_not_silently_trust_a_forged_envelope_valid_flag`
— forges an `envelope.valid=True` for golden 3's genuinely illegal bid (150,
below the item's starting bid) plus the round consequences a buggy
`step()` would have derived from trusting that forged flag, and confirms
`score_hammer_rule` still raises `AucArenaMeasurementError` on its own,
without relying on `aucarena_bid_legality` having caught the bug first.

## SUGGESTION 2 — `parse_action`'s `"-1" in response` substring check can
misparse a well-formed negative-looking bid text, inherited from upstream

**Disposition: fixed** (documentation only, no behavior change).

Verified: `environment.py:327-328` does perform a substring check
(`"-1" in response`), matching upstream's own `if '-1' in result:`
(`auctioneer_base.py:196`) verbatim — this is a faithful reproduction of an
upstream quirk, not a defect introduced by this adapter, and none of the
five goldens' scripted policies emit a response containing a literal `-1`
substring for a non-withdraw reason. The reviewer's own text already
characterizes this as correctly documented and not requiring a behavior
change (changing the substring semantics would break upstream parity, which
this adapter must preserve exactly).

Action taken: added an inline comment at `environment.py`'s `"-1" in
response` branch spelling out the substring-vs-exact-match caveat
explicitly (previously only the module docstring's general "-1 sentinel"
description existed, without calling out the substring nuance), so a future
scripted-policy author is warned before writing a policy response that
contains a literal `-1` substring for a non-withdraw reason. No test added:
this is a comment-only change with no reachable behavior to regress, and no
existing golden exercises the edge case.

## SUGGESTION 3 — `docs/aucarena_adapter_spec.md`'s "Governing facts" say
`docs/benchmark_qc.md` does not exist in this repo

**Disposition: deferred-to-ledger** (already logged).

Verified: `docs/benchmark_qc.md` does not exist anywhere in this worktree
(`ls docs/benchmark_qc.md` fails), confirming the finding. This is a
repo-wide documentation gap in the shared QC-gate contract, not a defect in
the aucarena adapter's own code — the adapter's spec already states this
honestly rather than silently inventing a citation. A ledger entry for
exactly this gap already exists in `ledger_entries/aucarena.md` (first
entry, severity `medium`, "The aucarena workflow brief instructs
implementers to read `docs/benchmark_qc.md` ... No such file exists
anywhere in the repo"), logged during an earlier milestone. No duplicate
entry added; the existing entry was re-verified as still accurate and still
open.

## SUGGESTION 4 — Golden 4 never asserts `agent.profit` is untouched

**Disposition: fixed.**

Verified: `tests/test_aucarena_environment.py`'s
`test_golden_4_agents_gibberish_is_malformed_not_illegal` asserted
`agent.budget == 3200` and `winner == "field_high"` but not
`agent.profit == 0`, unlike golden 3's equivalent test. Logically redundant
(profit can only change via `win_bid`, unreachable given `winner ==
"field_high"` is independently asserted) but worth the one-line addition
for symmetry and to make the "zero mutation" claim equally explicit for
both invalid-action goldens, as the reviewer suggested.

Fix: added `assert result.outcome["seats"]["agent"]["profit"] == 0` to
`test_golden_4_agents_gibberish_is_malformed_not_illegal`.

## Summary

| # | Severity | Disposition |
|---|---|---|
| 1 | WARNING | fixed |
| 2 | SUGGESTION | fixed (doc-only) |
| 3 | SUGGESTION | deferred-to-ledger (pre-existing entry) |
| 4 | SUGGESTION | fixed |

Fixed: 3 (findings 1, 2, 4). Refuted: 0. Deferred: 1 (finding 3).

Re-ran after all fixes: family test files (`tests/test_aucarena_cases.py`,
`tests/test_aucarena_environment.py`, `tests/test_aucarena_measurement.py`,
`tests/test_aucarena_parity.py`, `tests/test_aucarena_replay.py`,
`tests/test_aucarena_vendored_upstream.py`) plus
`tests/test_shared_runner_smoke.py`, all green.
