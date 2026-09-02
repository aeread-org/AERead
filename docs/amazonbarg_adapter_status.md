# amazonbarg bilateral-bargaining adapter — status

Branch `zeyu/amazonbarg-adapter`. Last verified 2026-09-02, after milestone 3
(scripted harness, end-to-end, replay).

## What the adapter claims

For the 45-session `home-kitchen` + `toys-games` pilot pair (44
mutual-interest sessions + `toys-games_22`, the pilot's one
conflicting-interest session), the adapter runs upstream's exact bilateral
buyer/seller bargaining protocol (`session.parseReply` +
`utils.Action.ActionParser`, delegated in-process, never reimplemented)
through the real kernel scheduler, and scores every episode by delegating to
upstream's own `eval.py:Metrics` — never a hand-written legality or
profit/ratio recomputation. Five leaves are published, `composition_kind
="leaf"` throughout, never blended into one number:

| Leaf | Verifier family | Owner | Claim |
|---|---|---|---|
| `amazonbarg_deal_authenticity` | `rule_constraint` | delegated (`wrongAction`) | matches a genuine prior offer and the buyer's declared need |
| `amazonbarg_zopa_membership` | `rule_constraint` | AERead-owned, over delegated `B`/`C`/`D` | deal price inside `[cost, budget]` |
| `amazonbarg_deal_lower_bound` | `objective_reference` | AERead-owned | deal price vs. `S_min = cost` |
| `amazonbarg_deal_upper_bound` | `objective_reference` | AERead-owned | deal price vs. `S_max = budget` |
| `amazonbarg_bargained_ratio` | `comparative` | AERead-owned scorer, delegated arithmetic | tested seat's ratio vs. the fixed scripted counterpart |

`amazonbarg_deal_authenticity` and `amazonbarg_zopa_membership` are
deliberately kept separate (spec section 2): golden 3 (Breville) is a real
case where upstream calls a below-cost deal legitimate and AERead's own
added check is the only thing that catches it. Milestone 3 (this update)
adds the scripted counterpart harness (`harness.py`), an end-to-end run of
at least two full episodes through the real shared-runner path with sealed
evidence, and an offline replayer (`replay.py`) that reproduces both state
and score with zero further model/network calls.

## Evidence

**Two full episodes run end to end through the real scheduler, sealed as
durable evidence, then replayed by a second, independent plugin instance
with zero provider calls, reproducing state and score byte-identically.**

- Golden 1 (`home-kitchen_2`, Shark vacuum, closes `[DEAL] $135`) and golden
  5 (`toys-games_22`, the pilot's one CI session, correctly quits with no
  ZOPA) are each driven through `ScriptedAmazonbargHarness` and the genuine
  `run_episode`/`AmazonbargPlugin`/`PluginRegistry` path — not a hand-wired
  shortcut. Every served decision is appended as a hash-chained
  `EvidenceStore` event and the store is sealed from the scheduler's own
  `episode_completed` lifecycle callback once the episode terminates.
  `tests/test_amazonbarg_harness.py` verifies the chain
  (`EvidenceStore.verify_chain()`/`verify_seal()`) and that every event
  payload round-trips exactly.
- Each recorded episode is extracted (`record_episode`), round-tripped
  through plain JSON text (`RecordedEpisode.to_json()`/`from_json()`), and
  replayed (`replay_episode`) by a **second**, independently constructed
  `AmazonbargPlugin` — never the one that produced the original run.
  `tests/test_amazonbarg_replay.py` asserts:
  - `compare_episode_results(...).matches is True` for both goldens, and,
    unlike `tau3_retail` (whose replay only ever matches *content*, because
    `step()` re-stamps a fresh wall-clock timestamp on every message —
    documented on that adapter's own `replay._strip_message_timestamps`),
    **the raw, byte-exact final state matches too**
    (`final_state_matches is True`,
    `canonical_json_bytes(replayed.final_state) ==
    canonical_json_bytes(original.final_state)`) — `AmazonbargPlugin.step()`
    stamps nothing, so this is a strictly stronger guarantee, verified
    directly rather than assumed.
  - Both measurement leaves families (deal-authenticity/zopa/bounds and the
    comparative ratio, both seats) recomputed from the replayed episode's
    own recorded history via `score_replayed_episode` are `==`
    (dataclass-equal, i.e. byte-identical) to the same leaves computed from
    the original run's history, for both goldens — including golden 5's
    degenerate `invalid_measurement` envelopes, which reproduce with the
    same typed reason codes, not merely the same top-level status.
  - `replay_and_verify` end-to-end returns `status="match"` and the exact
    expected `amazonbarg_bargained_ratio` primary (`~=0.49` for the buyer
    seat on golden 1).
  - A tampered recorded decision (the DEAL's price text changed, its action
    *type* left alone so the episode still terminates after the same
    number of decisions) diverges — `matches is False`,
    `final_state_matches is False`, the two runs' final actions differ —
    **without raising**. This is an honest, documented difference from
    `tau3_retail` (whose `Tau3RetailPlugin.step()` independently
    re-executes and cross-checks every tool call against a live bridge and
    raises `SchedulerContractError` on a tamper): amazonbarg has no tool
    calls to cross-check, so a tampered reply is simply re-parsed into a
    genuinely different trajectory, never caught internally by `step()`
    itself. The replay guarantee here rests entirely on
    `compare_episode_results`/`assert_replay_matches` being run and checked
    by the caller.

**Suite: 106/106 passed** for the full amazonbarg family test-file set
(`test_amazonbarg_cases.py` 32, `test_amazonbarg_environment.py` 18,
`test_amazonbarg_measurement.py` 18, `test_amazonbarg_shim.py` 12,
`test_amazonbarg_harness.py` 5, `test_amazonbarg_replay.py` 11) plus
`test_shared_runner_smoke.py` (10) — zero failed, zero skipped (the pinned
upstream checkout is present at
`/Users/sunzeyu/Documents/econ benchmark/upstream-amazonbarg`, so every test
that needs it actually ran, never silently skipped).

**No regression: full repo suite 822 passed, 31 skipped, 1 xfailed.** The 31
skips are pre-existing, unrelated external-bridge dependencies for other
adapter families (confirmed none is amazonbarg-related by grepping the
skip report for `amazonbarg` — zero hits).

**Provider-free, network-free throughout.** Every test in this milestone
runs entirely in-process, through `upstream_shim`'s delegation mechanism —
no subprocess bridge, no API key, no network call. `test_amazonbarg_shim.py`
already pins the stub miss-counter at `0` across the whole suite; this
milestone adds nothing that could raise it (the harness/replay modules
never call `upstream_shim` directly — only `measurement.py`'s
`compute_upstream_metrics`, already covered).

## What's still declared-but-not-executed

Only the 45-session pilot pair actually runs end to end tonight; the other
885 of the full 930-session corpus are digested at the file level (Gate 1)
and get no `CaseManifest`, scripted trajectory, harness run, or replay.
Milestone 3 itself only drives **2 of the 45 pilot sessions** (goldens 1 and
5) through the harness/replay path, per the milestone's own acceptance bar
("at least 2 full episodes") — the remaining 43 pilot sessions and their
five goldens' worth of measurement coverage are exercised by
`test_amazonbarg_measurement.py`'s existing scored-transcript tests, but not
yet by a harness-run + sealed-evidence + replay cycle each. Extending the
harness/replay pair to the full 45-session pilot (and, separately, deciding
whether to materialize and score any of the other 885 sessions) is future
work, not part of this milestone's scope.

## Known limits, stated rather than implied

- **The scripted counterpart is one fixed policy, not a distribution of
  opponents.** `amazonbarg_bargained_ratio`'s claim (and this milestone's
  own harness scripts) is relative to that one AERead-authored fixture,
  never a general capability score (spec section 6).
- **No stochastic estimation.** Every leaf's `evaluation_class` stays
  `"deterministic"` — scripted trajectories only; a real model policy in
  either seat is out of scope here.
- **Replay's guarantee is external, not internal.** Unlike
  `Tau3RetailPlugin.step()` (which owns its own tool-replay cross-check and
  raises on divergence), `AmazonbargPlugin.step()` has no tool calls to
  cross-check, so `replay.py`'s comparison functions must actually be
  called and their result actually checked — a caller that replays and
  never calls `assert_replay_matches`/inspects `StateComparison.matches`
  would not be told about a divergence. See the tamper test above for the
  concrete, verified shape of that gap.
- **`amazonbarg_zopa_membership` and the bound leaves are AERead
  additions** upstream never computes or validates — still true as of this
  milestone, restated from the milestone-2 status (never report them as
  "the paper's own headline metric").
- **`budget_ratio=0.8` and `max_turns=6` remain the only pins explored.**
  No sensitivity analysis over either value is part of this or any prior
  milestone.

## Kernel/runner defects or limitations found this milestone

None new. The three kernel-contract limitations already on file from
milestones 1-2 (`ledger_entries/amazonbarg.md`: the two-value
`ScoreEnvelope.status` enum having no distinct "degenerate" state; the lack
of a directionless `ObjectiveScopeSpec.direction` option; and the
`verifier_taxonomy.md` §5.1 vs. real `_REFERENCE_KINDS` drift) remain the
current, complete list — this milestone's harness/replay work exercises all
three code paths again (goldens 1 and 5) without surfacing anything new.
The `sys.modules` shim technique (spec section 3.1, also logged there as a
deliberate departure from the task's two named fallback patterns) is
unchanged by this milestone: `harness.py`/`replay.py` never call
`upstream_shim` directly, only `measurement.py`'s already-shimmed
`compute_upstream_metrics`.
