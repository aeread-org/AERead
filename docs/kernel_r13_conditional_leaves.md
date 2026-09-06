# Kernel ruling R13 — case-conditional leaves are declared, decided by the plugin, and receipted as inapplicable

**Provenance.** Branch `zeyu/kernel-r13-conditional-leaves`, forked from
`zeyu/kernel-r12-seat-context` (PR #109) at `cda0a736`. Implements ruling
R13 of `kernel_scoring_contract_spec.md` ("Case-conditional leaves are
declared, decided by the plugin, and receipted as inapplicable"), found by
the agenticpay migration on 2026-09-06.

## The problem

Some families build a leaf only for some of their own cases: agenticpay's
`contract_legality` exists for the 25 contract-mode cases and not for the 3
basic cases; termsbench has three regime-conditional leaves (`overlap` /
`nodeal`). The manifest's leaf set is static and the finalizer requires the
returned set to equal it on every execution. Neither existing scope fits:
the leaf is not `deferred` (nothing is pending) and reporting it
`invalid_measurement` on a case that has no such dimension would label "not
applicable" as "measured and failed" — the same mislabelling the deferred
rule exists to prevent. Dropping the leaf loses reporting the family
already does.

## What changed

### 1. `LeafPolicyDeclaration.case_conditional`

`src/aeread/shared_runner/schemas.py`'s `LeafPolicyDeclaration` gains:

- `case_conditional: bool = False`, added to `_CANONICAL_OMIT_IF_DEFAULT`
  (the same `ClassVar` R1/R9/R12 already use on `MeasurementDeclaration`
  and `LeafPolicyDeclaration` itself) so a leaf that does not use it hashes
  byte-for-byte as it did before this change.
- A cross-field invariant, enforced in both `MeasurementDeclaration.from_dict`
  and `MeasurementDeclaration.__post_init__` (so a `dataclasses.replace`
  cannot smuggle it past parsing, the same "every construction path" pattern
  R12's `seat_scope`/`subject_reduction` guard and
  `kernel_contract_impl_review.md` finding 4 already established): a
  `case_conditional` leaf may not be `primary_leaf_id` and may not be in
  `admission_leaf_ids`. Both must exist for every execution admitted under
  one static manifest, which a case-conditional leaf by definition does
  not. A family whose headline is genuinely regime-conditional either
  chooses an unconditional cross-regime primary or splits that regime into
  a distinct family version with its own static manifest.

A `case_conditional` leaf may also be `deferred` (rule 4 below) — the two
scopes are orthogonal; `case_conditional` says *whether this execution's
case has the leaf at all*, `scope` says *when a leaf that does apply
becomes available*.

### 2. The plugin hook — `inapplicable_leaf_ids(family_case)`

Applicability is decided by code over the validated case, not a predicate
language in data. `task/evaluation.py` gains:

- `_inapplicable_leaf_ids(plugin, family_case) -> frozenset[str]` — probes
  for an optional `inapplicable_leaf_ids` hook on the plugin
  (`getattr(plugin, "inapplicable_leaf_ids", None)`, called only when
  callable), returning empty when the plugin does not define one. This is
  the exact optional-hook shape `task/scheduler.py`'s `close` teardown hook
  already uses — no new mechanism was invented.
- `registry.py` documents this hook (and `close`) next to
  `REQUIRED_FAMILY_PLUGIN_HOOKS`, in a comment naming both as *optional*:
  `_validate_plugin` does not require either, and never should — a plugin
  with no case-conditional leaf need not define it at all.

The hook is called **exactly once** per `finalize_family_execution`,
`replay_family_receipt`, and `audit_family_receipt`, and its result (`I`)
is threaded into both `_enforce_declared_leaf_policy` and the receipt —
never recomputed a second time for either purpose.

### 3. Enforcement — `_enforce_declared_leaf_policy`

`_enforce_declared_leaf_policy` gains a required `inapplicable_leaf_ids`
parameter (`I`) and two ordered groups of checks, replacing the single
pre-R13 leaf-set equality:

1. **`I` must name only declared `case_conditional` leaves.**
   `I ⊆ {declared case_conditional leaf ids}` (not restricted to
   `finalize_time` leaves — rule 4 lets a leaf be both `case_conditional`
   and `deferred`). An id in `I` that is not declared `case_conditional`
   raises `"plugin inapplicable_leaf_ids named a leaf that is not declared
   case_conditional: [...]"` — the plugin's own contract violation,
   independent of anything the scorer does.
2. **The scorer's returned set must equal `declared finalize_time − I`.**
   Three distinct violations, checked in this order, each with its own
   message (every message also keeps the pre-R13 phrase "does not match
   its declared finalize-time leaf policy", so the existing, unmodifiable
   `tests/test_shared_runner_family_scoring_policy_enforcement.py` — which
   pins that exact phrase for an unrelated, non-case-conditional Housing
   scenario — keeps passing unchanged):
   - **Returned an inapplicable leaf** (`produced ∩ I ≠ ∅`) — an
     inapplicable leaf is never returned, never `invalid_measurement`,
     never `deferred`.
   - **Omitted an applicable leaf** (`(declared − I) − produced ≠ ∅`).
   - **Returned an undeclared leaf** (`produced − (declared − I) ≠ ∅`,
     after the two checks above have already ruled out `I`-membership as
     the cause).

`finalize_family_execution`, `replay_family_receipt`, and
`audit_family_receipt` each compute `inapplicable_ids =
_inapplicable_leaf_ids(plugin, family_case)` once and pass it to
`_enforce_declared_leaf_policy`.

### 4. The receipt — `EvaluationReceipt.inapplicable_leaf_ids`

`task/receipts.py`'s `EvaluationReceipt` gains:

- `inapplicable_leaf_ids: tuple[str, ...] = ()` (a **plain** default, not
  `field(default_factory=tuple)` like `deferred_leaf_ids` above it —
  `_CANONICAL_OMIT_IF_DEFAULT` compares against `dataclasses.Field.default`,
  which is `MISSING` for a `default_factory` field and would therefore
  never match, silently defeating the omission regardless of the field's
  actual value; see the field's own comment), added to a **new**
  `_CANONICAL_OMIT_IF_DEFAULT` `ClassVar` on `EvaluationReceipt` (this class
  did not carry one before this change; `deferred_leaf_ids` is
  deliberately NOT added to it — it predates this change and is
  unconditionally serialized already, and adding it now would itself be a
  digest-perturbing change, exactly what this mechanism exists to avoid).
- `__post_init__` validation mirroring `deferred_leaf_ids`'s own shape:
  sorted, no duplicates, each a valid identifier, and disjoint from BOTH
  the produced scores' leaf ids and `deferred_leaf_ids` (rule 4: every
  declared leaf has exactly one disposition on every receipt — returned,
  deferred, or inapplicable).
- A fix to `_receipt_content_sha256` (the function that computes
  `receipt_sha256`): it previously built its hash-input payload as a plain
  dict of every dataclass field, which bypasses
  `run.resolver._canonical_value`'s `_CANONICAL_OMIT_IF_DEFAULT` recursion
  entirely (that recursion only fires when it encounters a dataclass
  INSTANCE, not a hand-built dict). Without this fix,
  `write_evaluation_receipt` (which calls `canonical_json_bytes(receipt)` —
  the dataclass itself, which DOES honour the omission) would persist bytes
  omitting `inapplicable_leaf_ids` while `receipt_sha256` was sealed over a
  payload that included it, and every receipt with the field at its
  default (every receipt sealed by every family today) would fail its own
  round-trip verification. `_receipt_content_sha256` now skips the same
  `_CANONICAL_OMIT_IF_DEFAULT`-eligible-and-default fields the canonical
  serializer does.

**Disjointness / disposition.** At each of the three call sites:

```
deferred_leaf_ids     = sorted(_declared_deferred_leaf_ids(manifest) - I)
inapplicable_leaf_ids = sorted(I)
```

Inapplicability takes precedence: a leaf that is both `case_conditional`
and `deferred` appears in `inapplicable_leaf_ids` on a case where it does
not apply, and in `deferred_leaf_ids` otherwise. `replay_family_receipt`
and `audit_family_receipt` each recompute `I` from the plugin's hook and
reject a receipt whose recorded `inapplicable_leaf_ids` disagrees —
mirroring the existing `deferred_leaf_ids` check at the same two call
sites, added in the same commit.

Inapplicability is a leaf disposition, not a cell exclusion: nothing in
`_score_admission` changed, so a receipt whose only omitted leaf is an
inapplicable diagnostic (never in `admission_leaf_ids`, since rule 1
forbids that) is `ok`/`included` exactly as it always was.

### 5. Protocol test — the synthetic case-conditional family

`tests/test_shared_runner_scoring_contract.py` gains:

- `_hook_inapplicable_leaf_ids(plugin, family_case)` — the protocol path's
  own probe for the hook (same optional-hook shape as the kernel's; kept
  separate rather than importing the kernel's private helper, since this
  module exercises the PROTOCOL a plugin publishes against the manifest,
  not the kernel's internal call graph).
- `_assert_family_obeys_the_scoring_contract`'s leaf-set equality is now
  `{produced} == declared.leaf_ids - I` per fixture (computed via the hook
  above) — mathematically identical to the pre-R13 equality for every
  family with no `case_conditional` leaf (`I` is always empty), so every
  already-registered family's fixtures are unaffected.
- `_reference_case` gains an optional `payload` override (previously fixed
  to `{"scenario_id": case_id}`) so a subclass's case can carry more than a
  bare scenario id.
- `_CaseConditionalPlugin`/`_CaseConditionalScorer` — a `_ReferencePlugin`
  subclass (same style as `_SeatScopedPlugin`) with one unconditional
  primary leaf (`label_balance`, the same terminal-state tally
  `_ReferenceScorer` already computes) and one declared `case_conditional`
  diagnostic leaf (`case_conditional_diagnostic`) that applies only to a
  case whose payload carries `"mode": "contract"` (mirroring agenticpay's
  motivating shape exactly: applicable for contract-mode cases, not basic
  ones). A `mode` constructor argument selects four named behaviours:
  `"default"` (hook and scorer both follow the case's own mode faithfully),
  `"hook_returns_undeclared"` (the hook always names the PRIMARY leaf,
  never declared `case_conditional`, regardless of the case), and two
  scorer-only adversaries, `"returns_when_inapplicable"` and
  `"omits_when_applicable"`.
- `_case_conditional_case`/`_case_conditional_family_manifest`/
  `_case_conditional_extra_pins`/`_run_case_conditional_episode` — reuse
  `_reference_case`/`_with_declared_leaf_policy`/`_run_reference_episode`'s
  existing generalized parameters exactly as `_seat_scoped_*` does;
  `_case_conditional_family_manifest(primary_case_conditional=True)`
  deliberately builds an INVALID manifest to exercise rule 1's
  declaration-time rejection.
- `("kernel_contract_case_conditional_v1", "1.0.0")` is added to
  `_SINGLE_FIXTURE_EXEMPT_FAMILIES` — a fictional key, same reasoning as
  the seat-scoped family's own entry: each test below drives one fixture
  (one case mode) at a time through the protocol helper, not a
  paired-history pair, so no second, outcome-identical,
  trajectory-differing fixture is needed.

Ten new tests exercise, through both the protocol path and the real
finalizer: an applicable case (both leaves returned), an inapplicable case
(only the primary returned, receipted as inapplicable, receipt still
`ok`/`included`), a hook returning an undeclared id (rejected), a scorer
omitting an applicable leaf (rejected), a scorer returning the inapplicable
leaf (rejected), a manifest declaring the primary `case_conditional`
(rejected at declaration, before any execution), and replay/audit each
rejecting a receipt whose recorded `inapplicable_leaf_ids` disagrees with
the recomputed hook result.

## Stated limits (from the ruling, verbatim in substance)

- The kernel does not check that the hook's decision matches the case's
  semantics (a family could declare a case inapplicable that is not); that
  is the family's duty and a reviewer's check, like the primary choice
  (ruling R8's own stated limit for exactly this shape of judgement call).
- Receipt closure (task #13, outside this change's scope) must count an
  inapplicable leaf as "declared, not measured, by design", never as
  missing.

## Deviations from a strictly self-contained per-commit history

- **Commit `de908095` (evaluation.py) alone imports cleanly but any
  `finalize_family_execution`/`replay_family_receipt`/`audit_family_receipt`
  call fails.** It threads `inapplicable_ids` into both
  `_enforce_declared_leaf_policy` AND the receipt
  (`EvaluationReceipt(..., inapplicable_leaf_ids=...)`,
  `receipt.inapplicable_leaf_ids` comparisons) — ruling R13's own item 2
  text ("pass the result to both the enforcement and the receipt") -- but
  `EvaluationReceipt` does not carry that field until the very next commit
  (`08148388`). Verified directly: at commit `de908095` checked out alone
  (via a throwaway `git worktree add --detach`, never touching this
  branch's own working tree), `import aeread.shared_runner.task.evaluation`
  succeeds, but `tests/test_shared_runner_family_evaluation.py` fails 7 of
  8 tests with `TypeError: EvaluationReceipt.__init__() got an unexpected
  keyword argument 'inapplicable_leaf_ids'`. The two commits together
  restore a fully working state; taken alone, commit `de908095` is not
  independently green. This mirrors this exact branch lineage's own
  precedent: ruling R12's commit `b0d8bebb` ("carry SeatContext...") broke
  two test files outside its scoped file list, fixed four commits later in
  `46f1c8c3`/`fix(tests): thread the required SeatContext...`. No
  behavioral gap results; this is a commit-boundary sequencing note, not a
  functional deviation.
- **`analysis/research.py`'s `_deserialize_receipt` does not thread
  `inapplicable_leaf_ids`** from a serialized mapping the way it already
  does for `deferred_leaf_ids` (`value.get("deferred_leaf_ids", ())`) —
  this file is outside the file list this change was scoped to, and every
  receipt deserialized through it today has `inapplicable_leaf_ids == ()`
  regardless (no family declares a `case_conditional` leaf yet), so no
  test observes any difference. A receipt with a genuinely non-empty
  `inapplicable_leaf_ids` deserialized through `_deserialize_receipt` would
  silently lose that field on the round trip. Flagged here rather than
  fixed silently outside scope; recommend a small follow-up mirroring the
  existing `deferred_leaf_ids` line exactly.

## Commits

1. `feat(schemas): declare case-conditional leaves with LeafPolicyDeclaration.case_conditional`
   — ruling item 1.
2. `feat(evaluation): plugin hook inapplicable_leaf_ids and enforcement at finalize, replay, audit`
   — ruling items 2 and 3 (declaration + hook + enforcement + call-site
   threading; see the deviation note above for why this alone is not
   independently green).
3. `feat(receipts): record inapplicable_leaf_ids beside deferred_leaf_ids`
   — ruling item 4.
4. `test(scoring-contract): exercise a case-conditional family through the protocol path`
   — ruling item 5.
5. `docs: record ruling R13 conditional-leaf design and tests` — this
   document.

## Every test added or extended for this ruling

`tests/test_shared_runner_schemas.py`:

- `test_leaf_policy_declaration_without_seat_scope_is_digest_neutral`
  (extended, not renamed — the R12 golden it already pins predates BOTH
  `seat_scope` and `case_conditional`, so the same pinned value proves R13's
  own digest neutrality too; two new assertions added for
  `case_conditional` set on a non-primary leaf)
- `test_leaf_policy_declaration_without_case_conditional_defaults_to_false`
- `test_measurement_declaration_rejects_a_case_conditional_primary_leaf`
- `test_measurement_declaration_rejects_a_case_conditional_admission_leaf`
- `test_measurement_declaration_post_init_rejects_a_case_conditional_primary_bypassing_from_dict`
- `test_measurement_declaration_post_init_rejects_a_case_conditional_admission_leaf_bypassing_from_dict`

`tests/test_shared_runner_receipts.py`:

- `test_receipt_inapplicable_leaf_ids_defaults_to_empty_and_is_sorted`
- `test_receipt_rejects_duplicate_inapplicable_leaf_ids`
- `test_receipt_rejects_an_inapplicable_leaf_id_that_overlaps_a_produced_score`
- `test_receipt_rejects_an_inapplicable_leaf_id_that_overlaps_deferred_leaf_ids`
- `test_receipt_without_inapplicable_leaf_ids_is_digest_neutral`
- `test_durable_receipt_round_trip_preserves_a_non_default_inapplicable_leaf_ids`

`tests/test_shared_runner_scoring_contract.py`:

- `test_case_conditional_applicable_case_returns_both_leaves_through_the_protocol_path`
- `test_case_conditional_inapplicable_case_omits_the_diagnostic_leaf_through_the_protocol_path`
- `test_case_conditional_applicable_case_returns_both_leaves_at_finalize`
- `test_case_conditional_inapplicable_case_omits_the_diagnostic_leaf_at_finalize`
- `test_case_conditional_hook_returning_an_undeclared_id_is_rejected_at_finalize`
- `test_case_conditional_scorer_omitting_an_applicable_leaf_is_rejected_at_finalize`
- `test_case_conditional_scorer_returning_an_inapplicable_leaf_is_rejected_at_finalize`
- `test_case_conditional_manifest_rejects_a_case_conditional_primary_at_declaration`
- `test_case_conditional_replay_rejects_a_receipt_whose_inapplicable_leaf_ids_disagree_with_the_recomputed_hook`
- `test_case_conditional_audit_rejects_a_receipt_whose_inapplicable_leaf_ids_disagree_with_the_recomputed_hook`

## Digest-neutrality evidence

- **Schemas.** `_PRE_R12_CELL_SCOPE_MEASUREMENT_SHA256 =
  "794e778702d6fffbf7ab92a038188f9071631c18afdc53027e994d289a639f88"` —
  computed against commit `78614540` (pre-dating `seat_scope` AND
  `case_conditional` both), still equal to the CURRENT code's canonical
  bytes for a manifest with declared leaves and `case_conditional` present
  but at its default. A manifest that sets `case_conditional=True` on the
  non-primary (`tenant_nl_assertions_leaf`, itself `deferred` — proving a
  leaf may be both) hashes to a DIFFERENT value.
- **Receipts.** `_PRE_R13_RECEIPT_WITHOUT_INAPPLICABLE_LEAF_IDS_SHA256 =
  "4a8c8e334387725cf6a393addb95600c8061de554c757313e96aa9a362352269"` —
  computed against commit `cda0a736` (this branch's own fork point, before
  `EvaluationReceipt` carried `inapplicable_leaf_ids` at all), equal to the
  CURRENT code's canonical-bytes SHA-256 for the existing `_receipt()`
  fixture unchanged. A receipt sealed with a non-empty, disjoint
  `inapplicable_leaf_ids` hashes to a DIFFERENT value, and still verifies
  (`verify_evaluation_receipt`) and round-trips through durable JSON
  (`write_evaluation_receipt`/`read_evaluation_receipt`).

## Per-rule enforcement, test, and mutation coverage

| Rule | Enforced by | Positive test | Negative test | Mutation-verified |
|---|---|---|---|---|
| `case_conditional` leaf may not be primary | `MeasurementDeclaration.__post_init__`/`from_dict` | `test_leaf_policy_declaration_without_case_conditional_defaults_to_false` | `test_measurement_declaration_rejects_a_case_conditional_primary_leaf`, `test_measurement_declaration_post_init_rejects_a_case_conditional_primary_bypassing_from_dict`, `test_case_conditional_manifest_rejects_a_case_conditional_primary_at_declaration` | yes — schemas.py: removing the `_CANONICAL_OMIT_IF_DEFAULT` entry breaks the digest golden; the primary/admission guards themselves are proven by the bypass tests raising on a direct `dataclasses.replace` |
| `case_conditional` leaf may not be admission | `MeasurementDeclaration.__post_init__`/`from_dict` | (implicit — every passing manifest) | `test_measurement_declaration_rejects_a_case_conditional_admission_leaf`, `test_measurement_declaration_post_init_rejects_a_case_conditional_admission_leaf_bypassing_from_dict` | yes — same bypass-test shape as the primary guard |
| Digest neutrality of `case_conditional` | `_CANONICAL_OMIT_IF_DEFAULT` | `test_leaf_policy_declaration_without_seat_scope_is_digest_neutral` | (same test; asserts both the neutral and non-neutral case) | yes — removing `"case_conditional"` from the omit set changed the golden hash from `794e7787...` to `9c3d6b14...` |
| `I ⊆ declared case_conditional ids` | `_enforce_declared_leaf_policy` | `test_case_conditional_applicable_case_returns_both_leaves_at_finalize` | `test_case_conditional_hook_returning_an_undeclared_id_is_rejected_at_finalize` | yes — disabling the guard changes the raised message from "not declared case_conditional" to "returned an inapplicable leaf: ['label_balance']" (the primary, now wrongly treated as inapplicable) |
| Returned an inapplicable leaf | `_enforce_declared_leaf_policy` | `test_case_conditional_inapplicable_case_omits_the_diagnostic_leaf_at_finalize` | `test_case_conditional_scorer_returning_an_inapplicable_leaf_is_rejected_at_finalize` | yes — disabling the guard changes the message to "returned an undeclared leaf: ['case_conditional_diagnostic']" |
| Omitted an applicable leaf | `_enforce_declared_leaf_policy` | `test_case_conditional_applicable_case_returns_both_leaves_at_finalize` | `test_case_conditional_scorer_omitting_an_applicable_leaf_is_rejected_at_finalize` | yes — disabling the guard makes the receipt seal successfully (test fails with "DID NOT RAISE"), and independently makes the pre-existing, unmodifiable `tests/test_shared_runner_family_scoring_policy_enforcement.py::test_finalize_rejects_a_scorer_that_drops_a_declared_finalize_time_leaf` fail the same way |
| Receipt `inapplicable_leaf_ids` sorted/deduped/valid | `EvaluationReceipt.__post_init__` | `test_receipt_inapplicable_leaf_ids_defaults_to_empty_and_is_sorted` | `test_receipt_rejects_duplicate_inapplicable_leaf_ids` | verified directly by the test's own raise assertion |
| Receipt disjoint from produced scores | `EvaluationReceipt.__post_init__` | (implicit — every sealed receipt) | `test_receipt_rejects_an_inapplicable_leaf_id_that_overlaps_a_produced_score` | verified directly by the test's own raise assertion |
| Receipt disjoint from `deferred_leaf_ids` | `EvaluationReceipt.__post_init__` | (implicit — every sealed receipt) | `test_receipt_rejects_an_inapplicable_leaf_id_that_overlaps_deferred_leaf_ids` | yes — removing the deferred-overlap guard makes the test fail with "DID NOT RAISE" |
| Digest neutrality of `inapplicable_leaf_ids` | `EvaluationReceipt._CANONICAL_OMIT_IF_DEFAULT` + `_receipt_content_sha256` fix | `test_receipt_without_inapplicable_leaf_ids_is_digest_neutral` | (same test; asserts both the neutral and non-neutral case) | yes — removing the `_CANONICAL_OMIT_IF_DEFAULT` entry changes the golden hash from `4a8c8e33...` to `6f701143...`; removing the omission from `_receipt_content_sha256` (leaving the class-level set intact) breaks BOTH this test AND the pre-existing, unmodifiable `test_durable_receipt_round_trip_is_canonical_and_tamper_evident` with "serialized receipt_sha256 does not match receipt content" |
| Replay rejects a mismatched `inapplicable_leaf_ids` | `replay_family_receipt` | (implicit — every passing replay test) | `test_case_conditional_replay_rejects_a_receipt_whose_inapplicable_leaf_ids_disagree_with_the_recomputed_hook` | yes — disabling the check lets a tampered receipt replay silently (no exception at all) |
| Audit rejects a mismatched `inapplicable_leaf_ids` | `audit_family_receipt` | (implicit — every passing audit test) | `test_case_conditional_audit_rejects_a_receipt_whose_inapplicable_leaf_ids_disagree_with_the_recomputed_hook` | yes — disabling the check term lets the tampered receipt audit silently (no exception at all) |
| Protocol path's set rule (`returned == declared − I`) | `_assert_family_obeys_the_scoring_contract` | `test_case_conditional_applicable_case_returns_both_leaves_through_the_protocol_path` | `test_case_conditional_inapplicable_case_omits_the_diagnostic_leaf_through_the_protocol_path` (would have failed the PRE-R13 equality, since the inapplicable case's scorer correctly omits the diagnostic leaf) | verified directly — both tests pass only because the helper subtracts `I`; reverting the helper's own subtraction (restoring the raw pre-R13 equality) makes the inapplicable-case test fail |

## Verification

Targeted (`tests/test_shared_runner_schemas.py
tests/test_shared_runner_scoring_contract.py tests/test_shared_runner_smoke.py
tests/test_shared_runner_family_evaluation.py tests/test_shared_runner_receipts.py
tests/test_shared_runner_family_scoring_policy_enforcement.py`): see the
top-level report for the exact pass count from the background run.

Full suite (`pytest -q`, no bridges exported): see the top-level report for
the exact pass/skip/xfail counts from the background run.

## Review (post-implementation, independent)

An independent review of the five commits above (`be001ab6` through
`262b5137`) reported six items. All six were accepted and fixed, test-first,
mutation-verified, one commit per item.

### 1 (blocker) — `I ⊆ declared case_conditional ids` was skipped for a legacy family

**Finding.** `_enforce_declared_leaf_policy` returned early for a family
with no declared leaf policy BEFORE validating `I` at all. A legacy
family's plugin whose hook returns a non-empty set (a typo, or a stale
hook left over from a prior manifest version) would finalize a receipt
recording an undeclared inapplicable leaf; replay and audit would repeat
the same unchecked value indefinitely, since both recompute `I` from the
same broken hook and compare against the receipt's own (equally wrong)
recorded value.

**Disposition — fixed, commit `139757a1`.** The subset check
(`I ⊆ declared_case_conditional_ids`) now runs unconditionally, before the
no-declared-policy early return. A legacy family declares zero
`case_conditional` leaves, so any non-empty `I` from a hook it happens to
define is now caught immediately.

**Test.** `tests/test_shared_runner_family_evaluation.py::test_finalize_rejects_a_legacy_familys_hook_returning_an_undeclared_inapplicable_id`
-- Housing's real, production, no-leaf-policy manifest, plugin
monkey-patched with `inapplicable_leaf_ids` returning `{"typo_leaf"}`.

**Mutation.** Restoring the pre-fix ordering (early return before the
subset check) made the test fail with "DID NOT RAISE ValueError".

### 2 (should-fix) — the hook's return value was coerced, not validated

**Finding.** `frozenset(hook(family_case))` accepted any iterable: a `str`
silently became a set of its individual characters; other non-iterable
types raised a confusing `TypeError` from the wrong function; no member
type was ever checked.

**Disposition — fixed, commit `466a3006`.** `_inapplicable_leaf_ids` now
requires an actual `frozenset` or `set` (both, per the review; the type
hint says `frozenset[str]` but the validation is deliberately looser than
the hint on this one point) whose every member is `str`, raising a named
`TypeError` mentioning the plugin (`type(plugin).__qualname__`, since the
hook only receives the plugin instance, not its registered `plugin_id`)
and the offending type.

**Tests** (`tests/test_shared_runner_family_evaluation.py`):
`test_inapplicable_leaf_ids_rejects_a_hook_returning_a_list`,
`test_inapplicable_leaf_ids_rejects_a_hook_returning_a_str`,
`test_inapplicable_leaf_ids_rejects_a_hook_returning_a_set_with_a_non_string_member`,
and (positive control) `test_inapplicable_leaf_ids_accepts_a_plain_set_of_str`.

**Mutation.** Restoring the pre-fix `return frozenset(hook(family_case))`
made all three negative tests fail with "DID NOT RAISE TypeError".

### 3 (should-fix) — the unscored (operational-exclusion) path was never checked

**Finding.** `audit_family_receipt` evaluated the hook and compared
`inapplicable_leaf_ids` only inside `if receipt.get("scores")`. An unscored
receipt (`finalize_family_failure`'s typed operational exclusion) never
called the hook at all -- `finalize_family_failure` did not record a real
`I` (it silently defaulted to `()`, the same way `deferred_leaf_ids`
already does and continues to on this path -- confirmed by reading the
function directly, not assumed), so there was nothing meaningful for
audit to recompute and compare against even if it tried.

**Disposition — fixed, commit `90515de2`.** Leaf disposition is a case
property, not a scoring outcome, so:

- `finalize_family_failure` now computes `I` from the plugin's hook (the
  `family_case` it already computes) and records it on the receipt, and
  validates `I` against the manifest's declared `case_conditional` ids
  (the same check extracted into a shared
  `_reject_undeclared_inapplicable_ids` helper, now used by
  `_enforce_declared_leaf_policy`, `finalize_family_failure`, and audit's
  unscored branch).
- `audit_family_receipt`'s unscored branch now resolves the plugin/case,
  recomputes `I`, validates it, and compares it against the receipt's
  recorded value.
- `replay_family_receipt` has no equivalent branch to fix: it
  unconditionally requires exactly one `score_recorded` event
  (`if len(score_events) != 1: raise ...`) and so structurally never
  receives an unscored receipt at all -- confirmed by reading the function,
  not assumed. Recorded here rather than silently adding a no-op check to
  satisfy the letter of "replay/audit" without substance.
- `deferred_leaf_ids` on this path is left as `finalize_family_failure`
  already had it (always `()`, since no leaf is ever scored) -- that
  predates R13 and is out of this ruling's scope; only `inapplicable_leaf_ids`
  is R13's to make consistent here.

**Tests** (`tests/test_shared_runner_scoring_contract.py`), driven through a
genuine reconciled failure (one scripted label for a two-round episode, so
round_two's provider call fails closed and the scheduler raises with the
failure trail already sealed -- exactly what `finalize_family_failure`
documents itself as sealing):
`test_case_conditional_finalize_family_failure_records_inapplicable_leaf_ids`,
`test_case_conditional_finalize_family_failure_records_empty_inapplicable_leaf_ids_when_applicable`,
`test_case_conditional_audit_accepts_an_unscored_receipts_recomputed_inapplicable_leaf_ids`,
`test_case_conditional_audit_rejects_an_unscored_receipt_whose_inapplicable_leaf_ids_disagree_with_the_recomputed_hook`.

**Mutation.** Removing `finalize_family_failure`'s new `inapplicable_leaf_ids=`
kwarg made the "records" test fail on the exact assertion (`() ==
('case_conditional_diagnostic',)`). Removing audit's new unscored-branch
comparison made the "rejects" test fail with "DID NOT RAISE ValueError".

### 4 (should-fix) — precedence proven only for a finalize_time conditional leaf

**Finding.** The deferred/inapplicable disjointness precedence (rule 4)
was implemented identically at all three call sites but only exercised by
`_CaseConditionalPlugin`'s finalize_time diagnostic -- no fixture had a
leaf that is BOTH `deferred` and `case_conditional`.

**Disposition — fixed, commit `7e036d73`.** A new, deliberately SEPARATE
synthetic family (`_CaseConditionalDeferredPlugin`, its own manifest and
case builders) with one leaf that is both `scope="deferred"` and
`case_conditional=True` -- kept separate from `_case_conditional_family_manifest`
so this fixture could not perturb any already-committed case-conditional
test's exact leaf-set assertions. Since a deferred leaf never appears in
`scores` regardless of applicability, the scorer here is simpler than
`_CaseConditionalScorer`: it always returns only the primary.

**Tests** (`tests/test_shared_runner_scoring_contract.py`), both case
modes, through all three real entry points:
`test_case_conditional_deferred_precedence_applicable_case_at_finalize`,
`test_case_conditional_deferred_precedence_inapplicable_case_at_finalize`,
`test_case_conditional_deferred_precedence_replay_applicable_case`,
`test_case_conditional_deferred_precedence_replay_inapplicable_case`,
`test_case_conditional_deferred_precedence_audit_applicable_case`,
`test_case_conditional_deferred_precedence_audit_inapplicable_case`.

**Mutation**, one per path's own `- inapplicable_ids` subtraction:
removing it in `finalize_family_execution` made the inapplicable-case
finalize test fail with the receipt's own disjointness guard
(`MeasurementContractError: inapplicable_leaf_ids must not overlap with
deferred_leaf_ids`); removing it in `replay_family_receipt`'s
`deferred_leaf_ids` comparison made the inapplicable-case replay test fail
with "receipt deferred_leaf_ids does not match the declared policy";
removing it in `audit_family_receipt`'s scored-branch comparison made the
inapplicable-case audit test fail with "receipt admission does not match
the replayed score".

### 5 (should-fix) — the protocol helper never checked `I`'s subset property

**Finding.** `_assert_family_obeys_the_scoring_contract` checked
`returned == declared - I` but never `I ⊆ declared case_conditional ids`.
A hook returning an id that names NO declared leaf at all (not even the
primary) subtracts nothing from `declared.leaf_ids`; a scorer unaffected
by the hook's lie (returning exactly the declared set) then satisfies the
equality regardless -- the broken hook passes silently.

**Disposition — fixed, commit `db7525e5`.** The helper now asserts
`I ⊆ declared_case_conditional_ids` (computed from
`registration.manifest.measurement.leaves`) with a message naming the
family and the offending ids, before the leaf-set equality.

**Test.** `tests/test_shared_runner_scoring_contract.py::test_case_conditional_protocol_helper_rejects_an_undeclared_inapplicable_id`
-- a new `_CaseConditionalPlugin` mode, `"hook_returns_a_typo"`, returning
an id that is not even the primary (the earlier `"hook_returns_undeclared"`
mode, which names the primary, was tried first and rejected for this
specific test: subtracting a real declared id from `declared.leaf_ids`
collaterally breaks the leaf-set equality too, which would have let the
test pass for the wrong reason -- see the mutation below for why this
distinction mattered in practice).

**Mutation.** Removing the new subset assertion made the test fail with
"DID NOT RAISE AssertionError" -- a genuine silent pass, not merely a
differently-worded failure (confirmed by first attempting the mutation
against the `"hook_returns_undeclared"` adversary, where removing the
assertion produced a *different* AssertionError rather than none at all,
which is why the test uses `"hook_returns_a_typo"` instead).

### 6 (blocker) — `research.py::_deserialize_receipt` dropped `inapplicable_leaf_ids`

**Finding.** `docs/kernel_r13_conditional_leaves.md` itself recorded this
as a known, unfixed gap: `_deserialize_receipt` never read
`inapplicable_leaf_ids` back from the serialized mapping, so the first
family to declare a `case_conditional` leaf would lose the field on this
specific round trip (research.py's own serialize/deserialize path, not
the kernel's `write_evaluation_receipt`/`read_evaluation_receipt`, which
was already proven correct in commit `08148388`).

**Disposition — fixed, commit `6ac18352`.** Checked `deferred_leaf_ids`
first, as instructed: it was already correctly read back
(`tuple(value.get("deferred_leaf_ids", ()))`), a pre-existing, correct
line -- not a defect. `inapplicable_leaf_ids` gets the identical treatment,
newly added: `tuple(value.get("inapplicable_leaf_ids", ()))`.

**Test.** `tests/test_shared_runner_research.py::test_deserialize_evaluation_receipt_round_trips_inapplicable_leaf_ids`
-- mirrors the file's own existing `..._round_trips_deferred_leaf_ids` test
exactly, extended to also carry a non-empty `deferred_leaf_ids` in the same
receipt (proving both fields survive together, not just in isolation).
`_receipt()`'s test fixture builder gained an `inapplicable_leaf_ids`
keyword to support this.

**Mutation.** Removing the new `inapplicable_leaf_ids=` line from
`_deserialize_receipt` made the test fail with
`ResearchContractError: serialized EvaluationReceipt is invalid` (the
rebuilt receipt's `receipt_sha256` no longer matches, since the rebuilt
object silently defaulted the field to `()` instead of the original's
non-empty value).

### Deviation update

The doc's earlier "Deviations" section (recording `research.py`'s gap as
known-but-unfixed, out of the original file scope) is superseded by finding
6 above: the file was brought into scope for this review round and the gap
is now fixed, not merely documented.
