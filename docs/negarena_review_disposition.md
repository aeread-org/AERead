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

## Second-review findings

Source: `docs/negarena_codex_triage.md`, the triage of the codex (cross-model) adversarial pass
recorded in `docs/negarena_review_codex.md`. Declared **5 confirmed, 0 refuted, 0 kernel**. Every
finding below was independently re-verified against the code before any fix was made, in the
severity order the triage doc itself uses (critical, high, high, medium, low). Nothing in this
pass was deferred to `runner_defect_ledger.md`: the triage declared zero kernel-classified
findings, and none of the five turned out to implicate `src/aeread/shared_runner/` itself —
Finding 1's call site (`family_evaluation.py::finalize_family_execution`) is the kernel's fixed,
generic contract; the gap was that the adapter's own scorer did not satisfy it, which is an
adapter-owned fix.

### Finding 1 (CRITICAL) — production scorer is not callable

**Disposition: FIXED.**

**Confirmed independently.** Reproduced the exact `TypeError: 'NegarenaScorer' object is not
callable` the finding describes by driving a real episode through the real scheduler, a genuine
`resolve_run_plan`-sealed `RunPlan`, and calling `finalize_family_execution` itself (the actual
production call site named by the finding) — every existing negarena test before this pass called
`score_seat_outcome`/`score_agreement_reached` directly instead, which is exactly the bypass the
finding calls out.

**Fix.** `NegarenaScorer.__call__` (`measurement.py`) now conforms to the shared kernel's
single-outcome scorer signature. The generic call site
(`plugin.build_scorer(family_case)(outcome, evidence_refs=...)`) carries no seat/opponent pairing
context real per-seat scoring needs, so `__call__` reports the primary leaf as a typed
`invalid_measurement` (never a fabricated per-seat score) rather than crashing;
`score_seat_outcome`/`score_agreement_reached` remain the real per-seat/agreement entry points for
callers that have that context (mirroring `tau3_retail`'s identical `Tau3RetailScorer`
convention). Getting a negarena `CellExecution` through that call path at all also required
renaming `NegarenaPlugin.initial_state`'s second parameter `cell -> run` (`family_evaluation.py`
calls it by keyword) and declaring `reference_provider_ids` in `family_manifest`'s scoring section
for every implementation id a measurement leaf references (without it, `EvaluationReceipt`'s own
pin cross-check rejected every negarena receipt outright).

**Test added.** `tests/test_negarena_kernel_finalizer.py::test_finalize_family_execution_does_not_crash_and_seals_a_typed_receipt`
— drives the real scheduler and the real `finalize_family_execution`, not a shortcut. Verified
failing first: reverting `measurement.py` to its pre-fix state reproduces
`TypeError: 'NegarenaScorer' object is not callable` at `family_evaluation.py:245`, exactly as the
finding describes.

### Finding 2 (HIGH) — replay record is not bound to its execution inputs

**Disposition: FIXED.**

**Confirmed independently.** Confirmed `RecordedEpisode` serialized only `case_id`/`decisions` and
that `replay_episode` validated only `recorded.case_id == case.case_id` — a case re-authored with
different valuation/upstream pin but the same `case_id`, paired with a newly matching `PlanCell`,
would replay silently against the wrong inputs with no report that the original execution was not
what actually ran.

**Fix.** `replay.py`'s `RecordedEpisode` now seals `case_sha256` (the case's own
`content_sha256`) and `cell_sha256` (a content hash of the whole `PlanCell` — covers
`profile_by_seat`/seeds/replicate, not just `cell_id`) at `record_episode()` time.
`replay_episode()` rejects a recording whose sealed hashes do not match the case/cell it is asked
to replay against, with a typed `ReplayError` naming which one diverged, before any bridge call is
made.

**Tests added**, both driving `replay_episode` itself (the production replay entry point every
other test in the module also calls, not a hand-wired shortcut):
`tests/test_negarena_harness.py::test_replay_rejects_a_case_with_the_same_case_id_but_different_content`
(a re-authored case, same `case_id`, paired with a cell rewritten to still agree with it — so only
`replay_episode`'s own sealed-recording check can catch the substitution, not the scheduler's
`_validate_cell_case`) and
`::test_replay_rejects_a_cell_with_a_different_opponent_profile` (same case, a cell rebuilt with a
different `profile_by_seat`). Both fail against the pre-fix `record_episode`/`replay_episode`
signatures with `TypeError: record_episode() missing 2 required keyword-only arguments` (the
three pre-existing call sites needed the same `case=`/`cell=` update, and one hand-built
`RecordedEpisode(...)` construction needed the two new required fields).

### Finding 3 (HIGH) — family harness seals an incomplete evidence lifecycle

**Disposition: FIXED.**

**Confirmed independently.** Confirmed `ScriptedNegarenaHarness` appended only
`negarena_decision_served` events and implemented none of the scheduler lifecycle callbacks for
phase boundaries, transitions, terminal state, or outcome — an accepted negotiation's sealed
evidence contained only served responses, with no sealed transition, settlement result, score, or
evidence reference proving how the reported values were derived.

**Fix.** `harness.py::record_full_evidence_lifecycle` translates an already-completed
`EpisodeResult` into the same durable event types the kernel's own `MinimalChatExecutor` would
append live (phase/transition/terminal/outcome), recomputing nothing — called before
`finalize_family_execution` appends `score_recorded` and seals, so a negarena receipt now carries
the complete lifecycle Finding 1's fix also depends on reaching.

**Test added.** `tests/test_negarena_kernel_finalizer.py::test_finalize_family_execution_seals_the_complete_evidence_lifecycle`.
Verified failing first: reverting `harness.py`/`environment.py` to their pre-fix state makes the
module fail to even collect (`ImportError: cannot import name 'record_full_evidence_lifecycle'`).

### Finding 4 (MEDIUM) — an unperformed comparison is reported as a match

**Disposition: FIXED.**

**Confirmed independently.** Reproduced `ReplayReport(..., comparison=None).status == "match"` —
`status` returned `"mismatch"` only for an explicit nonmatching comparison and fell through to
`"match"` for every other state, including a comparison that never ran (no `original` supplied to
`replay_and_verify`). The pre-fix test at the finding's cited location asserted exactly this
returned `"match"`, despite its own comment calling the state "not comparable."

**Fix.** `ReplayReport.status` (`replay.py`) now returns a third, explicit `"not_compared"` when
`comparison is None`, and only reports `"match"`/`"mismatch"` when a comparison actually ran.

**Tests.** The pre-existing
`tests/test_negarena_harness.py::test_replay_and_verify_ties_replay_comparison_and_scoring_together`
had its `report_no_original.status == "match"` assertion corrected to
`report_no_original.status == "not_compared"` (that assertion was the bug the finding names, not a
weakening — it now asserts the behavior the finding says should hold, and drives
`replay_and_verify` itself, the production entry point, with no `original` supplied). A new, bridge-free
unit test was also added:
`::test_replay_report_status_is_not_compared_when_no_comparison_was_made`, constructing a
`ReplayReport` directly so this specific property holds even when no bridge interpreter is
provisioned. Both fail against the pre-fix `status` property (the corrected assertion demands
`"not_compared"`, which the pre-fix property never returns).

### Finding 5 (LOW) — provisioning uses the wrong default upstream path

**Disposition: FIXED.**

**Confirmed independently.** From this worktree, `tools/negarena_bridge`'s pre-fix
`../../../..` resolved to `/Users/sunzeyu/Documents/econ benchmark/AERead/upstream-negarena` (a
path that does not exist), not the real sibling checkout at
`/Users/sunzeyu/Documents/econ benchmark/upstream-negarena`, because a linked git worktree
(`AERead/.worktrees/negarena/tools/negarena_bridge`) sits two levels deeper than a main checkout
(`AERead/tools/negarena_bridge`) — a fixed `..` count cannot resolve correctly from both. Confirmed
the missing-directory branch only prints a note and continues (exits 0), rather than failing, so
an operator running the script from this worktree without setting
`AEREAD_NEGARENA_UPSTREAM_ROOT` would get a script that reports success without ever verifying
that upstream's game classes import.

**Fix.** `provision.sh` now resolves the default via a new `default_upstream_root()` function that
walks up from `${HERE}` to the ancestor directory literally named `AERead`, then descends into
`upstream-negarena` next to it — correct regardless of how many directories deep the checkout
running the script happens to be nested (main checkout or any linked worktree). A
`--print-default-upstream-root` introspection flag prints the resolved default and exits without
creating a venv or touching the network, so this logic is testable in isolation.

**Tests added**, both bridge-free and network-free:
`tests/test_negarena_provisioning.py::test_default_upstream_root_matches_the_documented_sibling_checkout`
(run from this repo's own real worktree location, must resolve to the documented sibling checkout
every other negarena test/doc already hardcodes) and
`::test_default_upstream_root_agrees_between_a_main_checkout_and_a_worktree` (the same script
copied into two synthetic layouts at different depths, each must resolve to `upstream-negarena`
next to its own `AERead`). Verified failing first against the pre-fix script (which has no
`--print-default-upstream-root` flag at all): both exit with `CalledProcessError` (exit status 2).

### Summary

| Finding | Severity | Disposition |
|---|---|---|
| 1 — production scorer is not callable | CRITICAL | Fixed |
| 2 — replay record is not bound to its execution inputs | HIGH | Fixed |
| 3 — family harness seals an incomplete evidence lifecycle | HIGH | Fixed |
| 4 — an unperformed comparison is reported as a match | MEDIUM | Fixed |
| 5 — provisioning uses the wrong default upstream path | LOW | Fixed |

Nothing was refuted, nothing was deferred to `runner_defect_ledger.md` (0 kernel-classified
findings). A structurally identical instance of Finding 4's bug (`ReplayReport.status` reporting
`"match"` for an unrun comparison) was spotted by inspection in
`src/aeread_families/tau3_retail/replay.py` while confirming this one — out of scope for this
negarena-only pass and left untouched, noted here so it is not lost.

Full family test suite (`test_negarena_cases.py`, `test_negarena_environment.py`,
`test_negarena_harness.py`, `test_negarena_kernel_finalizer.py`, `test_negarena_measurement.py`,
`test_negarena_parity.py`, `test_negarena_provisioning.py`) + `tests/test_shared_runner_smoke.py`,
bridge-backed (`AEREAD_NEGARENA_BRIDGE_PYTHON` exported): **84 passed, 0 skipped, 0 failed**
(358.39s) — 77 pre-existing plus 7 new regression tests (1 for CRITICAL-1's production path, 2 for
HIGH-2, 1 for HIGH-3's production path, 1 for MEDIUM-4, 2 for LOW-5). Same set with the bridge
interpreter unset: **43 passed, 41 skipped, 0 failed** (bridge-dependent tests, including the new
ones that need it, skip cleanly; the two Finding-5 tests and the one pure Finding-4 unit test need
neither the bridge nor the network and run either way).

## Verification follow-up

Source: `docs/negarena_fix_verification.md`, an independent cross-model check of the second-review
fix pass above. It reported Findings 2 and 3 as claimed-fixed-but-genuinely-incomplete, and
Finding 5 as fixed in the code but not protected by its own named tests (both named tests exit via
an introspection flag that never reaches the real assignment the finding was about). Each of the
three was independently re-verified against the code before any further fix was made; per-item TDD
red-first evidence and mutation-test results are below.

### Finding 2 (remaining gap) — replay record still not bound to `cell_id`

**Disposition: FIXED (the genuinely adapter-owned part); one part narrowed as a stated limit.**

**Confirmed independently.** `record_episode` checked `case.case_id != result.case_id` but never
`cell.cell_id != result.cell_id` — a caller could pass `record_episode` a `cell` argument that
never actually produced `result`, sealing a `cell_sha256` from the wrong cell. Neither record time
nor replay time alone would ever catch a *consistently* wrong cell supplied at both points, since
replay only ever compares the sealed hash against whatever cell a later caller happens to supply.

**Fix.** `record_episode` (`replay.py`) now also rejects `cell.cell_id != result.cell_id`,
mirroring the existing case-identity check, before sealing any hash.

**Test added.** `tests/test_negarena_harness.py::test_record_episode_rejects_a_cell_that_did_not_produce_the_result`.
Verified failing first (`Failed: DID NOT RAISE ReplayError`) against the pre-fix `record_episode`.
Mutation-verified: reverting only the new `cell.cell_id != result.cell_id` guard (copy to `/tmp`,
edit, restore) reproduces the same failure; the guard restored, the test passes again.

**Narrowed, not fixed.** The independent check also named a second gap: `RecordedEpisode` seals no
`ImplementationPin`s, so a replay proves case/cell *content* identity but not that the same
family-plugin/scorer/harness/runtime code produced the recording. `PlanCell` itself carries no
pins field (pins live only on `RunPlan`), and `record_episode`/`replay_episode` take a `cell`/
`case`, never a `RunPlan` — closing this would mean threading a `RunPlan` (or its pin tuple)
through both functions' signatures, with no precedent anywhere in this repository (`tau3_retail`'s
own `RecordedEpisode` binds neither content hashes nor pins). This is a shared replay-contract
question, not a negarena-only implementation gap, so it is stated as a known limit in
`docs/negarena_adapter_status.md`'s "Known limits" section rather than fixed here.

### Finding 3 (remaining gap) — the complete evidence lifecycle was only ever sealed by a test's own manual call

**Disposition: FIXED.**

**Confirmed independently.** `record_full_evidence_lifecycle` (added by the second-review fix
pass) was invoked nowhere in production code — the only call site anywhere in the repository was
`tests/test_negarena_kernel_finalizer.py`'s own helper, which called `run_episode` then separately
remembered to call `record_full_evidence_lifecycle` by hand. Nothing enforced that second call; a
real caller reaching `finalize_family_execution` via `ScriptedNegarenaHarness` could forget it and
seal only `negarena_decision_served` events.

**Fix.** `run_scripted_negarena_episode` (`harness.py`) is now the one production entry point this
adapter ships for driving a scripted episode: it drives `ScriptedNegarenaHarness` + `run_episode`
and *always* calls `record_full_evidence_lifecycle` internally before returning, so a caller
reaching a terminated episode through this function has the complete lifecycle by construction, not
by remembering a second call. `test_negarena_kernel_finalizer.py`'s helper (the one place in the
repository that reaches `finalize_family_execution`) was refactored to call this function instead
of hand-wiring `run_episode` + a manual `record_full_evidence_lifecycle` call, so the two
Finding-1/Finding-3 tests already in that module now depend on the production wiring, not a
test-only shortcut.

**Test added.** `tests/test_negarena_kernel_finalizer.py::test_run_scripted_negarena_episode_seals_the_complete_lifecycle_automatically`
— calls only `run_scripted_negarena_episode`, with no manual `record_full_evidence_lifecycle` call
anywhere in the test itself, and asserts the full lifecycle is present. Verified failing first
(`ImportError: cannot import name 'run_scripted_negarena_episode'`) since the function did not yet
exist. Mutation-verified: reverting only the internal `record_full_evidence_lifecycle` call (copy
to `/tmp`, edit, restore) kills all three tests in the module, including
`test_finalize_family_execution_does_not_crash_and_seals_a_typed_receipt` (Finding 1's own test,
now transitively dependent on the same wiring) — restored, all three pass again.

### Finding 5 (test/use-site gap) — the named tests never reached the real assignment

**Disposition: FIXED.**

**Confirmed independently.** Both tests named by the second-review fix pass
(`test_default_upstream_root_matches_the_documented_sibling_checkout`,
`test_default_upstream_root_agrees_between_a_main_checkout_and_a_worktree`) drive only
`--print-default-upstream-root`, which calls `default_upstream_root` directly and exits before the
real, normal-mode `UPSTREAM_ROOT="${AEREAD_NEGARENA_UPSTREAM_ROOT:-$(default_upstream_root
"${HERE}")}"` assignment further down the script ever runs. Reverting only that real assignment
(leaving the helper function and the flag untouched) left both tests green while normal
provisioning broke again — reproduced directly (see mutation below).

**Fix.** `provision.sh` now computes `UPSTREAM_ROOT` exactly once, immediately after
`default_upstream_root` is defined — not a second time, later, right before the import-check gate
as before. A new `--print-resolved-upstream-root` introspection flag prints that same variable and
exits before creating a venv or touching the network; unlike `--print-default-upstream-root`, it
honors an `AEREAD_NEGARENA_UPSTREAM_ROOT` override exactly like the real run does. Because the real
assignment and the flag now read the identical, single-computed variable (not two independently
maintained expressions), a regression in the real assignment cannot avoid being caught by a test
that drives the new flag.

**Tests added**, all network-free: `test_resolved_upstream_root_matches_the_default_when_no_override_is_set`,
`test_resolved_upstream_root_honors_an_explicit_env_override` (a code path
`--print-default-upstream-root` never exercised at all — it always ignored the environment), and
`test_resolved_upstream_root_agrees_between_a_main_checkout_and_a_worktree` (the same synthetic
main-checkout/worktree-depth proof as the pre-existing test, through the real assignment this
time). Mutation-verified directly, reproducing the reviewer's exact scenario: copy the script to
`/tmp`, revert only the real `UPSTREAM_ROOT=...` assignment to the pre-046e293 fixed-depth
expression (`${HERE}/../../../../upstream-negarena`), leaving `default_upstream_root` and both
flags untouched — the two pre-existing `--print-default-upstream-root` tests and the new env-
override test still pass (3 passed), while the two new tests that check the resolved default at
each checkout depth fail exactly as expected (2 failed). Restored, all 5 pass again.

### D-15 (excluded from this pass, per instruction)

`runner_defect_ledger.md` D-15 (kernel expects one `ScoreEnvelope` per family; `NegarenaScorer`
already declares `__call__` for this, per the D-15 census) is latent, not live, and is a shared-
kernel contract gap outside this branch's authority to resolve — no code change was made for it.
Per D-15's own ruling, `__call__` does not silently pick one leaf's real value as primary: it
reports the primary leaf (`negarena_seat_outcome`) as a typed `invalid_measurement` (no fabricated
score) and never returns the second leaf (`negarena_agreement_reached`) at all through this path —
i.e. it surfaces 0 of 2 leaves as real scores. This is now stated plainly, pointing at D-15, in
`docs/negarena_adapter_status.md`'s "Known limits" section.

### Final counts

Full family test suite (`test_negarena_cases.py`, `test_negarena_environment.py`,
`test_negarena_harness.py`, `test_negarena_kernel_finalizer.py`, `test_negarena_measurement.py`,
`test_negarena_parity.py`, `test_negarena_provisioning.py`) + `tests/test_shared_runner_smoke.py`,
bridge-backed (`AEREAD_NEGARENA_BRIDGE_PYTHON`/`AEREAD_NEGARENA_UPSTREAM_ROOT` exported): **89
passed, 0 skipped, 0 failed** (315.28s) — 84 pre-existing plus 5 new regression tests (1 for
Finding 2's remaining gap, 1 for Finding 3's remaining gap, 3 for Finding 5's use-site gap). Same
set with the bridge interpreter unset: **46 passed, 43 skipped, 0 failed**; every skip reason is
"upstream NegotiationArena Python interpreter unavailable" (checked directly with `pytest -rs`) —
none of the 43 skips hides an unrun claim. `test_negarena_provisioning.py`'s 5 tests need neither
the bridge nor the network and always run.

### CI portability fix (PR #33) — machine-specific assertion in `test_negarena_provisioning.py`

CI (both the 3.10 and 3.12 jobs) failed
`test_default_upstream_root_matches_the_documented_sibling_checkout` with
`AssertionError: assert '/home/runner...ream-negarena' == '/Users/sunze...ream-negarena'`.

**Confirmed independently.** `DOCUMENTED_SIBLING_CHECKOUT` was a literal absolute string
(`/Users/sunzeyu/Documents/econ benchmark/upstream-negarena`) hardcoded to the machine the test
was authored on, used as the expected value in two strict-equality assertions
(`test_default_upstream_root_matches_the_documented_sibling_checkout` and
`test_resolved_upstream_root_matches_the_default_when_no_override_is_set`). CI's checkout root is
named `AERead` too (`actions/checkout@v4`'s default `$GITHUB_WORKSPACE` is
`/home/runner/work/AERead/AERead`), so `provision.sh`'s own portable
`default_upstream_root()` walk correctly produced a `.../upstream-negarena` path on CI — the
failure was purely the Python-side hardcoded constant, not a regression in `provision.sh` itself.

**Fix.** `DOCUMENTED_SIBLING_CHECKOUT` is now derived, not hardcoded: a new `_ancestor_named(path,
name)` helper walks up from this test file's own `REPO_ROOT` to the ancestor literally named
`"AERead"` (mirroring `default_upstream_root()`'s identical walk in `provision.sh`, just
implemented independently in Python rather than by invoking the script), then appends
`"upstream-negarena"`. This asserts the *relationship* the docs actually promise (sibling of the
top-level `AERead` directory) rather than one developer's absolute path, so it holds on any
checkout location while still failing if the default stops resolving to that sibling.

**Verified locally with a real CI-shaped layout**, not just reasoning: copied the test file and
`provision.sh` into a synthetic `/tmp/ci_sim/AERead/{tests,tools/negarena_bridge}` tree (no
`/Users/sunzeyu/...` path anywhere, no real `upstream-negarena` sibling directory present) and ran
`pytest tests/test_negarena_provisioning.py` from there directly — all 5 pass.

**Mutation-verified** (per the usual method): copied `provision.sh` to `/tmp`, changed
`default_upstream_root()`'s sibling directory name from `upstream-negarena` to
`some-other-checkout-name`, reran the suite — the 4 tests that assert the sibling-name
relationship failed exactly as expected (`test_resolved_upstream_root_honors_an_explicit_env_override`,
which never touches the default, stayed green); restored from the `/tmp` copy, all 5 pass again.

Scanned the rest of `tests/test_negarena_*.py` for other machine-specific absolute paths
(`grep -rn "/Users/sunzeyu" tests/test_negarena_*.py`): five other files
(`test_negarena_environment.py`, `test_negarena_harness.py`, `test_negarena_measurement.py`,
`test_negarena_parity.py`, `test_negarena_kernel_finalizer.py`) hardcode the same absolute path,
but only ever as an `os.environ.get("AEREAD_NEGARENA_UPSTREAM_ROOT", "<default>")` fallback that is
immediately gated by a real directory-existence check (`pytest.skip(...)` if absent) — the
documented, deliberate bridge-unavailable-skips-cleanly convention this whole family's tests
already follow, not a bare assertion. On CI, where that directory does not exist regardless of
which literal string is used, those five files skip cleanly today and are not a source of failure;
confirmed no other file contains a strict-equality assertion against the hardcoded path (`grep -n
"UPSTREAM_ROOT ==\|== UPSTREAM_ROOT" tests/test_negarena_*.py` returns nothing). Left unchanged.
