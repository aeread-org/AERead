# collusion adapter — status

Branch `zeyu/collusion-adapter`. Last verified 2026-09-02 (milestone 3 of 3).

## What the adapter claims

Reimplements the repeated Bertrand-oligopoly logit-demand duopoly of Fish,
Gonczarowski, and Shorrer, *Algorithmic Collusion by Large Language Models*
(arXiv `2404.00806v6`), as one AERead family. No upstream code exists for
this paper (verified: no repository is cited, none exists at the arXiv
listing) — every line is AERead's own faithful reimplementation of the
paper's published formulas; "parity" means hand-verified closed-form
arithmetic against the paper's own quoted Appendix A.5 numbers, not a diff
against an executable artifact (`docs/collusion_adapter_spec.md` §1/§5).

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

## Evidence

**Family suite: 67 passed, 0 failed, 0 skipped** across the five
`test_collusion_*.py` files (`AEREAD` project venv, Python 3.11):

| File | Tests |
|---|---|
| `tests/test_collusion_cases.py` | 17 |
| `tests/test_collusion_environment.py` | 15 |
| `tests/test_collusion_measurement.py` | 17 |
| `tests/test_collusion_harness.py` (new) | 9 |
| `tests/test_collusion_replay.py` (new) | 9 |

**`tests/test_shared_runner_smoke.py`: 10 passed**, run alongside the family
suite to confirm no regression to the shared kernel (this family has no
coupling into that file; it is a generic runner smoke test). Combined:
**77 passed, 0 failed, 0 skipped** in ~101s.

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
