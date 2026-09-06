Source: independent adversarial review, delivered verbatim to this migration for
disposition. Each finding re-verified against the code directly before any action was taken.

--- BEGIN REVIEW ---
1. `src/aeread_families/negarena/measurement.py:508-510,539-548` — The scorer accepts an independent `evidence_refs` argument and propagates it instead of using `scoring_input.evidence_refs`. Calling it with populated scoring input but omitting the keyword produces both leaves with empty provenance; passing unrelated refs fabricates provenance. This violates the requirement that provenance equal `FamilyScoringInput.evidence_refs` verbatim.

2. `tests/test_shared_runner_scoring_contract.py:1492-1499,2350-2352,2710-2713,2720-2749` — NegArena is counted as enrolled unconditionally, but its only behavioral protocol test skips when the external bridge is unavailable. Consequently, a normal run without the bridge can pass catalog closure while never checking NegArena's returned leaf set, determinism, provenance, or terminal-state isolation. The separate opt-in skip gate does not make this protocol coverage unconditional.

FINDINGS: 2
--- END REVIEW ---

## Disposition

### Finding 1 — REFUTED

**Claim.** `NegarenaScorer.__call__` takes `evidence_refs` as a separate keyword
instead of reading `scoring_input.evidence_refs`, so a caller that omits or
mismatches it produces empty or fabricated provenance.

**Code evidence.**

- `measurement.py:508-510` is exactly the `FamilyScorer` Protocol signature
  required by `kernel_scoring_contract_spec.md` section 2 verbatim:
  `def __call__(self, scoring_input: FamilyScoringInput, *, evidence_refs:
  tuple[str, ...] = ()) -> FamilyScoreSet: ...`. The spec's own production call
  site is `plugin.build_scorer(family_case)(scoring_input,
  evidence_refs=scoring_input.evidence_refs)` — the finalizer, not the scorer,
  owns threading `scoring_input.evidence_refs` into the `evidence_refs`
  keyword. `NegarenaScorer.__call__` propagating a separately-named
  `evidence_refs` parameter into the leaves it builds is the contract, not a
  deviation from it — and is byte-for-byte the same shape as the reference
  migration (`govsim/measurement.py:841-878`, verified directly: identical
  signature, identical propagation).
- Every one of the three production call sites that can reach a family scorer
  (`task/evaluation.py:843-848` finalize, `:1092-1097` replay, `:1261-1265`
  audit) passes `evidence_refs=scoring_input.evidence_refs` and then calls
  `_check_evidence_refs_are_scoring_input_verbatim(score_set, scoring_input)`
  immediately afterward (`task/evaluation.py:773-794`), which raises
  `ValueError` if any returned score's `evidence_refs` disagrees with
  `scoring_input.evidence_refs`. This guard already exists in the kernel
  precisely to catch "nothing stops a scorer from fabricating a different
  [value] on the envelopes it returns" (its own docstring, citing
  `kernel_contract_impl_review.md` finding 13) — it is not something this
  migration needed to add, and it makes the exact fabrication scenario the
  finding describes unreachable through any production path (finalize,
  replay, or audit): a receipt can never be sealed with provenance that
  disagrees with `scoring_input.evidence_refs`.
- No in-repo production call site invokes `NegarenaScorer.__call__` directly
  outside those three kernel paths (`grep` over `src/aeread_families/negarena/`
  confirms the only other consumer, `parity.py:174`, calls the named
  `.score_seat_outcome(...)` method, never `__call__`).

**Conclusion.** The scenario described (calling `__call__` with a missing or
wrong `evidence_refs`) is possible only by bypassing the finalizer/replay/audit
entirely — e.g. a test calling the scorer directly — and is true of every
family built to this contract, including the reviewed reference migration. It
is the specified shape, not a negarena-specific defect, and the kernel already
enforces the invariant the finding is worried about on every real path. No
code change made.

### Finding 2 — CONFIRMED; FIXED for three of four named gaps; one residual limit stated

**Claim.** `("negarena", "0.1.0")` satisfies the protocol suite's closed-world
catalog-closure check via `_BRIDGE_GATED_ENROLLED_FAMILY_VERSIONS`, but its own
behavioral check, `test_negarena_obeys_the_scoring_contract`, skips whenever
the real upstream bridge is unavailable — so a normal run without the bridge
can pass the whole module while never exercising NegArena's `__call__`
contract (returned leaf set, determinism, provenance, terminal-state
isolation) at all.

**Verified true as described.** `_negarena_bridge()`
(`tests/test_shared_runner_scoring_contract.py:1474-1499`) calls
`pytest.skip(...)` when the pinned upstream checkout or bridge interpreter is
absent; `_negarena_fixture_pair` calls it at line 1807, so
`test_negarena_obeys_the_scoring_contract` (2720-2749) skips under the same
condition. `_BRIDGE_GATED_ENROLLED_FAMILY_VERSIONS` (2350-2352) is a
hand-maintained set that satisfies `_assert_trusted_catalog_is_closed`
(2710-2713) regardless of whether that behavioral test actually ran in the
same session. A `pytest tests/test_shared_runner_scoring_contract.py -q` run
with no bridge env vars exported does show
`test_every_registered_family_obeys_the_scoring_contract` passing and
`test_negarena_obeys_the_scoring_contract` skipped — confirmed directly, not
assumed.

**Why it is not fully closable within this migration.** The remedy the
finding implies — make NegArena's behavioral contract check run unconditionally —
is unavailable for two independent reasons, both structural to this family,
not oversights of this migration:

1. Ruling R7's terminal-state-isolation check and R9's sensitivity witness
   require two REAL, genuinely differing settlements that share a
   byte-identical outcome. Only the real bridge (upstream's own
   `after_game_ends()`) can produce a genuine differing settlement; fabricating
   one would mean this module computing `Trade.execute_trade`/`Valuation.value`
   itself, exactly the reimplementation the adapter's own design rule (spec
   section 3, this module's docstring) forbids.
2. Making the check mandatory by default would mean reversing the
   already-established, pre-existing project convention that every
   external-bridge-dependent fidelity check in this codebase (tau2, econevals,
   agenticpay, econagent, alympics — all in `conftest.py` before this branch
   existed) is off by default and escalated to a hard failure only via its own
   `AEREAD_<FAMILY>_BRIDGE_REQUIRED` opt-in gate. `AEREAD_NEGARENA_BRIDGE_REQUIRED`
   already exists (`conftest.py:106-116,132`) and is verified directly against
   the real `conftest.pytest_terminal_summary` hook
   (`tests/test_negarena_bridge_required_gate.py`). Changing that convention
   for every bridge-gated family is a cross-cutting test-policy decision this
   migration should not make unilaterally.

**What was fixed.** Three of the four named gaps — returned leaf set,
determinism, provenance — do not actually require the real bridge: an
`invalid_measurement`/`malformed_action` termination reason short-circuits
both `score_seat_outcome` and `score_agreement_reached` before either reaches
the bridge (`measurement.py`'s `INVALID_TERMINATION_REASONS` branch), a fact
this family's own suite already exercises at the bare-function level
(`test_negarena_measurement.py::test_score_seat_outcome_never_touches_the_bridge_for_an_invalid_termination`,
`::test_score_agreement_reached_never_needs_the_bridge_for_a_malformed_termination`)
but never at the `NegarenaScorer.__call__`/`FamilyScoreSet` level that a real
receipt actually goes through. Added
`tests/test_shared_runner_scoring_contract.py::test_negarena_contract_leaf_set_determinism_and_provenance_without_the_bridge`,
which calls `NegarenaScorer.__call__` end-to-end with a hand-built
`FamilyScoringInput` (invalid termination reason, no phase instances) and a
sentinel `bridge` that raises `AssertionError` if `.settle` is ever called,
and asserts: the returned leaf set equals the manifest's declared
finalize-time leaf set, primary/admission match the declaration, the scorer
is deterministic across two calls on the same input, and every returned
envelope's `evidence_refs` equals `scoring_input.evidence_refs` verbatim. This
test requires no upstream checkout and no bridge interpreter and always runs.

**Test name:** `test_negarena_contract_leaf_set_determinism_and_provenance_without_the_bridge`
(`tests/test_shared_runner_scoring_contract.py`).

**Mutation result:** with `measurement.py`'s `NegarenaScorer.__call__` mutated
to return `scores=(seat_outcome_score,)` (dropping `agreement_score`), the new
test fails with `AssertionError: assert {'negarena_seat_outcome_leaf'} ==
{'negarena_agreement_reached_leaf', 'negarena_seat_outcome_leaf'}`. The
mutation was applied via a `/tmp` copy of the file (never a `git checkout` of
uncommitted work), the failure observed, then the original file byte-for-byte
restored and `diff`-confirmed identical before continuing.

**Residual, stated limit (not escalated as an open owner-decision question —
recorded for visibility, matching the spec's own "Stated limit" convention;
this residual does not touch the leaf set, primary, admission membership, or
an estimand definition, so it is not withheld from this document on that
ground either — it is simply not fixable without either violating the
family's own fidelity rule or changing a five-family-wide test-policy
convention this migration does not own).** The terminal-state-isolation
contrapositive (R7) and the trajectory sensitivity witness (R9) for
`negarena_seat_outcome` remain checked only when the bridge is provisioned,
exactly like every other bridge-dependent family's fidelity claims in this
codebase. `AEREAD_NEGARENA_BRIDGE_REQUIRED=1` converts that skip into a hard
failure for any run that must certify it; it is off by default so a
contributor working on something unrelated is not surprised by it, mirroring
five other pre-existing families' identical convention.
