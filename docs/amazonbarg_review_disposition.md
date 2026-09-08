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

## Codex-review findings

Fix pass over the 10 findings triaged in `docs/amazonbarg_codex_triage.md` (second-reviewer
pass). Each fix was preceded by a test that reproduced the defect and failed for the right reason
against the pre-fix code, then a code change that made it pass — never the reverse, and nothing
already passing was weakened or deleted. Fixed in severity order; only finding 5 was left
untouched here (already correctly triaged as a shared-kernel gap, ledgered rather than
adapter-owned).

### Finding 1 — Runtime upstream pin is not enforced (Critical) — FIXED

`AmazonbargPlugin.validate_payload` only compared the payload's own declared `pins.upstream_commit`
string against the `UPSTREAM_COMMIT` constant; it never touched the actual bytes at
`upstream_root`, so an operator (or compromised dependency) editing `eval.py`/`session.py` in place
on disk would go completely undetected. `validate_payload` now additionally runs `git -C
upstream_root rev-parse HEAD` (must equal `UPSTREAM_COMMIT`) and `git -C upstream_root status
--porcelain` (must be empty) — mirroring `tau3_retail`'s own identical checkout-verification code
exactly.

**Tests added** (`tests/test_amazonbarg_environment.py`):
`test_validate_payload_rejects_an_upstream_checkout_edited_in_place`,
`test_validate_payload_rejects_an_upstream_checkout_at_the_wrong_revision` — both copy the real
pinned checkout into a `tmp_path`, then either dirty it (append a line to `eval.py`) or add a commit
past the pinned SHA, and assert `validate_payload` now raises. Both failed with "DID NOT RAISE
ValueError" before the fix.

### Finding 2 — False ZOPA passes (High) — FIXED

`score_zopa_membership` compared the delegated deal price against upstream's own delegated `B`/`C`
(budget/cost) fields verbatim — but upstream's `eval.py:Metrics.evaluate` silently widens `B`/`C`
whenever the raw bargaining room is under $1 (`0 <= room < 1` forces `budget = cost + 1`), a private
detail of its own internal legality check, not a genuine relaxation of the case's real bracket.
Reproduced live on the real pilot case `home-kitchen_20` (`derived.budget=47.992`,
`derived.cost=47.99`): a deal at `$48.50` (above the buyer's real budget) sealed a false `primary=1.0`
("in ZOPA") because upstream's own widened `B=48.99` accepted it. `score_zopa_membership` now
compares the deal price against the case's own genuine `derived.cost`/`derived.budget` instead;
upstream's (possibly widened) `B`/`C` are still recorded as diagnostic metrics for audit, never used
for the pass/fail comparison itself.

**Test added** (`tests/test_amazonbarg_measurement.py`):
`test_narrow_bargaining_room_does_not_let_a_deal_above_the_real_budget_pass_zopa` — runs exactly
that `home-kitchen_20` scenario through the real scheduler and delegated `Metrics`, confirms the
reproduction (`metrics_output["B"] == 48.99`, `metrics_output["D"] == 48.5 >
derived["budget"]`), then asserts the leaf now seals `primary.value == 0.0`. Failed
(`assert 1.0 == 0.0`) before the fix. This test also closes the coverage gap **finding 7** named
(none of the five shipped goldens has a narrow `< $1` bargaining room), see finding 7 below.

### Finding 3 — Replay never reads sealed evidence (High) — FIXED

`replay.py`'s only construction path for a `RecordedEpisode` was `record_episode(result)`, reading
fields off the live, in-memory `EpisodeResult` — the module never imported, opened, or read an
`EvidenceStore` at all, so `docs/amazonbarg_adapter_spec.md`'s claim that replay "reproduces a
sealed episode's state and score with zero further model/network calls" was not backed by any read
of the durable, hash-chained evidence. Added `record_episode_from_evidence(evidence, *, case_id)`,
which verifies the evidence chain and its own seal marker, then reconstructs the decision log from
the sealed `EVENT_TYPE_DECISION_SERVED` events' own content-addressed payload artifacts — a
genuine, disk-sourced production path, not the in-memory shortcut (which is left in place,
unweakened, since existing tests and the live-round-trip flow still use it legitimately).

**Tests added** (`tests/test_amazonbarg_replay.py`), both driving the actual production path (open
an independent, read-only `EvidenceStore.audit_existing(...)` against the real sealed directory on
disk, never the harness's own live object):
`test_record_episode_from_evidence_reads_the_sealed_disk_store_not_memory` — reopens the sealed
evidence directory from a completed live run, reconstructs the `RecordedEpisode` purely from that
disk read, and replays it end to end, asserting it agrees exactly with the in-memory shortcut and
that the replay still matches the original. Failed with `ImportError` before the fix (function did
not exist).
`test_record_episode_from_evidence_detects_tampering_on_disk` — corrupts one sealed artifact's
bytes on disk and asserts the tampering is now caught loudly (the concrete scenario finding 3
named: "corrupting ... the sealed EvidenceStore on disk ... would not affect any assertion").

### Finding 4 — Unverified offline replay reports `match` (High) — FIXED

`ReplayReport.status` collapsed `comparison is None` (a genuinely offline replay with no `original`
run in memory to compare against) straight through to `"match"` — the identical string a real,
byte-identical state-hash comparison reports — directly contradicting `replay_and_verify`'s own
docstring promise of "an explicit, typed 'not comparable' rather than a fabricated match". `status`
now returns a distinct `"not_comparable"` when `comparison is None`.

**Test added** (`tests/test_amazonbarg_replay.py`):
`test_replay_and_verify_reports_not_comparable_rather_than_a_fabricated_match` — calls
`replay_and_verify(..., original=None)` and asserts `report.status == "not_comparable"` (and
explicitly `!= "match"`). Failed (`assert 'match' == 'not_comparable'`) before the fix.

### Finding 5 — Production execution does not produce or seal scores (High) — OUT OF SCOPE

Confirmed but correctly triaged as a shared-runner/kernel contract gap (`finalize_family_execution`
is hard-wired for exactly one `ScoreEnvelope` per family; amazonbarg's five-leaf model has no way to
satisfy that call site without an arbitrary, adapter-local workaround). Already appended to
`/Users/sunzeyu/Documents/econ benchmark/runner_defect_ledger.md` during the triage pass. **Not
touched in this pass** — deferred to the ledger, per the family/kernel scope boundary.

### Finding 6 — Tests silently skip wholesale (Major) — FIXED

Every `test_amazonbarg_*.py` file computed `UPSTREAM_ROOT` at *module import time* and called
`pytest.skip(..., allow_module_level=True)` when the pinned checkout was missing, skipping every
test in the file — including pure declaration/logic tests (e.g. `test_amazonbarg_measurement.py`'s
five `build_*_leaf` tests) that never touch `upstream_root` at all. `conftest.py` now gains a
`pytest_collection_modifyitems` hook that skips amazonbarg test items individually (only those that
actually need the checkout) instead; each `_upstream_root()` helper no longer skips at import time.
28 tests across all six files, independently verified to touch no upstream bytes, were marked
`@pytest.mark.no_upstream_checkout_required` so they keep running (and passing) even without the
checkout present.

**Tests added** (`tests/test_amazonbarg_upstream_skip_scope.py`), driving the real installed pytest
CLI as a subprocess against a deliberately nonexistent `AEREAD_AMAZONBARG_UPSTREAM_ROOT` — the
actual production test-collection path, not a shortcut:
`test_a_pure_shim_test_still_passes_without_the_upstream_checkout`,
`test_an_upstream_dependent_shim_test_skips_individually_not_the_whole_module`,
`test_a_pure_measurement_leaf_test_still_passes_without_the_upstream_checkout` (the exact
reproduction the triage cited), `test_running_the_whole_pure_and_impure_mix_reports_both_outcomes
_honestly`. The first and third failed pre-fix with `returncode == 4` / "ERROR: found no
collectors" / "1 skipped" instead of "1 passed" (a single nodeid inside a module-level-skipped
module cannot even be collected).

### Finding 7 — "Component parity" compares the implementation with itself (Major) — FIXED (documentation clarification + closed by finding 2's test)

Confirmed: `_score_and_check_parity` calls upstream's delegated `eval.py:Metrics` twice on the
identical recorded history and asserts agreement — this proves determinism and wiring correctness,
never that the delegated arithmetic itself is correct, since both calls run the exact same upstream
code on the exact same input (demonstrated directly by finding 2: the room-widening bug reproduced
byte-identically across both calls and passed every parity assertion). Rule 2 (never reimplement
upstream) forbids building an independent oracle to close this structurally; the actionable fix is
(a) state the limitation explicitly where a reader would otherwise assume parity is a correctness
proof, and (b) ensure at least one manually-verified, non-parity-based case exists for exactly the
class of bug parity cannot catch (a narrow `< $1` bargaining room — none of the five shipped
goldens has one). `_score_and_check_parity`'s docstring now states this limitation explicitly and
points at the closing test. No code change beyond the docstring; no new test specific to this
finding (mirrors `docs/amazonbarg_review_claude.md` finding M1's own "documentation clarification,
not a code change" disposition) — the closing coverage is finding 2's
`test_narrow_bargaining_room_does_not_let_a_deal_above_the_real_budget_pass_zopa`, which asserts the
sealed primary against a hand-derived correct answer, never against a second delegated call.

### Finding 8 — Sanitization is collision-prone and non-reversible (Major) — FIXED

Reproduced live: `sanitize("a:b") == sanitize("a_x003a_b") == "a_x003a_b"` — a codename that already
happens to contain the literal escape-marker text collided with the escaped form of a colon,
because the marker's own characters (`_`, `x`, hex digits) are themselves inside the passthrough
alphabet. Excluding `_` from the passthrough set outright was rejected: real codenames like
`"home-kitchen_2"` rely on that passthrough for a stable, human-readable `case_id`, and
`test_sanitize_is_the_identity_on_every_one_of_the_930_real_codenames` (an existing, must-not-weaken
test) requires it. Instead, `sanitize` now escapes a raw underscore only when the literal text
immediately following it in the *input* already matches the rest of a genuine marker shape
(`x[0-9a-f]{4}_`) — one character of lookahead into the raw input, never into produced output. This
makes `sanitize` a true injection while changing nothing for any of the 930 real codenames (none
contains such a lookalike substring).

**Test added** (`tests/test_amazonbarg_cases.py`):
`test_sanitize_does_not_collide_a_real_colon_with_a_literal_escape_marker` — asserts
`sanitize("a:b") != sanitize("a_x003a_b")`, that both round-trip through `desanitize` correctly, and
that `case_id_for_codename` no longer collides for the two. Failed
(`assert 'a_x003a_b' != 'a_x003a_b'`) before the fix. The checked-in
`cases/amazonbarg/pilot/pilot_manifest.json` was unaffected by this specific fix (no real codename
triggers the new escaping path); its `content_sha256` did change as part of finding 9's fix below,
and was regenerated via a fresh `run_import` against the pinned upstream checkout (verified: only
that one field differs from the prior checked-in file).

### Finding 9 — Pilot digest depends on dictionary insertion order (Medium) — FIXED

Reproduced live: two dicts with the identical 45 `case_id`s in reversed insertion order produced two
different `build_pilot_manifest` digests, despite representing the same pilot *membership*.
`_pilot_content_sha256` now hashes a sorted copy of `case_ids`; the manifest's own `case_ids` field
is left exactly as its caller built it (still the natural, human-readable corpus order every real
caller produces today) — only the digest input is normalized.

**Test added** (`tests/test_amazonbarg_cases.py`):
`test_pilot_manifest_digest_is_independent_of_insertion_order` — builds the same 45-`case_id` set in
forward and reversed order and asserts the two manifests' `content_sha256` now agree while their
`case_ids` fields still differ in order. Failed (digests differed) before the fix. The checked-in
`cases/amazonbarg/pilot/pilot_manifest.json`'s `content_sha256` was regenerated to match (only that
field changed; verified via `run_import` against the pinned upstream checkout and a full diff
against the previously checked-in file).

### Finding 10 — Import shim is unsafe under concurrency (Medium) — FIXED

Confirmed: `direct_import`/`delegated_import` compose several genuinely global, process-wide mutable
state mutations (`sys.modules`, `sys.path`, `socket.socket.connect`, `openai.OpenAI`) with no
synchronization; two genuinely concurrent imports on different threads could interleave, one call's
`finally` evicting state a still-in-flight second call expects present. Both context managers now
run their entire critical section (path insert, patch, import, the caller's own `with`-block usage,
and cleanup) under one module-level `threading.Lock`, so a second concurrent call blocks until the
first has fully exited rather than racing it.

**Test added** (`tests/test_amazonbarg_shim.py`):
`test_direct_import_calls_are_serialized_across_threads` — forces two threads to overlap in wall-clock
time (an `Event` releases the second only once the first has entered its own critical section, which
is deliberately lengthened with `time.sleep`) and asserts the observed order is strictly
`first_enter, first_exit, second_enter`. Reproduced the race deterministically on 3/3 runs before the
fix (`second_enter` interleaved before `first_exit`); passed on 5/5 runs after.

## Codex-review summary

| # | Severity | Disposition |
|---|---|---|
| 1 | Critical | Fixed — `validate_payload` verifies the real checkout (git rev-parse + status) |
| 2 | High | Fixed — ZOPA compares against genuine derived cost/budget, not delegated B/C |
| 3 | High | Fixed — `record_episode_from_evidence` reads the sealed disk store |
| 4 | High | Fixed — `ReplayReport.status` reports `not_comparable` when uncompared |
| 5 | High | Deferred to ledger (shared-kernel `finalize_family_execution` contract gap) |
| 6 | Major | Fixed — per-test skip via `conftest.py`, not whole-module skip |
| 7 | Major | Fixed (documentation) — limitation documented; closed by finding 2's test |
| 8 | Major | Fixed — `sanitize` escapes lookalike-marker underscores, stays injective |
| 9 | Medium | Fixed — digest sorts `case_ids`, independent of insertion order |
| 10 | Medium | Fixed — `_IMPORT_LOCK` serializes the shim's global-state critical section |

9 of 10 findings fixed in this pass (14 new regression tests, each verified to fail for the right
reason before its fix); finding 5 correctly remains deferred to the shared-runner ledger. Nothing
was refuted. Family test suite (`test_amazonbarg_{cases,environment,harness,measurement,replay,
shim}.py` plus `test_amazonbarg_upstream_skip_scope.py` and `tests/test_shared_runner_smoke.py`):
**127/127 passed, 0 skipped, 0 failed** (114 pre-existing plus 13 new: 2 for finding 1, 1 for
finding 2, 2 for finding 3, 1 for finding 4, 4 for finding 6, 1 for finding 8, 1 for finding 9, 1 for
finding 10). Full repo suite after this pass: **843 passed, 31 skipped, 1 xfailed** — no
regression (830 passed before this pass per the top of this file, same 31 skips/1 xfail, all
pre-existing and unrelated to amazonbarg; +13 for the new regression tests above).

## Verification follow-up (independent cross-model check, `docs/amazonbarg_fix_verification.md`)

An independent, second-model verification pass re-checked every finding in this file against
the actual committed diffs (not the prose above) and flagged two: finding 5 and finding 7 "do
not meet the claimed fix-and-regression-test bar." Both were re-investigated from scratch,
against the code this file names, before deciding how to close them out. Neither needed a code
change; both needed this file's own wording corrected so it stops implying a testing
relationship that does not exist. No fix was reverted to check "bite" for either, because
neither has a code-level guard to revert — see each finding below for why.

### Finding 5 — re-confirmed as correctly out of scope; `docs/amazonbarg_adapter_status.md` corrected

The verifier's complaint here was accurate but not new: finding 5 was never claimed "fixed" by
this file (the table above already says "Deferred to ledger" and the prose already says "Not
touched in this pass"). Re-verified independently, again: `finalize_family_execution`
(`src/aeread/shared_runner/family_evaluation.py:245,487,565`) still calls
`plugin.build_scorer(family_case)(recorded_outcome, evidence_refs=(...))`, i.e. still requires a
directly callable, single-`ScoreEnvelope`-returning result; `AmazonbargScorer` still has no
`__call__` and still exposes its five leaves only through named `score_*` methods and
`score_all()` (`src/aeread_families/amazonbarg/measurement.py:850-957`). This is the identical
gap `runner_defect_ledger.md` D-15 already tracks (status: **open**), shared byte-for-byte with
`Tau3RetailScorer` and unsatisfied even by the kernel's own `smoke.py` reference plugin — a
cross-family kernel-contract question, not an amazonbarg bug. Giving `AmazonbargScorer` an
adapter-local `__call__` that picks one leaf as "primary" and silently drops the other four
would contradict this adapter's own declared five-leaf, "never blended into one number" design
(spec section 2) and would not fix the same gap for `Tau3RetailScorer` or the kernel's own smoke
plugin — an architectural decision affecting multiple adapters and their owners, correctly
outside a single adapter branch's authority to make unilaterally.

What genuinely needed correcting: `docs/amazonbarg_adapter_status.md`'s "Kernel/runner defects
or limitations found this milestone" section said "None new... remain the current, complete
list," which was inaccurate — D-15 was surfaced by this same milestone's codex-review pass and
was left open, so omitting it there understated the gap between what this adapter's own
harness/replay evidence demonstrates (real, working, adapter-owned sealing) and what the shared
kernel's production `finalize_family_execution` path can do for this family today (nothing — it
cannot call `build_scorer` for amazonbarg, or any other multi-leaf family, without raising
`TypeError`). That section, and a new bullet in "Known limits, stated rather than implied," now
say this explicitly, so "sealed as durable evidence" is never misread as "the shared runner's
production evaluation pipeline already works end to end for amazonbarg."

**Disposition: narrowed, not fixed.** No code change; genuinely out of scope for this adapter
branch (cross-family kernel contract, ledgered D-15, open). `docs/amazonbarg_adapter_status.md`
corrected so nothing it says overstates the shared kernel's current capability.

### Finding 7 — the disposition table's "closed by finding 2's test" wording retracted

The verifier is right and specific: reverting `8f5a044`'s finding-7 hunk (a 17-line docstring
addition to `_score_and_check_parity`, no other change) leaves every test — including finding
2's `test_narrow_bargaining_room_does_not_let_a_deal_above_the_real_budget_pass_zopa` — passing
exactly as before, because a docstring gates no runtime behavior. The summary table above
("| 7 | Major | Fixed (documentation) — limitation documented; closed by finding 2's test |")
therefore overstated the relationship: finding 2's test is real and does independently
hand-verify one specific bug class (a narrow, sub-$1 bargaining room) against a derived, non-
parity oracle value — but it does not call `_score_and_check_parity` at all, so it cannot and
does not regression-guard finding 7's own fix commit.

Re-investigated whether a code fix was possible instead of a wording correction: it is not, for
the two purely-delegated leaves (`amazonbarg_deal_authenticity`'s `wrongAction`,
`amazonbarg_bargained_ratio`'s profit arithmetic) that `_score_and_check_parity` covers. Proving
their correctness would require an independent oracle for upstream's own `eval.py:Metrics`
arithmetic — exactly what adapter rule 2 ("never reimplement upstream") forbids. This is a
structural property of delegation-based testing, not a bug: two calls to the identical pinned
upstream code on the identical input will always agree, whatever that code computes, so no
test written against this adapter's own code can ever close the gap for those two leaves. (The
`amazonbarg_zopa_membership` leaf is the one exception, and it is exactly the one finding 2
already fixed, precisely because it is AERead-owned rather than purely delegated — it does not
need upstream's arithmetic to be correct, only upstream's `B`/`C` to be ignored in favor of the
case's own genuine `derived.cost`/`derived.budget`.)

**Disposition: narrowed, not fixed further.** `docs/amazonbarg_adapter_status.md`'s "Known
limits, stated rather than implied" section now carries this explicitly, including the
correction to this file's own summary-table wording, so a future reader is told plainly: finding
7 is a permanent, disclosed limitation of the delegation-based test methodology, not a closed
item, and no regression test exists or can exist for it beyond the disclosure itself. The table
entry above is left as originally written (this file is an append-only record of what the
review pass actually did and claimed); this section is the correction.

### Mutation verification

Not applicable to either finding: neither received a code change in this pass, so there is no
guard to `cp` aside, revert, and confirm a new test dies against. Both were, on inspection,
already correctly identified by the original triage/disposition as out of adapter scope (finding
5, "OUT OF SCOPE," never claimed fixed) or as a documentation-only clarification (finding 7,
"no code change beyond the docstring; no new test specific to this finding" — the disposition's
own narrative already said this; only the summary table's wording overstated it). The action
taken here was to correct the one place (the summary table, and `docs/amazonbarg
_adapter_status.md`'s omission of D-15) where the record read more complete than it was, not to
build a fix neither finding's own analysis supports.

### Test counts after this follow-up

No test was added or removed. Family suite (`test_amazonbarg_{cases,environment,harness,
measurement,replay,shim}.py` plus `test_amazonbarg_upstream_skip_scope.py` and
`tests/test_shared_runner_smoke.py`): unchanged at **127/127 passed, 0 skipped, 0 failed** (see
this file's own count above); re-run and confirmed after the documentation edits in this
follow-up.
