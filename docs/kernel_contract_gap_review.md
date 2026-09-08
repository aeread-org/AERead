# Kernel scoring-contract conformance-gap review

**Provenance.** The section below, delimited by `BEGIN REVIEW` / `END REVIEW`,
is reproduced verbatim from an independent conformance-gap review of the
kernel scoring contract (`kernel_scoring_contract_spec.md`, "Rulings — round
2": R6, R7, R8) as implemented on branch `zeyu/kernel-contract` at commit
`0b65052`. It was supplied to this document's author for verification and
remediation, not authored by that author.

The **Dispositions** section following it was added by the engineer who
verified each finding against the code and, where confirmed and actionable,
fixed it. Every disposition that claims a fix names the commit-eligible code
change, the test whose failure-before/pass-after was mutation-verified (the
guard was temporarily reverted or neutered via a `/tmp` backup-and-restore,
never `git checkout`, the target test confirmed to fail, then the fix was
restored and the test confirmed to pass again), and states plainly where full
compliance with a ruling is blocked by another frozen constraint rather than
silently narrowing scope to make the numbers look better.

--- BEGIN REVIEW ---
At current HEAD `0b65052`, R6 is not implemented. R8's four intra-manifest
guards appear sound, but nine residual gaps remain.

1. **High — R6's trusted-catalog closure is absent.** `TRUSTED_BUILTIN_PLUGIN_KEYS` contains twelve triples (`src/aeread/shared_runner/registry.py:64-129`), but the protocol test constructs a private registry and fixtures together for only five families (`tests/test_shared_runner_scoring_contract.py:893-915`). Its equality assertion at `:933-942` is therefore true by construction. Adding a trusted family without adding any protocol fixture cannot fail this test. Seven existing trusted entries—including ConsentIR, all three datacenter versions, single_offer, tau3, and the sequential reference plugin—are already omitted.

2. **High — registration still accepts manifests without a leaf policy.** `_validate_plugin` checks only the manifest type and callable hooks (`src/aeread/shared_runner/registry.py:268-280`); it never invokes `manifest.finalize_time_leaf_policy()`. Finalization then explicitly treats an absent policy as unconstrained (`src/aeread/shared_runner/task/evaluation.py:540-574`). For example, ConsentIR registers a manifest with no `leaves` or `primary_leaf_id` (`src/aeread_families/consent_ir/environment.py:277-304`). Its scorer can change its leaf set, primary, or admission policy and still pass registration and finalization.

3. **High — an all-mislabelled family can opt out of R7.** Paired fixtures are required only when the scorer already reports a trajectory-scoped leaf; any family with fewer than two fixtures skips the contrapositive entirely (`tests/test_shared_runner_scoring_contract.py:967-998`). A trajectory-reading leaf labelled `terminal_state` can therefore be supplied with one fixture and pass—the exact escape R7 was intended to close.

4. **Medium — the determinism pre-check can still blame nondeterminism as mislabelling.** Initial calls run left then right (`tests/test_shared_runner_scoring_contract.py:947-965`), followed later by rebuilt-scorer repeats left then right (`:1021-1041`). A cached scorer alternating output by invocation parity produces `A, B, A, B`: both same-input comparisons pass, but the cross-history comparison at `:1051-1064` fails as "mislabelled." A scorer with instance-local call-state is also never invoked twice on the same instance because `build_scorer` is called again.

5. **Medium — R7 ignores two measurement outputs.** `_score_measurement_content` omits `utility_by_seat` and `capture_by_seat` (`tests/test_shared_runner_scoring_contract.py:918-930`), although they are `ScoreEnvelope` fields (`src/aeread/shared_runner/measurement.py:329-339`) and become benchmark result facts (`src/aeread/shared_runner/analysis/research.py:1126-1142`). A terminal-labelled leaf can derive only its per-seat allocation from trajectory order while keeping the compared fields constant; it passes.

6. **Medium — the comparison still admits nested provenance.** `MetricValue.metadata` accepts an unrestricted mapping and participates in dataclass equality (`src/aeread/shared_runner/measurement.py:297-312`). Thus a genuinely terminal-scoped metric whose numeric value is identical but whose metadata records the run's outcome-event ID passes the same-input repeats and then fails the cross-run check as "trajectory-dependent." Excluding only top-level `evidence_refs` does not establish R7's measurement-versus-provenance boundary.

7. **Medium — `input_scope` is not a stable manifest declaration.** `LeafPolicyDeclaration` records only leaf ID and finalize/deferred scope (`src/aeread/shared_runner/schemas.py:252-266`). The protocol derives terminal/trajectory classification solely from the first fixture's returned leaf objects (`tests/test_shared_runner_scoring_contract.py:967-981`) and excludes the leaf specification from equality (`:918-930`). A scorer can return the same leaf ID with different `input_scope`, estimand version, or scorer implementation across cases without a conformance failure.

8. **Medium — the purported registry assertions cannot detect a registry regression.** `test_registry_rejects_registration_of_a_plugin_with_an_inconsistent_leaf_policy` never creates or calls a registry (`tests/test_shared_runner_schemas.py:670-682`). The later apparent registration case constructs the invalid replacement while evaluating the call's arguments, so it raises before `register_trusted` executes (`:722-734`). Removing or bypassing registration validation would leave both tests green.

9. **Design ambiguity — R8 leaves an actively consumed namespace unmapped.** `primary_estimand` remains required (`src/aeread/shared_runner/schemas.py:359,449-453`) and run-plan resolution requires that name in `AnalysisPlan.estimands` (`src/aeread/shared_runner/run/resolver.py:854-864`), while emitted primary result facts use the leaf's different `estimand_id` (`src/aeread/shared_runner/analysis/research.py:1114-1123`). A future author can coherently choose `primary_estimand=A` and primary-leaf estimand `B`, then be required to configure analysis for `A` even though receipts expose `B`. R8 permits this but does not define what `A` means.

No files were modified. Tests were not run because the requested read-only constraint forbids their temporary/evidence writes.

FINDINGS: 9
--- END REVIEW ---

## Dispositions

Legend: **FIXED** = confirmed and closed with a code change and a
mutation-verified regression test. **CONFIRMED, NOT FIXED** = the finding's
factual claim held up under direct inspection (and, in one case, direct
experiment against the code), but a full fix is blocked by another frozen
constraint this exercise is explicitly forbidden from breaking, or requires
architectural/scope decisions outside a conformance-gap fix. **REFUTED (as an
actionable gap)** = the finding's code evidence is accurate, but the ruling
it cites already considered and deliberately accepted exactly this
consequence, so there is nothing to fix without contradicting a frozen
ruling. Zero findings were refuted as factually inaccurate; one (9) is
refuted only as something actionable within this change.

### Finding 1 — R6's trusted-catalog closure is absent

**CONFIRMED; mechanism FIXED; full closure over all twelve trusted keys
remains a documented, named, out-of-kernel-scope gap.**

Verified exactly: `TRUSTED_BUILTIN_PLUGIN_KEYS` (`registry.py`) has twelve
entries; `_build_protocol_test_registry_and_fixtures`
(`test_shared_runner_scoring_contract.py`) built a private `PluginRegistry`
and a `fixtures` dict from the *same* five-family construction, so
`assert set(fixtures) == set(registrations)` was true by construction and
could never fail — the review's claim, byte for byte.

Ruling R6 names `TRUSTED_BUILTIN_PLUGIN_KEYS` as the enrollment authority and
says the protocol test must close over it. Before writing code, I tried to
implement R6's *other* clause literally — "structural conformance moves into
`PluginRegistry._validate_plugin`... it checks: the manifest declares a
finalize-time leaf policy" — as an experiment (not committed): every
production family registers via `register_trusted` with a manifest that does
not yet declare a leaf policy (verified by grep for all ten real
`(family_id, version)` keys in `TRUSTED_BUILTIN_PLUGIN_KEYS` -- i.e. every
entry other than the two kernel-owned test-only keys;
`kernel_contract_impl_review.md` finding 5 already established this for the
five migrated ones). Requiring the policy at `_validate_plugin` made
`build_housing_smoke()` raise immediately:
`AuthoringValidationError: measurement.leaves and measurement.primary_leaf_id
must be declared before a finalize-time leaf policy can be read`. Housing's
manifest is exactly the one ruling R1 forbids perturbing — adding a leaf
policy to it would change `plan_sha256` and cascade into the two frozen
digests this exercise is explicitly required to keep green without
re-baking. Since every current registration (including Housing's) goes
through `register_trusted`, and R6 states the check is "unbypassable" via
either `register` or `register_trusted`, literal compliance is not just hard
here, it is proven incompatible with a constraint this exercise must not
violate — short of completing the full per-family manifest migration (spec
section 5, "eleven migration agents") for every one of the ten real trusted
keys, which is explicitly out of scope ("closing conformance gaps... not
rebuilding"). This is escalated, not silently worked around: the
`_validate_plugin` leaf-policy requirement is **not implemented**.

What **is** implemented, and does not touch any production manifest or
frozen digest: the protocol test's closed-world assertion now closes over
`TRUSTED_BUILTIN_PLUGIN_KEYS` directly, via
`_assert_trusted_catalog_is_closed`, checked against `set(fixtures)` plus a
new, explicit, named, reasoned exemption constant
(`_NOT_YET_MIGRATED_TRUSTED_KEYS`) listing exactly the seven trusted keys
that have not migrated to the `FamilyScoringInput` contract. A key present in
neither bucket now fails the real protocol test. This closes the review's
*exact demonstrated attack* — "adding a trusted family without adding any
protocol fixture cannot fail this test" — for any *new* trusted key, and for
the seven existing ones only by way of a visible, named, audit-trail entry
rather than silent omission.

**Test:** `test_trusted_catalog_closure_rejects_an_unenrolled_key` (isolated
proof of the guard's logic) and
`test_every_registered_family_obeys_the_scoring_contract` (real integration).
**Mutation-verified (real integration):** temporarily removed
`("consent_ir_v1", "1.0.0")` from `_NOT_YET_MIGRATED_TRUSTED_KEYS` via a
`/tmp` backup/restore; `test_every_registered_family_obeys_the_scoring_contract`
failed with `AssertionError: trusted plugin key(s) [('consent_ir_v1',
'1.0.0')] are neither enrolled ... nor named in
_NOT_YET_MIGRATED_TRUSTED_KEYS`; restored and it passed again.

**Recommendation for the spec author:** R6's registry-level requirement, as
literally written, cannot be satisfied for any currently-trusted family
without either (a) re-baking Housing's frozen campaign digests (forbidden by
ruling R1 and by this exercise's own instructions), or (b) completing the
full eleven-family manifest migration first. Decide whether R6's
`_validate_plugin` clause should be read as applying only to *newly* trusted
families going forward (which would need an explicit grandfather mechanism
the current ruling text does not describe), or whether it should wait until
migration completes.

### Finding 2 — registration still accepts manifests without a leaf policy

**CONFIRMED; same root cause as finding 1; not independently fixable without
the same R1/frozen-digest conflict.**

Verified precisely: ConsentIR's `family_manifest()`
(`src/aeread_families/consent_ir/environment.py`) declares no `leaves`,
`primary_leaf_id`, or `admission_leaf_ids`; `_enforce_declared_leaf_policy`
(`task/evaluation.py`) is a documented no-op when no policy is declared. This
is the identical gap finding 1 describes, viewed from the finalizer/
registration side rather than the protocol-test side, and finding 1's
experiment already proves the direct fix (require
`finalize_time_leaf_policy()` at registration) breaks Housing's registration
today. Not independently re-attempted for the same reason.

**Partial mitigation from finding 1's fix:** a *new* trusted family with no
leaf policy at all can no longer be added to `TRUSTED_BUILTIN_PLUGIN_KEYS`
without either declaring one (and enrolling a real fixture) or being added,
by name, to `_NOT_YET_MIGRATED_TRUSTED_KEYS` — it can no longer happen
silently. **Partial mitigation from finding 8's fix:** a `manifest.measurement`
that is not even a validly-typed `MeasurementDeclaration` (a strictly worse
case than ConsentIR's, which has a *valid* declaration that simply carries no
policy) is now rejected at registration.

**Not fixed:** ConsentIR (and every other unmigrated family) can still change
its scorer's leaf set, primary, or admission membership freely, exactly as
the finding describes, because its manifest's `MeasurementDeclaration` is
valid but empty. Escalated alongside finding 1.

### Finding 3 — an all-mislabelled family can opt out of R7

**CONFIRMED; FIXED.** Verified the escape exactly: the old guard
(`if trajectory_leaf_ids: assert len(produced_by_case) >= 2`) only forced a
second fixture when the scorer's *own* output already declared a trajectory
leaf. Also verified this is not hypothetical: all four already-migrated real
families (`housing_v1`, `procurement_allocation_v1`,
`procurement_grounding_v1`, `commercial_state_calibration_v1`) are, today,
single-leaf and declare that one leaf `input_scope="terminal_state"` (grepped
every `input_scope=` occurrence in each family's environment module) — i.e.
each is currently exactly the shape the finding describes, supplying exactly
one fixture.

The paired-fixture requirement is now unconditional except for a new, named,
reasoned exemption constant, `_SINGLE_FIXTURE_EXEMPT_FAMILIES`, listing
exactly those four keys with the stated reason (providing the second,
outcome-identical, trajectory-differing fixture for each is per-family domain
work, spec section 5, out of kernel scope). Any family — new or existing —
that is neither exempted by name nor supplies two fixtures now fails loudly,
closing the specific escape described (mislabel every trajectory-reading leaf
as `terminal_state` and supply only one fixture).

**Test:** `test_every_registered_family_obeys_the_scoring_contract`.
**Mutation-verified:** temporarily removed `("housing_v1", "1.0.0")` from
`_SINGLE_FIXTURE_EXEMPT_FAMILIES` via a `/tmp` backup/restore; the real test
failed with `AssertionError: housing_v1@1.0.0 supplies fewer than two
contract fixtures and is not in _SINGLE_FIXTURE_EXEMPT_FAMILIES`; restored
and it passed again.

### Finding 4 — the determinism pre-check can still blame nondeterminism as mislabelling

**CONFIRMED; FIXED.** Verified the exact call-order vulnerability: the old
code built `produced_by_case` by calling each fixture's scorer once, in
order (calls 1, 2), then later, in a separate loop, called each fixture's
scorer again, in the same order (calls 3, 4). A scorer whose output depends
only on a *global* call counter (not on `scoring_input`) — the review's
"cached scorer alternating output by invocation parity" — produces
`X, Y, X, Y`: calls 1 and 3 share parity (both compare equal, "looks
deterministic"), as do 2 and 4, so both same-input checks pass and the true
defect only ever surfaces as a cross-fixture "mislabelled" failure.

The determinism recheck is now performed immediately after each fixture's
original call (call 2 right after call 1, for that fixture, before the other
fixture is ever touched), inside the same per-case loop that builds
`produced_by_case`, rather than batched afterward. Under adjacent calls, the
same period-2-parity scorer now disagrees with itself on the very next call
and is correctly diagnosed as nondeterministic.

**Test:**
`test_determinism_precheck_adjacency_defeats_call_parity_aliasing`, a new
test built from a purpose-built adversarial plugin
(`_CallParityAdversarialPlugin`/`_CallParityAdversarialScorer`, sharing
module-level call-count state so fresh `build_scorer(...)` instances still
alternate — closing the review's own noted caveat that instance-local state
would not persist across `build_scorer` calls) run against two REAL sealed
episodes (byte-identical outcome, differing trajectory) built by the same
`_run_reference_episode` machinery `test_every_registered_family_obeys_the_scoring_contract`
uses. The test directly demonstrates, against the real kernel replay/scoring
call path: under the OLD (batched) call order, both same-input comparisons
incorrectly pass and the cross-fixture comparison incorrectly disagrees
(the misdiagnosis); under the NEW (adjacent) call order, the same scorer is
caught disagreeing with itself on consecutive calls (the correct diagnosis).
**Mutation-verified:** the test embeds both the "old order" and "new order"
call sequences and asserts the property of each directly — this is the
mutation check itself, run against the unmodified fix in place; no file
revert was needed because the test is a direct proof of the adjacency
property rather than an indirect one.

### Finding 5 — R7 ignores two measurement outputs (`utility_by_seat`, `capture_by_seat`)

**CONFIRMED; FIXED.** Verified `ScoreEnvelope.utility_by_seat` and
`.capture_by_seat` exist (`measurement.py`) and were absent from
`_score_measurement_content`'s comparison tuple. `_score_measurement_content`
now includes both (each reduced via `_metric_mapping_content`, see finding
6). This is consistent with, not contrary to, ruling R7's stated principle
("compare measurement content, not provenance") — a per-seat allocation
breakdown is measurement content, exactly analogous to `metrics`; R7's
enumerated field list simply predates or omitted these two fields, and R7
only explicitly excludes `evidence_refs`.

**Test:** `test_score_measurement_content_includes_seat_breakdowns`.
**Mutation-verified:** temporarily reverted `_score_measurement_content` to
its pre-fix five-field tuple via a `/tmp` backup/restore; the test failed
with `assert ('ok', MetricValue(...)) == ('ok', MetricValue(...))` (a
byte-identical primary and status but differing `utility_by_seat` no longer
detected); restored and it passed again (same revert/restore covered finding
6 below).

### Finding 6 — the comparison still admits nested provenance (`MetricValue.metadata`)

**CONFIRMED; FIXED.** Verified `MetricValue.metadata` is an unrestricted
`Mapping` field (not `compare=False`), so two `MetricValue` instances with
identical `value`/`unit` but differing `metadata` are unequal by
`__eq__`. Added `_metric_value_content`/`_metric_mapping_content`, reducing
every `MetricValue` reachable from a `ScoreEnvelope` (`primary`, and each
value inside `metrics`, `reference_values`, `utility_by_seat`,
`capture_by_seat`) to its `(value, unit)` pair before comparison, discarding
`metadata` — establishing the measurement-versus-provenance boundary R7
intended (previously only top-level `evidence_refs` was excluded).

**Test:** `test_score_measurement_content_ignores_metric_metadata`, which
first asserts the raw `MetricValue` objects **do** differ (proving there is
something for the guard to do), then asserts
`_score_measurement_content` treats them as equal.
**Mutation-verified:** same revert/restore as finding 5; the test failed with
`assert ('ok', MetricValue(value=1.0, unit='count', metadata=...event_left))
== ('ok', MetricValue(..., metadata=...event_right))`; restored and it passed
again.

### Finding 7 — `input_scope` is not a stable manifest declaration

**CONFIRMED; FIXED, without adding a manifest-level classification.** Verified
`LeafPolicyDeclaration` carries only `leaf_id`/`scope`/`deferred_artifact`
(`schemas.py`), and the protocol test derived `trajectory_leaf_ids`/
`terminal_leaf_ids` solely from the *first* fixture's returned leaves, never
checking that a later fixture's leaf spec (including `input_scope`,
`estimand_version`, verifier, or scorer ref) agrees with the first.

The finding's own suggested remedy — adding `input_scope` to the manifest —
would directly contradict ruling R5 ("derive `trajectory_leaf_ids` from the
leaf's declared `EstimandSpec.input_scope` ... rather than a new
hand-maintained list — one source of truth"), so that path was rejected.
Instead, the protocol test now asserts that every fixture beyond the first
returns a `MeasurementLeafSpec` *identical* to what the first fixture
returned for the same `leaf_id` — this strengthens an existing in-test
check using data the test already has, rather than adding a new manifest
field, so it does not conflict with R5.

**Test:** `test_every_registered_family_obeys_the_scoring_contract` (the new
per-case stability assertion).
**Mutation-verified:** temporarily patched `_ReferenceScorer.__call__` (via a
`/tmp` backup/restore) so its second invocation returns the balance leaf with
`estimand_version="9.9.9"` instead of the first invocation's `"1.0.0"`; the
real protocol test failed with `AssertionError:
kernel_contract_reference_v1/label_balance returned a different
MeasurementLeafSpec across fixtures`; restored and it passed again. (An
initial attempt varied `input_scope` directly and instead tripped an
unrelated, pre-existing `ScoreEnvelope` unit-consistency guard first,
confirming the new check specifically requires a mutation that does not
collide with an earlier invariant.)

### Finding 8 — the purported registry assertions cannot detect a registry regression

**CONFIRMED; FIXED.** Verified precisely: both
`test_registry_rejects_registration_of_a_plugin_with_an_inconsistent_leaf_policy`
and the registration case inside
`test_measurement_declaration_rejects_an_inconsistent_leaf_policy_from_dataclasses_replace`
raise while constructing their *argument* to `register_trusted`
(`FamilyManifest.from_dict`/`dataclasses.replace` on `measurement` itself
raises, since `MeasurementDeclaration.__post_init__` already validates it) —
Python evaluates that argument before the call runs, so `register_trusted`'s
body never executes in either case. Also verified, empirically, that the
underlying gap is real and *not* merely theoretical: `FamilyManifest` has no
`__post_init__`, so `dataclasses.replace(valid_manifest,
measurement="not a MeasurementDeclaration")` **constructs successfully and
registers successfully** today — confirmed by direct experiment before
writing the fix.

Added a type check to `PluginRegistry._validate_plugin`: `manifest.measurement`
must be an actual `MeasurementDeclaration` instance. This is a safe,
unconditional addition — it does not require a leaf *policy* to be declared
(so it does not reopen finding 1/2's Housing conflict), only that the field
holds a validly-typed object, which every real family's manifest (migrated
or not) already satisfies.

**Test:**
`test_registry_rejects_a_manifest_whose_measurement_field_bypassed_validation`,
which reaches `register_trusted`'s body with an already-valid-looking
`FamilyManifest` (the top-level `dataclasses.replace` succeeds, since
`FamilyManifest` itself has no `__post_init__`), so the rejection can only
come from the registry's own new check, not from argument construction.
**Mutation-verified:** temporarily removed the new check from
`_validate_plugin` via a `/tmp` backup/restore; the new test failed with
"DID NOT RAISE TypeError"; restored and it passed again. Full
`test_shared_runner_schemas.py` suite re-run green after restore (62 passed).

### Finding 9 — R8 leaves `primary_estimand` unmapped to the primary leaf's estimand

**REFUTED as an actionable gap (accurate description; not a defect).**
Verified the code evidence exactly as stated: `primary_estimand` is required
in `schemas.py`; `resolver.py`'s plan resolution requires that name in
`AnalysisPlan.estimands`; `research.py`'s emitted primary result facts use
the primary leaf's own (different) `estimand_id`. A manifest author can
coherently pick unrelated values for the two.

This is not a gap R8 failed to close — it is R8's own explicitly stated,
deliberate design decision, argued from a concrete counter-example
(tau3_retail's `primary_estimand="retail_task_reward"` versus its leaves'
`tau3_retail_db_state`/`tau3_retail_nl_assertions` estimand ids) and recorded
verbatim in the ruling: *"`primary_estimand` is deliberately left
unenforced... A relationship field may be added only after defining a real
many-to-one model... never to make two unrelated strings coincide."* R8's own
"Stated limit" paragraph names this exact consequence ("nothing here
prevents an author from wiring every identifier correctly and still choosing
a diagnostic or constraint leaf as the headline... it needs review by a
person") as accepted, not overlooked. Implementing the finding's implied
remedy (some `A`-means-`B` mapping) would silently override a ruling this
exercise is told to treat as frozen. No code change made.

## Summary

| # | Disposition |
|---|---|
| 1 | Confirmed; catalog-closure mechanism fixed and mutation-verified; full `_validate_plugin` leaf-policy enforcement escalated — proven incompatible with ruling R1 + the two frozen Housing digest tests until per-family manifest migration completes |
| 2 | Confirmed; same root cause as 1; partially mitigated by 1's and 8's fixes; not independently fixable for the stated reason |
| 3 | Fixed |
| 4 | Fixed |
| 5 | Fixed |
| 6 | Fixed |
| 7 | Fixed |
| 8 | Fixed |
| 9 | Refuted as an actionable gap — R8's own deliberate, stated design choice |

Findings fixed with a code change and a mutation-verified test: **3, 4, 5, 6,
7, 8** — 6 of 9. Finding 1 is fixed at the mechanism level (mutation-verified)
with a residual, explicitly named and escalated gap. Finding 2 shares finding
1's root cause and is confirmed but not independently fixed, for the same
escalated reason. Finding 9 is refuted as an actionable gap: its code
evidence is accurate but the ruling it cites (R8) already made this exact
trade-off deliberately.
