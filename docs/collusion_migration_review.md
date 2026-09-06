# Collusion scoring-contract migration — independent review

**Provenance.** The section below, delimited by `BEGIN REVIEW` / `END REVIEW`, is
reproduced verbatim from an independent review of branch
`zeyu/collusion-contract-migration` at commit `eeb59ecf` (worktree
`collusion-migrate`). It was supplied to this document's author for
verification, not authored by that author.

--- BEGIN REVIEW ---
1. **High — Production finalization is exercised only through a test-only evidence harness.** The exported `ScriptedCollusionHarness` records only `collusion_price_submitted` ([harness.py:126](</Users/sunzeyu/Documents/econ benchmark/AERead/.worktrees/collusion-migrate/src/aeread_families/collusion/harness.py:126>)). The new test explicitly acknowledges those events cannot be replayed and introduces `EvidenceRecordingCollusionHarness` inside the test suite ([test_collusion_replay.py:741](</Users/sunzeyu/Documents/econ benchmark/AERead/.worktrees/collusion-migrate/tests/test_collusion_replay.py:741>)); the purported production-finalizer test uses that substitute ([test_collusion_replay.py:1234](</Users/sunzeyu/Documents/econ benchmark/AERead/.worktrees/collusion-migrate/tests/test_collusion_replay.py:1234>)). Concrete failure: run an episode through the family's exported harness, then call `finalize_family_execution`; replay lacks `logical_action_started`, phase, transition, termination, and outcome events, so finalization fails before issuing a receipt. The migration proves a test-only path, not the family's production path.

2. **High — The finalize-time primary is structurally unmeasurable and excludes every successful production receipt.** The manifest declares `collusion_long_run_profit` as finalize-time, primary, and the sole admission leaf ([environment.py:219](</Users/sunzeyu/Documents/econ benchmark/AERead/.worktrees/collusion-migrate/src/aeread_families/collusion/environment.py:219>)). Yet `__call__` unconditionally supplies `baseline_profit_by_seat=None` ([measurement.py:872](</Users/sunzeyu/Documents/econ benchmark/AERead/.worktrees/collusion-migrate/src/aeread_families/collusion/measurement.py:872>)), which unconditionally produces `invalid_measurement` ([measurement.py:662](</Users/sunzeyu/Documents/econ benchmark/AERead/.worktrees/collusion-migrate/src/aeread_families/collusion/measurement.py:662>)). The receipt test normalizes this defect by expecting exclusion ([test_collusion_replay.py:1258](</Users/sunzeyu/Documents/econ benchmark/AERead/.worktrees/collusion-migrate/tests/test_collusion_replay.py:1258>)). Concrete failure: a clean 300-round episode always yields an excluded receipt and no usable headline result. A measurement requiring an unavailable artifact cannot honestly be the finalize-time admission primary; the baseline must become authenticated scoring input, or the leaf policy must change.

3. **Medium — The trajectory sensitivity witness passes on a terminal-state change, without demonstrating trajectory dependence.** The added malformed fixture changes `termination_reason` and rounds, and the comments explicitly use the different `invalid_measurement` reason to witness the profit leaf ([test_shared_runner_scoring_contract.py:1145](</Users/sunzeyu/Documents/econ benchmark/AERead/.worktrees/collusion-migrate/tests/test_shared_runner_scoring_contract.py:1145>)). The witness searches every fixture pair for any score-content difference without requiring identical projected terminal outcomes ([test_shared_runner_scoring_contract.py:1477](</Users/sunzeyu/Documents/econ benchmark/AERead/.worktrees/collusion-migrate/tests/test_shared_runner_scoring_contract.py:1477>)). Concrete failure: replace `collusion_long_run_profit` with an implementation that ignores `phase_instances` entirely but preserves the `termination_reason` gate; normal versus malformed fixtures still differ in validity reason, so the supposedly trajectory-sensitive leaf passes.

4. **Medium — The scorer does not make `FamilyScoringInput.evidence_refs` authoritative.** `__call__` accepts an independent `evidence_refs` argument ([measurement.py:839](</Users/sunzeyu/Documents/econ benchmark/AERead/.worktrees/collusion-migrate/src/aeread_families/collusion/measurement.py:839>)) and forwards that argument into every score ([measurement.py:872](</Users/sunzeyu/Documents/econ benchmark/AERead/.worktrees/collusion-migrate/src/aeread_families/collusion/measurement.py:872>)). Tests always pass the matching value ([test_shared_runner_scoring_contract.py:1691](</Users/sunzeyu/Documents/econ benchmark/AERead/.worktrees/collusion-migrate/tests/test_shared_runner_scoring_contract.py:1691>)), so mismatch behavior is uncovered. Concrete failure: invoke the scorer with sealed refs in `scoring_input` but stale or forged refs in the keyword argument; all four envelopes carry the latter, contrary to the contract's verbatim-provenance rule.

The exact-leaf-set direct tests do pass: 3 targeted tests passed in 25.71s. The full finalizer/protocol tests were not run because this read-only environment has no writable temporary directory.

FINDINGS: 4
--- END REVIEW ---

## Dispositions

Each finding below was independently re-verified against the code (not merely
re-read from the review) before any action was taken, including re-deriving
its file/line citations and, where the review's own precedent was the
already-verified reference migration (`govsim`, worktree `.worktrees/govsim`,
commits `6dbe0c7..98f3b55`), comparing collusion's shape against that
family's own equivalent code directly.

### Finding 1 — **Disposition: refuted.**

The review's premise is that `ScriptedCollusionHarness` *is* this family's
production finalization path, and that its inability to drive
`finalize_family_execution` is therefore a production defect. That premise
does not hold up against the code:

- `harness.py`'s own module docstring (line 1) states plainly: "Provider-free
  scripted-policy response source for `collusion` integration tests" — it was
  never held out as a production entry point, exported or not.
- `docs/collusion_adapter_spec.md`'s governing facts state prices are
  "free-form real numbers, string-parsed from LLM prose" — this family's real
  (production) episodes are LLM-agent-driven. Production execution of an
  LLM-driven family goes through the shared `AttemptExecutor`/
  `MinimalChatExecutor` machinery in
  `aeread.shared_runner.task.execution`, which *does* write the complete
  generic evidence trail (`logical_action_started`,
  `phase_instance_started`, `transition_applied`, `episode_terminated`,
  `family_outcome_recorded`, etc.) for every attempt — confirmed by grepping
  `append_event(` call sites in `src/aeread/shared_runner/task/execution.py`
  (over twenty, including `logical_action_started` at line 2173 and
  `family_outcome_recorded` at line 2862). Nothing about collusion's
  migration disables or bypasses that machinery; collusion has no
  `runner.py` of its own and is driven through the same generic
  `execute_plan_cell` path as every other LLM-driven family (aucarena,
  negarena, steer).
- The identical split already exists, unmodified, in the verified reference
  migration: `govsim`'s own exported harness, `ScriptedGovsimHarness`
  (`.worktrees/govsim/src/aeread_families/govsim/harness.py`, `__all__ =
  ["ScriptedGovsimHarness"]`), *also* writes only its own convenience event
  and cannot drive `finalize_family_execution`; govsim's
  `EvidenceRecordingGovsimHarness` — the exact class collusion's own
  `EvidenceRecordingCollusionHarness` docstring cites by name as its model —
  exists only inside govsim's own test suite, for the identical reason.
  `docs/collusion_adapter_status.md`'s "Receipt" section documents this
  split explicitly and by design, mirroring govsim's own already-approved
  status doc.

`EvidenceRecordingCollusionHarness` is not a workaround invented to dodge a
broken production path; it is a provider-free stand-in for the real
production executor's own event vocabulary, used to drive
`finalize_family_execution` deterministically in CI without a live model —
exactly the reference migration's own shape. No code change made.

### Finding 2 — **Disposition: confirmed, not fixed — escalated (architectural).**

The factual claim is correct and was reproduced directly:
`CollusionScorer.__call__` (`measurement.py:872`) unconditionally passes
`baseline_profit_by_seat=None` into `score_all`, and
`score_long_run_profit` (`measurement.py`, the `baseline_profit_by_seat is
None` branch) unconditionally returns `invalid_measurement` in that case.
Since `environment.py`'s manifest names `collusion_long_run_profit` as both
`primary_leaf_id` and the sole `admission_leaf_ids` entry, and
`task/evaluation.py`'s `_score_admission` excludes the receipt whenever any
admission leaf is invalid, **every** receipt produced by
`finalize_family_execution` for this family is `status="invalid_measurement"`
/ `inclusion_status="excluded"`, regardless of trajectory quality. This is
already known and stated in the code: `docs/collusion_adapter_status.md`'s
"Receipt" section calls it "a documented, structural fact, not a fixture
defect," and `test_collusion_replay.py`'s
`test_finalize_wires_collusion_to_the_shared_family_finalizer` pins exactly
this outcome.

Why this is not something a migration agent can fix in place, and why it is
being escalated rather than guessed at:

- The root cause is deeper than a missing plumbing wire. The spec's own
  leaf-4 declaration (`docs/collusion_adapter_spec.md` §2) requires the
  baseline to be "a named, versioned scripted baseline policy's own realized
  profit... under the *same* cell, horizon, and opponent condition" — not
  the closed-form Nash profit already sitting in
  `family_case["gold_reference"]["pi_nash"]`. `test_collusion_replay.py`'s
  own `shared_asymmetric_same_opponent_baseline_profit` fixture and its
  sibling test
  (`test_same_opponent_condition_baseline_differs_from_nash_vs_nash_pi_nash_for_an_asymmetric_opponent`)
  prove the two values differ materially whenever the real opponent is not
  itself playing Nash (a previously triaged and fixed bug — "collusion
  codex triage, Finding 2" — that substituting `pi_nash` here would
  silently reintroduce). Computing the *correct* baseline requires
  re-running the environment with one seat forced to Nash-play against the
  *same opponent policy function* the live episode actually used (not
  merely its recorded price history — a reactive opponent such as
  tit-for-tat would play differently against a different counterfactual
  price each round). For a real, LLM-driven opponent, "the same opponent
  policy function" is a live model, which no artifact reachable from
  `FamilyScoringInput` (`scoring_input.outcome`,
  `scoring_input.phase_instances`) can supply, and the frozen
  `FamilyScorer.__call__(scoring_input, *, evidence_refs=...)` signature
  (`kernel_scoring_contract_spec.md` §2) has no parameter for one. This is
  not a wiring gap this migration introduced; it is a pre-existing
  measurement-design limit already flagged in
  `docs/collusion_adapter_spec.md` §6 ("`score_long_run_profit`'s
  `baseline_profit_by_seat` argument is... trusted from the caller, not
  verified in code").
- The one available precedent that structurally avoids this trap — govsim's
  own `collusion`-analogous `comparative`/`baseline_delta` leaf,
  `govsim_survival_months` (`.worktrees/govsim/src/aeread_families/govsim/measurement.py`,
  `score_survival_months`) — sidesteps it by making `primary` a
  self-contained, always-computable quantity (the episode's own survival
  months) and treating the baseline delta as *optional* supplementary
  `metrics`/`reference_values` content, so `status="ok"` never depends on a
  baseline being supplied (govsim's own
  `test_finalize_family_execution_scores_a_real_...`-equivalent receipt test
  asserts `receipt.status == "ok"` / `inclusion_status == "included"`).
  Copying that shape for collusion would require redefining
  `collusion_long_run_profit`'s `primary` from "profit delta vs. baseline"
  to "own realized profit," which directly contradicts
  `docs/collusion_adapter_spec.md`'s own golden table (§4: golden 3's
  expected leaf-4 output is stated as "Δπ≈+11.46/round," i.e. the delta
  itself, not own profit) — a frozen-spec clause, not something this task's
  brief permits deviating from silently.
  Alternatively, declaring the leaf `scope="deferred"` would remove it from
  the finalize-time set entirely, which conflicts with the manifest's own,
  pre-existing (not introduced by this migration) `primary_estimand:
  "collusion_long_run_profit"` declaration and would force selecting a
  substitute primary from the two static-game distance diagnostics — both
  explicitly documented as diagnostics the family's own spec forbids
  promoting to a headline result (P04's warning).

Both viable fixes are genuine architectural/scientific-design decisions
about what this family's headline metric means or how the frozen
`FamilyScoringInput` contract's leaf-scope taxonomy should treat an
external, live-opponent-dependent baseline — decisions this migration task's
brief does not authorize a mechanical migration agent to make unilaterally,
and which would touch a clause the task named as frozen. No code change
made; flagging for the spec/family owner to decide between (a) accepting
`collusion_long_run_profit` as permanently non-admitting until a
live-baseline-recomputation capability exists elsewhere in the kernel, (b)
redefining the leaf's `primary` to be self-contained (govsim's shape,
requiring a golden-table amendment), or (c) extending
`kernel_scoring_contract_spec.md`'s `deferred` scope to leaves blocked on an
external re-simulation artifact, not only a judge/rater verdict.

### Finding 3 — **Disposition: confirmed, not fixed — escalated (direct corollary of Finding 2).**

The factual claim reproduces cleanly: in `score_long_run_profit`, the
`termination_reason` operational-failure check runs *before* the
`baseline_profit_by_seat is None` check, which itself runs *before* any
`outcome["history"]` access. Because `CollusionScorer.__call__` always
passes `baseline_profit_by_seat=None` (Finding 2), leaf 4's outcome through
the finalize path is structurally binary — exactly two reachable results,
`invalid_measurement("termination_reason_<x>")` or
`invalid_measurement("baseline_profit_not_provided")` — and which one occurs
is determined entirely by `termination_reason`, a fact the family's own
`__call__` docstring calls out as read directly from `scoring_input.outcome`
and explicitly "not itself trajectory content." The `reporting_window_
unavailable` and `"ok"` branches, which do read `outcome["history"]`, are
unreachable from `finalize_family_execution` today for exactly the reason
Finding 2 names. An implementation that dropped `phase_instances` entirely
for leaf 4 (but kept the shared `termination_reason` gate every leaf uses)
would indeed still pass R9(b)'s sensitivity witness on the malformed
fixture pair, as the review's concrete failure describes.

This is confirmed as a real gap, but it is not independently fixable:

- It cannot be fixed by adding more collusion fixtures. With
  `baseline_profit_by_seat` permanently `None` in production, no fixture
  pair can make leaf 4 reach the history-reading branches at all, so no
  supplied pair can *honestly* witness trajectory-sensitivity for this leaf
  until Finding 2 is resolved.
  - Fixing Finding 2 via govsim's self-contained-primary shape would, as a
    side effect, resolve this too (an always-computable own-profit primary
    reads `history` on every fixture, malformed or not), reinforcing that
    the two findings share one root cause and one owner-level decision.
- The alternative — changing `_assert_trajectory_leaves_are_witnessed`
  (`test_shared_runner_scoring_contract.py`) to also require the witnessing
  pair's *projected outcome* to match, per the review's own suggested
  mitigation — is a change to the shared, generic R9(b) kernel protocol
  test that every already-migrated family's fixtures run through, not a
  collusion-specific test. That is a `kernel_scoring_contract_spec.md`
  ruling change (an "R9(c)"), outside a single family's migration scope and
  risking regressions across every other enrolled family's fixtures; it
  needs the same spec owner as Finding 2, not a unilateral edit here.

No code change made. Flagged alongside Finding 2 for the same decision.

### Finding 4 — **Disposition: refuted.**

The cited code (`measurement.py:839`, `:872`) is accurately described:
`CollusionScorer.__call__` does take `evidence_refs` as an independent
keyword argument and forwards it verbatim into every score, without
cross-checking it against `scoring_input.evidence_refs` itself. But this is
the contract-mandated call shape, not a collusion-specific gap: every
already-migrated family's own `__call__` has the identical signature
(verified directly against the reference migration: govsim's
`GovsimScorer.__call__(self, scoring_input, *, evidence_refs=())`,
`.worktrees/govsim/src/aeread_families/govsim/measurement.py:841-843`, byte-
identical in shape), because `kernel_scoring_contract_spec.md` §2 itself
specifies the call site as
`plugin.build_scorer(family_case)(scoring_input, evidence_refs=scoring_input.evidence_refs)`
— the scorer is not the layer the frozen contract makes responsible for
authenticating provenance.

The actual authority lives one level up:
`task/evaluation.py::_check_evidence_refs_are_scoring_input_verbatim`,
called unconditionally from `finalize_family_execution` right after the
scorer returns (`evaluation.py:669`), raises `ValueError` if any returned
score's `evidence_refs` disagrees with `scoring_input.evidence_refs` — this
is what makes `scoring_input.evidence_refs` authoritative for *every*
family, collusion included, before a receipt can ever be sealed. The
review's own citation (`measurement.py`) never reaches this function
because it is not in that file.

The review is right about one real, narrower gap, though: no test in this
repository (collusion's or any other already-migrated family's) previously
exercised the mismatch branch of that check — every existing test supplies
matching values, so the check's *raise* path was reachable but untested,
for every family, not only collusion. Since I had a real, working
collusion fixture on hand, I closed that specific coverage gap for this
family with a new, purely additive test (no production code changed):

`tests/test_collusion_replay.py::test_finalize_family_execution_rejects_a_collusion_scorer_that_forges_evidence_refs`
monkeypatches `CollusionScorer.__call__` to return a `FamilyScoreSet` whose
scores carry a forged, non-matching `evidence_refs` tuple, drives a real
episode through `finalize_family_execution`, and asserts it raises
`ValueError` matching `"evidence_refs that disagree"`.

**Mutation check:** with
`task/evaluation.py`'s `_check_evidence_refs_are_scoring_input_verbatim(score_set,
scoring_input)` call site (line 669) replaced by `pass`, the new test fails
with `Failed: DID NOT RAISE ValueError` — confirming the test is actually
exercising the guard, not passing vacuously. Restored (verified `git status`
clean on `evaluation.py` afterward) and the test passes again.

No production code changed for this finding; `_check_evidence_refs_are_scoring_input_verbatim`
already made the claimed property false in practice.

## Summary

| Finding | Disposition |
|---|---|
| 1 (High) | Refuted |
| 2 (High) | Confirmed — not fixed, escalated (architectural decision needed) |
| 3 (Medium) | Confirmed — not fixed, escalated (corollary of Finding 2) |
| 4 (Medium) | Refuted; coverage gap closed with one new additive test |

Two of the review's four findings describe real, reproducible code behavior
but require a decision this migration task's brief does not authorize a
migration agent to make unilaterally: whether to redefine
`collusion_long_run_profit`'s headline meaning against the frozen spec's own
golden table, or to extend the frozen kernel contract's `deferred`-scope
vocabulary to cover leaves blocked on a live-opponent re-simulation
artifact rather than only a judge/rater verdict. Both are recorded here,
unfixed, for the spec/family owner to rule on.
