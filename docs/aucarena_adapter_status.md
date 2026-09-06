# aucarena adapter — status

Branch `zeyu/aucarena-contract-migration`, stacked on `zeyu/kernel-r9r10` (rulings
R9/R10). Last verified 2026-09-06. Milestone 3 of 3 (scripted harness + end-to-end +
replay) landed earlier, on `zeyu/aucarena-adapter`; milestones 1-2 of that same earlier
sequence (cases/environment/scorer/goldens) landed before it. This branch's own migration
milestone 2 of 3 (`kernel_scoring_contract_spec.md`, `docs/aucarena_migration_plan.md`) is
the "Leaf policy" section immediately below -- a distinct, later milestone numbering from
the one in the paragraph above, which predates the scoring-contract migration entirely.

## What the adapter claims

For each of the five QC Gate-2 goldens (`docs/aucarena_adapter_spec.md` section 5), a
scripted, all-`"rule"`-or-`"scripted"`-bidder auction runs deterministically end to end
through the real kernel phase scheduler (`aeread.shared_runner.scheduler.run_episode`), with
every bid-legality, bid-recording, and hammer-determination rule delegated to hand-vendored,
provenance-headed copies of upstream `jiangjiechen/auction-arena`'s own pure functions
(`_vendored_upstream.py`) — never reimplemented from spec prose. It declares four
measurement leaves, never one blended number (`docs/aucarena_adapter_spec.md` section 2):

| Leaf | Verifier family | Reference kind | Scope | Declared |
|---|---|---|---|---|
| `aucarena_budget_invariant` | `rule_constraint` | `state_invariant` | trajectory | always |
| `aucarena_bid_legality` | `rule_constraint` | `constraint_satisfaction` | trajectory | always |
| `aucarena_hammer_rule` | `rule_constraint` | `temporal_property` | trajectory | always |
| `aucarena_profit_vs_field` | `comparative` | `head_to_head` | terminal_state | always; `invalid_measurement` when the roster's field is empty (golden 5) |

No `objective_reference` leaf is declared: per the P21 row in both
`docs/verifier_taxonomy.md` §13 and `docs/problem_bound_case_audit.md`, profit and TrueSkill
do not solve the auction policy game, so `aucarena_profit_vs_field` stays a head-to-head
comparison against a *named, declared* frozen rule-bidder field — never a universal
auction-skill score.

Milestone 3 adds two more claims, both new this milestone:

1. **Sealed evidence.** The shipped `ScriptedAucArenaHarness` (`src/aeread_families/
   aucarena/harness.py`) optionally records every served bid decision into a real
   `EvidenceStore` — a hash-chained, tamper-evident `bid_decision_served` event per decision,
   keyed by the scheduler's own `phase_instance_id`/`logical_action_id`. Two full episodes
   (goldens `successful` and `invalid_unauthorized`) each produce their own independently
   sealed evidence generation, verified with `verify_chain()`, `seal()`, and a fresh
   `EvidenceStore.audit_existing(...).verify_seal()` — not merely an in-memory claim.
2. **Offline replay, byte-identical.** `src/aeread_families/aucarena/replay.py` records an
   episode's raw decision log, JSON-round-trips it, and replays it through a second,
   independent `AucArenaPlugin` instance with zero further policy calls. Because this family
   has no bridge process and no wall-clock content anywhere in its state, the replayed final
   state matches the original **byte-for-byte** (`canonical_json_bytes` equal), not merely in
   content — stronger than `tau3_retail`'s own replay guarantee, which must specifically
   strip per-message timestamps to compare content only.

## Leaf policy (kernel_scoring_contract_spec.md, migration milestone 2 of 3)

`family_manifest()`'s `measurement` block now declares this family's leaf policy
explicitly (spec section 3), and `AucArenaScorer.__call__` takes a
`FamilyScoringInput` and returns a `FamilyScoreSet` carrying every one of the four
leaves below — the shim that previously returned only `aucarena_profit_vs_field` (see
the retired "Known limits" entry below) is gone.

| Leaf | Scope | Primary | Admission |
|---|---|---|---|
| `aucarena_budget_invariant_leaf` | `finalize_time` | no | no |
| `aucarena_bid_legality_leaf` | `finalize_time` | no | no |
| `aucarena_hammer_rule_leaf` | `finalize_time` | no | no |
| `aucarena_profit_vs_field_leaf` | `finalize_time` | **yes** | **yes** |

**Why `aucarena_profit_vs_field` is primary.** It is this family's own
already-declared `primary_estimand` (`family_manifest()`'s `measurement` block,
present since before this milestone), and it names the estimand of primary interest
by design: per the P21 row in both `docs/verifier_taxonomy.md` §13 and
`docs/problem_bound_case_audit.md`, profit and TrueSkill do not solve the auction
policy game, so no `objective_reference` leaf is declared at all, and the
comparative head-to-head leaf is the one this family stakes its headline claim on
(`measurement.py`'s own module docstring makes the identical statement). It was not
picked because it was the easiest leaf to compute through the pre-migration seam —
if anything it is the opposite: `aucarena_profit_vs_field` is this family's only
*terminal-state-scoped* leaf, and the pre-migration `__call__` could reach it
directly from a bare `outcome` mapping with zero trajectory reconstruction, while the
three `rule_constraint` leaves need the full replayed `phase_instances` (and, for
`aucarena_hammer_rule`, `world_seed`/`enable_discount` read off the last replayed
transition's own state via `_ScoringInputResult`, since `FamilyScoringInput` carries
no `final_state` field). The choice tracks the family's own declared estimand and its
"profit/TrueSkill do not solve the game" design stance, not which leaf was
convenient under the old signature.

**Why it alone gates admission.** The three `rule_constraint` leaves are
integrity/parity diagnostics on the environment's own rule application — "the
component parity check the spec's test plan calls for" (this file's own "What the
adapter claims" section above) — never competing candidates for the headline result,
and per `measurement.py`'s own scorers none of them has a real
`invalid_measurement` path to gate on at all: each of `score_budget_invariant`,
`score_bid_legality`, and `score_hammer_rule` always returns `status="ok"`; a
genuine violation is recorded as a `0.0`-valued metric under an otherwise-valid
envelope (e.g. `score_budget_invariant`'s `primary=MetricValue(0.0 if violations
else 1.0, "pass")`), and a disagreement between the environment's own recorded
state/legality/consequences and this module's independent recompute is treated as
an adapter defect and raises `AucArenaMeasurementError` directly, which aborts
finalization before admission gating is ever reached. `aucarena_profit_vs_field` is
the only leaf whose estimand definition requires something that is not always
present (a non-empty comparator field, golden 5's single-seat roster) and therefore
the only one with a real `invalid_measurement` path
(`score_profit_vs_field`'s empty-`field_seats` branch) — the leaf whose exclusion
behavior actually matters is the one gating admission. This mirrors `govsim`'s own
admission choice (primary alone; its two `rule_constraint` diagnostics are declared
but do not gate) for the same underlying reason.

**Deferred leaves: none.** Every leaf in this family is
`evaluation_class="deterministic"` with no judge, rater, or other not-yet-existing
artifact anywhere in its verifier declaration (`measurement.py`'s `build_*_leaf`
functions and its own module docstring: "provider-free and judge-free... all four
are `deterministic`"); nothing here waits on an artifact that "may not exist yet"
(spec section 4), so all four are declared `scope="finalize_time"` and none is
`scope="deferred"`.

`docs/aucarena_migration_plan.md`'s own "Does `outcome()` embed the trajectory?"
section additionally confirms rulings R9/R10 (`trajectory_outcome_paths`) do not
apply here: `outcome()` carries no field recording individual bid amounts, rounds,
or parse/legality determinations — only per-item final dispositions and per-seat
final tallies — so the whole-outcome paired-history pair is constructible without a
projection, unlike `collusion`/`datacenter_development`.

## Enrollment and receipt (kernel_scoring_contract_spec.md, migration milestone 3 of 3)

`aucarena` is dropped from `_NOT_YET_MIGRATED_TRUSTED_KEYS` in
`tests/test_shared_runner_scoring_contract.py` and enrolled with real fixtures
(`_aucarena_fixtures`) in the always-on
`test_every_registered_family_obeys_the_scoring_contract` — no bridge-gated test or
conftest.py gate is needed (unlike `govsim`): this family has no bridge process at all,
and its scoring-contract fixtures build a small, custom, checked-in-corpus-independent
case directly (`tests/test_aucarena_replay.py`'s own `kernel_contract_fixture_case`).

Three findings surfaced while implementing this milestone, investigated and fixed before
enrolling — full disposition, empirical verification, and mutation-test evidence in
`docs/aucarena_migration_review.md`:

1. `aucarena_budget_invariant_leaf`/`aucarena_hammer_rule_leaf` could not satisfy ruling
   R9(b)'s sensitivity witness (neither has any way to produce a differing score on a
   legitimately-scripted episode) — fixed with an additive, violation-arithmetic-untouched
   diagnostic metric on each.
2. `aucarena_bid_legality_leaf`'s witness additionally needed a same-case fixture
   carrying a genuine illegal bid, not just a longer trajectory.
3. This family had never produced an `EvaluationReceipt` at all: `initial_state`'s second
   parameter was named `cell` and dereferenced, but replay calls it with `run=None`; fixed
   by renaming to `run` and making `world_seed` reachable from `family_case` instead
   (duplicated from the outer `CaseManifest.world_seed`, mirrored into the five checked-in
   goldens via the real import CLI), plus declaring `scoring.reference_provider_ids` (nine
   component ids, previously unreferenced by the manifest) so a `RunPlan` pinning them
   resolves at all.

`tests/test_aucarena_replay.py::test_finalize_wires_aucarena_to_the_shared_family_finalizer`
drives one real, provider-free episode through `task.evaluation.finalize_family_execution`
and asserts `status == "ok"`, `inclusion_status == "included"`, exactly the four declared
finalize-time leaves, and the declared `primary_leaf_id` — the first receipt this family
has ever produced.

## Evidence

**On this machine, with the pinned upstream auction-arena checkout present: 0 failed, 0
skipped** across the family test files. **This is conditional, not unconditional** (corrected
per `docs/aucarena_codex_triage.md` Finding 8 — an earlier revision of this doc claimed "zero
skips anywhere in this family... there is no upstream bridge interpreter to be missing", which
is false on any machine without this developer's own hardcoded default checkout path or the
`AEREAD_AUCARENA_UPSTREAM_ROOT` override): `tests/test_aucarena_cases.py` (QC Gate 1, 19
tests: pinned item-pool sha256/count, id resolution, importer byte-determinism, the
case-id colon-grammar regression) gates on that checkout via a module-level
`pytest.skip(..., allow_module_level=True)`, exactly like `tau3_retail`'s own bridge-Python
gate — a missing checkout collapses all 19 of that module's tests into one `1 skipped` line,
not a failure, with no further signal in a plain CI log.

`conftest.py`'s `pytest_terminal_summary` hook (already used to make a missing tau2 bridge
loud) now also covers this gate. Independent cross-model verification
(`docs/aucarena_fix_verification.md`) found the opt-in alone insufficient: nothing in this
repo's own `.github/workflows/ci.yml` sets `AEREAD_AUCARENA_QC_GATE_REQUIRED` (or the
pre-existing tau2 equivalent), so an ordinary default run — exactly what every contributor and
every CI job actually does — stayed completely silent regardless of the gate's existence. The
hook now reports a matching skip unconditionally: set `AEREAD_AUCARENA_QC_GATE_REQUIRED=1` (CI,
and any run meant to certify this family's QC-Gate-1 claims) to turn it into a failed run with a
provisioning hint; leave it unset and the same skip still prints a visible note (test count,
reasons, and how to enforce) — never again the prior silent no-op. Only the *exit status* stays
untouched by default, so a local contributor not working on this family is never surprised. This
repo's own CI still does not set the enabling var, so a default CI run today will *show*, but
not fail on, this note — enforcing it there would first require provisioning the pinned upstream
checkout in CI, a separate, out-of-scope decision this pass does not make.

```bash
AEREAD_AUCARENA_UPSTREAM_ROOT=<pinned-checkout> PYTHONPATH=src pytest tests/test_aucarena_*.py -q
# 111 passed (100 passed before this milestone's leaf-policy/__call__ migration
# added the manifest leaf-policy test and the golden-5 __call__ case)
AEREAD_AUCARENA_QC_GATE_REQUIRED=1 PYTHONPATH=src pytest tests/test_aucarena_cases.py -q
# fails loudly, with a provisioning hint, if that checkout is absent
```

**Full repo suite: 826 passed, 31 skipped, 1 xfailed, 0 failed** (pre-migration baseline;
not re-run whole-repo this milestone, which touched only this family's own files). The 31
skips are pre-existing and unrelated to this family: `rllm` integration tests (`No module
named 'rllm'`) and `tau3_retail` tests gated on a pinned upstream tau2-bench Python
interpreter (`$AEREAD_TAU2_BRIDGE_PYTHON`). Re-ran with and without this branch's changes to
confirm the skip set is unchanged by this work.

**This milestone's own family suite: 121 passed, 0 failed, 0 skipped** (the seven family
test files above plus `tests/test_shared_runner_smoke.py`), re-verified both with
`AEREAD_AUCARENA_UPSTREAM_ROOT` exported and with it unset -- unchanged either way on this
machine, since `tests/test_aucarena_cases.py`'s own default checkout path (see the
"conditional, not unconditional" note above) already resolves to a present checkout here;
the skip this family's QC-Gate-1 tests would show on a machine without that checkout, or
without the env var override, is unaffected by this migration.

```bash
PYTHONPATH=src pytest tests/test_shared_runner_smoke.py -q
# 10 passed
```

**Every one of the five goldens replays byte-identically, state and score.**
`tests/test_aucarena_replay.py::test_replay_reproduces_every_golden_byte_identically` is
parametrized over all five (`successful`, `valid_but_poor`, `invalid_unauthorized`,
`malformed_operational`, `degenerate_reference`); for each, `canonical_json_bytes(final_state)`
and every one of the four leaves' recomputed `ScoreEnvelope`s are asserted byte-equal between
the live run and its offline replay — including golden 5's `aucarena_profit_vs_field`
surviving replay as `invalid_measurement`, not silently re-scored as an economic zero
(`test_replay_and_verify_reproduces_the_invalid_measurement_status`).

**Mutation tested, and the result was not what was first assumed.** The original plan was
"tamper one recorded bid, expect `compare_episode_results` to report a soft, typed
mismatch." That is not what happens: because this family's `"simultaneous"` phase mode makes
eligibility for the *next* round state-derived (the current highest bidder and each seat's
withdraw flag, both set by the very bid value under test), corrupting even one well-formed,
still-legal bid from the one seat whose response actually carries information (`"agent"`;
`"rule"` seats' raw responses are accepted but never inspected) changes which seat the
scheduler must request next. `RecordedResponseSource` catches that immediately — surfaced as
`SchedulerContractError` by the kernel scheduler's own response-source exception wrapping —
before the replayed episode can complete at all, let alone reach a state comparison. This is
verified, not assumed (`test_tampering_a_mid_trajectory_bid_is_caught_immediately_not_
silently_replayed`), and is a stronger, earlier-failing integrity property than a
post-hoc state diff would give. `compare_episode_results`'s own comparison logic is proven
separately not to be vacuous with a synthetic, scheduler-free fixture
(`test_compare_episode_results_reports_specific_mismatches_not_one_boolean`) and with two
independently-produced live runs of different goldens
(`test_compare_episode_results_would_report_a_genuine_divergence`).

**Sealed evidence is durable and independently re-verifiable, not just an in-memory claim.**
`test_two_full_episodes_each_produce_independently_sealed_evidence` seals two full episodes'
evidence generations, calls `seal()` twice (idempotent, same seal both times), and opens each
one through `EvidenceStore.audit_existing()` — a fresh, read-only handle, not the writer that
produced it — confirming `verify_seal()` agrees.
`test_sealed_evidence_rejects_further_writes` confirms a sealed generation cannot silently
accept another event.

## Why there is no bridge to provision

Unlike `tau3_retail` (which needs a live, `langchain`/`torch`-loaded upstream `Environment`
to reproduce a policy game the vendored functions alone cannot settle), this family's
scripted-`"rule"`-bidder path is deterministic bookkeeping with no LLM call reachable on it
(`docs/aucarena_adapter_spec.md` section 1, "Governing facts"). The four rules this adapter
must reproduce exactly — bid legality, bid recording/tie-break, hammer determination, and
profit/budget bookkeeping — are vendored as free functions with per-function provenance
headers (`_vendored_upstream.py`), covered directly by hand-computed-trace unit tests
(`tests/test_aucarena_vendored_upstream.py`) and cross-checked against the environment's own
recorded trajectory by an independent recompute (`tests/test_aucarena_parity.py`). There is
nothing left to delegate to a subprocess, and nothing to provision.

## Known limits, stated rather than implied

- **Scripted `"rule"`/`"scripted"` bidders only.** LLM-driven bidders (`plan_strategy` beyond
  `"none"`/`"static"`, belief tracking, learning-from-prior-auction) are not wrapped; they
  require the `langchain`-chained prompt/parse path this adapter deliberately never imports
  (`docs/aucarena_adapter_spec.md` section 7).
- **`aucarena_profit_vs_field` is a head-to-head comparison, not a policy optimum.** Per the
  P21 row in both `docs/verifier_taxonomy.md` and `docs/problem_bound_case_audit.md`, this
  route is `not_demonstrated` for saturation and must stay that way in any paper claim.
- **The scenario corpus is AERead-authored, not an upstream-published task list** — upstream
  ships only a raw 26-item pool and a generator, not an enumerable task set
  (`docs/aucarena_adapter_spec.md` section 1). Growing coverage means authoring more scenario
  records against the same pinned pool, not importing more upstream tasks.
- **`enable_discount` (price cuts after failed-to-sell rounds) and the human-bidder path are
  unvendored.** Every case this adapter admits fixes `enable_discount=False`;
  `validate_payload` rejects any payload that sets it otherwise.
- **No tool-call layer.** Bids are plain typed actions, not `ToolDefinition`-bound calls, so
  the shared-runner tool/state-evidence machinery `tau3_retail` exercises is not exercised by
  this family — sealed evidence here covers the raw decision itself, not a delegated tool
  result.
- **`parity.py` was never built, on purpose (unchanged since milestone 1).**
  `tests/test_aucarena_parity.py` already runs the same two-independent-code-paths comparison
  a shipped module would; a third module would add indirection, not additional coverage.
- **Content-tamper mutation testing on the *hammer/legality path itself* (as opposed to the
  bid values under test) was not separately attempted this milestone** — the discovery above
  (any bid-value tamper cascades into a decision-order mismatch) made the originally-planned
  "tamper and observe a soft state mismatch" test path unreachable for this family's own
  goldens; the comparator's non-vacuity is instead established with synthetic fixtures and
  two genuinely different live runs (see Evidence, above).
- **The "parity" tests cannot catch a bug inside the vendored functions themselves**
  (`docs/aucarena_codex_triage.md` Finding 7, disclosed and acknowledged, not fixed this
  milestone). `tests/test_aucarena_parity.py`'s own module docstring already states this
  plainly: `environment.py`'s live decision and `measurement.py`'s "independent" recompute
  both call the identical `vendored.bid_sanity_check`/`vendored.check_hammer`/
  `vendored.record_bid` functions, so both sides would agree identically on a wrong answer.
  The real defense against a transcription error in those vendored functions is
  `tests/test_aucarena_vendored_upstream.py`'s hand-derived numeric assertions — a real,
  gating pytest suite, but authored once and never independently re-derived by a second,
  blind process. The spec's own "Test plan" (section 6) names exactly this as an optional,
  non-gating hardening step; it stays manual. No fix is possible here that does not also
  defeat its own purpose (any re-derivation performed by whoever already has full view of the
  vendored code is not blind), so this is recorded as a standing, disclosed limitation rather
  than a closed finding.
- **`aucarena_profit_vs_field`'s reference-hash identity covers item order and the field
  roster, not the full spec-declared pairing (`docs/aucarena_codex_triage.md` Finding 6).**
  `_field_roster_sha256` (`measurement.py`) hashes the frozen field (seat ids, model names,
  budgets) and item order; `case_id`/`world_seed` are *not* included and cannot be from this
  leaf — `build_scorer` is called with only the case's bare `payload`
  (`plugin.build_scorer(family_case)`, confirmed by every `build_scorer(family_case)` call site
  in this family's own tests), and `case_id`/`world_seed` live on the outer `CaseManifest`, not
  inside `payload`. Closing that half of the pairing identity would need a kernel signature
  change, not an adapter fix. The item-order half is pinned and tested
  (`tests/test_aucarena_measurement.py::test_profit_vs_field_reference_hash_distinguishes_item_order_not_only_the_field`
  and `::test_build_scorer_reference_hash_reflects_the_real_cases_item_order`); the
  `case_id`/`world_seed` half of the pairing is tracked at the outer kernel bookkeeping layer
  instead (`cell_id`/`case_id` already on the receipt).
- ~~**`AucArenaScorer.__call__` can surface only one of this family's four declared leaves...**~~
  **Retired 2026-09-06.** `AucArenaScorer.__call__` now takes a `FamilyScoringInput` and returns
  a `FamilyScoreSet` carrying all four declared leaves (see "Leaf policy" above) — the kernel
  contract gap this entry described (`runner_defect_ledger.md` entry **D-19**) is resolved for
  this family by the `kernel_scoring_contract_spec.md` migration; whether the other three
  families D-19 named (`govsim`, `steer`, `negarena`) have migrated is tracked in their own
  status docs, not here.
- **Two Finding-5/Finding-2 codex-review findings are confirmed but not auto-fixed this pass**
  (see `docs/aucarena_review_disposition.md`'s "Codex-review findings" section for the full
  reasoning): whether a malformed/illegal bid should still terminate a round with no retry
  (Finding 2, upstream itself retries without bound) and what single scalar, if any,
  `aucarena_profit_vs_field`'s `primary` should report for a multi-seat field (Finding 5, the
  current unweighted mean can dilute a decisive loss) are both product/architecture decisions
  with more than one defensible answer and no spec-mandated one — not code bugs with a single
  correct fix. Escalated rather than guessed. Today's disclosed behavior is pinned by name, not
  only asserted in prose:
  `tests/test_aucarena_measurement.py::test_golden_3_earns_no_credit` and
  `::test_golden_4_other_leaves_match_golden_3_outcome` assert `status == "ok"` for a
  malformed/illegal round (Finding 2), and
  `::test_golden_1_profit_vs_field_is_finite_and_mixed_sign` pins the exact unweighted-mean
  formula (Finding 5) — a future silent change to either behavior breaks a named test instead of
  slipping through unremarked.

## Ledger

No new kernel/runner defect found this milestone. Three pre-existing entries from earlier
milestones remain open in `ledger_entries/aucarena.md` (missing `docs/benchmark_qc.md`;
`build_scorer` receiving no seed-bearing object, worked around by this family persisting
`world_seed` in its own state) — unchanged by this work, not re-litigated here.
