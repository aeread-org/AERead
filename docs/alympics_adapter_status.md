# alympics.wac adapter — status

Branch `zeyu/alympics-adapter`. Last verified 2026-09-02. Milestone 3 of 3
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
grew independently of this migration — this branch's only test-file
change is `tests/test_alympics_wac_replay.py`, `git diff --stat
zeyu/kernel-r9r10..HEAD` confirms); corrected here rather than carried
forward unchecked, and `tests/test_shared_runner_scoring_contract.py` is
now added to the reproduce command below, since this migration enrolled
this family in it (see "Protocol-test fixtures" above) and it is
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
PYTHONPATH=src ../../.venv/bin/python -m pytest \
  tests/test_alympics_wac_cases.py \
  tests/test_alympics_wac_environment.py \
  tests/test_alympics_wac_harness.py \
  tests/test_alympics_wac_measurement.py \
  tests/test_alympics_wac_parity.py \
  tests/test_alympics_wac_replay.py \
  tests/test_shared_runner_scoring_contract.py \
  tests/test_shared_runner_smoke.py -q
```

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
  (`docs/problem_bound_case_audit.md`) the family stays `baseline_only` —
  none of this demonstrates anything about live agent behavior or a
  solved policy optimum.
- **Kernel exception-wrapping (ledgered, generic, not alympics-specific):**
  the scheduler wraps any `response_source` exception raised mid-episode
  into `SchedulerContractError`, so `replay.ReplayError` only surfaces
  directly for pre-flight checks (e.g. case-id mismatch, checked before
  `run_episode` is ever called); an exhaustion/ordering error raised from
  inside a live scheduler turn surfaces as `SchedulerContractError` instead
  (the original type is still recoverable via `.__cause__`). See
  `ledger_entries/alympics.md` for the full write-up; this is core kernel
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

### The focal-seat convention (a stated limit, not an invented one)

Ruling R12 (kernel_scoring_contract_spec.md) says families whose case
names the tested seat "ignore seat context" and are unaffected by that
ruling's per-seat-primary machinery. On this branch, that premise does not
hold: `family_case` (the validated `payload`) does **not** carry a
`focal_seat` field — every existing caller (this family's own unit tests,
`replay.score_replayed_episode`) passes `focal_seat` in explicitly, and
spec section 2's "one seat rotates as focal across paired trials" is a
cross-trial *authoring* convention, never something a single case encodes.
`AlympicsWacScorer.__call__` — the seam the finalizer calls, with no
external `focal_seat` parameter reachable from `FamilyScoringInput` alone
— therefore fixes one declared, deterministic convention:
`measurement.FOCAL_SEAT = SEAT_ORDER[0]` (`"alex"`), matching every
existing test's own default focal seat. This is stated here, not invented
silently: a future extension that lets a case (or an `EvaluationBlock`)
name a rotating focal seat per trial would change only this one constant's
resolution, not the four leaves' own scoring logic.

### Receipt

`tests/test_alympics_wac_replay.py::test_finalize_wires_alympics_wac_to_the_shared_family_finalizer`
drives one small, real, upstream-backed clean episode (every seat bids a
fixed, always-legal `1` every round; nobody is ever eliminated) through
`task.evaluation.finalize_family_execution` for the first time this family
has ever produced an `EvaluationReceipt`. The receipt comes back with
`status="ok"`, `inclusion_status="included"`, exactly the four declared
leaf ids, and `primary_leaf_id="alympics_wac_terminal_wealth_leaf"`.

### Protocol-test fixtures (paired history + sensitivity witness)

`tests/test_shared_runner_scoring_contract.py::test_alympics_wac_obeys_the_scoring_contract`
(kept out of the always-on
`test_every_registered_family_obeys_the_scoring_contract` — see
`_BRIDGE_GATED_ENROLLED_FAMILY_VERSIONS`'s own docstring for why: this
family's fixtures need the pinned upstream Alympics checkout, which every
other family that test verifies deliberately does not) drives three real
episodes on one small, shared case (six rounds, constant supply 100):

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
  row (the focal seat every leaf actually measures) is identical in both.
  `alt` (same case) has every seat, including `alex`, bid illegally
  (`10**9`) every round: `alex`'s own `bid_legality` invalid reason fires
  from round 1, flipping `terminal_wealth`/`survival`/`bid_legality` (all
  three gated by the same `_bid_legality_invalid_reason` check) to
  `invalid_measurement`; all five seats reach `hp=-2, no_drink=5`
  simultaneously at round 4 (`all_seats_eliminated`), giving
  `settlement_exactness` a different `rounds_checked` metric (`4.0` vs
  `6.0` on `left`/`right`) even though its own `status` stays `"ok"`. This
  is what witnesses all four leaves' sensitivity — none of them changes on
  `left`/`right` alone.

Full protocol-test file: 32 passed with the checkout present; 31 passed, 1
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
  convention): confirmed, escalated to the owner.** This is the same
  `measurement.FOCAL_SEAT` gap the "Open questions" section below already
  states as a limit — the review independently confirmed it from the code
  and recorded two remediation options (extend `family_case`/grid-cell
  schema with a `focal_seat` field, or wire ruling R12's `SeatContext`
  through), neither of which this migration implements, since either would
  redefine the primary estimand's inputs rather than merely its plumbing.
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

Disposition tally: 1 confirmed and escalated, 2 refuted, 0 fixed (neither
refuted finding described an actual defect in this branch's code).

## Open questions for the kernel/spec owner

The focal-seat convention above (`measurement.FOCAL_SEAT`) is a genuine
gap between ruling R12's stated premise for this family and this branch's
actual `family_case` schema — flagged for the spec owner to confirm
whether `family_case` should eventually carry a `focal_seat` field (or
whether R12's own per-seat machinery, once a kernel `SeatContext` lands,
should cover this family after all). Not blocking: the fixed convention
above is stated, deterministic, and matches every existing test's own
default. This is the same gap independent review Finding 1 above confirmed
and escalated (`docs/alympics_migration_review.md`); it is recorded here
and there under one disposition, not two independent open items.

The two open items already on record before this migration
(`docs/benchmark_qc.md` unmerged to `main`; `observe()`'s balance-credit
lag) are unchanged and are tracked in `ledger_entries/alympics.md`, not
repeated here.
