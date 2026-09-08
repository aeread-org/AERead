# aucarena adapter — codex review triage

Source: `docs/aucarena_review_codex.md` (recovered second-reviewer transcript;
the reviewer's sandbox could not write a report, so this is a **summary**,
not a per-finding list — one top-line paragraph naming 8 issues in a single
sentence, declaring "FINDINGS: 9"). Per the run instruction, each described
issue below is treated as one finding and independently investigated from
its description, not from the reviewer's authority. Note up front: the
sentence names 8 distinct issues while the transcript declares 9 — this
gap itself is flagged as Finding 0.

Each finding was independently re-verified against the code (read at the
cited `file:line`, and where practical, reproduced by executing the actual
code path in this venv) before classification. This is a triage pass only:
nothing below has been fixed.

---

## Finding 0 — declared count (9) does not match the described issues (8)

**Classification: CONFIRMED** (as a reviewer-transcript defect, not an
adapter defect — logged here for completeness, not counted in the
confirmed/refuted totals below).

`docs/aucarena_review_codex.md`'s summary paragraph lists exactly 8 items
("a non-callable production scorer, malformed/illegal bids being
economically scored instead of re-bid, replay accepting convergent action
tampering as a match, divergent RNG tie-breaking, an invented mean-field
metric, incomplete comparator identity, self-referential parity tests, and
module-wide silent skips") but the transcript's `FINDINGS: 9` line and "2
critical, 5 high, 2 medium" (=9) do not add up to a ninth distinct,
describable issue. Nothing in the recovered text names a ninth issue, so
there is nothing further to investigate here; the 8 items below are the
full set this triage could reconstruct.

---

## Finding 1 — "AucArenaScorer is not callable" (non-callable production scorer)

**Classification: CONFIRMED.**

`AucArenaScorer` (`src/aeread_families/aucarena/measurement.py:686-733`) is
a frozen dataclass exposing four named methods
(`score_budget_invariant`/`score_bid_legality`/`score_hammer_rule`/
`score_profit_vs_field`) and defines no `__call__`.
`AucArenaPlugin.build_scorer` (`src/aeread_families/aucarena/environment.py:540-548`)
returns this object as-is, and its own docstring claims: "the current kernel
does not yet call `build_scorer` itself... this makes the declaration and
all four scorers live the day it does" — mirroring the identical claim in
`tau3_retail.measurement.Tau3RetailScorer`'s docstring.

That claim is false for the actual shared-runner kernel. The real,
exercised production path is `finalize_family_execution`
(`src/aeread/shared_runner/family_evaluation.py:245`):

```python
score = plugin.build_scorer(family_case)(
    recorded_outcome,
    evidence_refs=(outcome_event.event_id,),
)
```

— i.e. the kernel calls whatever `build_scorer` returns *as a function*.
This is not hypothetical: `HousingV1Plugin.build_scorer`
(`src/aeread/shared_runner/housing.py:787-793`) already returns exactly such
a callable (`def score(outcome, *, evidence_refs=()): ...; return score`),
and `tests/test_shared_runner_housing.py` exercises this exact call
convention today through `finalize_housing_execution`/`finalize_family_execution`.

Reproduced directly (registered `AucArenaPlugin` through the real
`PluginRegistry`, ran a golden episode, then called
`resolved.build_scorer(family_case)(result.outcome, evidence_refs=('ev1',))`
exactly as the kernel does):

```
scorer type: <class 'aeread_families.aucarena.measurement.AucArenaScorer'>
TypeError as expected: 'AucArenaScorer' object is not callable
```

**Failure scenario:** the moment `aucarena` is ever run through
`finalize_family_execution` (the only kernel path this repo has for scoring
a completed cell), scoring crashes with `TypeError`. No test in this family
calls `build_scorer(...)(...)`; every test calls the named methods directly
(`tests/test_aucarena_measurement.py`, `tests/test_aucarena_parity.py`,
`tests/test_aucarena_replay.py`), so the family's own green suite never
exercises the calling convention the kernel actually uses. This is a
family-side fix (give `AucArenaScorer` a `__call__`, or have `build_scorer`
return a callable wrapper the way `housing.py` does) — not a kernel change,
so it is in scope here, not ledgered. (`tau3_retail.Tau3RetailScorer` has
the identical shape and the identical false docstring claim; not separately
ledgered since the instruction is to ledger *kernel* findings, and this is
a family-adapter contract mismatch, not a kernel defect.)

---

## Finding 2 — malformed/illegal bids are scored as a real economic outcome instead of re-bid

**Classification: CONFIRMED.**

Upstream's actual game (`upstream-aucarena/auction_workflow.py:22-29,124-150`)
never lets a malformed or illegal response become a final, scored action: a
malformed response ("not parsible") loops forever inside `parse_bid_price`
re-asking the bidder (`while bid_price is None: ... msg = bidder.bid(...)`),
and an illegal, well-formed bid loops forever inside a `while True:
bid_sanity_check(...)` re-ask (`ask_for_rebid`/`rebid_for_failure`) until a
legal bid is produced. There is no retry cap; upstream structurally cannot
terminate a round with a bidder's malformed/illegal response counted as
that bidder's final action.

This adapter's `environment.py` does the opposite by design: `parse_action`
(`environment.py:299-341`) and `legal` (`environment.py:345-365`) classify a
response once, and `step` (`environment.py:388-396`) treats a
malformed-or-illegal action as final for the round: `if not envelope.valid:
continue  # illegal or malformed: zero mutation (spec goldens 3/4)`. No
retry, no re-ask — the seat is simply excluded from that round going
forward, exactly as if it had legally withdrawn.

The measurement layer then scores this adapter-invented terminal state as a
genuine economic result, not as something invalid or unscoreable:
`tests/test_aucarena_measurement.py:255-262`
(`test_golden_3_earns_no_credit`, illegal bid) and lines 270-296 (`golden 4`,
malformed) both assert `scorer.score_profit_vs_field(result=result).status
== "ok"` with a real, finite `primary` value. Golden 3's illegal 150-bid
trajectory — one upstream would have *never allowed to complete* (it would
have kept demanding a re-bid) — is reported as a legitimate, scoreable
`-`profit-vs-field` outcome.

**Failure scenario:** a policy under test that once emits a malformed or
below-price string is permanently and silently converted into "withdrew for
this item," and `aucarena_profit_vs_field` reports a real negative economic
score for a game state that could never actually terminate that way under
upstream's own rules. Nothing in `docs/aucarena_adapter_spec.md` discloses
this divergence (no mention of "re-bid", "retry", or "rebid" anywhere
outside one throwaway reference at spec line 254, which only clarifies the
*parse* classification, not that upstream would never let the round end
there at all). This is an environment/measurement design decision inside
this family (`environment.py`, `cases.py`, `measurement.py`), not the shared
kernel.

---

## Finding 3 — replay's `comparison.matches` accepts a validity-changing tamper as a match

**Classification: CONFIRMED** — this is the review's own "Executed probes
confirmed" bullet, and it reproduces exactly as described.

`StateComparison.matches` (`src/aeread_families/aucarena/replay.py:222-249`)
and `compare_episode_results`
(`src/aeread_families/aucarena/replay.py:252-291`) compare only
`phase_instance_count_matches` (a length check, not a content check),
`terminal_matches`, `outcome_matches`, and `final_state_matches` — all
derived from `EpisodeResult.terminal`/`.outcome`/`.final_state` (the game's
numeric state: profit, budget, items). None of these fields, nor any other
field `StateComparison` inspects, touch `phase_instances[i].actions[j]`'s
`envelope.valid`/`parse` classification — the very data
`aucarena_bid_legality`'s `malformed_action_count` metric is computed from.

Reproduced directly: ran golden 5 (`degenerate_reference_01`, single seat,
single item) live with its real policy (legal withdrawal, `"-1"`), recorded
it, then replayed it with the one recorded decision's response text changed
from `"-1"` (legal withdraw) to `"uh, I'll think about it"` (malformed —
the same string golden 4's own scripted policy uses). Because a withdrawal
and a malformed response produce the identical downstream game state for
this single-seat, single-item scenario (no bid recorded either way, hammer
falls, item unsold, profit/budget untouched):

```
phase_instance_count_matches: True
terminal_matches: True
outcome_matches: True
final_state_matches: True
OVERALL comparison.matches: True

original bid_legality metrics:  {}
replayed bid_legality metrics:  {'malformed_action_count': MetricValue(value=1.0, unit='count', metadata={})}
```

`assert_replay_matches` would not raise on this tampered replay, yet the
replayed episode's `aucarena_bid_legality` leaf reports a `metrics` value
the original episode's leaf does not have. The module's own docstring
(`replay.py:44-58`) claims a tampered response "replays into a genuinely
different (but still self-consistent) episode, which
`compare_episode_results`/`assert_replay_matches` catch as an explicit,
typed mismatch" — that claim is false for exactly this class of tamper
(one that changes an action's *validity classification* without changing
the *aggregate terminal numbers*). The only existing tampering test
(`tests/test_aucarena_replay.py:351-388`,
`test_tampering_a_mid_trajectory_bid_is_caught_immediately_not_silently_replayed`)
tampers a bid *amount* on a multi-seat, multi-round golden, where the
scheduler's own request-ordering check catches it before
`StateComparison` is ever consulted — so this gap in `StateComparison`
itself has never been exercised by any test in the suite (single-seat/
single-round goldens 2 and 5, where no request-order side effect exists to
paper over it).

---

## Finding 4 — per-call RNG reseeding can silently overturn an already-resolved tie

**Classification: CONFIRMED**, with an important caveat: upstream itself
has no reproducible tie-break to match (`upstream-aucarena/src/auctioneer_base.py:76`
uses the bare, unseeded, module-level `random.choice` — there is no
"correct" upstream answer to converge to), and this is openly disclosed:
`tests/test_aucarena_vendored_upstream.py:122-123` states in-line "Same seed
-> same tie-break outcome every time (reproducibility, not upstream's own
literal RNG stream, since upstream never seeded this)." So this is not a
hidden divergence from upstream — but it is a real, reproducible defect
relative to the vendored function's *own* documented invariant.

`environment.py:404` reseeds a brand-new `random.Random` on every bidder
processed in a round (`f"{world_seed}_{cur_item['id']}_{bid_round}_{call_index}"`),
and passes it into `vendored.record_bid`
(`src/aeread_families/aucarena/_vendored_upstream.py:171-196`), whose
docstring says it "Faithfully reproduces upstream's full per-call rescan of
`round_bids` (including its harmless re-draw of the tie-break RNG for
entries that already equal the running highest bid)". That "harmless"
characterization depends on the rescan sharing *one continuous* RNG across
the whole round (upstream's actual behavior) — under this adapter's
fresh-per-call reseed, a tie between two bidders resolved on an earlier
call is silently *re-flipped* by an unrelated seed the moment a third
bidder is appended in the same round, because the rescan starts over from
index 0 with a brand-new `Random` instance each time.

Reproduced: this is not merely theoretical — the roster-order tie-break
*does* fire live in golden 1 (instrumented `random.Random.choice`; golden
"successful" makes 6 calls, in pairs of `['agent','agent']` (harmless
self-tie) then `['agent','field_high']` (the real tie), each pair
one item). But no golden ever has 3 simultaneously-tied live bidders in one
round (`field_low` always withdraws immediately in every golden, per the
spec), so the only scenario where the fresh-per-call reseed diverges from
even the vendored function's own stated "harmless redraw" invariant — a
3-way tie — is never exercised. A synthetic 3-way-tie simulation (`A`,
`B`, `C` all bid 1000) confirms the per-call-reseed scheme and a
single-continuous-stream scheme give different winner distributions for
the same nominal seed sequence.

**Failure scenario:** any future golden with 3+ simultaneously-eligible,
identically-bidding seats in one round would have its final tie-break
winner determined by an interaction between the reseed scheme and
`round_bids` rescan order that no test in this suite (unit or golden)
currently covers — `test_record_bid_breaks_a_tie_via_the_injected_rng`
(`tests/test_aucarena_vendored_upstream.py:112-124`) only ever exercises a
2-entry `round_bids` list.

---

## Finding 5 — the "mean-field" primary score is an invented aggregation that can misrepresent a real result

**Classification: CONFIRMED.**

`score_profit_vs_field` (`src/aeread_families/aucarena/measurement.py:626-680`)
reports `primary = tested_profit - mean_field_profit`, an unweighted
arithmetic mean of every field seat's terminal profit. Nowhere in
`docs/aucarena_adapter_spec.md` or `docs/research/verifier_taxonomy.md` is "mean" (or
any other aggregation rule) specified as the estimand's definition — the
spec only says "against the named, declared field" (`aucarena_adapter_spec.md`
line ~101), and `verifier_taxonomy.md`'s `head_to_head` definition ("field,
or matchup distribution", line 172) permits a field-level comparison but
does not mandate a mean. `_field_roster_sha256`'s scope covers only *which*
seats are the field, not how their profits should be combined. The
per-seat deltas *are* preserved transparently in `metrics` (nothing is
hidden), but the single `primary` value — the number a leaderboard or
threshold check would actually read — is this unstated, code-only choice.

Reproduced on golden 1 (`successful`, the only competitive golden): field
seats are `field_low` (always withdraws, profit `0`) and `field_high`
(profit `2000`); agent's profit is `800`.

```
reference_values: field_low_profit=0.0, field_high_profit=2000.0
metrics:          delta_vs_field_low=+800.0, delta_vs_field_high=-1200.0
primary (mean-field delta): -200.0
```

**Failure scenario:** the agent lost decisively to the only seat that ever
actually competed (`-1200` against `field_high`), but the single `primary`
number a downstream consumer reads reports only `-200` — an artifact of
averaging in `field_low`'s built-in-inert `0` profit, which structurally
dilutes any real underperformance by roughly half whenever the field mixes
an always-withdraw seat with a competitive one (exactly this corpus's own
composition). This is "a status... reported without the comparison that
would justify it": `primary` is presented as *the* comparative result, but
does not correspond to any single well-defined comparison a reader could
reconstruct from its number alone.

---

## Finding 6 — the estimand's own comparator identity is narrower than the spec claims

**Classification: CONFIRMED.**

`docs/aucarena_adapter_spec.md` (section 2, ~line 101-103) states:
"`aucarena_profit_vs_field`'s comparator (the frozen bidder field: seat ids,
`model_name`, budgets) **and the pairing (same `case_id`, same item order,
same `world_seed`) are part of the estimand** per `verifier_taxonomy.md`
§6" — grouping both the field composition *and* the case/seed pairing as
part of the same identity claim.

The only machine-checkable identity for this leaf is
`ReferenceSpec.source_sha256`, computed by `_field_roster_sha256`
(`src/aeread_families/aucarena/measurement.py:271-285`), which hashes
**only** `{seat_id, model_name, budget}` per field seat. Neither `case_id`,
item order, nor `world_seed` is part of this hash, `reference_id`
(`PROFIT_VS_FIELD_REFERENCE_ID = "aucarena_frozen_field_v1"`, a fixed
constant), or anywhere else in `ReferenceSpec`/`MeasurementLeafSpec`. The
function's own docstring is honest about this narrower scope ("two cases
with the same item order/seed but a different declared field are different
claims" — only defends the field-composition half), but the *adapter
spec's* broader claim that the pairing is "part of the estimand" is not
reflected in the leaf's own declared identity.

**Failure scenario:** two different cases with an identical field roster
(same seat ids/model_names/budgets) but a different item order or
`world_seed` — hence a genuinely different matchup and possibly a very
different `profit_vs_field` result — produce `ScoreEnvelope`s whose
`reference.source_sha256` is byte-identical. Any future consumer that uses
`source_sha256` as the signal for "these two scores are the same claim,
safe to pool" (which is the entire purpose of a reference identity hash in
this taxonomy) would pool across genuinely distinct scenarios, contradicting
the spec's own stated intent. Case/world_seed identity is tracked at the
outer kernel bookkeeping layer (`cell_id`/`case_id` on the receipt), so this
is not a total loss of traceability — but it means the leaf's own declared
`ReferenceSpec` identity, read in isolation, is incomplete relative to what
the family's own spec says it should be.

---

## Finding 7 — the "parity" tests are self-referential: they can never catch a bug inside the shared vendored function

**Classification: CONFIRMED** — again, an accurately-described, but
explicitly and honestly disclosed, property rather than a hidden defect;
included because the task description names exactly this shape ("a golden
whose oracle is the code under test") as a plausible finding class.

`tests/test_aucarena_parity.py`'s own module docstring (lines 1-27) states
outright: "the vendored functions in `_vendored_upstream.py` *are*
upstream's logic, hand-transcribed... The genuine parity check for this
family is therefore between two independent *code paths* over the same
sealed episode: the environment's own `step()` ... and `measurement.py`'s
`score_bid_legality`/`score_hammer_rule` ... which call **the same vendored
functions again**." Both `environment.py`'s live decision and
`measurement.py`'s "independent" recompute call the identical
`vendored.bid_sanity_check`/`vendored.check_hammer`/`vendored.record_bid`
functions. This genuinely catches a real, useful bug class (environment.py
failing to *call* the right check, or deriving it from stale/wrong live
state — this is what the earlier Claude review's WARNING 1 caught and the
disposition doc records as fixed), but it structurally cannot catch a bug
*inside* the shared vendored function itself, since both sides would agree
identically on a wrong answer.

The only layer that checks the vendored functions' correctness against
upstream's actual algorithm is `tests/test_aucarena_vendored_upstream.py`'s
hand-derived numeric assertions (e.g. `bid_rule(cur_bid=1000, ...) ->
1100`), which are a real, automated, gating pytest suite — but the spec's
own "Test plan" (section 6) additionally describes an "optional,
non-gating" hardening step ("re-derive the same trace by hand from the
upstream source text quoted in each provenance header") that is explicitly
*not* enforced anywhere as a standing check; it is a manual reviewer
exercise, never re-run automatically. So the family's actual defense
against a transcription error in the vendored functions rests entirely on
`test_aucarena_vendored_upstream.py`'s hand-authored expected values,
authored once, never independently re-derived by a second, automated
process.

---

## Finding 8 — an entire QC-Gate-1 test module silently vanishes when the pinned upstream checkout is absent

**Classification: CONFIRMED** — the most severe of the eight, and a direct
recurrence of this project's own previously-documented anti-pattern
("skips hide unrun claims").

`tests/test_aucarena_cases.py:26-39`:

```python
def _upstream_root() -> Path:
    candidate = os.environ.get(
        "AEREAD_AUCARENA_UPSTREAM_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/upstream-aucarena",
    )
    root = Path(candidate)
    marker = root / "data" / "pseudo_items.jsonl"
    if not marker.is_file():
        pytest.skip(
            f"pinned upstream auction-arena checkout not found at {root}",
            allow_module_level=True,
        )
    return root

UPSTREAM_ROOT = _upstream_root()
```

This runs at **module import time**, with `allow_module_level=True`. The
default path is a hardcoded absolute path under this one developer's home
directory (`/Users/sunzeyu/...`) — it will not exist on a fresh CI runner,
a container, or any other contributor's machine unless the env var is set
and provisioned. The file defines 19 `test_` functions covering exactly
"QC Gate 1" per its own docstring (pinned item-pool sha256/count, id
resolution 1-26, importer byte-determinism, `content_sha256` vs the
kernel's own resolver, and the colon-rejection case-id-grammar test).

Reproduced directly: pointing `AEREAD_AUCARENA_UPSTREAM_ROOT` at a
nonexistent directory and running the file:

```
$ AEREAD_AUCARENA_UPSTREAM_ROOT=/tmp/does_not_exist_$$ pytest tests/test_aucarena_cases.py -q
1 skipped in 0.06s
```

Not "19 skipped" — **1 skipped**, because `allow_module_level=True` skips
collection of the whole module as a single unit. On this machine the
upstream checkout happens to exist, so the family's "tests currently pass"
claim is true here — but it is true *only* here, contingent on this
specific absolute path, and would silently regress to "1 skipped" (not a
failure, not a warning) anywhere else, hiding all 19 QC-Gate-1 claims
(including the case-id colon-grammar regression test the family's own
docs elsewhere point to as load-bearing) with zero visible signal in a CI
log beyond a single easily-missed skip line. No `conftest.py`/CI config in
this worktree provisions or documents the upstream checkout for this
family; there is no `skip_reason` surfaced anywhere the test summary would
foreground it, and unlike `tests/test_tau3_retail_replay.py` (which the
project treats as an acceptable, documented gate on a pinned interpreter),
nothing in `docs/aucarena_adapter_status.md` calls out that this file's
coverage is conditional on a local, undocumented, developer-specific path.

---

## Summary

| # | Issue | Classification |
|---|---|---|
| 0 | declared count (9) vs described issues (8) mismatch | CONFIRMED (transcript defect, not counted) |
| 1 | `AucArenaScorer` not callable — kernel's real call convention would crash | CONFIRMED |
| 2 | malformed/illegal bids scored economically instead of re-bid (upstream never lets this terminate) | CONFIRMED |
| 3 | replay `comparison.matches` accepts a validity-changing (legal-withdraw -> malformed) tamper | CONFIRMED |
| 4 | per-call RNG reseed can silently overturn an already-resolved tie (3+-way, untested) | CONFIRMED |
| 5 | "mean-field" primary score is an unspecified, distortive aggregation | CONFIRMED |
| 6 | `ReferenceSpec.source_sha256` omits case_id/item-order/world_seed the spec claims are part of the estimand | CONFIRMED |
| 7 | parity tests share the same vendored function on both sides ("self-referential") | CONFIRMED (disclosed) |
| 8 | `test_aucarena_cases.py` module-wide silent skip on a hardcoded, developer-specific path | CONFIRMED |

**Totals (excluding Finding 0, a meta-observation about the transcript
itself): 8 confirmed, 0 refuted, 0 out-of-scope.**

None of these eight findings concern `src/aeread/shared_runner/` kernel
code needing a kernel-side fix — Finding 1's crash is caused by the
*family's* `AucArenaScorer` not conforming to a real, already-implemented
kernel contract (`housing.py` conforms to the identical contract today), so
its fix belongs in `measurement.py`/`environment.py`, not the kernel. No
ledger entry was added.

**Worst confirmed finding:** Finding 8 (the module-wide silent skip) is the
most severe in terms of blast radius — it can invalidate 19 tests' worth of
QC-Gate-1 coverage with zero CI signal on any machine other than this one —
but Finding 1 (non-callable production scorer) is the most severe in terms
of what it says about the family's actual production-readiness: the very
call this family's own `AucArenaPlugin.build_scorer` docstring predicts
will happen "the day [the kernel] does [call it]" already happens, today,
in `finalize_family_execution`, and would crash immediately.
