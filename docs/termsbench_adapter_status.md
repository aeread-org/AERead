## termsbench adapter — status

Branch `zeyu/termsbench-contract-migration`. Last verified 2026-09-06 (kernel
scoring-contract migration + regime split, final).

## The owner decision: split into two family versions

TERMS-Bench reports per regime, and its leaves are regime-specific:
`surplus_efficiency`/`feasible_agreement` (SE+/AGR+) exist only for Overlap
cases, `no_deal_agreement` (FAGR-) only for No-deal cases,
`protocol_compliance` (CritViol%) for both. Ruling R13 rule 1
(`kernel_scoring_contract_spec.md`) forces the choice:

> A `case_conditional` leaf may not be `primary_leaf_id` and may not be in
> `admission_leaf_ids`: both must exist for every execution admitted under
> one static manifest. A family whose headline is genuinely
> regime-conditional either chooses an unconditional cross-regime primary or
> splits that regime into a distinct family version with its own static
> manifest.

Two alternatives were considered and rejected:

- **An unconditional cross-regime primary.** Blending SE+ (Overlap) and
  FAGR- (No-deal) into one cross-regime headline would be an invented
  estimand with no paper definition — the two measure opposite things (value
  realized vs. false agreement avoided) under geometrically disjoint
  conditions (`Delta_i>0` vs. `Delta_i<0`). Declaring `protocol_compliance`
  (CritViol%) as the unconditional primary instead would promote a
  diagnostic constraint check to the headline, which is not what it is.
- **The regime-conditional design this branch originally implemented**
  (tag `termsbench-attempt1`, reset out of this branch's history before this
  migration): one manifest declaring all four leaves unconditionally,
  with a `_wrong_regime_envelope` helper returning
  `invalid_measurement("wrong_regime")` for whichever leaf(s) did not apply
  to a given case's regime, and `termsbench_surplus_efficiency_leaf` as the
  sole primary/admission leaf regardless of regime. That branch's own
  finalizer receipt tests proved this end to end, not merely as a
  hypothetical: an Overlap-regime receipt came back
  `status="ok"`/`inclusion_status="included"`, but the No-deal-regime
  receipt came back `status="invalid_measurement"`/`inclusion_status=
  "excluded"` — SE+ is `invalid_measurement("wrong_regime")` for 100% of
  No-deal cases by construction, and it was that design's sole admission
  leaf regardless of regime. This is exactly ruling R13's motivating
  problem, not a solution to it: every No-deal-regime receipt was
  structurally excluded from admission, and a `case_conditional` leaf still
  needed to be either the primary or excluded from admission on half the
  corpus. Never merged; kept reachable only as a git tag, described here
  rather than referenced as a branch.

**This is what was built instead:** two regime-specific family VERSIONS,
each with its own static leaf set, primary, and admission — `termsbench.overlap`
and `termsbench.nodeal`. Both are described below, in their own sections.

**The retired identity.** `termsbench` (`0.1.0`, plugin
`termsbench_environment`) is removed from `TRUSTED_BUILTIN_PLUGIN_KEYS` and
from `_NOT_YET_MIGRATED_TRUSTED_KEYS`. No `EvaluationReceipt` was ever
produced under that id (this family never reached the finalizer before this
migration — see "Receipt" in each section below), so nothing is orphaned by
retiring it.

## What both adapters claim

`termsbench.overlap`/`termsbench.nodeal` are a **faithful reimplementation
from the paper** of TERMS-Bench's bilateral alternating-offer
price-negotiation environment (arXiv `2605.13909v2`) — there is no upstream
code (the paper's own repository link is dead), so nothing here is a "port"
or a wrapper around someone else's binary. The environment, the counterpart
kernel (Candid/Taciturn/Expressive, 3 of the paper's 6 families), and all
measurement leaves are AERead's own from-scratch code, translating cited
equations, run through the real shared-runner scheduler
(`run_episode`/`PluginRegistry`), never a hand-wired shortcut. Ruling R11
(`kernel_scoring_contract_spec.md`): **No upstream implementation exists;
conformance means agreement with independently hand-derived paper-formula
goldens, not parity with upstream code.** See `docs/termsbench_adapter_spec.md`
for the full pre-split design and `docs/termsbench_migration_plan.md` for
this migration's own leaf-table and reference-source analysis.

One package (`src/aeread_families/termsbench/`), parametrized by regime:
`TermsBenchPlugin` carries a `regime` attribute fixed at construction and is
registered as two separate instances, each under its own manifest —
`PluginRegistry` keys a registration by `(family_id, family_version,
plugin_id)` on the manifest/instance it is given, never by class identity,
so this needed no subclassing. `TermsBenchPlugin.validate_payload` rejects
any case whose own `"regime"` does not match the instance's `regime`: a
wrong-regime case can no longer reach a family version's scorer at all — not
even as a named `"wrong_regime"` `invalid_measurement` (the rejected design
above). `measurement.py`'s scoring code (`build_leaves`, the `score_*`
functions) is unchanged and shared: since each `TermsBenchPlugin` instance
only ever validates its own regime's cases, `build_leaves(payload)` already
returns exactly that family version's own static leaf set for every case it
will ever see.

---

## `termsbench.overlap`

Family id `termsbench.overlap`, version `0.1.0`, plugin id
`termsbench_overlap_environment`. Cases: the 15 Overlap-regime pilot cases
(`cases/termsbench_overlap/pilot/`, one per (counterpart-family,
difficulty-bin) cell — 3 families x 5 bins).

### Leaf policy

| Leaf | Estimand | Scope | Primary | Admission |
|---|---|---|---|---|
| `termsbench_surplus_efficiency_leaf` (SE+) | `termsbench_surplus_efficiency` | `finalize_time` | **yes** | **yes** |
| `termsbench_feasible_agreement_leaf` (AGR+) | `termsbench_feasible_agreement` | `finalize_time` | no | no |
| `termsbench_protocol_compliance_leaf` (CritViol%) | `termsbench_protocol_compliance` | `finalize_time` | no | no |

No leaf is `case_conditional`: every case this family version's
`validate_payload` admits has `regime == "overlap"`, so all three leaves are
declared for every one of its cases, unconditionally, and ruling R13's hook
(`inapplicable_leaf_ids`) is not needed.

**Why `termsbench_surplus_efficiency_leaf` is primary.**
`family_manifest("overlap").measurement.primary_estimand` is
`"termsbench_surplus_efficiency"` — SE+ (eq. 56, Section F.1), the paper's
own headline value-axis quantity (realized agent surplus as a fraction of
the ZOPA). It is not "the leaf that was easiest to compute" — CritViol% is
in fact the simplest of the three (a boolean OR over three flags) and is
not proposed as primary.

**Why it alone gates admission.** `termsbench_feasible_agreement_leaf`
(AGR+) shares SE+'s exact validity gate (`_value_axis_validity`, gated on
`malformed_action_schema` alone): the two are never independently
valid/invalid for the same episode, so adding AGR+ to admission would add
no exclusion power SE+ does not already provide.
`termsbench_protocol_compliance_leaf` (CritViol%) is a genuine constraint
check, not a diagnostic, but `score_protocol_compliance` never returns
`invalid_measurement` (it unconditionally returns `status="ok"`, folding
violations into `primary`/`metrics` instead) — gating on it would never
fire, mirroring govsim's own treatment of its rule/constraint leaves as
non-gating diagnostics.

**Deferred leaves: none.** All three are `scope="finalize_time"`; none
depends on a judge verdict, external rater protocol, or another episode's
result. `SE+`/`AGR+` need only this episode's own `outcome`; CritViol% needs
only this episode's own accumulated violation flags.

### Receipt

This family had never produced an `EvaluationReceipt`:
`ScriptedTermsBenchHarness` writes only its own two convenience events
(`termsbench_agent_response`, `termsbench_counterpart_draws`) and never the
generic evidence trail (`logical_action_started`, `action_attempt_succeeded`,
`action_parsed`, `action_legality_checked`, `logical_action_succeeded`/
`logical_action_agent_action_failure`, `phase_instance_started`,
`transition_applied`, `phase_instance_succeeded`, `episode_terminated`,
`family_outcome_recorded`) that `task.evaluation.replay_family_scoring_input`
needs to replay, so `finalize_family_execution` (which calls that replayer
internally) could never have been driven for this family before this
migration. `EvidenceRecordingTermsBenchHarness` (`tests/test_termsbench_replay.py`)
reproduces that exact vocabulary, mirroring `AttemptExecutor`'s own event
shapes field-for-field — but wraps one `ScriptedTermsBenchHarness` instance
for response generation instead of re-implementing the agent-script cursor
and counterpart-kernel draw/resolve plumbing a second time.

`test_finalize_wires_termsbench_overlap_to_the_shared_family_finalizer`
drives one small, real, provider-free episode (agent opens at 110, the
counterpart accepts) end to end through the real finalizer and gets back a
receipt carrying every one of this family's three declared leaves, primary
`termsbench_surplus_efficiency_leaf`, one shared `evidence_refs` tuple across
all three scores. **`status="ok"`, `inclusion_status="included"`** — unlike
collusion/govsim (whose primary needs a comparison baseline no single-episode
`FamilyScoringInput` ever carries), every termsbench leaf is computed purely
from that episode's own outcome, so this receipt is genuinely admitted, not
structurally excluded.

### Enrolled in the scoring-contract protocol test

`('termsbench.overlap', '0.1.0', 'termsbench_overlap_environment')` is in
`TRUSTED_BUILTIN_PLUGIN_KEYS` and NOT in `_NOT_YET_MIGRATED_TRUSTED_KEYS`
(`tests/test_shared_runner_scoring_contract.py`). `_termsbench_overlap_fixtures`
supplies two provider-free episodes (`left`/`right`), driven through the
real scheduler via `EvidenceRecordingTermsBenchHarness`: same price, same
decision, same counterpart draws on both, differing ONLY in the agent's own
scripted message text. `TermsBenchPlugin.outcome()` never reads
message/transcript, so the two runs' outcomes are byte-identical while their
sealed `phase_instances` genuinely differ — the paired-history pair ruling
R7 requires.

**No leaf is trajectory-scoped in this manifest** (all three are
`input_scope="terminal_state"`), so ruling R9(b)'s sensitivity witness is
vacuous here by construction (empty `trajectory_leaf_ids` — there is no
leaf to witness, not a gap in coverage). What the pair actually exercises is
R7's contrapositive: all three `terminal_state` leaves must score
identically across `left`/`right`, which they do.

---

## `termsbench.nodeal`

Family id `termsbench.nodeal`, version `0.1.0`, plugin id
`termsbench_nodeal_environment`. Cases: the 15 No-deal-regime pilot cases
(`cases/termsbench_nodeal/pilot/`, one per (counterpart-family,
difficulty-bin) cell — 3 families x 5 bins).

### Leaf policy

| Leaf | Estimand | Scope | Primary | Admission |
|---|---|---|---|---|
| `termsbench_no_deal_agreement_leaf` (FAGR-) | `termsbench_no_deal_agreement` | `finalize_time` | **yes** | **yes** |
| `termsbench_protocol_compliance_leaf` (CritViol%) | `termsbench_protocol_compliance` | `finalize_time` | no | no |

No leaf is `case_conditional`: every case this family version admits has
`regime == "nodeal"`, so both leaves are declared for every one of its
cases, unconditionally.

**Why `termsbench_no_deal_agreement_leaf` is primary.**
`family_manifest("nodeal").measurement.primary_estimand` is
`"termsbench_no_deal_agreement"` — FAGR- (eq. 60, Section F.2), this
regime's own headline quantity: whether the episode produced a "false
agreement" (a bound price in a geometry with no positive ZOPA, which is
undesirable by construction — the counterpart kernel's own IR gate,
`acceptance_probability`'s `delta_bar<0.0` hard return of 0, guarantees the
counterpart never accepts an offer that is not individually rational for
it, so any bound price here can only arise from the agent script itself
accepting an IR-violating counterpart price). `direction="minimize"`: lower
FAGR- is better, the mirror image of AGR+'s `"maximize"`.

**Why it alone gates admission.** The same reasoning as `termsbench.overlap`'s
CritViol% above: `score_protocol_compliance` never returns
`invalid_measurement`, so gating admission on it would never fire.

**Deferred leaves: none.** Both are `scope="finalize_time"`; FAGR- needs
only this episode's own `outcome`, CritViol% only its own accumulated
violation flags.

### Receipt

Same structural gap as `termsbench.overlap` (`ScriptedTermsBenchHarness`
never wrote the generic replay-required evidence trail) and the same fix
(`EvidenceRecordingTermsBenchHarness`).
`test_finalize_wires_termsbench_nodeal_to_the_shared_family_finalizer`
drives six lowball agent offers with a forced walk-away hazard —
`termination_reason="counterpart_walk_away"`, no bound price — end to end
through the real finalizer and gets back a receipt carrying both declared
leaves, primary `termsbench_no_deal_agreement_leaf`, one shared
`evidence_refs` tuple. **`status="ok"`, `inclusion_status="included"`**,
`termsbench_no_deal_agreement_leaf.primary.value == 0.0` (no false
agreement) — same as `termsbench.overlap`, genuinely admitted, not
structurally excluded.

### Enrolled in the scoring-contract protocol test

`('termsbench.nodeal', '0.1.0', 'termsbench_nodeal_environment')` is in
`TRUSTED_BUILTIN_PLUGIN_KEYS` and NOT in `_NOT_YET_MIGRATED_TRUSTED_KEYS`.
`_termsbench_nodeal_fixtures` supplies the same message-text-only `left`/
`right` pair, on the six-lowball-offer No-deal scenario. Both leaves are
`input_scope="terminal_state"`; the sensitivity witness is vacuous here for
the identical reason as `termsbench.overlap`'s.

## R11 goldens

`docs/termsbench_adapter_spec.md`'s own 5 QC Gate-2 goldens (section 4) are
all Overlap-regime — none exercises eq. 60 (FAGR-) with its own hand-derived
arithmetic, only the shared 0/1 agreement-indicator code AGR+'s goldens
already cover. This migration adds two paired No-deal goldens to
`tests/test_termsbench_measurement.py`:
`test_golden_nodeal_no_false_agreement_reports_fagr_minus_zero` (a real
scripted disagreement, `FAGR- = 0`) and
`test_golden_nodeal_false_agreement_reports_fagr_minus_one` (a
hand-constructed outcome demonstrating the `FAGR- = 1` branch, mirroring
Gate 2 golden 2's own convention of pinning a fixture outcome directly to
isolate the scorer from the kernel's own IR gate, which makes that branch
unreachable through live scripted play). Every formula either family
version scores now has a hand-derived golden with the arithmetic written
beside the expected value in the test source.

## Evidence

**Full termsbench suite: 111 passed, 0 failed, 0 skipped**
(`tests/test_termsbench_cases.py` + `test_termsbench_counterpart.py` +
`test_termsbench_environment.py` + `test_termsbench_harness.py` +
`test_termsbench_measurement.py` + `test_termsbench_replay.py` +
`test_trusted_adapter_families.py` + `test_shared_runner_smoke.py`):

| File | Tests |
|---|---|
| `tests/test_termsbench_cases.py` | 28 |
| `tests/test_termsbench_counterpart.py` | 21 |
| `tests/test_termsbench_environment.py` | 13 |
| `tests/test_termsbench_harness.py` | 5 |
| `tests/test_termsbench_measurement.py` | 17 |
| `tests/test_termsbench_replay.py` | 16 |
| `tests/test_trusted_adapter_families.py` | 1 |
| `tests/test_shared_runner_smoke.py` | 10 |

**Plus the shared, cross-family `tests/test_shared_runner_scoring_contract.py`
(58 passed, 0 failed, 0 skipped)** — not termsbench-specific, so not counted
in the family-suite total above, but this is where both families' own
enrollment is actually exercised:
`test_every_registered_family_obeys_the_scoring_contract` now includes both
`_termsbench_overlap_fixtures` and `_termsbench_nodeal_fixtures` in its
closed-world, registry-driven sweep over every `TRUSTED_BUILTIN_PLUGIN_KEYS`
entry.

This family needs no bridge interpreter, so the counts above are the entire
suite for it — no bridge-gated subset exists to hide behind.

## Cases: the split

`cases/termsbench/pilot/` (30 cases: 15 Overlap + 15 No-deal, one combined
`pilot_manifest.json`) is retired and split into
`cases/termsbench_overlap/pilot/` (15 cases + `pilot_manifest.json`,
`pilot_id="termsbench_overlap_pilot_v1"`) and
`cases/termsbench_nodeal/pilot/` (15 cases + `pilot_manifest.json`,
`pilot_id="termsbench_nodeal_pilot_v1"`), each regenerated deterministically
via `cases.py`'s own generator (`run_generate(output_dir, regime=...)` /
`run_generate_all()`) — no manual edits to any case file. Every case now
carries `family_id = FAMILY_ID_BY_REGIME[its own regime]` — `cases.py`
already parametrizes case generation by regime, so this is a natural
consequence of that, not a special-case rule. `termsbench` is not a
digest-frozen family and had no pin file referencing the old identity, so
there was nothing else to update for the identity rename.

## Known limits, stated rather than implied

- **Milestone 1's stated limits still apply, unchanged by the split or the
  migration**: the Oracle-Cue Bayes-optimal DP (App. D–E) is deferred, no
  `Gap_π`/upper-bound claim; `BE_type` is out of scope; only 3 of 6
  counterpart families are implemented; the urgency-shift regime is
  deferred; counterpart language is a deterministic template, never an LLM.
  See `docs/termsbench_adapter_spec.md` section 6.
- **The harness/replay tests exercise scripted trajectories, not model
  behaviour.** Every episode in `test_termsbench_harness.py`/
  `test_termsbench_replay.py` (including the two new finalizer-receipt
  tests) is a fixed agent script chosen to hit a specific termination case
  deterministically. That proves the scheduler/harness/replay/finalizer
  machinery is correct; it says nothing about how any agent scores.
- **Evidence sealing is adapter-owned twice over, for two different
  purposes.** `ScriptedTermsBenchHarness` seals its own two
  domain-specific event types (evidentiary logging of RNG draws) for
  `test_termsbench_harness.py`/`test_termsbench_replay.py`'s own tests;
  `EvidenceRecordingTermsBenchHarness` (new this migration) separately
  seals the generic `AttemptExecutor`-shaped trail
  `replay_family_scoring_input` needs. Neither is a new kernel primitive,
  and the two never seal the SAME event stream (a test using one does not
  get the other's events for free).
- **Replay's byte-identical claim is proved on 2 scripted episodes per
  family version (4 total), not either 15-case pilot corpus.** No
  parity-CLI-style full-corpus sweep exists for termsbench (there is no
  upstream binary to sweep against) — replay correctness here is a targeted
  proof on representative trajectories, not an exhaustive one.
- **The finalizer receipt tests are one episode per family version, not a
  corpus sweep.** `test_finalize_wires_termsbench_overlap_to_the_shared_family_finalizer`/
  its nodeal companion each prove the finalizer wiring works end to end for
  one representative scripted trajectory; they do not sweep every pilot
  case through the finalizer.
- **`RecordedResponseSource` exceptions surface wrapped, not bare.** Any
  `ReplayError` it raises mid-episode is caught and re-raised as
  `SchedulerContractError` by `run_episode` itself — only `replay_episode`'s
  own pre/post checks raise a bare `ReplayError`.
- **The kernel does not check that `validate_payload`'s regime rejection is
  semantically the right split** (ruling R13's own stated limit, by
  analogy): a reviewer, not a validator, confirmed SE+/AGR+ genuinely belong
  to Overlap and FAGR- to No-deal, per the paper's own eq. 56/57/60
  preconditions.

## No kernel/runner defect found

Nothing in this migration required a kernel/runner change or worked around
a kernel defect. `PluginRegistry.register_trusted`, `resolve_run_plan`,
`replay_family_scoring_input`, and `finalize_family_execution` all worked
exactly as documented for two newly-split, newly-migrated family versions.
