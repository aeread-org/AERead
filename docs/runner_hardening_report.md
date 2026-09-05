# Shared-runner kernel hardening report — branch `zeyu/runner-hardening`

Date: 2026-09-02. Base: `origin/main` @ `2c913dd` (the defect ledger's verification
baseline). Scope: `src/aeread/shared_runner/` and its tests, driven by
`runner_defect_ledger.md`. Method: per defect — failing test first (red for the
defect's reason), minimal fix, mutation verification (fix temporarily reverted via
`cp` roundtrip, test must die, restore), full targeted files green. All work is
provider-free; no network, no keys, no LLM calls in any test.

An adversarial cross-model review of the diff ran mid-pass; its five findings were
each independently verified and the four valid-in-substance ones fixed (see
"Review findings" below).

## Per-defect record

### D-04 — guarded snapshot path in ToolExecutor handlers (verify-first) — `1dee3b3`
- **Verification**: on main @ 2c913dd, all three exception handlers in
  `ToolExecutor.invoke` (ToolFailure / CancelledError / BaseException) already route
  post-effect snapshots through `_observed_after_or_mark_unknown`. Claim confirmed,
  no code change needed for the ledgered item itself.
- **Tests added** (one per handler path): a snapshot failure inside the handler
  degrades to a durable `tool_invocation_outcome_unknown` event
  (`failure_condition: bookkeeping_failed`) while the ORIGINAL exception propagates
  with the bookkeeping error chained as `__context__`.
- **Mutation**: unguarding each call site (bare `_observed_after`) kills exactly its
  test — three mutants, three kills.

### D-09 (new, found during D-04) — handler tails could still mask — `5373aa1`
- **Defect**: the bookkeeping AFTER the guarded snapshot (`_state_change` artifact
  write, terminal `append_event`, record construction) ran unguarded inside the same
  handlers; an evidence write failure there replaced e.g. a retryable
  `supplier_timeout` with an `EvidenceIntegrityError`, changing retry dispatch.
- **Failing tests**: three (one per handler), red with the bookkeeping error
  replacing the original.
- **Fix**: guard each handler tail; re-raise the original with the bookkeeping error
  as `__context__`. The durable `tool_invocation_started` event already marks the
  invocation unterminated for audit, so no outcome claim is lost.
- **Mutation**: the red run is the reverted state; each test fails without its guard.
- **Review addendum** `34dfb9b`: composed failure (snapshot fails AND the guard's own
  outcome_unknown write fails) still masked — the guard's internal write is now
  guarded too. Red-first test; mutant (inner guard re-raises) killed.

### D-03 — resume-safe `tool_invocation_id` minting — `40a9fb7`, hardened `9af111b`
- **Verification**: the ordinal path is used only when a caller passes no explicit id
  (KernelToolPort always passes one).
- **Failing tests**: a resumed executor re-minted an existing id (collision), and the
  resumed sequence diverged from the uninterrupted one.
- **Fix**: the minting ordinal is read from the durable evidence chain (count of
  `tool_invocation_started` events) — after review hardening, at MINT TIME rather
  than construction time. Fresh legacy-only runs keep byte-identical ids (0,1,2…);
  a resumed executor, a second live executor over the same store, and legacy traffic
  interleaved with explicit-id traffic all continue the one durable sequence. This is
  the ported KernelToolPort invariant: two physically distinct invocations can never
  share an id.
- **Mutation**: restoring the zero initializer kills both original tests; restoring
  construction-time counting kills both review-addendum tests.

### D-01 — parity: missing field becomes a typed unavailable verdict — `148914d`
- **Failing tests**: one absent field raised `ParityContractError` and killed every
  other field's verdict (two tests, red with that exception).
- **Fix**: `_extract` became a tolerant `_lookup`; `ParityFieldResult` gains
  `status` ("compared" | "unavailable") and `unavailable_sides`; `ParityReport`
  gains `unavailable_fields`; report status precedence is
  mismatch > unavailable > match, so an unobserved field can never read as a match.
- **Mutation**: restoring the raising lookup kills both tests.
- **Note**: `report_sha256` for identical inputs changes once (new basis keys). No
  consumer pins report hashes (verified across `src/` and `tests/`).

### D-02 — parity: derived-field marking — `ac54adf`, hardened `852e9bb`
- **Failing tests**: no way to declare a field derived; a derived match read as
  independent confirmation.
- **Fix**: `ParityField.derived_from` (validated: only other declared fields, no
  self-reference, no duplicates — and after review hardening, no cycles);
  results carry `derived` and the `derived_from` tuple into the content-addressed
  report. Undeclared fields default to independent — every existing spec valid
  unchanged.
- **Mutation**: dropping flag propagation, dropping spec validation, dropping the
  cycle check, and dropping tuple carriage each kill their test.

### D-07 — `upstream_task_id` must pass the identifier grammar — `1437e4a`
- **Failing tests**: a colon (`"retail:14"`) and whitespace/uppercase were accepted
  by `CaseManifest.from_dict`.
- **Fix**: the optional field validates through the same `_identifier` parser as
  `case_id`; absent stays `None`. tau3's pilot ids are already grammar-clean.
  **Adapters for tonight's five families must normalize foreign upstream ids**
  (lowercase, `[a-z0-9_.-]`, no colons) and keep the raw string in
  provenance/payload if it matters.
- **Mutation**: restoring `_optional_string` kills both tests.

### D-05 — blind state_reader tripwire (partial by design) — `e429765`
- **Failing test**: a constant-stub reader on a real 100→70 debit recorded
  `state_changed=False` with no typed trace anywhere.
- **Fix (the enforceable projection)**: a MUTATING tool with
  `idempotency_supported=False` that succeeds while the observed state hash did not
  move now appends a durable non-terminal `tool_invocation_mutation_unobserved`
  event (`condition: mutation_unobserved`). Reconciliation unaffected; QC can gate
  on it. Idempotent no-ops and honestly observed changes stay silent.
- **Mutation**: verified in both directions (never-fires kills the positive test;
  unconditional-fire kills the negative test).
- **Residual, documented in the ledger**: the kernel cannot verify reader fidelity
  against ground truth at admission — that needs family-level golden mutation cases
  (Q-01 scaffold territory). Idempotent tools' first-call no-ops remain
  undistinguished by design.

### D-06 — exact comparison at zero tolerance — `76da0f1`
- **Failing test**: `2**53` vs `2**53 + 1` under `numeric_tolerance` with
  `absolute_tolerance=0.0` compared EQUAL through float conversion.
- **Fix** (in `parity.py`, where the comparison actually lives — the ledger said
  "measurement"): int pairs difference with exact integer arithmetic; a
  zero-tolerance match is decided by Python's exact cross-type numeric equality.
  Nonzero tolerances keep float semantics — that is what a declared tolerance means.
- **Mutation**: restoring the float-only path kills the test.

### D-08 — field_rating cannot claim deterministic — `a439064`
- **Failing test**: `VerifierSpec(verifier_family="comparative",
  evaluation_class="deterministic")` over a `field_rating` reference was accepted.
- **Fix**: that combination is rejected; `judge_dependent` (and
  `stochastic_estimator` for rater-population estimates) remain valid.
- **Mutation**: removing the guard kills the test.

### H-03 — harness protocol completeness at registration — `0ff68c2`
- **Failing tests**: `HarnessRegistry.register` accepted an object with only
  id/version/requires; a missing `act` surfaced as an AttributeError mid-episode.
- **Fix**: registration requires callable
  `open_episode`/`act`/`close_episode`/`classify_failure`, plus `state_reader` when
  `requires.memory` goes beyond `{"disabled"}` (the protocol's conditional hook).
  Every in-tree harness already conforms.
- **Mutation**: hook check and state_reader check verified independently.

### H-01 — profile tool grant enforced at the port — `ead8656`
- **Failing tests**: with the runtime declaring `get_balance` + `refund_order` and
  the profile granted only `get_balance`, a model request for `refund_order`
  EXECUTED (port-level test red on TypeError for the missing parameter; the
  executor-wiring test red with the ungranted mutation actually running).
- **Fix**: `KernelToolPort` gains `granted_tools` (`None` = no grant beyond the
  runtime's declared set — direct family/test constructions unchanged); a dispatch
  outside the grant is a typed `tool_dispatch_rejected` /
  `ToolFailure("tool_not_granted")` before the runtime sees it. `AttemptExecutor`
  wires `frozenset(profile.tools)`.
- **Mutation**: grant check and executor wiring verified independently.

### H-02 — one-disposition-per-intent seal rule — BLOCKED (design ruling needed)
Analysis in the ledger. Short form: an orphaned intent is genuinely reachable today
(pre-start failures inside `ToolExecutor.invoke` after `tool_dispatch_intended`),
but a hard seal-time rule would make exactly that failure-path evidence UNSEALABLE
(breaking finalize-on-failure/retry flows), and crash/resume re-minting the same
deterministic id can produce a second intent for one dispatch, which a naive
exactly-one rule also rejects. Enforcement point and resume multiplicity need a
design ruling — not something to enforce ad hoc the night five families rebase.

## Adversarial review findings (cross-model), each independently verified

1. Composed snapshot+event-write failure masks the original — **valid**, fixed
   `34dfb9b` (see D-09 addendum).
2. Two live executors over one store collide — **mechanically valid** (not reachable
   through kernel wiring, which never shares an `action_attempt_id` across
   executors, but real for direct constructions) — fixed `9af111b`.
3. Legacy id drift across resume under mixed explicit/legacy traffic — **valid**,
   fixed `9af111b`.
4. Derived cycles admitted / dependency graph absent from digest — **cycle half
   valid**, fixed `852e9bb`; the digest half was pre-existing (comparison paths and
   tolerances were never in the report basis either), improved anyway by carrying
   `derived_from` into results.
5. `ParityReport` positional-signature break — **valid**, fixed `852e9bb`
   (trailing default).

## End-to-end verification (exact counts)

All three runs from a clean tree at the final commit, with
`AEREAD_TAU2_BRIDGE_PYTHON` and `AEREAD_TAU2_UPSTREAM_ROOT` exported and
`AEREAD_TAU2_BRIDGE_REQUIRED=1` so a silently skipped fidelity test FAILS the run.

1. **Full suite with tau2 bridge** (clean tree @ `b5fed3d`, 12m39s):
   **781 passed, 3 skipped, 1 xfailed, 0 failed** — baseline on main @ 2c913dd was
   754 passed, 3 skipped, 1 xfailed, so the delta is exactly the 27 tests added by
   this branch. All 3 skips are `could not import 'rllm'` (the baseline's rllm-only
   skips); with `AEREAD_TAU2_BRIDGE_REQUIRED=1` a silently skipped tau3 fidelity
   test would have FAILED the run, so the 31 upstream-fidelity tests genuinely ran.
2. **Harness e2e file** (`tests/test_harness_end_to_end.py`): **6 passed** (the 5
   baseline tests plus the new ungranted-tool refusal test), 0 skipped, 0 failed.
3. **Complete episode through `execute_plan_cell`** (provider-free scripted housing
   cell, run at `b5fed3d`): episode valid, 5 logical actions, evidence sealed at
   **52 events / 39 artifacts**
   (artifact_root `88bab10e01d0e7b8b3a982ff57058c4367ea33a451b3ee702edc0d6357788cb2`),
   receipt `41c9b65e9ac40c3a00f0371cc41092cea26b6852f5678d9c219c3d084376b172`,
   primary score **389.54 utility_points (status ok)** — then
   `replay_family_receipt` recomputed state and score from the sealed evidence and
   confirmed byte-identity (the replay raises on any divergence; it did not).

## Found but not fixed

- **H-02** — blocked on a design ruling (above).
- **D-05 residual** — reader-fidelity verification needs family golden mutation
  cases; proposed home: the Q-01 golden-contract scaffold.
- **Pre-start orphaned intents** (surfaced during H-02 analysis): a failure between
  `tool_dispatch_intended` and `tool_invocation_started` leaves an intent with no
  disposition. Harmless to reconciliation today, but it is the concrete input the
  H-02 ruling should cover.
- **H-04** untouched by instruction (canonical-JSON `None` serialization belongs to
  the canonical-JSON-spec task; changing it breaks every existing record hash).
- **H-05/H-06, Q-01…Q-04, O-01/O-02** — out of tonight's scope, unchanged.

---

# Round 2 — follow-up entries D-10…D-14 (2026-09-02)

Input: five ledger entries merged from eleven external-benchmark integrations
(runner_agent_followup.md). Same method: red-first TDD, mutation verification per
guard, additive/behavior-preserving for existing callers.

## Per-defect record (round 2)

### D-10 — `docs/benchmark_qc.md` missing from main — BLOCKED (confirm-only, by brief)
Independently re-confirmed from this worktree: no `*benchmark_qc*` file and no
"QC Gate" phrase anywhere in docs/ at the 2c913dd base; the file exists only at
`2b831fe`, reachable solely from `origin/codex/procurement-harness-bakeoff`, which is
open as **PR #26**. Dispositioned "blocked — awaiting PR #26"; deliberately NOT
copied ad hoc — reconciling it against the six independently-written adapter specs is
that PR's call.

### D-11 — taxonomy §5.1 names vs the real objective_reference contract — `ecfb593`
- **Ruling**: the CODE set is the intended contract — eleven families were written
  and are green against it, and housing pins the one-leaf-per-bound pattern. Adding
  new reference kinds the night before eleven rebases was rejected.
- **Fix**: §5.1 rewritten as a claim-pattern table mapping each conceptual name
  (bound certificate, baseline headroom, support-normalized outcome, objective value
  only) to the real per-bound leaves it is built from, with the settable enumeration
  stated verbatim; §5.3 gains the derived-statistic clarification.
- **Bonus drift caught by the new guard**: the comparative table said
  `human_reference`; the real kind is `human_reference_comparison`. Corrected.
- **Test**: a drift guard — every backticked name in any table column headed
  "Reference kind" must be accepted by the contract, and every objective_reference
  kind must be documented. Red before the doc fix; mutation-verified by restoring
  the old doc text (cp roundtrip).

### D-12 — no kernel-guaranteed route to the seed at score time — `f7a11cb`
- **Failing test**: `EpisodeResult` had no `world_seed` (AttributeError).
- **Fix**: trailing defaulted field `world_seed`, populated from the case manifest at
  the single construction site. Replay-side, the seed was already recoverable from
  the plan's case manifest; this closes the in-process half. `build_scorer`'s
  signature deliberately untouched (13+ families implement the hook).
- **Mutation**: dropping the threading kills the test.

### D-13 — `max_logical_actions` semantics undocumented and unpinned — `21eaa12`
- **Ruling**: the BEHAVIOR (whole-episode cap per `phase_id`, summed across
  recurrences) is correct and stays: the cap is a runaway guard, a per-instance
  reset would let a declared cycle burn actions up to the case budget unchecked,
  and the eleven pending branches are green against the summed semantics.
- **Fix**: PhaseSpec docstring now states the contract; a new test pins the
  distinguishing case — two actions per instance under a cap of five trips on the
  sixth action (third instance), refused before dispatch, even though every single
  instance stays under the cap.
- **Mutation**: inserting a per-instance reset at the loop top kills the new test
  (and, reassuringly, the pre-existing endless-cycle test).

### D-14 — no teardown signal for family plugins — `a15f898`
- **Failing tests**: three — normal-path teardown, typed close-failure, and
  teardown-on-episode-failure without masking.
- **Fix**: optional `close(family_case, state)` hook invoked at most once by
  `run_episode`: on the normal path after the outcome and result are built (a
  failing close is a typed `SchedulerContractError("family close failed")`), and on
  the failure path before the episode error propagates, where a close failure never
  replaces the in-flight error (it chains as `__context__` — the same never-mask
  contract as the ToolExecutor handlers). `REQUIRED_FAMILY_PLUGIN_HOOKS` unchanged;
  no adapter branch's plugin class defines a conflicting `close` attribute (verified
  across all eleven branch heads — econagent's `close` methods live on bridge helper
  classes, not the registered plugin).
- **Mutation**: three mutants killed independently (normal-path call dropped,
  failure-path call dropped, masking guard dropped).

## Adversarial review (round 2), each finding independently verified

1. **Preflight sat outside the teardown boundary** — **valid**, fixed `7b53c5e`.
   `validate_payload` is exactly where a family spawns the process the hook exists to
   release, so a failure in `phases()` or `initial_state()` leaked it. Preflight now
   runs inside the protected block; a `family_case` of None (the plugin never received
   a validated case) still skips teardown, and a post-validation preflight failure
   calls `close(family_case, None)`.
2. **`close` detected by duck-typing alone** — **valid**, fixed `7b53c5e`. A plugin
   carrying an unrelated zero-argument `close()` would have completed its episode and
   then failed with an opaque TypeError. The hook's signature is bound before the
   call; a mismatch raises `SchedulerContractError` naming the collision.
3. **`world_seed`'s None default changes canonical bytes for existing callers** —
   **refuted with evidence**. `scheduler.py:881` is the ONLY `EpisodeResult`
   construction site in the kernel and in all eleven adapter branches (checked at each
   branch head), and it always passes `case.world_seed`; adapter replay rebuilds
   results through `run_episode` too, so both sides carry the integer. Nothing hashes
   or persists a whole `EpisodeResult` — receipts carry only `.outcome`, and the
   bakeoff's `canonical_json_bytes(result)` serializes a different object. No
   persisted digest changes; the branch's own sealed-episode replay proof is
   byte-identical.
4. **Drift-guard parser read only the first backticked token per cell** — **valid**,
   fixed `a48b7db`; mutation-verified by adding a second, fake kind to an existing
   cell. Known remaining limitation, by design: the guard checks membership in the
   union of all families' kinds, not the per-family pairing `VerifierSpec` enforces.

### Regression I introduced and fixed (found by the full suite, not by targeted files)

The §5.1 rewrite replaced the literal identifiers `bound_certificate`,
`baseline_headroom` and `outcome_support_normalized` with spaced prose, breaking the
pre-existing `test_shared_runner_design_contract` assertion that requires those exact
tokens in the taxonomy. Fixed at `3d50177` by restoring them as unbackticked
claim-pattern labels — satisfying the contract test while keeping them out of the
drift guard's backticked-kind extraction. Targeted test files were green throughout;
only the full suite caught it.

## End-to-end verification (round 2), exact counts

1. **Full suite with the tau3 bridge** and `AEREAD_TAU2_BRIDGE_REQUIRED=1`:
   **790 passed, 3 skipped, 1 xfailed, 0 failed** (round 1 was 781/3/1; the delta is
   round 2's new tests). All 3 skips are the baseline's rllm-import skips.
2. **`tests/test_harness_end_to_end.py`**: **6 passed**, 0 skipped, 0 failed.
3. **Sealed-episode replay** through `execute_plan_cell` (provider-free housing
   cell): episode valid, 5 logical actions, 52 events / 39 artifacts sealed, primary
   score 389.54 utility_points (status ok), and `replay_family_receipt` reproduced
   state and score byte-identically from the sealed evidence.
4. **Merged-state regression** — this branch merged into a copy of
   `zeyu/integration-test` (all eleven adapter families), full suite with every
   provisioned family bridge live and three bridge-required flags set:
   **1,804 passed, 3 skipped, 1 xfailed, 0 failed**, against that branch's own
   clean-tree baseline of **1,757 passed, 3 skipped, 1 xfailed** measured in an
   untouched worktree. The +47 is exactly this branch's added tests; nothing
   regressed and nothing newly skipped.

### What the merged check caught (and why runs 1-3 were not enough)

The first merged run came back **38 failed, 7 errors**. Every failure traced to one
cause: round 1's D-07 reused the *exportable* identifier grammar (lowercase-only) for
`upstream_task_id`, and the landed families carry real upstream ids such as
`Task1BasicPriceNegotiation` and `Task4_s1_beauty_product_negotiation` — ids that
contain no colon and no whitespace and were never the hazard.

The over-tightening was wrong on the merits, not merely inconvenient: this field
exists to record the foreign id **verbatim** so results can be joined back to
upstream, and lowercasing it destroys exactly that. The hazard the entry was opened
against is the row-id parsing class (a colon once collapsed rLLM's GRPO grouping into
a single group), not letter case. Corrected at `b85d9e1` with a purpose-fit
`_foreign_identifier`: letters, digits, `_`, `.`, `-`, alphanumeric at both ends;
colons, whitespace, separators and quoting characters still refused. Both halves are
now pinned as parametrized tests — the hazard class stays rejected, and real foreign
ids from the landed families round-trip unchanged.

The branch's own suite was green (790/0 failed) through all of this. Only the
merged-state run against the eleven families could surface it.

### A process failure worth recording

An earlier "baseline" run reported 1 failure that did not exist: the baseline suite
was running in `.worktrees/hardening-integration-check` when I merged into that same
worktree, so a doc-reading test picked up the half-written tree mid-run. The clean
re-measurement in an untouched worktree returned exactly 1,757/3/1. This is the
"only trust numbers from a clean tree" rule, violated by writing into the tree under
test; both later runs used separate worktrees.

## Compatibility notes for tomorrow's rebases

- All kernel changes are additive or behavior-preserving for existing callers:
  new dataclass fields default; `granted_tools=None` keeps direct port
  constructions unrestricted; fresh-run legacy tool ids are byte-identical;
  every pre-existing test passes unmodified (none weakened or deleted).
- Two deliberate tightenings that CAN reject previously-accepted inputs:
  `upstream_task_id` now must pass the identifier grammar (D-07 — normalize foreign
  ids), and `HarnessRegistry.register` now rejects protocol-incomplete harnesses
  (H-03 — all in-tree harnesses conform). Flagging both for the family branches.
- `ParityReport.report_sha256` values change once for identical inputs (D-01 basis
  keys). No consumer pins them.
