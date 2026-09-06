# econevals migration review

<!-- Provenance: independent review supplied 2026-09-05 for branch zeyu/econevals-contract-migration. -->
<!-- Verified against the code and disposed by the migrating agent in the same session. -->

--- BEGIN REVIEW ---
- High — measurement.py:332, measurement.py:630, measurement.py:789: the objective leaf declares `input_scope="terminal_state"`, but the production scorer obtains its state from `scoring_input.phase_instances`. This is a direct trajectory read. The paired fixture does not catch it because it merely keeps the last attempt equal and compares resulting scores (test_shared_runner_scoring_contract.py:1386); a scorer can read trajectory data and still return equal values for that particular pair. Concrete failure: two executions have byte-identical outcomes but different replayed final-transition states—for example, an earlier attempt changes cumulative `state["attempts"]`; the supposedly terminal-scoped scorer consumes different trajectory objects despite its declaration.

- Medium — measurement.py:436, measurement.py:760: the migration adds scoring semantics instead of merely composing the existing score methods. Existing `score_terminal_state` returns `objective=None` when the gate fails; the new `_objective_not_computed` branch invents an `invalid_measurement` objective envelope. Because that objective is the sole admission leaf (environment.py:279), this changes receipt inclusion. Concrete failure: a well-formed but illegal action previously yields a measured gate failure (`status="ok"`, value `0`) and no objective; after migration it additionally creates an invalid primary objective and excludes the entire receipt, as the new receipt test codifies at test_econevals_replay.py:694. That admission decision did not come from an existing family score method.

FINDINGS: 2
--- END REVIEW ---

## Disposition

### Finding 1 (High — objective leaf declared `terminal_state` but reads `scoring_input.phase_instances`): REFUTED

Verified against the code and refuted. The premise that this is a "direct trajectory
read" is true only in the narrow sense that `scoring_input.phase_instances` is a
trajectory-carrying structure; what the leaf's *score* actually depends on is not.

- `measurement.py`'s own module docstring (lines 630-660,
  `_state_from_phase_instances`) explains why `phase_instances` is consulted at all:
  `EconevalsPlugin.outcome()` returns only `{termination_reason, period_count,
  num_attempts}` (confirmed independently in `docs/econevals_migration_plan.md`'s
  "Paired-history pair: constructible — yes" section, lines 208-227) — it never carries
  the `attempts` list either leaf needs, so `scoring_input.outcome` alone cannot supply
  the terminal state. `phase_instances` is the only carrier that reconstructs it.
- Reading it is safe per ruling R2/R3 of `kernel_scoring_contract_spec.md`: every phase
  boundary's post-state hash is cross-checked against sealed evidence during the
  verified deterministic re-execution that produces `phase_instances`, so a state that
  diverged from the real run would already have failed finalization before this scorer
  is ever called.
- Critically, the extraction is bounded to the terminal state only:
  `_state_from_phase_instances` returns `phase_instances[-1].transitions[-1].state`
  (the state after the FINAL logical action), and `score_terminal_state`
  (`measurement.py:735-745`) reads `attempts[-1]` — the last entry — and nothing else.
  `score_procurement`/`score_scheduling`/`score_pricing` (`measurement.py:515-622`)
  each take a single `attempt: Mapping[str, Any]` parameter (already `attempts[-1]`)
  and never index into any other entry. There is no code path by which an earlier
  period's attempt can influence the returned score, regardless of which
  `FamilyScoringInput` field supplied the state that contains it.
- Verified empirically, not just by reading: constructed two `state["attempts"]` lists
  sharing an identical final attempt but a *substantially* different first attempt —
  first a legal, high-utility (999.0) period 0 vs. an infeasible period 0; then a legal
  period 0 vs. a malformed-input period 0 — and called
  `EconevalsScorer.score_all` directly on each. Both leaves (gate and objective)
  produced bit-identical `(status, primary, validity)` content across every pair, in
  both the gate-passes and gate-fails branches. This is a strictly more adversarial
  pair than the review's own "concrete failure" scenario (an earlier attempt changing
  `state["attempts"]`), and the score still does not vary.
- The actual, committed paired-history fixture
  (`tests/test_shared_runner_scoring_contract.py::_econevals_fixture_pair`, lines
  951-1009) is not the toothless check the review describes either: its two fixtures
  submit *different* illegal offers in period 0 (`"left_bad_offer"` vs.
  `"right_bad_offer"`) — a genuinely different `phase_instances[0]`/`attempts[0]` — with
  an identical final-period submission, so `left_input.phase_instances !=
  right_input.phase_instances` while the outcome is byte-identical (both asserted
  directly in `test_every_registered_family_obeys_the_scoring_contract`). Ruling R7's
  contrapositive then requires every `input_scope="terminal_state"` leaf to score
  identically across that pair — exactly the scenario the review says is uncaught. This
  test is part of the designated re-run below and passes.
- Section 1 of the spec's line "Terminal-only scorers read `scoring_input.outcome`
  explicitly" describes the two callables that motivated `FamilyScoringInput`'s shape
  (housing's closure, `datacenter_development.__call__`), in contrast to the rejected
  `Mapping`-inheriting design; it is not a rule that a `terminal_state`-declared leaf
  may never consult `phase_instances` when `outcome` cannot supply the terminal state.
  Nothing in sections 3-5 or the rulings forbids it, and R3 explicitly sanctions reading
  `phase_instances` content beyond what is directly logged, for exactly this reason.
- This is the same distinction the reference disposition for a structurally different
  case (amazonbarg finding 1, `docs/amazonbarg_adapter_status.md`/
  `AERead/.worktrees/amazonbarg-migrate/docs/amazonbarg_migration_review.md`) draws:
  there, the leaf's `primary` value itself is transcript-derived (delegated to
  upstream's `eval.py:Metrics` over the full history) and the family's own `outcome()`
  cannot pin it even in principle, which is why that finding was confirmed and
  escalated. Here, the value is provably a pure function of the terminal attempt alone.

No code change made. The declared `input_scope="terminal_state"` is accurate to what
the leaf measures, and the paired-history contrapositive that exists specifically to
catch this class of mislabelling already exercises a genuinely differing trajectory and
passes.

### Finding 2 (Medium — `_objective_not_computed` invents an admission-affecting envelope): REFUTED

Verified against the code and refuted. This family had no production scoring wiring at
all before this migration to compare against, and the behavior described is the forced,
documented consequence of the frozen contract's rules, not new business logic invented
by the migrating agent.

- Confirmed directly against the pre-migration commit
  (`git show 6ad7a094^:src/aeread_families/econevals/measurement.py` and the matching
  `environment.py`): `EconevalsScorer` had no `__call__` method, and `build_scorer`'s
  result was never invoked as a scorer by any finalizer. `kernel_scoring_contract_spec.md`
  section 7 names econevals as one of the three terminal-only families deliberately held
  back from migrating under the old single-envelope convention — there is no
  pre-existing `__call__`/admission behavior for this migration to have changed. The
  family's own status doc says so explicitly (`docs/econevals_adapter_status.md`'s "Leaf
  policy" section: "Before this milestone this family had no `__call__` at all... so
  there is no pre-existing shim to retire here, only new code to add.").
- `score_terminal_state` is unchanged by this migration and still returns
  `(gate, None)` when the gate does not pass — the review is correct about that. What
  turns that `None` into an envelope is required by the contract, not invented: section 3
  requires "The scorer must return exactly that set — no more, no fewer" (every declared
  leaf, every case), and section 4 fixes `ScoreEnvelope.status` at exactly
  `{"ok", "invalid_measurement"}` with no third "pending"/"not computed" state. Given no
  legally-scoreable achieved value exists for the objective when the gate fails,
  `invalid_measurement` is the only status the frozen contract leaves available;
  `_objective_not_computed`'s own docstring (measurement.py:444-482) states this
  reasoning directly and calls it "a plumbing widening, never a change to the underlying
  arithmetic" — the gate's own status/value (`_gate_fail`, `status="ok"`, value `0.0`,
  a real domain fact) is read, not overwritten.
- The admission consequence is likewise forced, not chosen freely: section 3's rule is
  "Admission: Precisely the leaves whose `invalid_measurement` status excludes the
  receipt. The primary is always included." `econevals_objective_leaf` is the leaf
  that reports this family's substantive economic headline (the achieved value vs. the
  case's pinned exact optimum); making it primary is not "picking a convenient... leaf
  as the headline" the way ruling R8's stated limit warns against — the alternative
  (the legality gate) is explicitly considered and rejected in
  `docs/econevals_adapter_status.md`'s "Leaf policy" section ("The gate leaf is not
  proposed as primary: it is a legality precondition..., not the outcome being
  measured."). Once the objective is primary, "the primary is always included [in
  admission]" is mandatory, not a decision the migrating agent made independently.
- This is exactly the taxonomy's own sanctioned composition, not an invented one:
  `docs/research/verifier_taxonomy.md` section 10 defines `hybrid_gate` as "apply
  deterministic prerequisites such as legality, then report the admitted outcome
  vector" — i.e., a legality failure is precisely the case where there is no admitted
  outcome. Section 9 adds "An invalid or missing observation must not be scored as an
  economic zero" — fabricating an `ok`/`0` objective value for an illegal action would
  violate that rule, not satisfy it.
- The concrete scenario the review names ("a well-formed but illegal action... excludes
  the entire receipt") is not a silent side effect: it is exactly what
  `tests/test_econevals_replay.py::test_finalize_wires_econevals_to_the_shared_family_finalizer`
  (added by this migration, per spec section 5 item 4) is written to demonstrate and
  explain in its own docstring, and `docs/econevals_adapter_status.md`'s "Leaf policy"
  section records the reasoning per section 5 item 5's requirement. The cited line
  (`test_econevals_replay.py:694`) has drifted from the review's snapshot — the actual
  assertion (`receipt.inclusion_status == "excluded"`) is at line 788 in the test
  named above — but the substance matches.
- Distinguishing this from a genuinely confirmed instance of the same finding shape
  (amazonbarg finding 2, where `tested_seat` is structurally unreachable from
  `FamilyScoringInput` and *every* successful production episode is excluded,
  unconditionally, with no legality-based distinction at all): here, exclusion is
  conditioned on the underlying action genuinely being illegal/infeasible/malformed —
  the common, successful, legal case is scored and admitted normally. There is no
  unconditional exclusion for this family to escalate.

No code change made. The admission behavior is the mandatory, documented consequence of
composing the family's existing `score_terminal_state` inside the frozen two-state,
full-leaf-set contract for the first time, matching the taxonomy's own `hybrid_gate`
definition.

## Summary

- Fixed: 0
- Refuted: 2
- Escalated (confirmed, owner decision required): 0

## Verification

Re-run of the family test files plus the designated protocol/smoke tests, with the
econevals bridge and upstream root exported and `AEREAD_ECONEVALS_BRIDGE_REQUIRED=1`
(a certifying run — a missing bridge fails rather than silently skips):

```
tests/test_econevals_measurement.py tests/test_econevals_environment.py
tests/test_econevals_cases.py tests/test_econevals_tools.py
tests/test_econevals_replay.py tests/test_shared_runner_scoring_contract.py
tests/test_shared_runner_smoke.py
```

Result: 142 passed, 0 failed, 0 skipped, 0 errors.
