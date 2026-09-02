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
