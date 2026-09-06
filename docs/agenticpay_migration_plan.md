# agenticpay.bilateral migration plan (kernel_scoring_contract_spec.md)

Milestone 0 output. Precondition checks recorded below; no code changed in this
milestone. Shape to follow is the reference migration
(worktree `.../AERead/.worktrees/govsim-migrate`, `git log --oneline
zeyu/kernel-r9r10..HEAD`) and the R9/R10 precedent
(worktree `.../AERead/.worktrees/collusion-migrate`), both read in full before
writing this plan. Neither reference migration exercises ruling R12
(seat context); this family needs it, so the design decision below has no
committed in-repo precedent to copy and is argued from the spec text and the
kernel's own R12 protocol-test fixture instead (see "Seat scope" below).

## Preconditions confirmed on this base

- Worktree is on branch `zeyu/agenticpay-contract-migration`; `git log --oneline
  zeyu/kernel-r12-seat-context..HEAD` is empty (HEAD *is* the base commit,
  `cda0a7363bab11a3a80f884d32040c411b343e6e`) — nothing to migrate onto yet,
  confirmed after `git fetch origin`.
- `FamilyScoringInput` exists in `src/aeread/shared_runner/task/evaluation.py`;
  `LeafPolicyDeclaration` exists in `src/aeread/shared_runner/schemas.py`
  (confirmed by `grep -l`, both non-empty).
- `('agenticpay.bilateral', '0.1.0', 'agenticpay_bilateral_environment')` is in
  `TRUSTED_BUILTIN_PLUGIN_KEYS` (`src/aeread/shared_runner/registry.py:68`), and
  `("agenticpay.bilateral", "0.1.0")` is in `_NOT_YET_MIGRATED_TRUSTED_KEYS`
  (`tests/test_shared_runner_scoring_contract.py:1898`). `environment.py`'s
  `register_plugin` already calls `registry.register_trusted(...)`, so this
  family is not exposed to the worked example's registration-breaks-after-rebase
  trap — it was already carried this way before this branch forked.
- `grep -c trajectory_outcome_paths src/aeread/shared_runner/schemas.py` → `11`
  (nonzero — R9/R10 machinery exists on this base).
- `grep -c seat_context src/aeread/shared_runner/task/evaluation.py` → `30`
  (nonzero — R12 machinery exists on this base: `SeatContext`,
  `_seat_context_for_cell`, `_check_seat_context_seat_set`,
  `_enforce_subject_seat_primaries` are all present and already wired into
  `finalize_family_execution`/`replay_family_receipt`/`audit_family_receipt`).
  `LeafPolicyDeclaration.seat_scope`/`subject_reduction` also exist in
  `schemas.py`, both `_CANONICAL_OMIT_IF_DEFAULT` (digest-neutral per R1's
  principle).
- Family test suite, bridge exported (`AEREAD_AGENTICPAY_BRIDGE_PYTHON`,
  `AEREAD_AGENTICPAY_UPSTREAM_ROOT`): `tests/test_agenticpay_bilateral_cases.py`,
  `test_agenticpay_bilateral_environment.py`,
  `test_agenticpay_bilateral_measurement.py`, `test_agenticpay_bilateral_replay.py`,
  `tests/test_shared_runner_smoke.py` — **76 passed, 0 failed, 0 skipped**, no
  warnings, in 32.96s. This is the green baseline this migration must not
  regress (higher than `docs/agenticpay_adapter_status.md`'s recorded 71,
  consistent with test additions since that doc was last updated). No import
  fixups were needed — every import in this family's package and tests already
  resolves against the post-reorganization kernel paths on this base.

Baseline failure class: **none**. No finalizer-wiring failures, no stale
imports; the baseline is green outright.

## Today's declared leaves and their `input_scope`

All leaves are built by `measurement.py::build_leaves`, called from
`environment.py`'s `AgenticpayBilateralPlugin.build_scorer`. Three are declared
unconditionally; the fourth only for contract-mode (realistic-split) cases.

| Leaf id | Estimand id | `input_scope` | Verifier family | Evaluation class | Declared when |
|---|---|---|---|---|---|
| `agenticpay_deal_reached_leaf` | `agenticpay_deal_reached` | `terminal_state` | `rule_constraint` | `deterministic` | always |
| `agenticpay_buyer_surplus_share_leaf` | `agenticpay_buyer_surplus_share` | `terminal_state` | `objective_reference` | `deterministic` | always |
| `agenticpay_seller_surplus_share_leaf` | `agenticpay_seller_surplus_share` | `terminal_state` | `objective_reference` | `deterministic` | always |
| `agenticpay_contract_legality_leaf` | `agenticpay_contract_legality` | `trajectory` | `rule_constraint` | `deterministic` | contract-mode cases only (`measurement.is_contract_mode`) |

No leaf has a judge/rater/rubric field anywhere in `measurement.py`; every
scorer is deterministic arithmetic over the replayed episode's own terminal
state / round trace, or a bridge-verified before/after comparison
(`AgenticpayBridge.replay_round`'s `_overlay_contract_validity`) — never a
re-derivation of upstream's own extraction/validation logic.

## Reference-source classification

| Leaf | Needs | Classification |
|---|---|---|
| `agenticpay_deal_reached` | `terminal["reason"]` — this episode's own termination outcome | **replayed-episode** |
| `agenticpay_buyer_surplus_share` | `terminal["agreed_price"|"buyer_utility"|"z_max"]` (this episode) + `family_case` reservation prices / `contract_config` (closed-form constants) | **replayed-episode** (the episode-specific terminal value is the binding dependency; the case constants alone never determine an actual share) |
| `agenticpay_seller_surplus_share` | same shape, seller side | **replayed-episode** |
| `agenticpay_contract_legality` | `terminal["round_trace"]` — this episode's own per-round trace | **replayed-episode** |

None of the four is closed-form-from-case alone (none is computable without
running/replaying the episode), none needs a separate-run artifact (no
baseline-policy comparison run), and none needs a judge/rater artifact. All
four are therefore `scope="finalize_time"` — **no leaf is `deferred`, and there
is no reference gap.** The estimand text for all four is already honestly
computable from `FamilyScoringInput` alone; no owner decision about splitting
an estimand is needed.

## Seat scope (ruling R12)

**`agenticpay_buyer_surplus_share` and `agenticpay_seller_surplus_share` are
today declared as two separate always-on leaves, but the estimand each one
computes — "what surplus share did *this* seat realize under its own
reservation price/utility" — is inherently per-seat in exactly R12's sense**:
one value exists for the buyer, a different one for the seller, and neither is
meaningful independent of *which* seat is actually the tested subject in a
given evaluation cell. This family's roles (`buyer`, `seller`) are both
`testable: true` with a `scripted` counterpart declared for each
(`environment.py::family_manifest`), so a real evaluation cell may test either
seat against a scripted opponent (or, in principle, both in self-play) — the
family cannot know in advance which role is "the" subject, and the two
existing leaves' ids (`agenticpay_buyer_surplus_share_leaf` /
`agenticpay_seller_surplus_share_leaf`) hard-code an answer to that question
that the family manifest itself does not actually declare anywhere today. This
is precisely the R12 problem statement: "one value exists for each seat, and a
summed or blended two-seat number is not the estimand," and precisely the fix
negarena's `negarena_seat_outcome` leaf and the kernel's own R12 protocol-test
fixture (`tests/test_shared_runner_scoring_contract.py`'s
`_SeatScopedScorer`/`_seat_scoped_family_manifest`) already establish the shape
for: **one** `MeasurementLeafSpec` with `seat_scope="subject_seat"`, whose
scorer computes both sides' shares (reusing today's `_score_surplus_share`
math unchanged — the formula/degeneracy rules are correct today and are not
being revisited) and returns them as `utility_by_seat={"buyer": ..., "seller":
...}`, with `primary` set to the actual `seat_context.subject_seats` singleton
value per R12 rule 2 (`invalid_measurement` reason `no_subject_seat` /
`ambiguous_subject_seat` otherwise, unless a `subject_reduction` is declared
for a self-play cell). Seat ids in this family are literally `"buyer"` /
`"seller"` (confirmed: `environment.py`'s `eligible_actors`/`phases`, and
`tests/test_agenticpay_bilateral_environment.py`/`test_agenticpay_bilateral_replay.py`'s
`profile_by_seat=MappingProxyType({"buyer": ..., "seller": ...})`), so they
line up directly with `SeatContext.subject_seats`/`profile_by_seat` with no
translation layer.

**Proposed milestone-2 design (not implemented this milestone): collapse the
two role-specific leaves into one seat-scoped leaf**, tentatively
`agenticpay_surplus_share_leaf` / estimand `agenticpay_surplus_share`,
`seat_scope="subject_seat"`. This is a bigger change than a mechanical rename
(it changes `measurement.py`'s public leaf ids, `AgenticpayBilateralScorer`'s
two per-side score methods, and every test that references
`BUYER_SURPLUS_LEAF_ID`/`SELLER_SURPLUS_LEAF_ID`), which is why it is recorded
here as a decision rather than made now. Flagging for reviewer attention: this
is the one substantive redesign in this migration, and the alternative
(picking one side's leaf as a fixed primary and demoting the other to a
non-admission diagnostic) was rejected because it would silently score the
wrong party whenever a cell tests the other seat — not a hypothetical, since
both roles are independently `testable` today.

`agenticpay_deal_reached` and `agenticpay_contract_legality` are **not**
per-seat: "did the negotiation conclude with agreement" and "did every
attempted contract submission satisfy the declared bounds" are properties of
the joint negotiation trajectory, identical however the manifest's
`subject_seats` are set for a given cell. Both stay `seat_scope="cell"` (the
default).

## Proposed primary: the seat-scoped surplus-share leaf

`family_manifest()`'s coarse family-level `measurement.primary_estimand` is
already `"agenticpay_bilateral_surplus_share"` — a *singular*, role-neutral
label, not `"...buyer_surplus_share"` or `"...seller_surplus_share"`. That
wording only matches a unified, seat-scoped leaf in meaning; it does not match
either of the two existing role-specific leaf ids, which is itself evidence
that the existing two-leaf split was a scoring-contract gap, not a deliberate
declaration that one side is the family's headline number. Per ruling R8 this
correspondence is unenforced by the kernel and is exactly the kind of judgment
a reviewer must check by reading meaning, not string equality — recorded here:
`agenticpay_deal_reached` and `agenticpay_contract_legality` are rule/constraint
gates over the negotiation's mechanics, not the substantive outcome quality the
manifest's `primary_estimand`, `direction="maximize"`, and unit-interval
optimum bounds describe; only a surplus-share leaf is a `maximize`d, bounded
`[0, 1]` quantity, matching the manifest's `optimum_lower_bound`/
`optimum_upper_bound` exactly. This is not "the one that was easiest to
compute" (spec section 3's forbidden reasoning) — `agenticpay_deal_reached` is
in fact the simplest of the four (a single boolean read off `terminal["reason"]`)
and is explicitly not proposed as primary.

## Admission: the surplus-share leaf alone

Matches both reference migrations' convention (govsim: primary alone; collusion:
primary alone) and this family's own already-documented reasoning
(`docs/agenticpay_adapter_status.md`'s leaf table already separately labels the
two rule-constraint leaves from the two `objective_reference` leaves):

- `agenticpay_deal_reached` is a diagnostic, not an admission gate: a
  `"timeout"` outcome is a genuine, meaningful negotiation failure the family
  wants to *report*, not a case whose receipt should be excluded outright — and
  in practice a `"timeout"` already routes the surplus-share leaf itself to
  `invalid_measurement` (reason `"no_agreement_reached"`), so gating admission
  on `agenticpay_deal_reached` separately would be redundant with the primary's
  own admission behavior, not an independent check.
- `agenticpay_contract_legality` is likewise a diagnostic: it is declared only
  for a subset of cases (contract-mode) and a rejected submission is
  informative (per-round detail already retained in `metrics`), not grounds by
  itself to exclude the receipt while the surplus-share leaf still scored `ok`.

So `admission_leaf_ids = (<surplus_share_leaf>,)`, trivially satisfying
`MeasurementDeclaration.__post_init__`'s "primary is in admission" rule.

## Deferred leaves: none

All four (post-redesign: three) leaves are `scope="finalize_time"`. None
depends on a judge verdict, external rater protocol, or another episode's run
that might not exist at finalization — every scorer in `measurement.py` is
closed-form arithmetic over the verified re-executed episode's own terminal
state / round trace, or a bridge call that only re-validates *this* episode's
own already-submitted contract text (never a separate run). There is no
artifact for a `deferred_artifact` field to name.

## Reference gap: none

No leaf's estimand, by its own definition, requires a separate-run or
judge-dependent artifact. The estimand is not being changed.

## Paired-history pair: NOT constructible on the whole outcome (rulings R9/R10 apply)

`AgenticpayBilateralPlugin.outcome()` (`environment.py`) returns `dict(terminal)`
verbatim, and `terminal()` includes `"round_trace": list(state["round_trace"])`
— the full ordered per-round history of raw `buyer_action`/`seller_action` text,
contract-attempt flags, and before/after price/contract state. Two episodes
with different negotiation transcripts therefore essentially never produce a
byte-identical `outcome`, so a whole-outcome paired-history pair is not
constructible by construction — this is exactly collusion's shape (`outcome()`
embeds `history`), not govsim's (whose `outcome()` carries only final
aggregates).

Per R9, this family will declare `trajectory_outcome_paths = ("/round_trace",)`
in `family_manifest()`'s `measurement` block (mirroring collusion's
`"trajectory_outcome_paths": ["/history"]` exactly). The paired-history check
then operates on the **projection** (outcome with `/round_trace` removed):
`reason`, `rounds`, `buyer_price`, `seller_price`, `agreed_price`,
`buyer_contract`, `seller_contract`, `agreed_contract`, `buyer_utility`,
`seller_utility`, `z_max`, `global_score`, `buyer_score`, `seller_score` — all
final/terminal scalars, none of which vary independently of `round_trace` once
the terminal state is fixed. Concretely buildable the same way collusion did
it: two bridge-backed episodes with different per-round message text/ordering
that converge to the identical final price/contract/utility state (e.g. two
different two-round paths to the same agreed price), giving a genuinely
different `round_trace` but an identical projection.

Only one leaf has `input_scope="trajectory"` — `agenticpay_contract_legality`
— so the sensitivity witness (R9's relaxed form: "some fixture pair on which
the leaf differs," not necessarily *the* paired-history pair) needs a second,
separate fixture pair: one round-trace with an accepted contract submission,
another with a rejected one (same or different final agreement), demonstrating
`agenticpay_contract_legality`'s primary actually changes. `agenticpay_deal_reached`
and the surplus-share leaf(s) are `terminal_state`-scoped and are checked by
the ordinary mislabelling/R7 contrapositive on the same pair, not by a
trajectory-sensitivity witness.

`constructible` (whole-outcome pair): **false** — matches this milestone's own
framing text describing collusion's identical shape.

## Rulings applied

- **R8**: no forced string correspondence between `primary_estimand` and the
  primary leaf's estimand id; correspondence in meaning is argued above.
- **R9/R10**: `outcome()` embeds the trajectory at `/round_trace`; declare
  `trajectory_outcome_paths=("/round_trace",)`; the projected pair is
  constructible even though the whole-outcome pair is not; the sensitivity
  witness for the one `trajectory` leaf needs its own fixture pair, not
  necessarily the paired-history pair.
- **R12**: the two existing per-role surplus-share leaves are collapsed
  (milestone-2 work, not done here) into one `seat_scope="subject_seat"` leaf;
  `agenticpay_deal_reached`/`agenticpay_contract_legality` stay `seat_scope="cell"`.

## What is not decided here

The exact new leaf/estimand/reference/scorer ids for the merged surplus-share
leaf, and the corresponding rewrite of `AgenticpayBilateralScorer`'s two
per-side score methods and every test referencing
`BUYER_SURPLUS_LEAF_ID`/`SELLER_SURPLUS_LEAF_ID`, are milestone-2 work
("declare leaf policy in the manifest"). This plan fixes the *shape* of that
decision (one seat-scoped leaf, not two) and the reasoning; the literal
identifiers are an implementation detail for that milestone, not a judgment
call this document needs to lock in.
