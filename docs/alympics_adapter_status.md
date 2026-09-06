# alympics.wac adapter — status

Originally built on branch `zeyu/alympics-adapter` (last verified 2026-09-02); now carried on `zeyu/alympics-contract-migration`, re-verified 2026-09-06 (see update below). Milestone 3 of 3
(scripted harness + end-to-end + replay); milestones 1-2 (cases,
environment, measurement) landed earlier on this branch.

**Update, `zeyu/alympics-contract-migration` (this branch, 2026-09-06):**
this family is now migrated to `kernel_scoring_contract_spec.md`'s
`FamilyScoringInput` scoring contract and enrolled in
`tests/test_shared_runner_scoring_contract.py`'s protocol test. See
"Scoring contract migration" below for the leaf policy, the receipt, and
what changed from the description above (most of the rest of this doc,
describing the original adapter build, is otherwise unchanged and still
accurate).

## What the adapter claims

For the pinned Water Allocation Challenge (`microsoft/Alympics`, commit
`caed7c8c3b8f9de9ac8be1ba54407a51087affc5`), a complete episode — every
round's salary credit, bid legality gate, greedy winner admission,
settlement, and elimination check — can be driven **entirely through the
real kernel scheduler path** (`run_episode`/`AlympicsWacPlugin`, Mode C
simultaneous phase graph), with **zero network calls, zero API keys, zero
LLM calls**: every seat's bid comes from one of four named, deterministic
scripted policies (`proportional`, `aggressive`, `conservative`,
`myopic_need` — `harness.py`), never from a live model, and upstream's own
`_get_salary`/`_check_winner`/`_round_settlement`/`success_bid`/
`unsuccess_bid` execute unmodified via `environment._delegate_round`.

A completed episode's decision log can be **serialized to plain JSON,
reloaded, and replayed offline with zero further provider calls**, and the
replayed run's final state is required to be **byte-identical** to the
original live run's — not merely content-equivalent modulo a documented
non-deterministic field (unlike `tau3_retail`, whose per-message wall-clock
`timestamp` never survives two independent runs identically; this family's
state carries no such field, and the test suite pins exact equality as a
checked fact, not an assumption). All four declared leaves
(`alympics_wac_terminal_wealth`, `alympics_wac_survival`,
`alympics_wac_bid_legality`, `alympics_wac_settlement_exactness`) can be
recomputed purely from a replayed episode plus a replayed baseline episode
— never by re-deriving a baseline through a hand-written formula.

Every bid a scripted harness serves is sealed as one durable,
hash-chained evidence event (`EvidenceStore.append_event`/`.seal()`), the
same append-only mechanism `tau3_retail`'s tool executions use — this
family has no tools to delegate through (`family_manifest`'s
`needs_tools: False`), so a served bid decision is the analogous
"externally observable thing a live provider would have produced."

## Evidence

**Two full episodes driven end-to-end through the harness, each with its
own sealed evidence generation** (`tests/test_alympics_wac_harness.py`):

| Case | Policy assignment | Termination | Round-1 bids (verified) |
|---|---|---|---|
| `reference_baseline` | all `proportional` | `rounds_exhausted` at round 20 | `{alex:24, bob:27, cindy:30, david:33, eric:36}` — matches spec section 4 golden 1 exactly |
| `mixed_policies_a` | `alex:aggressive, bob:conservative, cindy:proportional, david:myopic_need, eric:proportional` | `rounds_exhausted` at round 15, `alex` the sole survivor | `{alex:40, bob:9, cindy:30, david:22, eric:36}`, round-1 winner `alex` |

`mixed_policies_a` exercises all four named policies in one episode. Both
runs are checked for `len(harness.requests) == result.logical_action_count
== evidence.seal().event_count` — the harness never under- or
over-records relative to what the scheduler actually asked for — plus
`evidence.verify_chain()`, `evidence.verify_seal()`, and that
`append_event` after `seal()` raises `EvidenceSealedError`. A third test
runs both cases back-to-back into two independent `EvidenceStore`
generations and confirms neither leaks identity into the other
(`episode_id`, `event_root_sha256` both differ).

**Replay reproduces state byte-identically, not just semantically**
(`tests/test_alympics_wac_replay.py`): both the full 20-round
`reference_baseline` run and the mid-game-elimination `mixed_policies_a`
run are recorded, round-tripped through `RecordedEpisode.to_json`/
`from_json` (a genuine plain-JSON record, not a reused in-memory object),
replayed through a **second, independent** `AlympicsWacPlugin`, and
compared field-by-field: `phase_instance_count_matches`,
`state_hashes_match` (every phase instance's `pre_state_sha256`/
`post_state_sha256`), `terminal_matches`, `outcome_matches`, and
`final_state_matches` are all `True` — confirmed additionally by a direct
`canonical_json_bytes(replayed.final_state) ==
canonical_json_bytes(original.final_state)` byte comparison.

**All four leaves recomputed from replay alone**
(`test_replayed_episode_recomputes_all_four_leaves_using_a_replayed_baseline`,
`test_replay_and_verify_end_to_end_returns_a_matching_report`): the actual
`mixed_policies_a` episode and a second, derived baseline episode (focal
seat `alex` swapped to `proportional` via `harness.baseline_policy_assignment`,
opponent panel held fixed) are each recorded and replayed independently,
and `score_replayed_episode` reproduces `terminal_wealth`, `survival`,
`bid_legality`, and `settlement_exactness` all as `status="ok"` — the
`settlement_exactness` leaf's own shadow-recompute (a second, independent
call into `_delegate_round`) passes against the replayed round log alone,
with no live upstream run in the loop beyond that recompute. For
`reference_baseline` (already all-`proportional`), the baseline policy
assignment for its own focal seat is identical to the actual one, so the
comparative wealth/survival deltas are exactly `0.0` — checked, not
assumed.

**Full family test suite + kernel smoke, re-verified on this branch's HEAD
(2026-09-06): 151 passed, 0 failed, bridge exported.** The milestone-3
per-module counts below were stale even before this migration branch
forked (`cases.py`/`environment.py`/`measurement.py`'s own test modules
grew independently of this migration — this branch's only change to this
family's own `test_alympics_wac_*` modules is
`tests/test_alympics_wac_replay.py` (the shared
`tests/test_shared_runner_scoring_contract.py` also changed, for the
enrollment in commits 4e3bc842/4b4d05b5, plus a comment-only
cross-reference fix in 14146c2a) — `git diff --stat
zeyu/kernel-r9r10..HEAD` confirms); corrected here rather than carried
forward unchecked, and `tests/test_shared_runner_scoring_contract.py` is
now added to the reproduce command below, since this migration enrolled
this family in it (see "Protocol-test fixtures" below) and it is
bridge-gated for this family's own slice the same way the other six files
are:

```
cases              30 passed
environment        25 passed
harness            13 passed
measurement        26 passed
parity              2 passed
replay             13 passed
scoring-contract    1 alympics-specific test + 31 other-family tests, 32
                     total passed (shared file — see "Protocol-test
                     fixtures" above; do not read the 31 as this family's
                     own coverage)
smoke              10 passed   (tests/test_shared_runner_smoke.py)
```

Without the bridge (`AEREAD_ALYMPICS_UPSTREAM_ROOT` pointed at a path that
does not carry the pinned checkout): **71 passed, 0 failed, 6 skipped** —
`environment`/`harness`/`measurement`/`parity`/`replay` each skip as one
module-level skip (5), plus `test_alympics_wac_obeys_the_scoring_contract`
skips as one test-level skip (1); `cases`, `smoke`, and the other 31 tests
in `test_shared_runner_scoring_contract.py` are unaffected. (Merely leaving
`AEREAD_ALYMPICS_UPSTREAM_ROOT` unset does not exercise this path in every
checkout: several of these test modules fall back to a hard-coded
development-machine path when the variable is absent, so an unset-but-
present-by-coincidence checkout still runs green — point the variable at a
genuinely missing path, as above, to observe the skip.)

**Full repository suite (all families): historically reported as 815
passed, 31 skipped, 1 xfailed, 0 failed** (bridge exported); not
re-verified line-for-line on this pass because of the full suite's runtime,
so treat that specific figure as unconfirmed rather than re-certified here.
The qualitative claim — that the skips belong to other bridge-gated
families (tau2/tau3, rLLM integration) and none belong to this family —
still holds given the per-family numbers just verified above.

Reproduce:

```bash
cd AERead/.worktrees/alympics-migrate
AEREAD_ALYMPICS_UPSTREAM_ROOT=<pinned caed7c8c checkout> AEREAD_ALYMPICS_UPSTREAM_REQUIRED=1 PYTHONPATH=src ../../.venv/bin/python -m pytest \
  tests/test_alympics_wac_cases.py \
  tests/test_alympics_wac_environment.py \
  tests/test_alympics_wac_harness.py \
  tests/test_alympics_wac_measurement.py \
  tests/test_alympics_wac_parity.py \
  tests/test_alympics_wac_replay.py \
  tests/test_shared_runner_scoring_contract.py \
  tests/test_shared_runner_smoke.py -q
```

(Optionally also list `tests/test_alympics_wac_upstream_required_gate.py` — 4
tests, passes; included in the migration plan's 112-test baseline but
omitted from the command above — with it the total is 155, not 151.)

## The four scripted policies (spec section 6: constants finalized here)

Each is a pure, deterministic function of *only* the seat's own
observation — never another seat's state, never this harness's own past
responses (the same leakage boundary spec section 2 leaf 4 requires of
the environment itself, restated from the harness side):

| Policy | Formula | Note |
|---|---|---|
| `proportional` | `3 * requirement` | Fixed every round; verified against spec section 4 golden 1's own bid vector. |
| `conservative` | `1 * requirement` | Fixed every round; spec section 4 golden 2's "valid but poor" policy. |
| `aggressive` | `5 * requirement` | Fixed every round; over-bids `proportional` on a fixed multiplier. |
| `myopic_need` | `requirement * (1 + no_drink)` | Reacts only to this seat's own, already-escalating drought penalty (`no_drink` — upstream's own literal "need" counter). |

`aggressive` and `myopic_need` are this adapter's own choice; spec section
6 explicitly defers their exact constants to implementation time, and no
earlier milestone locks in a different value. **`myopic_need` deliberately
never reads `observation["balance"]`**, which sidesteps an already-ledgered
limitation (`ledger_entries/alympics.md`): `observe()`'s reported balance
lags upstream's own live, salary-credited balance by one round's
`daily_salary`, for every seat, every round. `proportional`/`aggressive`/
`conservative` are balance-independent by construction and are likewise
unaffected.

## Known limits, stated rather than implied

- **Tampering detection at replay time is comparison-based only, not an
  inline oracle.** Unlike `tau3_retail` (whose `step()` independently
  re-executes and cross-checks every recorded tool call against the
  upstream bridge during replay itself), `replay_episode` here has no
  second oracle to compare a recorded bid against — it faithfully replays
  whatever the record says and settles it exactly like a live run would.
  A tampered recorded bid is only caught by explicitly calling
  `compare_episode_results(original, replayed)` against the original run;
  `replay_episode` alone succeeds and produces a different, but internally
  consistent, outcome. Verified directly:
  `test_replay_detects_a_tampered_bid_only_via_comparison_against_the_original`.
- **Resolved by this migration (commit `286fd246`, "feat(alympics): migrate
  to the FamilyScoringInput scoring contract"): the finalize-time seam no
  longer needs a caller-supplied baseline episode at all.** Before this
  migration, the only production-reachable path
  (`replay.score_replayed_episode`) required the caller to already have run
  and replayed a second, baseline episode. `AlympicsWacScorer.__call__` —
  the seam `task.evaluation.finalize_family_execution` actually calls now —
  calls `_recompute_baseline_episode` directly instead and never depends on
  a second, separately run episode, closing the migration plan's own
  "plumbing note" (docs/alympics_migration_plan.md, "Today's declared
  leaves" section). This is no longer listed as a known limit of the
  production scoring path. For the record, not as a limitation:
  `replay.py`'s own `score_replayed_episode` helper (used only by this
  family's unit tests in isolation, not by production scoring) keeps its
  pre-migration calling convention unchanged, still requiring a
  caller-supplied baseline. Both paths — old and new — already
  independently recompute and reconcile that baseline before accepting it
  (docs/alympics_fix_verification.md finding 2): `AlympicsWacScorer.
  score_terminal_wealth`/`score_survival` reject a supplied baseline that
  does not match `_recompute_baseline_episode` exactly, seat by seat, so a
  caller could never submit a fabricated `baseline_final_players`/
  `baseline_round_log` and have it accepted merely because its
  `baseline_policy_id` label matches. Only the bare
  `measurement.score_terminal_wealth`/`score_survival` functions (used
  directly by this family's own unit tests to isolate other gates, never by
  a production caller) check only the label.
- **A routine CI run does not, by itself, prove this family's
  upstream-fidelity tests ran.** Every environment/measurement/harness/
  parity/replay test module here skips, module-level, when the pinned
  upstream Alympics checkout is absent, and `.github/workflows/ci.yml` runs
  plain `pytest tests/ -q` with neither the checkout provisioned nor
  `AEREAD_ALYMPICS_UPSTREAM_REQUIRED` set (docs/alympics_fix_verification.md
  finding 9). Since this migration (commit `4e3bc842`, "test(alympics):
  enroll in the scoring-contract protocol test"),
  `tests/test_shared_runner_scoring_contract.py::test_alympics_wac_obeys_the_scoring_contract`
  skips the same way — a per-test skip carrying the identical
  "pinned upstream Alympics checkout not found" substring, deliberately
  deferred so it never propagates to that shared file's other-family
  coverage. `conftest.py`'s `pytest_terminal_summary` hook can turn any
  matching skip (this new one included, since it reuses the same substring
  rather than a separate `AEREAD_ALYMPICS_BRIDGE_REQUIRED` switch — a
  deliberate deviation from the govsim reference shape, recorded in commit
  `4e3bc842`'s own message) into a failed run, but only when
  `AEREAD_ALYMPICS_UPSTREAM_REQUIRED` is explicitly set — off by default,
  mirroring the project's own existing tau2/tau3 convention, and left that
  way deliberately: wiring it into default CI would mean provisioning a
  third-party checkout over the network, which this family's own
  provider-free/no-network posture rules out. A green default CI run
  therefore certifies only that `test_alympics_wac_cases.py`'s
  upstream-free tests ran, plus whichever of `test_shared_runner_scoring_contract.py`'s
  other-family tests do not need this bridge; certifying the rest requires
  explicitly setting `AEREAD_ALYMPICS_UPSTREAM_REQUIRED=1` (locally, or in a
  dedicated CI job that does provision the checkout) — the same posture
  tau2/tau3 already have, not a new inconsistency introduced here.
- **Milestone 3 exercises 2 of the 7 grid cells end-to-end**
  (`reference_baseline`, `mixed_policies_a`, plus one derived baseline
  variant of each) — the same pilot-scope posture as tau3's 18-task pilot
  and negarena's 6 scenarios, not a claim of full 7-cell coverage.
- **No provider or model call anywhere in this milestone.** Every "full
  episode" claim is against scripted policies; per P01's audit verdict
  (`docs/research/problem_bound_case_audit.md`) the family stays `baseline_only` —
  none of this demonstrates anything about live agent behavior or a
  solved policy optimum.
- **Kernel exception-wrapping (ledgered, generic, not alympics-specific):**
  the scheduler wraps any `response_source` exception raised mid-episode
  into `SchedulerContractError`, so `replay.ReplayError` only surfaces
  directly for pre-flight checks (e.g. case-id mismatch, checked before
  `run_episode` is ever called); an exhaustion/ordering error raised from
  inside a live scheduler turn surfaces as `SchedulerContractError` instead
  (the original type is still recoverable via `.__cause__`). See
  the cross-agent ledger at `econ benchmark/ledger_entries/alympics.md`
  (outside this repo) for the full write-up; this is core kernel
  behavior and was not changed here.

## Scoring contract migration (`zeyu/alympics-contract-migration`)

### Leaf policy

`family_manifest()` (`environment.py`) declares all four leaves
`scope="finalize_time"`: every leaf in `measurement.py` is
`evaluation_class="deterministic"` with no judge/rater/deferred-artifact
dependency (module docstring: "this family declares no rater/judge
component at all"), so none is `deferred`.

- **`alympics_wac_terminal_wealth_leaf` is primary.** Three independent
  sources already agreed before this migration (`measurement.py`'s module
  docstring, `docs/alympics_adapter_spec.md` section 2, and the manifest's
  own pre-existing `measurement.primary_estimand` field) — this is not "the
  one that was easiest to compute" (leaf 3, a single recorded-flag lookup,
  is materially simpler and is not primary). See
  `docs/alympics_migration_plan.md`'s "Proposed primary" section for the
  full argument.
- **`alympics_wac_bid_legality_leaf` and `alympics_wac_settlement_exactness_leaf`
  join it in admission.** Unlike a strategic-tradeoff rule-constraint leaf,
  both are measurement-integrity checks, not normative judgments about
  strategy: bid legality catches upstream's own silent bid-exceeds-balance
  exclusion "masquerading as an ordinary legal loss" (spec section 4 golden
  3), and settlement exactness catches a sealed `round_log` entry whose
  recorded post-state cannot be reproduced from its recorded pre-state and
  bids. Both already gate leaves 1/2 *internally* (`score_terminal_wealth`/
  `score_survival` call the same `_bid_legality_invalid_reason` helper), so
  admission membership is largely confirmatory for bid legality, but
  genuinely load-bearing for settlement exactness — a distinct failure mode
  not otherwise mirrored in leaf 1/2's own status.
- **`alympics_wac_survival_leaf` is diagnostic, not in admission** — matching
  its own declared status ("reported *separately* from wealth so a
  degenerate zero-information elimination is never averaged into wealth as
  if it were an ordinary loss").
- **`trajectory_outcome_paths = ("/eliminated_order",)`** (ruling R9):
  `outcome()` embeds this one trajectory-bearing field — an accumulated,
  per-round record of *when* each seat died, not a final aggregate (unlike
  `final_round_id`/`final_players`, both non-declared for the same reason
  govsim's own `num_round`/`resource_in_pool` are). See
  `docs/alympics_migration_plan.md`'s "Does `outcome()` embed the
  trajectory?" section for the full argument.
- **No leaf is deferred.**
- **Leaves 1-3 declare `seat_scope="subject_seat"`; leaf 4 stays the
  default `seat_scope="cell"`** (ruling R12, adopted post-R12 — see "The
  seat-context rule" below). No leaf declares `subject_reduction`: this
  family's cluster mapping is one focal seat per trial (spec section 2),
  never several subject seats scored together, so a self-play plan (more
  than one subject seat) is reported `ambiguous_subject_seat`, never
  silently averaged.

### The seat-context rule (replaces the former fixed-focal-seat convention)

`AlympicsWacScorer.__call__` resolves its focal seat per call from
`scoring_input.seat_context.subject_seats` (ruling R12), never from a
fixed module constant. `_resolve_focal_seat` (`measurement.py`) applies
ruling R12 rule 2's cases to leaves 1-3 (terminal wealth, survival, bid
legality): exactly one subject seat in `SEAT_ORDER` resolves it; zero
subject seats reports `invalid_measurement("no_subject_seat")`; two or
more reports `invalid_measurement("ambiguous_subject_seat")` (this family
declares no `subject_reduction`); exactly one subject seat outside
`SEAT_ORDER` reports `invalid_measurement("unknown_subject_seat")`. Leaf 4
(`alympics_wac_settlement_exactness_leaf`) is whole-round and needs no
focal seat at all — it is scored identically regardless of how seat-context
resolution went.

Each per-seat leaf's `ok` envelope carries the focal seat's own value in
`utility_by_seat` (key: the focal seat) with `primary` equal to it — the
kernel's own `_enforce_subject_seat_primaries` enforces that identity at
finalize time. Leaf 3 (bid legality) additionally carries every OTHER
participating seat's own legality gate in `utility_by_seat`, computed for
free from the same already-recorded `round_log` (`_bid_legality_utility_by_seat`);
leaves 1/2 (terminal wealth, survival) carry only the focal seat, since
reporting another seat's own baseline-relative delta would need a
SEPARATE baseline recompute for that seat — not cheap, and not this
leaf's declared comparison for that seat.

Leaves 1/2's reference identity (`source_sha256`/`reference_id`, via
`_opponent_panel_sha256`) **does** depend on which seat is later resolved
as the subject: `AlympicsWacScorer.leaves_for_focal_seat` builds it from
`panel_policy_ids(focal_seat)` — every OTHER seat's own declared policy —
because the baseline these leaves compare against is the SAME case
recomputed with `focal_seat`'s OWN policy replaced by
`baseline_policy_id`; a different focal seat is genuinely a different
comparison, even for an identical panel. Every OTHER field of the leaf's
`MeasurementLeafSpec` — estimand, verifier, the rest of the reference,
scorer ref — stays fixed regardless of focal seat. This is exactly what
the scoring-contract protocol test's cross-fixture "leaf's declared
identity must be stable" check, reconciled with ruling R12
(`docs/kernel_r12_seat_context.md`), permits: a `seat_scope=
"subject_seat"` leaf may instantiate its reference's own identity per
subject seat, never any invariant field. See "Reference-provenance
finding (second review pass)" below for why this paragraph once said the
opposite, and "Protocol-test fixtures" below for the fixture pair that
exercises it.

This replaces the former fixed convention (`measurement.FOCAL_SEAT =
SEAT_ORDER[0]`, i.e. always `"alex"` regardless of which seat a plan
actually tested) — the invented-evaluated-subject defect independent
review Finding 1 confirmed; see that finding's "Post-R12 note" in
`docs/alympics_migration_review.md` for the resolution record.

### Reference-provenance finding (second review pass)

A second, independent review pass found that the paragraph above used to
have it backwards: an earlier version of this migration made
`_opponent_panel_sha256` deliberately DROP `focal_seat` from its hash
payload, so leaves 1/2 would hash identically regardless of which seat
became the subject — purely to satisfy a gap in the kernel's own
leaf-identity stability check (PR #103, `kernel_contract_gap_review.md`
finding 7), which predates ruling R12 and had no notion of a per-seat
leaf. That made two MATERIALLY DIFFERENT baselines — the SAME case
recomputed with a DIFFERENT seat's policy replaced — collide on one
`source_sha256`: false provenance, not a cosmetic gap. The workaround's
own docstring said exactly this was why `focal_seat` was dropped.

**Fixed on both branches.** `zeyu/kernel-r12-seat-context` (PR #109)
reconciles the kernel's stability check with ruling R12: a `seat_scope=
"subject_seat"` leaf may now instantiate its `ReferenceSpec`'s own
identity — `reference_id`/`source_sha256` only — per subject seat, while
every invariant field stays fixed, and two fixtures sharing the SAME
subject seat must still be byte-identical (see
`docs/kernel_r12_seat_context.md`). This branch, rebased onto that fix,
reverts the workaround: `_opponent_panel_sha256` takes `focal_seat` again
and includes it in its hash payload; `leaves_for_focal_seat` again passes
`panel_policy_ids(focal_seat)`, not the case's full assignment; the
now-dead `full_policy_assignment` helper is removed. Every other
improvement the R12 migration made (the seat-context focal resolution,
the typed invalid reasons, `utility_by_seat`, the `different_focal_seat`
fixture below) is unchanged.

**A related, narrower, PRE-EXISTING limit, also raised by this review
pass and left as a stated limit rather than silently fixed (confirmed
against `zeyu/kernel-r12-seat-context`'s copy of this file, which predates
this migration branch entirely and already had the same shape):**
`_opponent_panel_sha256`'s payload is `{focal_seat, panel_policy_ids,
baseline_policy_id}` only — it does not cover `seat_order`, `personas`,
`supply_schedule`, or `grid_cell["rounds"]`, all of which
`_recompute_baseline_episode` also reads to determine the actual baseline
trajectory. Two DIFFERENT cases that happen to share the same
`(focal_seat, panel_policy_ids, baseline_policy_id)` tuple but differ in
one of those four fields would produce the SAME `source_sha256` despite
recomputing a genuinely different baseline. In practice this is not a
live provenance hole: `EvaluationReceipt.case_id`/`case_sha256` (kernel
fields on the enclosing receipt, never derived from the leaf's own
`source_sha256`) already disambiguate any two receipts a real consumer
would compare — the collision is confined to the bare leaf reference's
own self-described identity, in isolation from the receipt that carries
it, which nothing in this family or the kernel relies on as a
cross-case identity key today. Left unfixed here, as a stated limit, not
a defect this pass is chartered to fix.

**Tests** (`tests/test_alympics_wac_measurement.py`), three:

- `test_leaves_for_focal_seat_reference_identity_depends_on_the_focal_seat`
  (replaces the previous, now-incorrect `test_leaves_for_focal_seat_
  identity_does_not_depend_on_which_seat_is_focal`): for one case, leaves
  1/2 built for two DIFFERENT focal seats differ in `source_sha256` and
  agree on every invariant field; leaves 3/4 stay byte-identical
  regardless of focal seat; the SAME focal seat called twice is
  byte-identical.
- `test_focal_seat_is_part_of_the_leaf_1_2_reference_identity_even_for_an_
  identical_panel`: calls `build_terminal_wealth_leaf`/`build_survival_
  leaf` directly with the IDENTICAL `panel_policy_ids` dict for two
  DIFFERENT `focal_seat` values, isolating `_opponent_panel_sha256`'s own
  `focal_seat` parameter from `leaves_for_focal_seat`'s separate choice of
  which panel to pass (see next test) — otherwise `panel_policy_ids
  (focal_seat)`'s own key set, which already differs by focal seat for
  any case with more than one seat, would mask a regression in
  `_opponent_panel_sha256` itself.
- `test_leaves_for_focal_seat_builds_leaf_1_2_identity_from_the_opponent_
  panel_not_the_full_assignment`: asserts `leaves_for_focal_seat`'s output
  EQUALS `build_terminal_wealth_leaf`/`build_survival_leaf` called
  directly with `panel_policy_ids(focal_seat)` — checked by equality, not
  a hash inequality across focal seats, since `_opponent_panel_sha256`'s
  own `focal_seat` parameter would make two leaves differ by focal seat
  regardless of what panel `leaves_for_focal_seat` feeds in, masking a
  regression in THIS half of the fix if checked by inequality alone.

**Mutation** (two independent mutations, each isolating one half of the
fix, `/tmp` copy, restored):

- Dropping `focal_seat` from `_opponent_panel_sha256`'s payload again (but
  leaving `leaves_for_focal_seat` correct) makes
  `test_focal_seat_is_part_of_the_leaf_1_2_reference_identity_even_for_an_
  identical_panel` fail on its `source_sha256 != ` assertion — and
  correctly does NOT fail `test_leaves_for_focal_seat_reference_identity_
  depends_on_the_focal_seat`, confirming that broader test alone would
  have missed this specific regression (`panel_policy_ids(focal_seat)`'s
  own key set already differs by focal seat, independent of whether
  `_opponent_panel_sha256` also embeds it).
- Reverting `leaves_for_focal_seat` to pass the case's full policy
  assignment again (but leaving `_opponent_panel_sha256` correct) makes
  `test_leaves_for_focal_seat_builds_leaf_1_2_identity_from_the_opponent_
  panel_not_the_full_assignment` fail on the equality assertion — and
  correctly does NOT fail either of the other two tests, confirming
  `_opponent_panel_sha256`'s own `focal_seat` parameter alone would have
  masked this regression from a hash-inequality check.

Full record: `docs/alympics_migration_review.md`'s "Second review pass:
reference-provenance finding" section (appended, not merged into that
document's own first-pass disposition/summary).

### Receipt

`tests/test_alympics_wac_replay.py::test_finalize_wires_alympics_wac_to_the_shared_family_finalizer`
drives one small, real, upstream-backed clean episode (every seat bids a
fixed, always-legal `1` every round; nobody is ever eliminated) through
`task.evaluation.finalize_family_execution` for the first time this family
has ever produced an `EvaluationReceipt`. `build_alympics_setup`'s resolved
plan declares an `EvaluationBlock` with `kind="controlled"` naming exactly
one subject seat (`focal_seat="alex"`, an arbitrary choice among an
all-legal episode's five seats) — `finalize_family_execution`'s own
`_seat_context_for_cell` reads that into `scoring_input.seat_context`,
which `AlympicsWacScorer.__call__` resolves to that one seat. The receipt
comes back with `status="ok"`, `inclusion_status="included"`, exactly the
four declared leaf ids, and
`primary_leaf_id="alympics_wac_terminal_wealth_leaf"`.

### Protocol-test fixtures (paired history + sensitivity witness)

`tests/test_shared_runner_scoring_contract.py::test_alympics_wac_obeys_the_scoring_contract`
(kept out of the always-on
`test_every_registered_family_obeys_the_scoring_contract` — see
`_BRIDGE_GATED_ENROLLED_FAMILY_VERSIONS`'s own docstring for why: this
family's fixtures need the pinned upstream Alympics checkout, which every
other family that test verifies deliberately does not) drives three real
episodes on one small, shared case (six rounds, constant supply 100), then
reuses two of those SAME sealed episodes under a different declared
`subject_seats` (ruling R12) for two additional fixtures — five fixtures
total, three real episodes:

- **`left`/`right` — the paired-history pair.** `alex`/`bob`/`cindy` bid a
  fixed, always-legal `1` every round in both; `david` and `eric` each
  follow one of two hand-derived bid sequences that reach the identical
  terminal state — `hp=0, no_drink=5, balance=480, alive=False` — at two
  different round counts:
  - **short (5 rounds):** win round 1 (bid `120`, exactly the daily
    salary — legal, since `bid <= balance` holds with equality), then bid
    illegally (`10**9`, exceeding balance) rounds 2–5. Arithmetic: round 1
    win takes `hp: 8 → min(10, 10) = 10`, `no_drink → 1`, `balance:
    120 − 120 = 0`; rounds 2–5 each add one salary payment (`+120`) then
    lose (`hp -= no_drink; no_drink += 1`): `hp: 10→9→7→4→0`,
    `no_drink: 2→3→4→5`, ending `balance = 480` (four salary payments, no
    further bid cost) at `hp=0` — eliminated.
  - **long (6 rounds):** win rounds 1–2 (bids `120` then `120` — the
    second win's bid exactly cancels the extra round's salary: balance
    after round 2's win is `(120 − 120) + 120 − 120 = 0`, i.e. two salary
    payments minus two winning bids of `120` each), then bid illegally
    rounds 3–6. `hp` after both wins stays capped at `10` (`min(10, 10+2)`
    on the second win), `no_drink` resets to `1` each win; rounds 3–6 lose
    identically to the short sequence's rounds 2–5 (`hp: 10→9→7→4→0`,
    `no_drink: 2→3→4→5`), ending `balance = 720 − 120 − 120 = 480` (six
    salary payments minus the two winning bids) at `hp=0` — eliminated one
    round later than `short`.

  Swapping which of `david`/`eric` gets `short` vs `long` between `left`
  and `right` swaps their relative death order — `eliminated_order` is
  `["david", "eric"]` in `left` and `["eric", "david"]` in `right` — while
  `termination_reason="rounds_exhausted"`, `final_round_id=6`, and every
  seat's `final_players` entry (including `david`'s and `eric`'s own,
  since both sequences reach the identical terminal values) stay
  byte-identical: exactly the projected-outcome-identical,
  trajectory-differing pair ruling R9 requires. **Verified directly
  against the real pinned upstream checkout** (`_delegate_round`, driven
  by a standalone script reproducing this exact schedule) before being
  wired into the test file, per the worked example's warning against
  trusting an unconfirmed pair.
- **`alt` — the sensitivity witness (ruling R9(b)).** None of the four
  leaves changes between `left` and `right` alone, because `alex`'s own
  row (`left`/`right`/`alt` all declare `subject_seats=("alex",)`) is
  identical in `left`/`right`. `alt` (same case) has every seat, including
  `alex`, bid illegally (`10**9`) every round: `alex`'s own `bid_legality`
  invalid reason fires from round 1, flipping
  `terminal_wealth`/`survival`/`bid_legality` (all three gated by the same
  `_bid_legality_invalid_reason` check) to `invalid_measurement`; all five
  seats reach `hp=-2, no_drink=5` simultaneously at round 4
  (`all_seats_eliminated`), giving `settlement_exactness` a different
  `rounds_checked` metric (`4.0` vs `6.0` on `left`/`right`) even though
  its own `status` stays `"ok"`. This is what witnesses all four leaves'
  sensitivity — none of them changes on `left`/`right` alone.
- **`different_focal_seat` — ruling R12's subject-dependence witness.**
  Reuses `left`'s own sealed evidence (same case, same trajectory) with
  `subject_seats=("bob",)` instead of `("alex",)`. `bob` bids the same
  fixed, always-legal `1` every round as `alex` in `left` (neither is on
  the short/long-death schedule), so both resolve `"ok"` — but their
  personas' differing requirement/salary still make their terminal wealth
  genuinely different (hand-verified against the real upstream checkout:
  `alex` `138.0`, `bob` `156.0`). Proves the per-seat leaves depend on
  which seat `seat_context` names, never a fixed convention. (`david`/
  `eric` — the short/long-death seats — are deliberately not used here:
  their own oversized bids are independently illegal, which would gate
  their leaves to `invalid_measurement` for an unrelated reason.)
- **`ambiguous_subject_seats` — the honest `ambiguous_subject_seat` path.**
  Reuses `alt`'s own sealed evidence with TWO subject seats
  (`"alex", "bob"`) declared. This family declares no `subject_reduction`
  (its cluster mapping is one focal seat per trial), so
  `terminal_wealth`/`survival`/`bid_legality` all report
  `invalid_measurement("ambiguous_subject_seat")` — never a silently
  averaged self-play claim — while `settlement_exactness` stays `"ok"`
  (whole-round, unaffected by seat-context resolution).

Full protocol-test file: 38 passed with the checkout present; 37 passed, 1
skipped without it (every other family's own always-on coverage in that
file is unaffected either way — verified directly, see the mutation note
below).

### On ruling R11 (verbatim conformance note): does not apply here

Ruling R11 requires a family with **no upstream code** (collusion,
termsbench) to state that its conformance goldens are independently
hand-derived from the paper, not parity with upstream code. That premise
does not hold for this family: `environment.py` imports and runs the real,
pinned, unmodified `microsoft/Alympics` checkout directly (`_delegate_round`
calls upstream's own `_get_salary`/`_check_winner`/`_round_settlement`
verbatim), and this family's own goldens (spec section 4, `parity.py`) are
already checked for parity against that real upstream code, not against an
independent paper derivation. Stating R11's verbatim sentence here would
misrepresent this family as having no upstream implementation when it has
one; it is deliberately not stated.

### Mutation-test evidence

Verified directly (temporary edit, run, restore — never committed):

- Emptying `_BRIDGE_GATED_ENROLLED_FAMILY_VERSIONS` reproduces ruling R6's
  closure failure exactly:
  `AssertionError: trusted plugin key(s) [('alympics.wac', '0.1.0')] are
  neither enrolled in this test's FAMILY_SCORING_FIXTURES nor named in
  _NOT_YET_MIGRATED_TRUSTED_KEYS`.
- Dropping the `alt` fixture from `_alympics_kernel_contract_fixtures`'s
  returned tuple (leaving only `left`/`right`) reproduces the R9(b)
  sensitivity-witness failure, naming all four leaf ids:
  `AssertionError: alympics.wac: trajectory-scoped leaf(ves)
  ['alympics_wac_bid_legality_leaf', 'alympics_wac_settlement_exactness_leaf',
  'alympics_wac_survival_leaf', 'alympics_wac_terminal_wealth_leaf'] never
  changed across any of the 1 same-case pair(s) examined among the 2
  supplied fixtures`.
- Dropping `settlement_exactness` from `AlympicsWacScorer.__call__`'s
  returned `FamilyScoreSet.scores` (leaving it in `admission_leaf_ids`)
  fails both `test_finalize_wires_alympics_wac_to_the_shared_family_finalizer`
  and `test_alympics_wac_obeys_the_scoring_contract` with
  `MeasurementContractError: admission leaves are absent from the family
  score set: alympics_wac_settlement_exactness_leaf`.

### Independent review

An independent, diff-only, read-only review of this migration was
performed and recorded, with this branch's own re-verification against the
code, in `docs/alympics_migration_review.md` (committed as `b97bd9de`,
"docs(alympics): record independent review dispositions with mutation
evidence"). It raised three findings:

- **Finding 1 (High — this family's `alex`-as-evaluated-subject
  convention): confirmed, escalated to the owner, RESOLVED post-R12.** The
  review recorded two remediation options (extend `family_case`/grid-cell
  schema with a `focal_seat` field, or wire ruling R12's `SeatContext`
  through). The owner's ruling adopted the second: `AlympicsWacScorer.
  __call__` now resolves its focal seat per call from
  `scoring_input.seat_context.subject_seats`, replacing
  `measurement.FOCAL_SEAT = SEAT_ORDER[0]` entirely. See "The seat-context
  rule" above for what changed, and that finding's own "Post-R12 note" in
  `docs/alympics_migration_review.md` for the resolution record (the
  original finding text is left unchanged there, per that document's own
  policy of recording findings, not rewriting them).
- **Finding 2 (Medium — score provenance caller-controlled via
  `evidence_refs`): refuted.** `AlympicsWacScorer.__call__`'s
  `evidence_refs`-threading signature matches the contract's mandated
  shape verbatim (kernel_scoring_contract_spec.md section 2) and the
  reference migration's identical pattern; more directly, a mutation check
  recorded in that file — forging `__call__`'s `terminal_wealth` call to a
  fixed, unrelated `evidence_refs` value — was run and restored, and it
  failed both `test_alympics_wac_obeys_the_scoring_contract` (assertion)
  and, independently, the **production** finalizer itself
  (`task/evaluation.py`'s `_check_evidence_refs_are_scoring_input_verbatim`
  raised `ValueError` before a receipt could be sealed).
- **Finding 3 (High — trusted-catalog closure passing while this family's
  only protocol test skips): refuted.** Confirmed as the deliberate,
  already-precedented tau2/tau3/govsim mitigation shape, not a gap
  introduced here; verified directly that
  `AEREAD_ALYMPICS_UPSTREAM_REQUIRED=1` converts the described
  pass-while-skipping scenario into a hard failure (exit code 1) — the
  certifying-run protocol this migration operates under.

Disposition tally (as this migration originally landed): 1 confirmed and
escalated, 2 refuted, 0 fixed (neither refuted finding described an actual
defect in this branch's code). Finding 1 has since been resolved by
adopting ruling R12, above. A SECOND, later review pass raised one further
finding against the R12 adoption itself (the reference-provenance
workaround) — see "Reference-provenance finding (second review pass)"
above and `docs/alympics_migration_review.md`'s own second-pass section
for the full record; that document's first-pass findings/disposition/
summary above are unedited.

## Open questions for the kernel/spec owner

**Resolved.** The former focal-seat convention (`measurement.FOCAL_SEAT`)
was a genuine gap between ruling R12's stated premise for this family and
this branch's actual `family_case` schema, escalated here and in
independent review Finding 1 (`docs/alympics_migration_review.md`) for the
owner to choose between two remediation options. The owner adopted ruling
R12's `SeatContext` machinery (see "The seat-context rule" above); this is
no longer an open question.

The two open items already on record before this migration
(`docs/benchmark_qc.md` unmerged to `main`; `observe()`'s balance-credit
lag) are unchanged and are tracked in the cross-agent ledger at
`econ benchmark/ledger_entries/alympics.md` (outside this repo), not
repeated here.
