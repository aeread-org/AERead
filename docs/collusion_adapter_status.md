# collusion adapter — status

Branch `zeyu/collusion-adapter`. Last verified 2026-09-05 (kernel scoring-
contract migration, milestone 2 of 3).

## What the adapter claims

Reimplements the repeated Bertrand-oligopoly logit-demand duopoly of Fish,
Gonczarowski, and Shorrer, *Algorithmic Collusion by Large Language Models*
(arXiv `2404.00806v6`), as one AERead family. No upstream code exists for
this paper (verified: no repository is cited, none exists at the arXiv
listing) — every line is AERead's own faithful reimplementation of the
paper's published formulas; "parity" means hand-verified closed-form
arithmetic against the paper's own quoted Appendix A.5 numbers, not a diff
against an executable artifact (`docs/collusion_adapter_spec.md` §1/§5).
Ruling R11 (`kernel_scoring_contract_spec.md`): **No upstream implementation
exists; conformance means agreement with independently hand-derived
paper-formula goldens, not parity with upstream code.**

Four measurement leaves are declared per case, reported as an admitted
vector — never blended into one score:

| Leaf | Verifier family | Evaluation class | Role |
|---|---|---|---|
| `collusion_price_legality` | `rule_constraint` | `deterministic` | gate: a price outside `[0, ceiling_k * p_monopoly_seat]` excludes that round and every later round from leaves 2–4 |
| `collusion_distance_to_nash_price` | `canonical_reference` | `deterministic` | diagnostic only, never an optimum (P04) |
| `collusion_distance_to_monopoly_price` | `canonical_reference` | `deterministic` | diagnostic only, never an optimum (P04) |
| `collusion_long_run_profit` | `comparative` | `deterministic` | own profit (periods 251–300 mean) minus a named scripted baseline's own — never `objective_reference`, since no long-run oracle exists against an endogenous rival |

Milestones 1–2 (prior sessions) landed the 6-cell pilot corpus, the
environment plugin (phase graph, legality gate, demand/profit transition),
the scorer, and the five QC Gate-2 goldens. **This milestone (3 of 3)**
adds:

* `harness.py` — `ScriptedCollusionHarness`, serving the four spec-section-3
  named scripted policies (constant, tit-for-tat, Nash-play, monopoly-play —
  none paper-specified) through the real `run_episode` scheduler path, and
  sealing one evidence event per served price decision. `family_manifest()`
  now declares all four policy ids for the `pricing_agent` role (previously
  an empty list, explicitly marked "a later milestone" in the milestone-1/2
  code comment).
* `replay.py` — rebuilds a sealed episode from its recorded decision log
  with zero provider calls, folding responses through the real scheduler
  and `CollusionPlugin.step()`, then recomputes all four leaves from the
  replayed outcome via `measurement.CollusionScorer`.

## Leaf policy (kernel_scoring_contract_spec.md, migration milestone 2 of 3)

`family_manifest()`'s `measurement` block now declares this family's leaf
policy explicitly (spec section 3), and `CollusionScorer.__call__` takes a
`FamilyScoringInput` and returns a `FamilyScoreSet` carrying every one of
the four leaves below. Before this milestone `CollusionScorer` had no
`__call__` at all — see the retired note in its own docstring — so calling
it the way `task.evaluation.finalize_family_execution` calls every other
family's scorer (`plugin.build_scorer(family_case)(scoring_input,
evidence_refs=...)`) would have raised `TypeError: 'CollusionScorer' object
is not callable` before any score was recorded.

| Leaf | Scope | Primary | Admission |
|---|---|---|---|
| `collusion_price_legality` | `finalize_time` | no | no |
| `collusion_distance_to_nash_price` | `finalize_time` | no | no |
| `collusion_distance_to_monopoly_price` | `finalize_time` | no | no |
| `collusion_long_run_profit` | `finalize_time` | **yes** | **yes** |

**Why `collusion_long_run_profit` is primary.** It is this family's own
already-declared `primary_estimand` (`family_manifest()`'s `measurement`
block, present since milestone 2 of the original adapter build, unchanged
by this migration) and its headline economic quantity: realized own profit
over the paper's own App. A.4 reporting window, relative to the named
scripted Nash-play baseline under the same condition — the closest thing
this family has to "did the tested policy actually sustain higher prices
than competitive play." It was not picked because it was the easiest leaf
to compute: it is in fact the leaf most likely to report
`invalid_measurement` on its own (a reporting-window-unavailable or
missing-baseline case can invalidate it while every other leaf still scores
"ok" — see `score_long_run_profit`'s own docstring), and the two distance
diagnostics below are strictly cheaper, single-window reductions. The
choice tracks the family's own declared estimand and the paper's own
Appendix A.4 motivation, not convenience.

**Why it alone gates admission.** The other three are diagnostics, not
admission gates, for two independent reasons already recorded in
`measurement.py`'s own module docstring before this milestone:

- `collusion_price_legality` is a `rule_constraint`/`constraint_satisfaction`
  gate on which *rounds* are admitted into leaves 2–4 (module docstring: "A
  violation gates the episode: the violating round and every later round
  are excluded from leaves 2-4") — an internal computation detail, not a
  claim about whether the *receipt itself* can be measured. A well-formed
  but out-of-ceiling price still scores `status="ok"` with `primary.value
  == 0.0` (golden 3): a measured constraint violation, never an invalid
  measurement (`measurement.py`'s `FamilyScoreSet` docstring's own
  distinction). Gating admission on it would misuse `invalid_measurement`
  for "the model priced illegally" rather than its actual meaning, "this
  could not be measured" — the same reasoning govsim's status doc records
  for its own two rule/constraint diagnostics.
- `collusion_distance_to_nash_price`/`collusion_distance_to_monopoly_price`
  are explicitly documented as "diagnostic only, never an optimum (P04)"
  (module docstring) — single-period static-game distance measures with no
  certified long-run ceiling. A large or small distance is a measured
  (`status="ok"`) outcome, never grounds to exclude the receipt.

In practice, every leaf shares the identical operational-failure gate
(`OPERATIONAL_FAILURE_REASONS`: `retry_exhausted`/`error` invalidate all
four at once, golden 4), so today `admission_leaf_ids` naming only the
primary changes behavior only in the leaf-4-specific invalid cases
(missing baseline, or a reporting window with zero admitted rounds) that
the other three leaves do not share.

**Deferred leaves: none.** Every leaf in this family is
`evaluation_class="deterministic"` with no judge, rater, or other
not-yet-existing artifact anywhere in its verifier declaration
(`measurement.py`'s `build_*_leaf` functions); nothing here waits on an
artifact that "may not exist yet" (spec section 4), so all four are
declared `scope="finalize_time"` and none is `scope="deferred"`.

**`trajectory_outcome_paths`: `("/history",)`.** Ruling R9
(kernel_scoring_contract_spec.md, round 3): unlike govsim's own
`outcome()`, this family's `CollusionPlugin.outcome()` embeds the full
trajectory at `history` (`{termination_reason, rounds_played, history}`),
so this is the exhaustive list of the trajectory-bearing outcome fields a
reviewer should compare against `outcome()` directly. All four leaves are
declared `input_scope="trajectory"`, and `CollusionScorer.__call__` reads
`history` off `scoring_input.phase_instances` (via
`_history_from_phase_instances`), not off `scoring_input.outcome` — even
though, for this family, `outcome` also happens to carry the same data.
`termination_reason` is read from `scoring_input.outcome` directly: it is
a terminal fact every leaf's operational-failure gate checks, not itself
trajectory content.

## Evidence

**Family suite: 93 passed, 0 failed, 0 skipped** across the five
`test_collusion_*.py` files (`AEREAD` project venv, Python 3.11) plus
`tests/test_shared_runner_smoke.py`, re-verified against this milestone's
leaf-policy/`__call__` migration (`kernel_scoring_contract_spec.md`):

| File | Tests |
|---|---|
| `tests/test_collusion_cases.py` | 18 |
| `tests/test_collusion_environment.py` | 18 (+1 this milestone) |
| `tests/test_collusion_measurement.py` | 25 (+2 this milestone) |
| `tests/test_collusion_harness.py` | 9 |
| `tests/test_collusion_replay.py` | 13 |
| `tests/test_shared_runner_smoke.py` | 10 |

Per-file counts above are measured directly against this branch today; the
counts this table carried before this milestone had already drifted from
tests landed in earlier sessions and were not reconciled at the time — this
update corrects the table rather than only adding this milestone's three
new tests to stale numbers.

```bash
pytest tests/test_collusion_cases.py tests/test_collusion_environment.py \
       tests/test_collusion_harness.py tests/test_collusion_measurement.py \
       tests/test_collusion_replay.py tests/test_shared_runner_smoke.py
```

This family needs no bridge interpreter (unlike govsim/tau3_retail), so
this is the entire suite -- no bridge-gated subset exists to hide behind.

**Two full 300-round episodes driven through the real shared-runner path**
(not a hand-wired shortcut — genuine `run_episode` calls against the
registered phase graph and legality gate), one per new test file:

1. `test_collusion_harness.py`: `baseline-symmetric`/α=1/seed=0, both seats
   playing `monopoly_play_policy`. Reaches `max_periods` at round 300, every
   round legal, 600 served decisions (300 rounds × 2 seats), sealed with
   `EvidenceStore.seal()` — `EvidenceSeal.event_count == 600`, and re-sealing
   is confirmed idempotent.
2. `test_collusion_replay.py`: `asymmetric-quality`/α=10/seed=0, `firm_a`
   playing constant monopoly-play and `firm_b` playing tit-for-tat (opens at
   its own Nash price on round 0, then mirrors `firm_a`'s previous price
   every later round). Reaches `max_periods` at round 300; the exact
   round-0-vs-later-rounds price shape is asserted directly, proving the
   reactive policy's own logic ran through the real per-round observation
   the scheduler actually delivers, not a pre-computed shortcut.

**Offline replay reproduces state and score with zero provider calls.** The
second full episode above is recorded, JSON-round-tripped (`to_json()` /
`from_json()`, so replay never depends on reusing the original run's
in-memory objects), and replayed through a **second, independent**
`CollusionPlugin` instance via `RecordedResponseSource` — which makes no
model call and invokes no policy function at all, only replays the exact
recorded values. Every phase-instance state hash, the terminal record, the
outcome, and the raw final state all match the original run exactly:
`comparison.matches is True`, including `final_state_matches is True`. This
is a **stronger** guarantee than `tau3_retail`'s own replay (whose raw state
can never match itself byte-for-byte, because upstream re-timestamps every
message on replay) — collusion's state carries no wall-clock timestamp or
other non-reproducible field, so raw and content-level agreement coincide.
All four leaf scores recomputed from the replayed trajectory equal the
scores computed from the original trajectory exactly (`==` on the frozen
`ScoreEnvelope` objects, not merely "close").

**The state-hash comparator was proven to have teeth, not just report
"match" unconditionally.** `CollusionPlugin.step()` has no upstream bridge
to independently re-verify a recorded response against (unlike
`tau3_retail`, whose replay cross-checks every recorded tool call against a
pinned upstream interpreter) — so instead of a tool-replay-mismatch test,
this milestone tampers one recorded price by `+0.01` (staying legal) and
confirms the comparator correctly reports `state_hashes_match is False`,
`matches is False`, and `assert_replay_matches` raises `ReplayError` naming
the diverged phase instances.

**Timing, measured directly this session** (scripted, provider-free, no
network): one 300-round episode takes **~14.4s** through bare `run_episode`
and **~15.5s** through `ScriptedCollusionHarness` (600 evidence events,
~1.1s / ~1.8ms per event) — consistent with the O(n²) scheduler cost already
recorded in `ledger_entries/collusion.md` from milestone 2 (whole-state
re-hash/re-freeze every round); the harness's own evidence bookkeeping adds
only a small, expected fraction on top, not a new distinct cost.

## Corpus quantization: why the committed gold_reference floats are rounded

CI (Linux x86_64, CPython 3.10 and 3.12) failed
`test_committed_corpus_on_disk_matches_the_builder` with a `content_sha256`
mismatch that never reproduced on this machine (macOS/arm64, CPython 3.11).
Cause: `economics.market_shares` calls `math.exp`, which is not guaranteed
bit-identical across libm implementations, so the last bits of the
solver-derived `p_nash`/`pi_nash`/`p_monopoly`/`pi_monopoly` figures
legitimately differ macOS/arm64 vs. Linux/x86_64 — and `json.dumps`' float
formatting turns any last-bit difference into a different decimal string,
hence a different digest. `ceiling_k` and `SolverTrace`'s bracket bounds are
not affected (verified stable; they never go through `math.exp`).

Fix: every solver-derived `gold_reference` float — `p_nash`, `pi_nash`,
`p_monopoly`, `pi_monopoly`, both firms, applied uniformly — is now rounded
to `cases.GOLD_REFERENCE_DECIMALS = 9` decimal places before it enters the
case payload (and therefore the digest). Chosen empirically: forcing every
`math.exp` call in the solver to round to the *opposite* adjacent double (a
1–8 ULP-per-call perturbation, already coarser than two real libm
implementations should ever disagree by) moved the solved price by at most
~3.6e-14 and the solved profit by at most ~4.3e-12 across every pilot cell.
Nine decimal places leaves a >200x margin over that measured worst case,
while staying about 7 orders of magnitude below the ~0.01 precision that is
economically meaningful at these prices (order 1–10) and profits (order
10–100) — the paper's own Appendix A.5 figures are themselves quoted to only
2 decimals, and the arithmetic-parity test against them
(`test_symmetric_baseline_alpha1_matches_paper_appendix_a5_to_stated_precision`)
still passes unchanged. **Do not "restore full precision"** — that is
exactly what reintroduces the platform-dependent digest this fix closes.
`SolverTrace`'s own fields (iteration counts, alpha-derived bracket bounds)
are deliberately left unrounded: a future solver change must still change
`content_sha256`, not be silently absorbed by quantization.

`tests/test_collusion_cases.py::test_committed_gold_reference_floats_are_already_quantized_on_disk`
is the local regression: it reads only the committed on-disk corpus (no
rebuild, no second platform needed) and asserts every float in each case's
`gold_reference` already sits exactly on the 9-decimal grid.

## Known limits, stated rather than implied

- **Scripted policies are AERead-authored probes, not paper-specified**
  (spec §3/§6) — the paper's agents are always LLM-driven; these are
  test/harness fixtures, never a claim about model behavior.
- **No live-agent (LLM) run exists yet for this family**, at any milestone.
  Every trajectory in this repo, including this milestone's, is scripted
  and provider-free (ground rule, kept without exception).
- **No mutation testing was performed this session.** Unlike
  `tau3_adapter_status.md` (which reports 3 injected defects, 2 initially
  uncaught), this milestone's harness/replay coverage was not stress-tested
  by deliberately injecting a defect and confirming the suite catches it,
  beyond the one tamper test described above (which targets the replay
  comparator specifically, not the harness or scorer). Treat "0 failed" as
  "the tests that exist all pass," not as "coverage is exhaustive."
- **No independent code review of this milestone has occurred** (contrast
  `tau3_adapter_status.md`'s "independently reviewed" line).
- **Policy-combination coverage is partial.** The two full 300-round
  episodes each exercise one fixed policy pairing (monopoly-vs-monopoly,
  monopoly-vs-tit-for-tat). Other pairings (e.g. two tit-for-tat agents,
  constant-vs-Nash-play, or any pairing on the other 4 of 6 pilot cells) are
  exercised only by short-horizon structural tests, never at full 300-round
  scale.
- **The paper's own rolling-100-period prompt truncation** (§2.2, already
  logged in `docs/collusion_adapter_spec.md` §6) is still not implemented —
  this milestone's harness reads the full, untruncated history from
  `observation["price_history"]`/`["own_history"]`; a future harness that
  builds an actual LLM prompt from this same observation must truncate
  itself.
- **The ceiling and price floor remain AERead's own construction**, not
  paper-verified (spec §6, unchanged by this milestone).
- **`docs/benchmark_qc.md` still does not exist on this branch** (already
  logged in `ledger_entries/collusion.md`, corroborating master ledger
  `D-10`); nothing in this milestone depends on it beyond the citation
  already quoted into the spec.
- **Leaf 4's baseline provenance is caller-trusted, not verified in code.**
  `score_long_run_profit`'s `baseline_profit_by_seat` argument is
  structurally validated (exact seat keys, finite numbers) but nothing
  cross-checks that the caller actually computed it under this same
  cell/horizon/opponent condition (`docs/collusion_adapter_spec.md` §6;
  `docs/collusion_codex_triage.md` Finding 2). This is a deliberate,
  twice-reaffirmed scope limit, not an oversight: closing it would require
  either a new `CaseManifest.payload` field (re-digesting the committed
  pilot corpus) or the scorer independently recomputing the baseline from
  the recorded trajectory instead of trusting the caller's number at
  all — both real architecture decisions for a future milestone, not this
  one. `tests/test_collusion_replay.py`'s
  `test_same_opponent_condition_baseline_differs_from_nash_vs_nash_pi_nash_for_an_asymmetric_opponent`
  and the reproduction test beside it guard only this test file's own
  fixture value against silently drifting back to the wrong (Nash-vs-Nash)
  baseline; neither exercises, and neither can exercise, production's
  ability to reject a wrong baseline, because no such check exists
  (independent second-pass review, `docs/collusion_fix_verification.md`).

## Deviation from the tau3_retail pattern, flagged for review

`environment.py`'s `family_manifest()` now imports the four scripted-policy
id constants from `.harness` to populate `roles.pricing_agent.
scripted_policies`. `tau3_retail`'s own `environment.py` never imports its
`harness.py` (the dependency there runs the other way: `harness.py` imports
from `environment.py`); it declares a bare literal `["scripted"]` instead of
named ids, since tau3.retail's own scripted policy has no distinct scientific
identity to name. Collusion's four policies do (spec §3: constant,
tit-for-tat, Nash-play, monopoly-play are each named in the paper's own
reward-punishment literature citation), so duplicating four literal id
strings in both files risked drift; importing them once seemed the smaller
risk. This introduces a new dependency direction (`environment.py` →
`harness.py`) this family did not have before. No test depends on which
direction this points, so it is a design choice rather than a defect, but it
diverges from `tau3_retail`'s layering and is called out here for whoever
reviews cross-family conventions next.

## No new kernel/runner defect found this session

This milestone's timing measurement (above) reproduces, rather than adds
to, the O(n²) scheduler cost already recorded in `ledger_entries/
collusion.md` from milestone 2. No new defect in the shared runner, kernel,
or environment was found while building the harness or replayer; nothing
was appended to that ledger this session.
