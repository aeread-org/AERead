# Termsbench Codex Triage

This is the triage of docs/termsbench_review_codex.md. Its author (Codex) could not write files directly, so this document was transcribed on its behalf.

## Finding 1: Terminal-round walk-away probability is discarded

**Classification:** CONFIRMED

**Location:** `src/aeread_families/termsbench/kernel.py:690-702`; `docs/termsbench_adapter_spec.md:139-145`

**Evidence:** The contract describes each counterpart action as drawing both acceptance and walk-away probabilities before resolving the action. The implementation checks acceptance, but at `round_k >= horizon` returns `timeout` before calculating or sampling `omega_k`.

Concrete failure scenario: with `horizon=10`, `round_k=10`, `delta_bar=-0.2`, `u_accept=0.5`, and `u_walkaway=0.0`, acceptance probability is zero and walk-away hazard is positive. Sampling the hazard would produce `reject`, but the code returns `timeout` without reading `u_walkaway`.

## Finding 2: No-evidence harness does not create an unauditable published result

**Classification:** REFUTED

**Location:** `src/aeread_families/termsbench/harness.py:98-129`; `src/aeread_families/termsbench/harness.py:168-175`; `tests/test_termsbench_harness.py:264-280`; `src/aeread/shared_runner/execution.py:3225-3255`; `src/aeread/shared_runner/family_evaluation.py:232-258`

**Evidence:** The scripted test harness does make its family-specific evidence sink optional, and the cited test deliberately runs the raw scheduler without it. However, that is not the production publication path. `execute_plan_cell` always constructs an `EvidenceStore`, injects it into `AttemptExecutor`, and returns it in `CellExecution`. Finalization then reconstructs the outcome from that evidence, rejects disagreement with the episode result, records the score with an outcome-event reference, and seals the store.

Thus the code supports an evidence-free provider-free scheduler test, but the claim that this permits an unauditable published result is contradicted by the mandatory production execution and finalization path.

## Finding 3: Uncompared offline replay is labelled `match`

**Classification:** CONFIRMED

**Location:** `src/aeread_families/termsbench/replay.py:395-408`; `src/aeread_families/termsbench/replay.py:411-435`

**Evidence:** `replay_and_verify(original=None)` deliberately sets `comparison=None`, but `ReplayReport.status` returns `"mismatch"` only for a present, failing comparison and returns `"match"` for every other state. This contradicts the function's own documentation describing `None` as "not comparable."

Concrete failure scenario: replay a previously recorded or tampered episode without retaining its original `EpisodeResult`. The replay may execute successfully, but no original-versus-replayed comparison occurs; nevertheless, callers receive `status == "match"` and may report equivalence that was never established.

## Finding 4: Timeout reports one more round than was used

**Classification:** CONFIRMED

**Location:** `src/aeread_families/termsbench/environment.py:188-195`; `src/aeread_families/termsbench/environment.py:498-520`; `src/aeread_families/termsbench/environment.py:530-538`; `tests/test_termsbench_environment.py:172-183`

**Evidence:** State begins with `round=1`. Every counterpart transition increments it before handling the resulting decision. When the round-10 counterpart decision is `timeout`, the state is therefore changed to 11, and `terminal()` serializes that next-round cursor directly as `rounds_used`. The cited test explicitly expects `horizon + 1`, preserving the behavior.

Concrete failure scenario: for a horizon-10 episode whose round-10 counterpart action times out, the episode completed ten counterpart rounds but reports `rounds_used=11`, corrupting round-count statistics and any analysis keyed to the declared horizon.

## Finding 5: Difficulty-purity test checks spelling rather than dependency

**Classification:** CONFIRMED

**Location:** `tests/test_termsbench_cases.py:106-115`; `src/aeread_families/termsbench/cases.py:133-170`

**Evidence:** The test checks deterministic output for two immediately repeated calls and searches only the source text of `generate_payload` for three substrings. The current implementation is in fact based on generator draws, but the test does not establish that property transitively through called helpers.

Concrete failure scenario: change `generate_payload` to obtain difficulty from `_score(inputs)`, where `_score` consults a stable post-episode global or cached trajectory. If the helper and local names omit `state`, `outcome`, and `terminal`, both immediate calls return the same value and the source-substring assertion passes, despite difficulty depending on realized play. Conversely, an innocent local name containing one of those substrings would fail without behavioral impurity.

## Finding 6: Replay scoring test uses the same scorer as its golden

**Classification:** CONFIRMED

**Location:** `tests/test_termsbench_replay.py:272-290`; `src/aeread_families/termsbench/replay.py:355-386`

**Evidence:** The test computes both `original_scores` and `replayed_scores` by passing the same scorer through `score_replayed_episode`, then compares surplus efficiency and protocol compliance between those two results. Only feasible agreement and leaf presence receive independent literal expectations.

Concrete failure scenario: regress surplus-efficiency scoring to always return zero and protocol-compliance scoring to ignore violations. Both the original and replayed sides invoke the same broken functions, so the equality assertions remain green even though both reported values are wrong. Existing measurement tests may catch particular formula regressions, but this replay test does not independently validate those two scores.

COUNTS: confirmed=5 refuted=1 kernel=0
