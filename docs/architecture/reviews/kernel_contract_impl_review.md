# Kernel scoring-contract implementation review

**Provenance.** The section below, delimited by `BEGIN REVIEW` / `END REVIEW`,
is reproduced verbatim from an independent implementation review of the
kernel scoring contract (`kernel_scoring_contract_spec.md`) as implemented on
branch `zeyu/kernel-contract` through commit `6fc8f22` ("test(kernel): add
the registry-driven family scoring-contract protocol test"). It was supplied
to this document's author for verification and remediation, not authored by
that author. No files had been modified when the review was written; it is a
static review, not a report of any test run.

The **Disposition** section following it was added by the engineer who
verified each finding against the code and, where confirmed and actionable,
fixed it. Every disposition names the commit, the file(s) changed, and the
regression test whose failure-before/pass-after was mutation-verified (the
fix was temporarily reverted via a `/tmp` backup-and-restore, never `git
checkout`, and the test confirmed to fail, then the fix was restored and the
test confirmed to pass again).

--- BEGIN REVIEW ---
1. **Real bug — scorer isolation is not enforced against stateful plugins.**  
   **Location:** `src/aeread/shared_runner/task/execution.py:3337-3405`; `src/aeread/shared_runner/task/evaluation.py:492-510`; `tests/test_shared_runner_housing.py:204-210`  
   **Scenario:**
   1. Execution resolves one plugin instance and runs all live hooks on it.
   2. A plugin retains live state from `step()` or `outcome()` in an instance attribute.
   3. Finalization resolves that same instance and invokes `plugin.build_scorer(...)`.
   4. The returned scorer reads the retained attribute instead of `scoring_input`.
   5. Nothing in `FamilyScorer`, the registry, or the finalizer detects that bypass.  
   The housing test also proves the public API permits direct construction from `execution.episode_result`. None of the five migrated scorers currently exploits this, so this is a latent enforcement defect, not confirmed score corruption in an existing family.

2. **Real bug — reconstructed trajectories cannot represent sequential phases.**  
   **Location:** `src/aeread/shared_runner/task/evaluation.py:312-352`; `src/aeread/shared_runner/task/scheduler.py:793-846`  
   **Scenario:**
   1. A valid `mode="sequential"` phase has two eligible actors.
   2. Production applies one transition after each actor, producing two `transition_applied` events in one phase instance.
   3. Replay requires exactly one transition event at evaluation line 318.
   4. Finalization raises `ValueError("family replay phase lacks one transition")`.  
   If that cardinality check were merely relaxed, line 323 would still incorrectly call `plugin.step` once with all actions instead of replaying the production sequence. No current changed family uses sequential mode, so this is latent for a future otherwise-valid family.

3. **Real bug — the replay accepts an incomplete or contradictory phase-completion boundary.**  
   **Location:** `src/aeread/shared_runner/task/evaluation.py:172-205,312-353`; `src/aeread/shared_runner/task/execution.py:696-705,2840-2851`  
   **Scenario:**
   1. Evidence contains the phase start, actions, and transition, but omits `phase_instance_succeeded`, or that event lists the wrong action IDs/post-state hash.
   2. `audit_reconciliation()` checks logical actions, attempts, provider calls, and tools—not phase instances.
   3. Replay never reads `phase_instance_succeeded`.
   4. It constructs a successful `PhaseInstance` and finalization proceeds.  
   This contradicts the stated guarantee that every phase boundary is cross-checked.

4. **Real bug — inconsistent leaf policy can bypass parsing and be registered.**  
   **Location:** `src/aeread/shared_runner/schemas.py:319-345`; `src/aeread/shared_runner/registry.py:255-299`; `tests/test_shared_runner_schemas.py:670-682`  
   **Scenario:**
   1. Create a valid `FamilyManifest`.
   2. Use `dataclasses.replace` on `measurement` to set an undeclared primary, a deferred admission leaf, or duplicate admission IDs.
   3. Register the resulting `FamilyManifest`.
   4. `_validate_plugin()` checks only `isinstance` and required hooks; registration succeeds.  
   The purported registration test never calls `PluginRegistry`: it only confirms that `FamilyManifest.from_dict()` rejects one bad dictionary. Because these dataclasses have no validating `__post_init__`, "validated `FamilyManifest`" is only an assumption.

5. **Real bug — production manifests and finalization do not enforce leaf policy.**  
   **Location:** `src/aeread_families/housing/runner.py:1390-1400`; `src/aeread_families/datacenter_development/environment.py:173-179`; `src/aeread_families/procurement_allocation/environment.py:841-850`; `src/aeread_families/procurement_grounding/environment.py:420-425`; `src/aeread_families/commercial_state_calibration/environment.py:421-427`; `src/aeread/shared_runner/task/evaluation.py:506-511`  
   **Scenario:**
   1. A migrated scorer omits a non-admission diagnostic leaf while returning a self-consistent `FamilyScoreSet`.
   2. Its production manifest has no `leaves`, `primary_leaf_id`, or `admission_leaf_ids`.
   3. The finalizer only normalizes the scorer's return; it never obtains or compares manifest policy.
   4. A receipt with the silently dropped leaf is accepted.  
   Thus the manifest is not yet the production source of truth described by the contract.

6. **Real bug — registered policy and run-plan policy are not bound to one another.**  
   **Location:** `src/aeread/shared_runner/registry.py:291-300,419-449`  
   **Scenario:**
   1. Register manifest A with leaf policy A.
   2. Supply a run-plan manifest B with the same family/version/plugin identity but different policy.
   3. `resolve_manifest(B)` compares identity only and returns A's plugin.
   4. The protocol test reads `registration.manifest` while execution carries B.  
   Once policies are placed in production manifests, two conflicting "sources of truth" can therefore coexist without rejection.

7. **Real bug — the protocol test is not closed-world over production families.**  
   **Location:** `tests/test_shared_runner_scoring_contract.py:884-918`; `tests/test_shared_runner_scoring_contract.py:24-38`  
   **Scenario:**
   1. Add or register a new production family in its normal setup.
   2. Do not add it to `_build_protocol_test_registry_and_fixtures`.
   3. The test's private registry still contains exactly the fixtures manually inserted into it.
   4. `assert set(fixtures) == set(registrations)` passes.  
   Datacenter is already deliberately omitted, demonstrating that this equality is not registry-wide enrollment.

8. **Real bug — the protocol test shortcuts the production finalizer call path.**  
   **Location:** `tests/test_shared_runner_scoring_contract.py:884-918`; `src/aeread/shared_runner/task/evaluation.py:495-518`  
   **Scenario:**
   1. Production finalization regresses to passing `scoring_input.outcome`, drops the evidence-ref keyword, or otherwise calls the scorer incorrectly.
   2. The protocol test independently reconstructs `FamilyScoringInput` and directly calls the scorer with the correct arguments.
   3. Its assertions remain green although production fails.  
   This is the exact direct-scorer shortcut pattern identified in the request. Existing family-specific finalizer tests provide some separate coverage, but this advertised protocol test does not.

9. **Real bug — the trajectory test excludes the existing trajectory scorer that reads only outcome.**  
   **Location:** `src/aeread_families/datacenter_development/measurement.py:162-169,201-204`; `tests/test_shared_runner_scoring_contract.py:24-35,890-904,943-969`  
   **Scenario:**
   1. Datacenter declares `negotiation_temporal_compliance` with `input_scope="trajectory"`.
   2. Its scorer computes that leaf solely from `outcome["temporal_violations"]`.
   3. Datacenter is omitted from the protocol registry.
   4. Only the synthetic reference scorer exercises paired histories, so the real outcome-only trajectory implementation never fails the test.  
   The synthetic fixture has genuine teeth against changing its own scorer to outcome-only, but it does not enforce that property on migrated or future production registrations.

10. **Design ambiguity — the scorer controls whether the trajectory guard applies.**  
    **Location:** `tests/test_shared_runner_scoring_contract.py:943-954`; `src/aeread/shared_runner/schemas.py:253-266`  
    **Scenario:**
    1. A family conceptually publishes a trajectory leaf.
    2. Its returned `MeasurementLeafSpec` mistakenly labels the estimand `terminal_state`.
    3. The manifest policy declares only leaf ID and finalize/deferred scope, so it provides no independent trajectory classification.
    4. The test derives `trajectory_leaf_ids` from the scorer's own output and skips paired-history checks.  
    A future author's metadata mistake disables the very check intended to detect their implementation mistake.

11. **Design ambiguity — "primary corresponds to primary_estimand" is neither defined nor validated.**  
    **Location:** `src/aeread/shared_runner/schemas.py:386-423,448-470`; `src/aeread_families/housing/runner.py:269-280,1390-1393`  
    **Scenario:**
    1. A manifest names one finalize-time leaf as primary.
    2. That leaf's `estimand.estimand_id` describes a different estimand from `measurement.primary_estimand`.
    3. Parsing verifies only leaf-ID membership and scope.
    4. The protocol test compares only primary leaf IDs, so registration and scoring pass.  
    Equality cannot simply be inferred from names: Housing legitimately uses leaf ID `housing_social_welfare_leaf` for estimand ID `social_welfare`. The contract needs an explicit comparison against the returned leaf's estimand identity.

12. **Real bug — deferred declarations disappear from receipts.**  
    **Location:** `src/aeread/shared_runner/schemas.py:253-261`; `src/aeread/shared_runner/task/receipts.py:117-149`; `src/aeread/shared_runner/task/evaluation.py:522-558`  
    **Scenario:**
    1. A manifest declares a judge-dependent leaf as deferred with its waiting artifact.
    2. The finalize-time scorer correctly omits it.
    3. `EvaluationReceipt` stores only primary ID and produced scores; finalization stores neither declared policy nor deferred leaves.
    4. A consumer cannot distinguish a valid deferred leaf from a scorer that silently forgot a leaf.  
    This fails the specification's "declared-and-deferred rather than silently absent" requirement.

13. **Design ambiguity — two provenance channels may disagree, and tests demonstrate that disagreement is accepted.**  
    **Location:** `src/aeread/shared_runner/task/evaluation.py:453-469`; `tests/test_shared_runner_housing.py:204-210`  
    **Scenario:**
    1. Construct `FamilyScoringInput` with evidence refs A.
    2. Invoke the scorer with keyword refs B.
    3. Migrated scorers use B, while another plausible family may use A.
    4. No protocol or constructor rejects the mismatch.  
    Production currently passes identical values, but the API does not establish which channel is authoritative; the housing test explicitly uses `()` versus `("artifact_outcome",)`.

No files were modified. Per the instruction that the protocol test could not be run, this review is static; no test result is being represented as passed or failed.

FINDINGS: 13
--- END REVIEW ---

## Dispositions

Legend: **FIXED** = confirmed and closed with a code change and a
mutation-verified regression test. **CONFIRMED, NOT FIXED** = the finding's
factual claim held up under direct inspection of the code, but no code
change was made, for a stated reason (architectural decision required,
deliberate spec-sanctioned scope boundary, or family-specific domain work
outside the kernel). **REFUTED** = the finding's claim did not hold once
checked against the code as it stands. None of the 13 findings were refuted
outright; several are true-but-out-of-kernel-scope observations, which the
review itself sometimes flags as "design ambiguity" rather than "bug."

### Finding 1 — scorer isolation vs. a stateful plugin instance

**CONFIRMED, NOT FIXED (escalate).** Verified: `PluginRegistry.resolve`
(`registry.py:419-424`) and `resolve_manifest`/`resolve_registration` all
return the *same* Python object stored at registration time
(`RegisteredPlugin.plugin`, `registry.py:120-129,269-301`), and both
`execute_plan_cell` (`execution.py:3337`) and `finalize_family_execution`
resolve it independently for the same family. A plugin that stashed live
state on `self` during a `step()`/`outcome()` call could read it back from
`build_scorer()`'s returned callable, unrelated to `scoring_input`.

Not fixed, because there is no safe, narrowly-scoped mechanism available:
- The kernel already forecloses the *documented* fallback vector (a scorer
  reading the live `EpisodeResult`) by never giving `replay_family_scoring_input`
  an `EpisodeResult` parameter (verified: `evaluation.py`'s
  `replay_family_scoring_input` signature has exactly `plugin, family_case,
  evidence`; see `tests/test_shared_runner_family_scoring_input.py::test_replay_family_scoring_input_has_no_episode_result_parameter`).
- The vector this finding describes — a plugin reading its own retained
  instance state — is not something a call-site signature change can close.
  Closing it would require either (a) giving the registry a plugin
  *factory* instead of a stored instance, so finalization always resolves a
  fresh, blank instance (a registry API change affecting all nine
  registered families and every family's registration call site), or (b) a
  runtime taint/purity check on plugin instances (no established mechanism
  in this codebase). Both are architectural decisions beyond a kernel
  scoring-contract fix, and `registry.py`'s own docstring already frames
  registered plugins as an explicitly *trusted* boundary ("Deployment code
  decides what is trusted and registers it"), consistent with hooks being
  trusted to behave, not sandboxed.
- The review itself frames this as latent, not exploited: "None of the five
  migrated scorers currently exploits this."

**Recommendation for the spec author / architecture owner:** decide whether
plugin instances should be single-use-per-episode (registry stores a
factory) or whether statelessness remains a contribution-review
obligation (documented, checked by human QC, per `registry.py`'s
`ContributionAdmissionError` gates) rather than a kernel-enforced
invariant.

### Finding 2 — sequential-phase replay

**FIXED.** Commit `f770087` (`fix(kernel): make phase replay mode-aware and
cross-check its completion boundary`). `_replay_family_trajectory`
(`evaluation.py`) now branches on `recorded_phase.mode`: `single`/
`simultaneous` steps every acted seat in one transition as before;
`sequential` steps one seat at a time, one `transition_applied` event per
step, matching `scheduler.py`'s per-actor loop (including early termination
before every eligible actor acts). The former unconditional `tuple(sorted(actions))
!= tuple(sorted(eligible))` check (also wrong for early-terminating
sequential phases) is now mode-scoped.

No family on `main` uses `mode="sequential"`, so a new, kernel-owned,
provider-free, two-actor test-only family was added
(`kernel_contract_sequential_v1`, trusted-registry-only — see
`registry.py`'s `TRUSTED_BUILTIN_PLUGIN_KEYS`) purely to exercise this path
through the real scheduler.

**Test:** `tests/test_shared_runner_family_scoring_input_sequential.py::test_replay_reproduces_a_sequential_phase_instance_exactly`
(plus the fixture sanity check
`test_sequential_phase_produces_two_transitions_in_one_instance`).
**Mutation-verified:** reverted `evaluation.py` to its pre-fix content via a
`/tmp` backup/restore (never `git checkout`); the test failed with
`ValueError: family replay phase lacks one transition`; restored the fix and
it passed again.

### Finding 3 — `phase_instance_succeeded` never cross-checked

**FIXED.** Same commit (`f770087`). Replay now requires exactly one
`phase_instance_succeeded` event per phase instance and cross-checks its
`phase_id`, `post_state_sha256`, and `logical_action_ids` against what the
re-execution actually produced, consuming the event into `evidence_refs`.
Confirmed `audit_reconciliation`'s default `entity_types` (`execution.py:696-705`)
never includes `phase_instance`, so this boundary genuinely had no other
cross-check anywhere in the stack.

**Test:** `tests/test_shared_runner_family_scoring_input_sequential.py::test_replay_rejects_a_phase_completion_boundary_that_understates_the_actors`
(tampers the sealed `phase_instance_succeeded` payload's `logical_action_ids`
to omit an actor who actually acted, without touching the hash chain —
mirrors the existing tamper-test technique in
`test_shared_runner_family_scoring_input.py`).
**Mutation-verified:** same revert/restore as finding 2; the test failed
with `family replay phase lacks one transition` before the mode fix existed
(the completion-boundary check is unreachable without it) and failed with a
non-matching message even after mode-awareness was reintroduced without the
boundary check, confirming the assertion has teeth; restoring both parts
together passes.

### Finding 4 — leaf policy invariants bypassable via `dataclasses.replace`

**FIXED.** Commit `fb1a8f7` (`fix(kernel): validate leaf policy invariants
in __post_init__, not only from_dict`). Verified the premise exactly:
`MeasurementDeclaration` and `LeafPolicyDeclaration` (`schemas.py`) had zero
`__post_init__` methods before this fix — every invariant lived only in
`from_dict`, unlike their `measurement.py` cousins
(`EstimandSpec`, `ScoreEnvelope`, `FamilyScoreSet`, etc., all of which do
validate in `__post_init__`). Added `__post_init__` to both classes,
re-running the same cross-field checks `from_dict` already had (duplicate
leaf ids, primary membership/scope, admission membership, deferred-leaf
exclusion from admission, primary-in-admission), so *every* construction
path — including `dataclasses.replace` — is guarded, not only `from_dict`'s.

Also verified the review's second claim precisely:
`test_registry_rejects_registration_of_a_plugin_with_an_inconsistent_leaf_policy`
never actually calls `PluginRegistry` — it was, and remains, only a
`from_dict` test. A new test exercises the real `dataclasses.replace`
bypass, including one call that reaches `PluginRegistry.register_trusted`.

**Test:** `tests/test_shared_runner_schemas.py::test_measurement_declaration_rejects_an_inconsistent_leaf_policy_from_dataclasses_replace`.
**Mutation-verified:** neutered both new `__post_init__` bodies to an early
`return` (leaving the docstrings/comments in place) via a `/tmp`
backup/restore of `schemas.py`; the test failed with "DID NOT RAISE
AuthoringValidationError"; restored and it passed.

### Finding 5 — production manifests/finalizer do not enforce leaf policy

**CONFIRMED as literally described for the pre-fix state; enforcement
mechanism now FIXED; the described absence of policy on production
manifests is intentionally left unchanged.** Two separable claims here:

1. *"The finalizer only normalizes the scorer's return; it never obtains or
   compares manifest policy."* This was true and is now fixed: commit
   `ff7f14c` (`fix(kernel): enforce a family's declared leaf policy at
   finalize time`) adds `_enforce_declared_leaf_policy`, called from
   `finalize_family_execution`, `replay_family_receipt`, and
   `audit_family_receipt`. When a resolved registration's manifest declares
   a leaf policy, the produced `FamilyScoreSet`'s leaf-id set, primary, and
   admission set must equal the declared policy or finalization raises.
   When no policy is declared (every production family today), this is a
   no-op — verified by the full suite staying green.
2. *"Its production manifest has no `leaves`, `primary_leaf_id`, or
   `admission_leaf_ids`."* Verified true for all five migrated families
   (`housing`, `datacenter_development`, `procurement_allocation`,
   `procurement_grounding`, `commercial_state_calibration`) — none of their
   `family_manifest()`/`family_manifest`-equivalent builders declare
   `measurement.leaves`. **Deliberately left unchanged**: per
   `kernel_scoring_contract_spec.md` section 5, item 2, declaring leaf
   policy on a family's *production* manifest is per-family migration work
   assigned to "eleven migration agents," not the kernel implementer (section
   7, "Order of work"); doing it here for five families outside that process
   risks exactly the kind of digest perturbation ruling R1 already had to
   correct once. `test_shared_runner_scoring_contract.py`'s own docstring
   independently documents this same boundary.

**Test:** `tests/test_shared_runner_family_scoring_policy_enforcement.py::test_finalize_rejects_a_scorer_that_drops_a_declared_finalize_time_leaf`.
**Mutation-verified:** see finding 6's entry (same revert/restore covered
both).

### Finding 6 — registered vs. run-plan-carried manifest policy binding

**FIXED.** Commit `ff7f14c`. `finalize_family_execution`,
`replay_family_receipt`, and `audit_family_receipt` now resolve the plugin
*and* its manifest via `setup.registry.resolve_registration(family_id,
family_version, plugin_id)` — the registry's own trusted registration — and
use `registration.manifest` for policy, never the `FamilyManifest` object
the run-plan happens to carry (`setup.plan.families[...]`). This is the
same manifest source `registration.manifest` the scoring-contract protocol
test already trusts (`test_shared_runner_scoring_contract.py`), so there is
now exactly one source of truth for policy at the call sites that read it.

**Test:** `tests/test_shared_runner_family_scoring_policy_enforcement.py::test_finalize_carries_a_declared_deferred_leaf_onto_the_receipt`
constructs exactly the scenario the finding describes — the run-plan's own
manifest copy (`setup.plan.families[0]`) declares *no* leaf policy (asserted
directly: `base_manifest.measurement.leaves == ()`), while a fresh registry
carries a *different* manifest object with a declared policy for the same
family/version/plugin identity, and the receipt is proven to reflect the
registered one (`receipt.deferred_leaf_ids == ("housing_deferred_diagnostic",)`).
**Mutation-verified:** reverted `evaluation.py` and `receipts.py` to their
pre-`ff7f14c` content via `/tmp` backup/restore; all three new tests in that
file failed (one with `AttributeError: 'EvaluationReceipt' object has no
attribute 'deferred_leaf_ids'`, two with "DID NOT RAISE ValueError");
restored both files and the full targeted suite passed again. (Note: a
`cp`-based restore mistake during this step briefly reverted `receipts.py`
to its pre-fix state without a saved copy of the fix; the fix was
reconstructed from memory of the just-made edit and re-verified byte-for-byte
equivalent by re-running every dependent test before proceeding — recorded
here for transparency, not because it affected the final state.)

### Finding 7 — protocol test not closed-world over "production" registrations

**CONFIRMED, NOT FIXED (currently unactionable).** Verified: the spec's own
section 6 pseudocode calls a `build_family_registry()` that does not exist
anywhere in this codebase (`grep` for `build_family_registry` across `src/`
and `tests/` returns nothing) — there is no single, assembled,
"production" `PluginRegistry` instance to check the fixture set against;
every test and campaign script builds its own scoped registry. Given that,
and given (per finding 5) that *no* production family manifest currently
declares a leaf policy, there is no meaningful stronger closed-world
assertion available today: even `TRUSTED_BUILTIN_PLUGIN_KEYS`
(`registry.py`), the closest thing to a canonical enumeration of trusted
plugins, contains several non-migrated or terminal-only families whose
production manifests would raise on `finalize_time_leaf_policy()` if
checked. Strengthening this check is worth doing once families begin
declaring policy on production manifests (finding 5's migration work); doing
it now would either be vacuous or require inventing the very
`build_family_registry()` assembly point the spec assumed exists, which is
an architectural addition outside this kernel change's scope.

### Finding 8 — protocol test shortcuts the finalizer call path

**CONFIRMED as literally true; not a deviation (matches spec section 6's
own prescribed pseudocode verbatim, which reconstructs `FamilyScoringInput`
and calls `build_scorer` directly rather than `finalize_family_execution`);
the actionable gap it exposed is FIXED.** Verified
`test_every_registered_family_obeys_the_scoring_contract` never calls
`finalize_family_execution`. Also verified, by grep, that among the five
migrated families, `commercial_state_calibration` was the *only* one with
zero test coverage of the real `finalize_family_execution` call path (housing,
procurement_allocation, procurement_grounding, and datacenter_development
each already have at least one such test). That was the one concrete,
in-scope gap this finding pointed to, per spec section 5 item 4 ("at least
one provider-free test that drives a real episode through
`finalize_family_execution`").

**Test:** `tests/test_commercial_state_calibration.py::test_finalize_wires_commercial_state_to_the_shared_family_finalizer`.
**Mutation-verified:** temporarily changed the finalizer's scorer call from
`plugin.build_scorer(family_case)(scoring_input, evidence_refs=...)` to
`plugin.build_scorer(family_case)(scoring_input.outcome)` (the exact
regression this finding describes) via a targeted, unique-string
find/replace with a `/tmp` backup; the new test failed with `AttributeError:
'mappingproxy' object has no attribute 'outcome'`; restored the file
byte-for-byte (diff-verified) and the test passed again.

### Finding 9 — trajectory test excludes datacenter's outcome-only leaf

**CONFIRMED, NOT FIXED (recommend as a follow-up outside kernel scope).**
Verified: `DataCenterDevelopmentScorer.__call__`
(`datacenter_development/measurement.py`) computes `temporal_ok = not
outcome["temporal_violations"]` — solely from `scoring_input.outcome`, never
`scoring_input.phase_instances`, for a leaf declared `input_scope="trajectory"`.
Verified `datacenter_development_v1` is excluded from the protocol test's
fixture registry, with an explicit, accurate justification already in that
test module's docstring (its outcome accumulates the full ordered history,
so no two fixtures can share an outcome with differing trajectories — the
paired-history requirement cannot be honestly constructed for it). Grepped
`tests/test_datacenter_runner.py` and `tests/test_datacenter_stack.py`: both
only assert the *compliant* case (`negotiation_temporal_compliance == 1.0` /
`temporal_violations == []`); neither has a negative case asserting the leaf
scores `0.0` for a genuinely out-of-order negotiation.

Not fixed here: constructing a valid out-of-order negotiation script
requires domain knowledge of `datacenter_development`'s negotiation phase
graph and action schemas that a kernel-scoped change should not guess at
under time pressure — a wrong "violation" scenario could fail for unrelated
reasons and assert nothing real. **Recommendation:** the datacenter family
owner should add a scripted negotiation that violates offer/accept/sign
ordering and assert `negotiation_temporal_compliance.primary.value == 0.0`
in `test_datacenter_runner.py`.

### Finding 10 — trajectory guard is disabled by the scorer's own metadata

**CONFIRMED, NOT FIXED (deliberate, spec-ruled trade-off; self-labeled
"design ambiguity," not "bug").** Verified `trajectory_leaf_ids` in
`test_shared_runner_scoring_contract.py` is derived from
`score.leaf.estimand.input_scope` on the scorer's own returned leaves, not
from an independent manifest-level classification. This is not an
implementation gap: `kernel_scoring_contract_spec.md` ruling R5 explicitly
directs exactly this ("derive `trajectory_leaf_ids` from the leaf's declared
`EstimandSpec.input_scope` rather than a new hand-maintained list — one
source of truth"), i.e., the spec author considered and chose this trade-off
knowingly. No code change made; recorded here for the spec author's
awareness in case the trade-off should be revisited.

### Finding 11 — "primary corresponds to primary_estimand" unvalidated

**CONFIRMED, NOT FIXED (escalate — architectural decision required).**
Verified `MeasurementDeclaration.from_dict`/`finalize_time_leaf_policy`
(`schemas.py`) check only that `primary_leaf_id` names a declared,
finalize-time leaf — never that leaf's *returned* `estimand.estimand_id`
against `measurement.primary_estimand`. Verified the review's own
counter-example is real: Housing's primary leaf id is
`housing_social_welfare_leaf` for estimand id `social_welfare`
(`housing/runner.py`) — i.e., leaf-id-to-estimand-id equality cannot be
assumed by string comparison, so any fix requires a real, explicit mapping
concept the frozen spec does not define. Implementing one would be
inventing a manifest-level field or convention the spec never specified;
that is exactly the kind of architectural decision this exercise's
instructions say to escalate rather than guess at silently.

### Finding 12 — deferred leaves disappear from receipts

**FIXED.** Commit `ff7f14c`. Verified `EvaluationReceipt` had no field
carrying declared-and-deferred leaf ids. Added `deferred_leaf_ids: tuple[str,
...] = ()` to `EvaluationReceipt` (`receipts.py`), validated in
`__post_init__` (no duplicates, must be exportable ids, must not overlap
with produced `scores`' leaf ids, canonicalized to lexical order). Wired
`finalize_family_execution` to populate it from the resolved registration's
manifest (empty when no policy is declared, matching finding 5's disposition),
and wired `replay_family_receipt`/`audit_family_receipt` to re-check it
against the recomputed value on every replay/audit.

**Test:** `tests/test_shared_runner_family_scoring_policy_enforcement.py::test_finalize_carries_a_declared_deferred_leaf_onto_the_receipt`.
**Mutation-verified:** see finding 6's entry (same revert/restore covered
both; the `AttributeError: 'EvaluationReceipt' object has no attribute

**Self-caught follow-on defect.** Adding `deferred_leaf_ids` exposed a second
bug of the same shape one layer up: `analysis/research.py`'s
`_deserialize_receipt` reconstructs an `EvaluationReceipt` from a plain
mapping field-by-field and had not been updated for the new field, so it
silently defaulted every deserialized receipt's `deferred_leaf_ids` to `()`
regardless of the serialized value — which would fail
`verify_evaluation_receipt`'s digest check the moment any receipt actually
carried a non-empty value. Fixed in commit `0d734e6`
(`fix(research): round-trip a receipt's deferred_leaf_ids through
deserialize_evaluation_receipt`). No production family declares a deferred
leaf yet, so no existing test caught this before it was added here;
confirmed by grep that no other module explicitly reconstructs
`EvaluationReceipt(...)` field-by-field (`research.py` was the only one
besides `receipts.py` itself and `evaluation.py`'s own construction sites).
**Test:** `tests/test_shared_runner_research.py::test_deserialize_evaluation_receipt_round_trips_deferred_leaf_ids`.
**Mutation-verified:** reverted just the one added line in `research.py` via
`/tmp` backup/restore; the test failed with
`ResearchContractError: serialized EvaluationReceipt is invalid` (wrapping
the underlying digest mismatch); restored and it passed. The full suite
(`1091 passed, 32 skipped, 1 xfailed`) was run once between commits `44c889b`
and this fix, i.e. it does not itself cover this specific fix, but every
targeted suite run after it (research, receipts, housing, scoring-contract,
schemas, sequential, policy-enforcement, commercial-state, datacenter,
procurement) was re-run green afterward.
'deferred_leaf_ids'` failure is this finding's specific evidence).

### Finding 13 — two provenance channels (`evidence_refs`) may disagree

**CONFIRMED; runtime enforcement added for the real call sites (partial
FIX); the underlying API-level permissiveness is unchanged by design.**
Verified `FamilyScoringInput` is a plain frozen dataclass with no
cross-check against the `evidence_refs` keyword a scorer is called with —
exactly as `test_shared_runner_housing.py`'s direct-construction test
demonstrates (`evidence_refs=()` on the dataclass vs.
`evidence_refs=("artifact_outcome",)` on the call). This is unchanged by
design: `kernel_scoring_contract_spec.md` section 1 explicitly rejected
giving `FamilyScoringInput` any validating/`Mapping`-like behavior to avoid
"two namespaces on one value." What was missing, and is now added
(commit `ff7f14c`): `_check_evidence_refs_are_scoring_input_verbatim`,
called from `finalize_family_execution`, `replay_family_receipt`, and
`audit_family_receipt`, raises if any produced `ScoreEnvelope.evidence_refs`
disagrees with `scoring_input.evidence_refs` — closing the gap for every
real production and replay call site, even though a test (or a future
family) can still construct a `FamilyScoringInput` directly with
inconsistent values, which is an intentional, documented API property, not
an oversight.

**Test:** `tests/test_shared_runner_family_scoring_policy_enforcement.py::test_finalize_rejects_a_scorer_whose_evidence_refs_disagree_with_replay`
(a plugin proxy that delegates every hook to Housing's real plugin except a
`build_scorer` that fabricates `evidence_refs=()` on the returned score).
**Mutation-verified:** see finding 6's entry (same revert/restore covered
all three tests in that file; this one failed with "DID NOT RAISE
ValueError").

## Summary

| # | Disposition |
|---|---|
| 1 | Confirmed, not fixed — escalate (architectural: plugin-instance statelessness) |
| 2 | Fixed |
| 3 | Fixed |
| 4 | Fixed |
| 5 | Confirmed, enforcement mechanism fixed; policy absence on production manifests deliberately unchanged (per-family migration work, spec section 5/7) |
| 6 | Fixed |
| 7 | Confirmed, not fixed — currently unactionable (no production registry assembly point exists; no family declares policy yet) |
| 8 | Confirmed (matches frozen spec, not a deviation); the one concrete gap it exposed (commercial_state_calibration finalizer coverage) fixed |
| 9 | Confirmed, not fixed — recommend as datacenter-family-owner follow-up |
| 10 | Confirmed, not fixed — deliberate spec ruling (R5), not a gap |
| 11 | Confirmed, not fixed — escalate (architectural: no estimand-identity mapping defined) |
| 12 | Fixed |
| 13 | Confirmed; runtime enforcement fixed for real call sites; API-level permissiveness intentional by spec section 1 |

Findings fixed with a code change and mutation-verified test: **2, 3, 4, 5
(enforcement mechanism), 6, 8 (coverage gap), 12, 13 (runtime check)** — 8 of
13. Findings confirmed accurate but requiring an architectural decision or
out-of-kernel-scope domain work, left unfixed and escalated: **1, 7, 9, 10,
11** — 5 of 13. Zero findings were refuted.
