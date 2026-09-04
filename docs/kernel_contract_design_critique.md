<!--
Provenance: independent design critique of kernel_scoring_contract_spec.md, produced by a
reviewer operating under a restricted, permitted file-range view (it cannot write files itself).
Reproduced verbatim below; verdicts against the actual codebase follow in a separate section.
-->

## 1. Scorer input

1. The plain dataclass is the cleaner API: the current finalizer passes only `recorded_outcome`, while the new type makes outcome versus trajectory access explicit. But the claim that only two scorers depend on Mapping cannot be verified from the permitted ranges—the only visible dependency is the generic invocation. (`kernel_scoring_contract_spec.md:55-62`; `src/aeread/shared_runner/task/evaluation.py:315-320`)
2. `frozen=True` is insufficient for the promised deep immutability. Both `outcome` and `PhaseInstance.observations` remain mappings, while action/transition contents can contain mutable objects; the spec defines no freezing algorithm or canonical frozen representation. (`kernel_scoring_contract_spec.md:40-65`; `src/aeread/shared_runner/task/scheduler.py:267-278`)

## 2. Deferred leaves

3. The design works only for deferred, non-admission diagnostics. A deferred primary or admission leaf is omitted at finalization, but `FamilyScoreSet` requires the primary and every admission leaf to be present. The spec must explicitly forbid deferred leaves from both roles. (`kernel_scoring_contract_spec.md:120-127`; `kernel_scoring_contract_spec.md:137-145`; `src/aeread/shared_runner/measurement.py:413-436`)
4. "Recorded as declared-and-deferred" has no specified carrier. `FamilyScoreSet` contains only primary, returned scores, and admission IDs, and the visible finalizer passes nothing else onward. Receipt inclusion beyond `invalid_admission_leaf_ids` cannot be verified because receipt code is outside the authorized ranges. (`kernel_scoring_contract_spec.md:144-147`; `src/aeread/shared_runner/measurement.py:393-395`; `src/aeread/shared_runner/task/evaluation.py:315-320`)
5. The manifest could apparently classify every leaf as deferred, but normalization requires a nonempty score set containing a primary. Require at least one finalize-time primary leaf. (`kernel_scoring_contract_spec.md:140-143`; `src/aeread/shared_runner/measurement.py:399-416`)

## 3. Manifest policy

6. Actual manifest extensibility cannot be verified within the permitted files. The spec defines neither concrete fields/types nor parsing, defaults, serialization, compatibility, or version-bump behavior; the visible runtime resolves the manifest but never reads leaf policy. (`kernel_scoring_contract_spec.md:107-128`; `kernel_scoring_contract_spec.md:232-236`; `src/aeread/shared_runner/task/evaluation.py:297-320`)
7. The proposed test checks returned IDs, primary, admission IDs, and evidence references, but not whether the primary corresponds to `primary_estimand`, whether every deferred leaf names a wait artifact, or whether illegal primary/admission scope combinations exist. Those stated rules therefore lack a specified validator. (`kernel_scoring_contract_spec.md:120-150`; `kernel_scoring_contract_spec.md:196-214`)

## 4. Replay claim

8. The "already walks the full trajectory and discards it" claim is not verifiable from the authorized range. The visible portion walks phase starts and action starts through parse-result lookup, but lines 201–279—where transition replay, construction, and return would occur—were excluded. The visible caller receives only outcome plus an event. (`kernel_scoring_contract_spec.md:22-26`; `src/aeread/shared_runner/task/evaluation.py:138-200`; `src/aeread/shared_runner/task/evaluation.py:304-309`)
9. Retention is not specified field-by-field. `PhaseInstance` needs post-state hash, observations, complete action records, and transitions; the visible replay range has not shown how those values and their contributing event IDs become one immutable instance. (`src/aeread/shared_runner/task/scheduler.py:267-278`; `src/aeread/shared_runner/task/evaluation.py:150-200`; `kernel_scoring_contract_spec.md:67-68`)
10. "Exclusively from sealed evidence" is inaccurate: replay also invokes the current plugin's phases, initial state, and eligible-actor logic, using a currently validated family payload. The contract must distinguish evidence-carried data from values recomputed using live plugin code. (`kernel_scoring_contract_spec.md:42-47`; `src/aeread/shared_runner/task/evaluation.py:142-167`; `src/aeread/shared_runner/task/evaluation.py:301-308`)

## 5. Remaining implementer choices

11. Return shape contradicts itself: Section 2 preserves bare envelopes and sequences for single-leaf families, while Section 5 requires every migrating `__call__` to return `FamilyScoreSet` and says agents cannot choose the return shape. (`kernel_scoring_contract_spec.md:73-105`; `kernel_scoring_contract_spec.md:164-177`)
12. Evidence-reference ordering is underspecified. "Deterministic, deduplicated, ordered" does not say event-log order, lexical event-ID order, or dependency traversal order, nor which validation-only reads count as "used." (`kernel_scoring_contract_spec.md:67-68`; `src/aeread/shared_runner/task/evaluation.py:141-177`)
13. Provenance is duplicated in `FamilyScoringInput.evidence_refs` and the keyword argument, with no rule for detecting disagreement or which value is authoritative. (`kernel_scoring_contract_spec.md:50-53`; `kernel_scoring_contract_spec.md:73-79`; `kernel_scoring_contract_spec.md:93-96`)
14. The protocol test refers to `trajectory_leaf_ids`, but the manifest rules define only finalize-time versus deferred scope; no field or rule declares which finalize-time leaves are trajectory-sensitive. (`kernel_scoring_contract_spec.md:118-150`; `kernel_scoring_contract_spec.md:216-220`)
15. The paired-history protection is pseudocode, not a complete test: the critical score-difference assertion is an ellipsis, so eleven implementers can choose different comparisons, invalid-status handling, or leaf subsets. (`kernel_scoring_contract_spec.md:216-228`)

CRITIQUE-ITEMS: 15

---

## Verdicts against the actual codebase

Evaluated with full (unrestricted) repository access against this worktree's `origin/main`
(commit `a1e382a` at review time). Where the critique's stated reason was "cannot be verified
from the permitted ranges," I verified directly instead of leaving the question open.

**1. "Only two scorers depend on Mapping" — CONFIRMED, and worse than the critique suspected.**
Not merely unverifiable — it is false on current `origin/main`. At least five registered
families already call the shared finalizer with an `outcome: Mapping[str, Any]`-shaped scorer,
not two:
- `housing/runner.py` (closure) and `datacenter_development` (`measurement.py:136-138`, already
  returning `FamilyScoreSet`) — the two the spec names.
- `procurement_allocation/environment.py:765-767`, `procurement_grounding/environment.py:335-339`,
  `commercial_state_calibration/environment.py:329-334` — three more `__call__(self, outcome:
  Mapping[str, Any], *, evidence_refs: tuple[str, ...] = ())` scorers, each reached via
  `finalize_family_execution` in that family's own `runner.py` (`procurement_allocation/runner.py:153`,
  `procurement_grounding/runner.py:104`, `commercial_state_calibration/runner.py:529`), not test-only code.
`datacenter_development/stack_environment.py` reuses the same `FAMILY_ID`/scorer class as
`environment.py`, so it is not a sixth unit, but the corrected count is still five, not two.
Section 0's "verified facts," Section 1's two-file cost argument, and Section 7's migration
order/effort all need correcting to the real scope. This is a factual defect in the spec, not
an implementer judgment call, and it should be fixed before Section 7's "rebase all twelve
branches" step is scheduled.

**2. Freezing algorithm unspecified — CONFIRMED.**
`_freeze()` (`scheduler.py:34-46`) exists and is applied only to `observations` in the live
`PhaseInstance` construction (`scheduler.py:861`); `actions`/`transitions` there are plain tuples,
not deep-frozen. In `replay_family_state`, the `outcome` returned by `plugin.outcome(...)`
(`evaluation.py:273`) is never frozen at all. `frozen=True, slots=True` on `FamilyScoringInput`
only blocks reassigning its top-level attributes; nothing stops mutating a dict inside `outcome`
or a nested list inside an action record. The existing `_freeze` helper is private to
`scheduler.py` and the spec never references it. Needs a stated freezing algorithm (reuse
`_freeze`, export it, and apply it to `outcome` and every `PhaseInstance` field).

**3. Deferred primary/admission not explicitly forbidden — CONFIRMED.**
`FamilyScoreSet.__post_init__` (`measurement.py:397-437`) does reject this at runtime — it
requires `primary_leaf_id` to be a key of the returned `scores` and to be a member of
`admission_leaf_ids` — so the failure mode is caught, just not with a clear diagnostic pointing
at "you named a deferred leaf as primary/admission in the manifest." The spec should state the
prohibition in Section 3/4 text directly, and say where it is enforced (manifest-level
validation, ideally, not a generic `MeasurementContractError` from the score-set constructor).

**4. No carrier for "declared-and-deferred" — CONFIRMED.**
`EvaluationReceipt` (`receipts.py:116-148`) has fields for `primary_leaf_id` and `scores` only —
no admission-id list, no deferred-leaf list, nothing structured beyond a free-text
`failure.message` built in `_score_admission` (`evaluation.py:95-116`). A new receipt field is
needed if deferred leaves are to be "recorded," not silently absent.

**5. Manifest could declare zero finalize-time leaves — CONFIRMED.**
`FamilyScoreSet.__post_init__` requires `self.scores` to be a nonempty tuple containing the
primary (`measurement.py:399-400, 413-416`). A manifest with every leaf `deferred` cannot
satisfy this. The spec should require at least one `finalize_time` leaf capable of serving as
primary.

**6. Manifest schema unspecified — CONFIRMED.**
`FamilyManifest` (`schemas.py:347-370`) and `MeasurementDeclaration` (`schemas.py:249-291`) have
no field today for leaf policy, primary/admission leaf ids, or per-leaf scope — this is a wholly
new addition. The spec gives no field names/types, no `from_dict` parsing/defaults, no
serialization, and no rule for whether adding it bumps `FamilyManifest.SPEC_VERSION`
(`"aeread.family/0.1"`). Given the spec's own stated goal — removing judgment calls so eleven
agents don't each invent something different — this is a real gap the spec's author must close,
not something to leave implicit.

**7. Protocol test under-validates the stated rules — CONFIRMED**, as a direct consequence of #6:
since the manifest has no leaf-policy fields yet, none of primary-vs-`primary_estimand`,
deferred-leaf wait-artifact, or illegal scope combinations can be checked today. Separately,
even the sketched Section 6 test never joins `produced.primary_leaf_id` against the manifest's
existing `primary_estimand` (`MeasurementDeclaration.primary_estimand`, `schemas.py:251`) — a
family could set them inconsistently and the shown test would not catch it.

**8. "Already walks the full trajectory and discards it" — REFUTED** (the critique's doubt, not
the spec's claim). With full-file access, `replay_family_state` (`evaluation.py:138-278`) is
confirmed to walk phase starts, actions, parse results, legality, transitions, terminal, and
outcome in full, and to return only `(outcome, outcome_event)` — everything else computed along
the way is discarded. The spec's description at lines 22-26 is accurate.

**9. Retention not specified field-by-field — CONFIRMED, and this is the most significant single
finding: it is not merely underspecified, it is currently impossible.** The sealed event log
does not carry enough data to populate `PhaseInstance.observations` at all. `phase_instance_started`'s
payload carries only `phase, eligible_actors, pre_state_sha256` (`execution.py:2804-2820`), and
`phase_instance_succeeded`'s payload carries only `phase_id, post_state_sha256, logical_action_ids`
(`execution.py:2840-2851`, sealed from the `phase_completed` lifecycle hook). Per-seat observation
content is never written to durable evidence anywhere in this codebase, live or replay path. So
building `FamilyScoringInput.phase_instances` with a genuinely populated `observations` field, per
the literal `PhaseInstance` type the spec cites (`scheduler.py:268-278`), cannot be done from
sealed evidence today. The spec's author must choose: (a) add a new sealed event that carries
observations (a real event-schema/evidence-format change, unaddressed anywhere in the eight
sections), (b) recompute observations live via the plugin during replay (which then has the same
"not exclusively from sealed evidence" character as #10, and needs an equality check like the
other recomputed fields), or (c) drop/null the `observations` field for the replay-constructed
`PhaseInstance` and say so explicitly. This blocks writing `replay_family_scoring_input` as
currently specified.

**10. "Exclusively from sealed evidence" is inaccurate — CONFIRMED.** `replay_family_state` calls
live `plugin.phases`, `plugin.initial_state`, `plugin.eligible_actors`, `plugin.step`,
`plugin.terminal`, `plugin.outcome` (`evaluation.py:142-167, 224-277`) and checks each result for
equality against the sealed payload — it does not read the phase spec, transition result, or
outcome purely from evidence and skip the plugin. The docstring claim in Section 1
("reconstructed exclusively from sealed evidence... The live in-memory `EpisodeResult` is never
reachable") is true only for the *live episode object*; it is not true that no live code runs.
The contract should distinguish "sealed-and-checked" from "sealed-and-read-verbatim."

**11. Return-shape contradiction — CONFIRMED.** Section 2 states "All three return shapes stay
supported so single-leaf families need no change beyond their argument access," which reads as a
general property of the type, not scoped to only the three deferred terminal-only families.
Section 5 step 3 tells every migrating agent's `__call__` to return `FamilyScoreSet`. If any of
the eleven migrating families is single-leaf, these instructions conflict, and nothing in the
text resolves which governs. Needs an explicit scoping statement.

**12. Evidence-ref ordering underspecified — CONFIRMED.** "Deterministic, deduplicated, ordered"
(Section 1) never says event-log/append order vs. lexical event-id order vs. traversal order, and
does not say whether events read only to check equality (and not incorporated into the returned
`outcome`/`phase_instances`) count as "used." Both are real ambiguities an implementer must
resolve without guidance.

**13. Duplicated evidence_refs channel — NEEDS-RULING**, not a plain defect. Verified the
redundancy is real (`FamilyScoringInput.evidence_refs` and the `evidence_refs=` keyword are
always the same value at every call site shown — the finalizer at `evaluation.py` and the
protocol test both pass `scoring_input.evidence_refs` as the kwarg). But Section 5 does state the
governing rule ("provenance...is always `scoring_input.evidence_refs` verbatim"), and keeping the
keyword plausibly exists on purpose, to preserve call-signature parity with the pre-existing
`__call__(outcome, *, evidence_refs=...)` shape so a migrating scorer's outer call convention
doesn't also have to change. Whether the kernel should additionally assert the kwarg equals
`scoring_input.evidence_refs` at the one call site (defense in depth against a future third
caller passing something else) is a judgment call for the spec's author, not an obvious bug.

**14. `trajectory_leaf_ids` has no declared source — CONFIRMED.** `EstimandSpec.input_scope`
already has a `"trajectory"` value (`measurement.py:24`), so it is plausible this is meant to be
derived from leaves whose `estimand.input_scope == "trajectory"`, but Sections 3-4's manifest
rules never say this, and Section 6 uses `declared.trajectory_leaf_ids` as though it is already a
defined property. The spec must state where this field comes from.

**15. Paired-history assertion is incomplete — CONFIRMED.** Section 6's code ends with a literal
comment, not an assertion, for the one check the spec itself calls "the part with teeth." Section
7 assigns this test's authorship to the kernel implementer, not the eleven migration agents, so
this is an immediate authoring gap, not a future implementer's discretion. The spec must specify
the actual comparison — which leaves must differ (all trajectory leaves, or at least one), how an
`invalid_measurement` status on one side is treated, and whether non-trajectory leaves in the
same fixtures are asserted equal — before this test can be written as prescribed.

### Tally
CONFIRMED: 1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 14, 15 (13)
REFUTED: 8 (1)
NEEDS-RULING: 13 (1)

### Blocking assessment
Three of the CONFIRMED items are genuinely blocking, not implementer-discretion items the
spec already delegates correctly:
- **#1** — the migration's actual scope (5 families, not 2) changes Section 7's plan and
  should be corrected before work is sequenced.
- **#6** — there is no manifest schema to declare leaf policy against; Sections 3-4 cannot be
  implemented until the spec's author fixes the concrete fields/types/parsing/versioning.
- **#9** — `PhaseInstance.observations` cannot be reconstructed from sealed evidence with the
  current event schema at all; this needs an explicit ruling (new sealed event vs. live
  recompute-with-check vs. drop the field) before `replay_family_scoring_input` can be written.
- **#15** additionally blocks writing the one protocol-test assertion the spec calls load-bearing.

The remaining CONFIRMED items (#2, #3, #4, #5, #7, #10, #11, #12, #14) are real spec gaps but
each has a conservative default an implementer could adopt and flag for review without stalling
the start of work (e.g., reuse and export `_freeze`, add an explicit manifest-level prohibition
and a receipt field, require ≥1 finalize-time leaf, pick event-log order for `evidence_refs`,
derive `trajectory_leaf_ids` from `input_scope`). Recommendation: get the spec's author to rule
on #1, #6, #9, and #15 before coding starts; the rest can proceed in parallel with the choices
above stated in code comments and the family status docs for later confirmation.

---

## Resolutions — protocol-test milestone (`tests/test_shared_runner_scoring_contract.py`)

Ruling R5 accepted items #2-5, #7, #11, #12, #14, #15 and said to resolve each in this milestone,
recording any resolution that is a choice rather than a deduction here.

**#14 (`trajectory_leaf_ids` source) — resolved as ruled.** The protocol test derives it from the
already-produced `ScoreEnvelope.leaf.estimand.input_scope == "trajectory"`, not from a new manifest
field. No manifest change was needed: the manifest declares leaf identity and finalize/deferred
scope only (section 3); which finalize-time leaves are trajectory-scoped is read off the scorer's
actual output, consistent with `input_scope` already living on `EstimandSpec`, not on
`LeafPolicyDeclaration`.

**#15 (paired-history assertion) — completed.** For every leaf id in `trajectory_leaf_ids`, the
test asserts the leaf's `.primary` `MetricValue` differs between the two required fixtures'
produced score sets, after first asserting their `FamilyScoringInput.outcome` bytes are identical
and their `phase_instances` are not. A scorer that reads only `outcome` for a nominally
trajectory-scoped leaf therefore produces the same value for both fixtures and fails here — see
this file's own mutation-tested proof (temporarily made the reference leaf read
`outcome["x_count"] >= outcome["y_count"]`; the test failed with the two `MetricValue(1.0, ...)`
sides equal, as expected, then was reverted).

**#7 (protocol test under-validates) — partially resolved; one gap remains open by choice, not
oversight.** The test now validates leaf-set equality, primary, admission, and per-score
`evidence_refs` identity against `FamilyManifest.finalize_time_leaf_policy()`. It does **not**
additionally check that the primary leaf's `estimand_id` matches `MeasurementDeclaration.
primary_estimand` string-for-string; `finalize_time_leaf_policy()` only requires
`primary_leaf_id` to name a declared `finalize_time` leaf (schemas.py), independent of the
manifest's separate `primary_estimand` field. Adding that cross-check is straightforward but was
left out of this milestone because it touches `MeasurementDeclaration.from_dict`'s validation, not
the protocol test itself, and none of the fixtures in this file would exercise it either way
(each's `primary_estimand` was authored to already match). Flagging here rather than silently
absorbing scope.

**Choice: which families are enrolled in this test's own registry, and why
`datacenter_development_v1` is not one of them.** The protocol test builds its own
`PluginRegistry`, separate from any production registry (none exists yet that combines all
families) and separate from any campaign `RunPlan` (so attaching a leaf policy here cannot
perturb a frozen `plan_sha256`/`artifact_sha256`, per ruling R1). Four of the five families
already migrated to `FamilyScoringInput` (housing, procurement_allocation, procurement_grounding,
commercial_state_calibration) are enrolled with one real, provider-free fixture episode each;
none declares a trajectory-scoped leaf, so the paired-history requirement does not apply to them.

`datacenter_development_v1` is deliberately **not** enrolled. Its `negotiation_temporal_compliance`
leaf is genuinely `input_scope="trajectory"` (forced by `reference_kind="temporal_property"`, per
`measurement.py`'s `_REFERENCE_SCOPE`), but that family's `environment.py` accumulates the full
ordered `public_history`/`temporal_violations` state directly into its `outcome` payload
(`environment.py`'s `outcome()`, ~L544-545). That makes `outcome` itself a function of the entire
trajectory: any two runs whose trajectories differ will differ in `public_history` and therefore
in `outcome`, so a byte-identical-outcome/differing-trajectory pair cannot be produced by running
the real environment, and `_replay_family_trajectory`'s live cross-check would correctly reject
any fabricated evidence where a forged outcome disagreed with what replaying the actions actually
produces. This is not a flaw in the protocol test or in `negotiation_temporal_compliance`'s current
`__call__` (which reads the leaf from `outcome["temporal_violations"]`) — for this specific family,
`outcome` already is a complete, honest summary of the trajectory fact the leaf needs, so reading
it from there cannot silently diverge from the trajectory the way the paired-history check is
designed to catch elsewhere. It does mean this family cannot be used to demonstrate that check
has teeth. Rather than declare the requirement vacuously satisfied by omission, this milestone adds
one minimal, purpose-built, provider-free fixture family, `kernel_contract_reference_v1` (two
single-actor rounds; the outcome is an order-insensitive tally of both rounds' choices, but one
leaf reads which round chose "x" first from `phase_instances`) — registered as trusted
(`TRUSTED_BUILTIN_PLUGIN_KEYS` in `registry.py`) specifically so the protocol test has a genuine,
honestly-pairable trajectory-scoped leaf to exercise, and so a scorer that quietly reads only the
outcome for such a leaf is provably caught (see the #15 entry above). This is a choice, not a
deduction: an alternative would have been to accept that no family among the five demonstrates
paired-history teeth today and note it as a gap instead of adding a fixture family; the reference
family was preferred because an assertion with no failing witness anywhere in the suite is weaker
protection for the eleven migrations still to come.

---

## Resolutions — ruling R7 (mislabelling contrapositive)

Ruling R7 rejected the first-instinct assertion — "trajectory-declared leaves must score
differently across the pair" — as unsound (a legitimate trajectory metric may map two histories to
the same value) and directed the contrapositive instead: for every leaf declared
`input_scope="terminal_state"`, its score must be IDENTICAL across the two fixtures whose terminal
outcomes are byte-identical and whose trajectories differ. This milestone implements that in
`test_every_registered_family_obeys_the_scoring_contract`:

- The unsound "trajectory leaves must differ" loop is removed, not corrected — R7 states plainly
  that no sound replacement assertion exists for trajectory-declared leaves at this pair; the
  paired fixtures are still asserted to have a byte-identical outcome and a differing
  `phase_instances`, but nothing further is asserted about trajectory-declared leaves themselves.
- The pairing block's gate changed from "the family's leaves include at least one declared
  `trajectory`" to "the family supplied at least two fixtures," with the pre-existing `len(...) >=
  2` requirement kept as an unconditional assertion whenever a `trajectory`-declared leaf is
  present. This closes the exact gap R7 names: gating purely on the (self-reported, and exactly
  the thing under test) `trajectory` label would let a family that mislabels every trajectory-
  reading leaf as `terminal_state` skip the pairing block entirely, since it would then declare no
  `trajectory` leaves at all.
- A determinism pre-check runs before the mislabelling comparison: each of the two fixtures'
  scorers is invoked a second time on the same `FamilyScoringInput`, and every `terminal_state`
  leaf's measurement content is asserted equal to its first invocation. Its failure message
  ("...is nondeterministic: invoking the scorer twice on the SAME scoring input produced two
  different measurements...") is textually distinguishable from the mislabelling message
  ("...is declared input_scope=terminal_state but its score differs between two fixtures...").
- The comparison helper `_score_measurement_content` compares `status`, `primary`, `metrics`,
  `reference_values`, and `validity`, and deliberately excludes `evidence_refs` (verified against
  `ScoreEnvelope`'s field list in `measurement.py`: `status`, `leaf`, `primary`, `metrics`,
  `reference_values`, `validity`, `evidence_refs`, `utility_by_seat`, `capture_by_seat`). Two
  differing trajectories seal different sealed-event ids, so `evidence_refs` differs between the
  pair by construction regardless of whether the leaf is honestly terminal-scoped; comparing whole
  envelopes would fail every terminal-scoped leaf on every paired family, always, which is not the
  failure this check exists to report. `leaf` and the per-seat breakdowns are excluded as identity
  and provenance respectively, not measurement content — not named in R7's list, and both are
  either already asserted equal by leaf-id lookup (`leaf`) or unused by any fixture in this file
  today (`utility_by_seat`/`capture_by_seat`); a future family with genuine per-seat content should
  revisit whether they belong in this tuple.

**Mutation-verified, both directions (temporarily edited `_ReferenceScorer.__call__`, ran the
suite, confirmed the expected failure, then restored the file from a backup copy rather than a
VCS checkout):**

1. Made `label_balance` (declared `terminal_state`) add `1.0 if first_choice_is_x else 0.0` to its
   value — i.e. secretly trajectory-dependent while still labelled `terminal_state`. The suite
   failed with: `kernel_contract_reference_v1/label_balance is declared
   input_scope=terminal_state but its score differs between two fixtures with a byte-identical
   outcome and a differing trajectory -- it is secretly trajectory-dependent and mislabelled`,
   with the two `MetricValue` sides showing `1.0` vs `0.0` as expected. The new assertion fires.
2. Made the same leaf add a monotonically increasing counter value on every call (unrelated to
   trajectory or outcome — a stand-in for any nondeterministic scorer). The suite failed at the
   determinism pre-check, before the mislabelling comparison ever ran, with: `.../label_balance is
   nondeterministic: invoking the scorer twice on the SAME scoring input produced two different
   measurements, so no conclusion about terminal_state mislabelling can be drawn from the
   paired-fixture comparison below`. Nondeterminism is reported as nondeterminism, not as
   mislabelling.

**Stated limit (R7's own words, recorded here as directed): one counterexample pair cannot prove
non-dependence.** A leaf that is secretly trajectory-dependent can still coincide on this
particular pair of trajectories (e.g. a bug that depends on trajectory length rather than order,
when both fixtures happen to have the same length) and pass undetected. This check is a
falsification opportunity, not a proof: it catches the mislabelled leaf whenever the pair the
family supplies happens to discriminate, and says nothing when it does not. Stronger coverage
would need several deliberately discriminating trajectory mutations per family (varying order,
length, and per-actor identity independently) rather than one incidental pair; that is out of
scope for this milestone and is recorded here as the known gap rather than implied away.

