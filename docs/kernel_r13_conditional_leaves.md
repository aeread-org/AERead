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
