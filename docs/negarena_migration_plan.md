# negarena migration plan (kernel_scoring_contract_spec.md)

Milestone 0 output. Shape to follow is the reference migration (worktree
`.../AERead/.worktrees/govsim-migrate`, `docs/govsim_migration_plan.md`), read
in full before writing this plan. The second reference
(`.../AERead/.worktrees/collusion-migrate`) is read for the R9/R10
(trajectory-embedded-in-outcome) case, which does not apply here (see below).

**This revision supersedes the plan committed at `d7c6e955`.** That commit
misidentified the branch's base as `zeyu/kernel-r9r10`; `git merge-base` shows
the actual base is `zeyu/kernel-r12-seat-context` (whose own history includes
the R12 ruling this document analyzes below). Re-checking every precondition
against the real base surfaced a second, real baseline defect that the stale
`execution.py` path fix had been masking — see "Baseline: not clean, in two
layers" below —
so this milestone ends in a **STOP**, not a green baseline. No family code
(`environment.py`/`measurement.py`/`replay.py`) was changed; the only code
change in this milestone is the one authorized mechanical import-path fix
(commit `dd69c703`).

## Preconditions confirmed on this base (`git fetch origin`, then checked directly)

- `git fetch origin` ran clean. Branch `zeyu/negarena-contract-migration` is
  on top of `zeyu/kernel-r12-seat-context`
  (`git merge-base HEAD zeyu/kernel-r12-seat-context` ==
  `git rev-parse zeyu/kernel-r12-seat-context` == `cda0a736...`); the two
  commits ahead of that base before this milestone
  (`git log --oneline zeyu/kernel-r12-seat-context..HEAD`) are the prior
  (superseded) milestone-0 doc commit and this revision's own commits.
- `FamilyScoringInput` exists in `src/aeread/shared_runner/task/evaluation.py`
  (class at line 561); `LeafPolicyDeclaration` exists in
  `src/aeread/shared_runner/schemas.py` (class at line 347), alongside
  `seat_scope`/`subject_reduction` fields (ruling R12, added to this same
  class — see below).
- `('negarena', '0.1.0', 'negarena_environment')` is in
  `TRUSTED_BUILTIN_PLUGIN_KEYS` (`src/aeread/shared_runner/registry.py:76`),
  and `("negarena", "0.1.0")` is in `_NOT_YET_MIGRATED_TRUSTED_KEYS`
  (`tests/test_shared_runner_scoring_contract.py:1906`).
  `environment.py::register_plugin` already calls
  `registry.register_trusted(family_manifest(), plugin)`, so this family is
  not exposed to the worked example's trap 1 (registration silently breaking
  after rebase) — it was already carried this way before this branch forked.
- `grep -c trajectory_outcome_paths src/aeread/shared_runner/schemas.py` is
  **11** (nonzero) — the field exists on this base. `NegarenaPlugin.outcome()`
  (`environment.py:494-503`) returns only `{termination_reason,
  iteration_count, last_answer, last_trade}` — a terminal summary, never
  `state["history"]`. Rulings R9/R10 (a family whose outcome embeds its
  trajectory) therefore do not apply to this family; see "Rulings that do not
  apply here" below.
- `grep -c seat_context src/aeread/shared_runner/task/evaluation.py` is **30**
  (nonzero) — ruling R12's `SeatContext`/`_seat_context_for_cell`/
  `_enforce_subject_seat_primaries` machinery exists on this base. This
  matters directly: negarena's primary leaf is inherently per-seat (see the
  seat-scope classification below), and per the milestone's own instruction a
  per-seat leaf is not itself a reference gap when this machinery exists to
  carry seat identity to the scorer.

## Baseline: not clean, in two layers

### Layer 1 (fixed this milestone): stale `execution.py` path, spec section 5 item 1

Family test suite, bridge exported (`AEREAD_NEGARENA_UPSTREAM_ROOT`,
`AEREAD_NEGARENA_BRIDGE_PYTHON`), run *before* any code change:
`tests/test_negarena_environment.py`, `tests/test_negarena_cases.py`,
`tests/test_negarena_harness.py`, `tests/test_negarena_parity.py`,
`tests/test_negarena_measurement.py`, `tests/test_negarena_kernel_finalizer.py`,
`tests/test_negarena_provisioning.py`, `tests/test_shared_runner_smoke.py` —
**86 passed, 3 failed**, in ~284s. All three failures were in
`tests/test_negarena_kernel_finalizer.py`
(`test_finalize_family_execution_does_not_crash_and_seals_a_typed_receipt`,
`test_finalize_family_execution_seals_the_complete_evidence_lifecycle`,
`test_run_scripted_negarena_episode_seals_the_complete_lifecycle_automatically`),
and all three failed identically with `FileNotFoundError: ...
src/aeread/shared_runner/execution.py`. `_build_negarena_run_plan`
(`tests/test_negarena_kernel_finalizer.py:268-271`) hashed
`Path(__file__).parents[1] / "src" / "aeread" / "shared_runner" /
"execution.py"` to build an `ImplementationPin.sha256` — a path that predates
the kernel reorg this branch's base already carries (spec section 5 item 1:
`execution`/`scheduler`/`receipts`/`tools` -> `task.*`; the file now lives at
`src/aeread/shared_runner/task/execution.py`). The module's own *imports*
were already updated (`from aeread.shared_runner.task.execution import
CellExecution, EvidenceStore`, line 40); only this one hash-computation
literal was missed.

Per this milestone's own instruction, this is squarely spec section 5 item 1
and was fixed now, mechanically, in its own commit: `dd69c703 fix(negarena):
update stale execution.py path to task/execution.py`. No behavior changed
beyond pointing the hash at the file that actually exists.

### Layer 2 (not fixed — STOP): evidence-vocabulary mismatch, not an import issue

Re-running the identical suite after the fix: **87 passed, 2 failed**, in
~317s. The one test from layer 1 that never calls `finalize_family_execution`
(`test_run_scripted_negarena_episode_seals_the_complete_lifecycle_automatically`)
now passes. The two that do call it still fail, both with the same error:

```
ValueError: family replay action lacks one successful attempt
  at src/aeread/shared_runner/task/evaluation.py:384
```

This is a different, non-import defect, checked directly rather than assumed:
`task/evaluation.py`'s replay walk (`_replay_family_trajectory`, ~line
375-384) requires exactly one `action_attempt_succeeded` event per logical
action, and reads that event's payload for `"canonical_response"`. That event
type and payload shape match exactly what the kernel's real executor emits
(`task/execution.py:2685-2690`, `MinimalChatExecutor`:
`evidence.append_event("action_attempt_succeeded", {"canonical_response":
canonical}, ..., action_attempt_id=action_attempt_id, ...)` — it also tracks
per-attempt retries via `action_attempt_id`, which negarena's helper does not
model at all).

`aeread_families/negarena/harness.py`'s `record_full_evidence_lifecycle` —
the adapter's own hand-rolled stand-in for what the real executor would have
recorded live, used because negarena's `ScriptedNegarenaHarness` is a
`response_source`, not a `MinimalChatExecutor` — never emits an
`action_attempt_succeeded` event at all. It emits `logical_action_succeeded`
(when `envelope.valid`) or `logical_action_agent_action_failure`, each
carrying only `{"valid": ..., "failure_code": ...}` — no
`canonical_response`, no `action_attempt_id`. `grep -rln
"action_attempt_succeeded|logical_action_succeeded"
src/aeread_families/*/*.py` returns only `negarena/harness.py` — no other
already-migrated family package reimplements this event vocabulary by hand,
which is consistent with `record_full_evidence_lifecycle` (as a whole
function) appearing nowhere else in the repo either: other families exercise
the real `MinimalChatExecutor` directly rather than hand-simulating its
evidence trail. Negarena's own copy has drifted from the vocabulary the
kernel's replay path now requires.

**This is not spec section 5 item 1.** It is not a Python import or a
module-path literal; it is a mismatch in *evidence event types and payload
shape* between a hand-rolled helper this family package owns and what the
kernel's `finalize_family_execution` replay path currently expects — fixing
it correctly means deciding how (or whether) `ScriptedNegarenaHarness`/
`record_full_evidence_lifecycle` should model per-attempt retries the way the
real executor does, not a one-line rename. Per this milestone's own rule
("Any other baseline failure is a STOP"), this is reported, not fixed, here.

**Baseline after the one authorized fix: 87 passed, 2 failed, 0 skipped —
not clean. This milestone stops here rather than guess at the harness fix.**
The two failing tests are exactly the ones spec section 5 item 4 ("wire the
family to the finalizer") cares about — they are pre-existing tests already
written for that purpose (`docs/negarena_codex_triage.md` Findings 1/3), now
blocked again by a different defect than the one they were closed against
before. `docs/negarena_adapter_status.md`'s "89 of 89, last verified
2026-09-02" is stale for both reasons in sequence: it predates the path reorg
(layer 1) and, since it must have passed the `action_attempt_succeeded` check
at the time, it also predates whatever kernel-side change introduced or
tightened that requirement (layer 2) — the status doc's own claim is not
reproducible on this base until layer 2 is resolved.

```bash
export AEREAD_NEGARENA_UPSTREAM_ROOT="/Users/sunzeyu/Documents/econ benchmark/upstream-negarena"
export AEREAD_NEGARENA_BRIDGE_PYTHON="/Users/sunzeyu/Documents/econ benchmark/bridges/negarena-venv/bin/python"
PY=".../AERead/.venv/bin/python"
"$PY" -m pytest tests/test_negarena_environment.py tests/test_negarena_cases.py \
  tests/test_negarena_harness.py tests/test_negarena_parity.py \
  tests/test_negarena_measurement.py tests/test_negarena_kernel_finalizer.py \
  tests/test_negarena_provisioning.py tests/test_shared_runner_smoke.py -q
```

A minor, separate staleness noticed but **not** fixed (out of scope for the
one-line carve-out; does not fail any test): `harness.py`'s
`record_full_evidence_lifecycle` docstring names the shared kernel's executor
module as `aeread.shared_runner.execution` (prose only, not an import or a
hashed path) — the module is `aeread.shared_runner.task.execution` on this
base. Flagged for whoever fixes layer 2, since that fix will touch this same
function.

## Today's declared leaves and their `input_scope`

Both leaves are declared unconditionally for every case
(`measurement.py::build_leaves`); `family_manifest()`
(`environment.py::family_manifest`) does not yet declare
`leaves`/`primary_leaf_id`/`admission_leaf_ids` at all on this base — that is
exactly what the next milestone adds.

| Leaf id | Estimand id | `input_scope` (estimand / reference) | Verifier family | Evaluation class |
|---|---|---|---|---|
| `negarena_seat_outcome_leaf` | `negarena_seat_outcome` | `trajectory` / `trajectory` | `comparative` (`head_to_head`) | `deterministic` |
| `negarena_agreement_reached_leaf` | `negarena_agreement_reached` | `terminal_state` / `terminal_state` | `rule_constraint` (`constraint_satisfaction`) | `deterministic` |

No leaf has a judge/rater/rubric field anywhere in `measurement.py`; every
scorer is deterministic — either bridge-delegated settlement arithmetic
(leaf 1) or a pure predicate over `terminal["reason"]` (leaf 2).

## Reference-source classification

| Leaf | What the scorer needs for a `status="ok"` value | Classification | Why |
|---|---|---|---|
| `negarena_seat_outcome_leaf` | This episode's `state["history"][-2]` (the pre-accept proposed trade) and `terminal["reason"/"iteration_count"/"last_answer"]`, plus the validated `family_case.scenario`, fed through `NegarenaBridge.settle()` to reproduce upstream's own `after_game_ends()`. The "opponent" in `HEAD_TO_HEAD_REFERENCE_ID`'s `reference_kind="head_to_head"` is the *other seat in this same episode* (`result["player_outcome"][opponent_index]`, read off the same `bridge.settle()` call) — never a second, separately-run episode. | **replayed-episode** | Everything the scorer touches — history, terminal, family_case — comes from this one episode's own re-executed trajectory/outcome (`FamilyScoringInput.phase_instances`/`outcome`). No artifact from another run, and no rater/judge verdict, is needed by the estimand's own definition ("this seat's own realized value, against the specific opponent it was paired with," `measurement.py`'s module docstring). |
| `negarena_agreement_reached_leaf` | Only `terminal["reason"]` (this episode's own termination reason) — no bridge call, no settlement. | **replayed-episode** | A pure predicate over this episode's own terminal state; not derivable from `family_case` alone (the actual termination reason depends on how play unfolded), and needs no separate-run or judge artifact. |

Both leaves classify as **replayed-episode**, so both stay `scope="finalize_time"`
per the spec's rule. **Reference gap: none** — neither leaf's estimand, by its
own definition, requires a separate-run baseline or a judge verdict.

## Seat-scope classification (ruling R12)

`negarena_seat_outcome_leaf`'s estimand is inherently per seat: "what did
*this* seat realize under its own valuation" (`measurement.py`'s module
docstring, leaf 1) — one value for RED, a different one for BLUE, never a
summed/blended two-seat number. Under ruling R12 this is declared
`LeafPolicyDeclaration(..., seat_scope="subject_seat")`. Per the milestone's
own instruction, **this is not a reference gap** — R12 exists specifically so
the kernel, not the scorer, carries which seat is the tested subject
(`FamilyScoringInput.seat_context`, populated by `finalize_family_execution`/
`replay_family_receipt`/`audit_family_receipt` from the plan's
`EvaluationBlock.subject_seats` and the cell's `profile_by_seat` — never from
the live episode, so R2 still holds).

This resolves, rather than merely restates, the plumbing gap the prior
(superseded) revision of this document flagged as unresolved: that revision
worried `FamilyScoreSet`'s one-envelope-per-`leaf_id` invariant could not
carry both seats' values for one leaf. R12's actual design does not need two
envelopes: `negarena_seat_outcome_leaf` returns **one** `ScoreEnvelope` whose
`utility_by_seat` carries every seat's own value (both RED's and BLUE's — the
scorer already computes both today, see `score_seat_outcome`'s
`own_value`/`opponent_value`) and whose `primary` is the sole subject seat's
own value. `kernel_scoring_contract_spec.md`'s ruling-R12 problem statement
names this family by name ("found by the negarena migration, 2026-09-06"),
which is consistent with this being the exact case the ruling was written
for.

For any single-seat-subject negarena evaluation cell (the ordinary case —
one seat is the tested model, the other is a fixed scripted/pinned opponent),
`seat_context.subject_seats` has exactly one entry, so R12 rule 2's singleton
branch applies: `primary == utility_by_seat[subject]`, enforced by the
kernel's `_enforce_subject_seat_primaries`, not merely by convention. A
self-play cell (both seats subjects) would need a declared
`subject_reduction` before this leaf could score `ok` — not needed for any
case in today's corpus (`cases.py`'s roster pairs the tested seat against a
fixed opponent), so not declared here; a future self-play negarena case would
need that decision made explicitly, which is out of this migration's scope.

`negarena_agreement_reached_leaf`'s estimand ("did the episode end via an
in-band `ACCEPT`") is a single fact about the whole episode, not a function
of which seat is the tested subject — both seats experience the same
termination. It stays `seat_scope="cell"` (the default).

Confirmed directly (not assumed): `grep -c seat_context
src/aeread/shared_runner/task/evaluation.py` is 30 on this base (see
preconditions above), so the mechanism this classification depends on
actually exists here.

## Proposed primary: `negarena_seat_outcome_leaf`

`family_manifest()` (`environment.py`) already declares
`measurement.primary_estimand = "negarena_seat_outcome"` — exactly
`SEAT_OUTCOME_ESTIMAND_ID`, the estimand of `negarena_seat_outcome_leaf`. Per
ruling R8 the kernel does not enforce this correspondence mechanically, which
is exactly why a human has to check it: here the two independently-authored
fields agree in meaning (both name "what this seat realized"), not merely by
name coincidence.

Substantively this leaf is also the adapter's own stated headline number:
`docs/negarena_adapter_status.md` labels it "primary" in its leaf table and
`measurement.py`'s module docstring opens with it as leaf 1; leaf 2
(`negarena_agreement_reached`) is explicitly labelled "diagnostic" in both
places. It is not "the one that was easiest to compute" (spec section 3's
forbidden reasoning) — leaf 2 is in fact the simpler of the two (a pure
predicate over `terminal["reason"]`, no bridge call) and is not proposed as
primary.

## Admission: `negarena_seat_outcome_leaf` alone

Matches the family's own pre-existing, already-committed classification:
`measurement.py`'s module docstring calls leaf 2 "diagnostic" and states its
reason for existing separately — "so a degenerate no-agreement episode is
never silently averaged into the payoff leaderboard as a 'loss'"
(`docs/verifier_taxonomy.md` section 9). Per the spec ("Diagnostic leaves are
receipted but do not gate admission unless declared"), leaf 2 stays out of
`admission_leaf_ids`.

So `admission_leaf_ids = (negarena_seat_outcome_leaf,)`, and the primary is
(trivially) inside admission, satisfying `MeasurementDeclaration.__post_init__`.

## Deferred leaves: none

Both leaves are `scope="finalize_time"` (both replayed-episode, neither needs
a judge verdict or a separate-run artifact by its estimand's own definition).
There is no artifact for a `deferred_artifact` field to name. R12's
seat-context mechanism removes what the prior revision of this document had
flagged as a blocker to leaf 1 emitting a real `ok` value — that blocker was
plumbing (the call site had no way to know which seat was the tested
subject), never a reason to mark the leaf `deferred` (spec section 4: a leaf
may not be `deferred` merely because computing it is currently inconvenient).

## Paired-history pair: constructible — yes

`NegarenaPlugin.outcome()` (`environment.py:494-503`) returns only
`{termination_reason, iteration_count, last_answer, last_trade}` — never
`state["history"]`. On the most common termination path this is even more
collapsed than it first looks: when `reason == "accepted"`, `last_trade` is
the *accepting* turn's own trade tag, which upstream's parser always reduces
to the fixed sentinel dict `{"kind": "none"}` regardless of what was
negotiated earlier (`environment.py`'s `terminal()` docstring; confirmed in
`negarena_bridge_driver.py`, and used exactly this way by every golden
transcript in `parity.py`). So for any two episodes that both end in
`"accepted"` at the same `iteration_count`, the `outcome()` dict is
byte-identical regardless of what the intermediate rounds proposed — the real
negotiated trade lives only in `state["history"][-2]`, which
`FamilyScoringInput.phase_instances` carries but `outcome()` never does.

Concretely buildable from the existing golden-1 buy_sell transcript
(`parity.py::build_buy_sell_golden_one`, offers
`50->30->45->35->42->38->40` then `ACCEPT`, 8 turns): a second fixture over
the same case (`negarena.buy_sell.0`) using a different intermediate offer
sequence of the same length, varying the second-to-last offer specifically
(so the settlement itself also differs, giving the trajectory-scoped leaf a
genuine sensitivity witness per ruling R9's "the pair must show the leaf CAN
change" requirement) ending in the identical final `ACCEPT` turn, produces a
byte-identical `outcome()` with a genuinely different `phase_instances`
history. This also gives the mislabelling contrapositive (R7) a non-trivial
pair to check `negarena_agreement_reached_leaf` against.

No `trajectory_outcome_paths` declaration is needed, and none exists on this
base to declare it with — the whole outcome is checked directly, exactly as
before rulings R9/R10, matching govsim's case rather than collusion's.

## Rulings that do not apply here

R9/R10 (trajectory embedded in outcome): not applicable — `outcome()` carries
no trajectory-bearing field, so no `trajectory_outcome_paths` declaration is
needed.

R11 (no-upstream-code formula conformance): not applicable — negarena has a
real pinned upstream checkout (`vinid/NegotiationArena` at
`c447fafd439a20b84cdedeb2f8a85c4fad764745`) and never reimplements its
settlement math; `parity.py` already establishes byte-identical-`player_outcome`
parity against `NegarenaBridge.replay_transcript`, the genuine article R11
asks for when upstream code exists.

## Rulings that apply here

R12 (seat context reaches the scorer): applies to `negarena_seat_outcome_leaf`
— see "Seat-scope classification" above. This is not a reference gap; it is
resolved by declaring `seat_scope="subject_seat"` and letting the kernel
supply `seat_context`, which the next milestone's `__call__` implementation
will use.

## What blocks the next milestone

This milestone ends in a STOP, not a green baseline. Before any manifest/
`__call__` change: `harness.py`'s `record_full_evidence_lifecycle` (and, by
extension, `ScriptedNegarenaHarness`/`run_scripted_negarena_episode`) needs a
real decision — outside this milestone's scope, and outside the "one
mechanical fix" carve-out — about how to emit an `action_attempt_succeeded`
event (with `canonical_response` and, if the family ever needs retries,
`action_attempt_id`) per logical action so that
`finalize_family_execution`'s replay walk can read it back. Until that is
resolved, `test_finalize_family_execution_does_not_crash_and_seals_a_typed_receipt`
and `test_finalize_family_execution_seals_the_complete_evidence_lifecycle`
cannot pass, and this migration should not proceed to declaring leaf policy
or implementing `__call__` against an unverifiable finalizer path.
