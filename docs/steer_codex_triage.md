# Triage: Codex adversarial review of the `steer` adapter

Source report: `docs/steer_review_codex.md` (a recovered summary, not a
per-finding list — the reviewer's sandbox could not write the full report, so
its 8 findings survive only as one "top issue" plus a one-sentence list of
the other 7). Each of the 8 is treated as its own finding below, investigated
independently from the description and classified only on what the code
itself does — never on the reviewer's authority.

Working tree: `zeyu/steer-adapter`. No uncommitted changes were present
before this triage (`git status`/`git diff --stat` both clean apart from the
untracked recovered report). Nothing was fixed in this pass — triage only.

Result: **8 CONFIRMED, 0 REFUTED, 0 OUT_OF_SCOPE.** Every finding is
reproducible from code that lives entirely under `src/aeread_families/steer/`
or `tests/test_steer_*.py`; none of the 8 concerns `src/aeread/shared_runner/`
code itself (finding 1 is a contract *mismatch* with a shared-kernel caller,
but the fix is on the family side — see its section — so nothing was
appended to the runner defect ledger).

---

## Finding 1 (top issue) — production finalization calls the scorer as a callable; `SteerScorer` only provides `.score()`

**Classification: CONFIRMED.**

`SteerPlugin.build_scorer` (`src/aeread_families/steer/environment.py:359-377`)
returns a `SteerScorer` (`src/aeread_families/steer/measurement.py:192-231`),
a frozen dataclass exposing only a named method `.score(outcome, *,
evidence_refs=())` (`measurement.py:212-231`) — it defines no `__call__`.

The one real, production finalization path in this codebase,
`finalize_family_execution` (`src/aeread/shared_runner/family_evaluation.py`),
calls whatever `build_scorer(family_case)` returns **as a callable**, three
times: `family_evaluation.py:245-248`, `:487-490`, and `:565-567`, e.g.

```python
score = plugin.build_scorer(family_case)(
    recorded_outcome,
    evidence_refs=(outcome_event.event_id,),
)
```

This is not a hypothetical calling convention: the two plugins in this
codebase that this function is actually exercised against both implement it —
`HousingPlugin.build_scorer` returns a real closure
(`src/aeread/shared_runner/housing.py:787-791`: `def score(outcome, *,
evidence_refs=()): ...; return score`), and the shared-runner smoke fixture
returns `lambda outcome: outcome` (`src/aeread/shared_runner/smoke.py:126-127`).
`SteerScorer` is not compatible with either shape.

Reproduced directly (bridge-cache-only, no pandas):

```
scorer = measurement.build_scorer(row)
callable(scorer)              # False
scorer(outcome, evidence_refs=('ev1',))
# TypeError: 'SteerScorer' object is not callable
```

Every test that exercises `SteerScorer`/`plugin.build_scorer` (all of
`tests/test_steer_measurement.py`, `test_steer_goldens.py`,
`test_steer_replay.py`, `test_steer_e2e.py`, `test_steer_environment.py`)
calls `.score(...)` directly — never `scorer(...)` — so the suite never
exercises the shape `finalize_family_execution` actually needs, exactly as
the reviewer states.

Note: `src/aeread_families/tau3_retail/measurement.py`'s `Tau3RetailScorer`
has the identical shape (named methods, no `__call__`) — this is not a
steer-specific one-off, but fixing tau3_retail is out of this family's scope.
Because the fix for *this* family is local (give `SteerScorer` a `__call__`,
or have `build_scorer` return a callable wrapper, mirroring
`housing.py`/`smoke.py`'s existing convention in this same codebase), this is
not routed to the shared-kernel ledger.

---

## Finding 2 — false upstream pinning

**Classification: CONFIRMED.**

`UPSTREAM_REPO`/`UPSTREAM_COMMIT` are hardcoded constants
(`src/aeread_families/steer/cases.py:57-58`). `build_pins`
(`cases.py:86-98`) writes `UPSTREAM_COMMIT` verbatim into `pins.json`'s
`upstream_commit` field. At runtime, `SteerPlugin.validate_payload`
(`src/aeread_families/steer/environment.py:183-186`) checks
`pins.get("upstream_commit") != UPSTREAM_COMMIT` — comparing the value the
importer wrote *from* that constant back *against* that same constant. The
test suite does the same:
`tests/test_steer_cases.py:425`: `assert pins["upstream_commit"] ==
steer_cases.UPSTREAM_COMMIT`.

Nowhere in `cases.py`, `steer_bridge.py`, or `steer_bridge_driver.py` is the
*actual* upstream checkout's real git state ever read (`grep -n "rev-parse|git
log|subprocess.*git"` over all three files returns nothing but the
`--upstream-root` argparse help string). `steer_bridge_driver.py`'s
`--upstream-root` accepts any filesystem path with no verification that it is
even a git repository, let alone checked out at the pinned commit.

This is a real gap, not a documented convention shared across the codebase:
the sibling family `tau3_retail` — built earlier, described in the working
memory as the canonical-reference family — does exactly this check for real,
in `src/aeread_families/tau3_retail/environment.py:178-193`:

```python
revision = subprocess.run(
    ["git", "-C", str(self.upstream_root), "rev-parse", "HEAD"], ...
)
...
if revision.stdout.strip() != UPSTREAM_COMMIT:
    raise ValueError("upstream checkout revision mismatch: ...")
```

Steer's `SteerPlugin` doesn't even retain a handle to the raw upstream
checkout at runtime (only `steer_data_root`, the flattened cache directory —
`environment.py:154-155`), so today it structurally cannot perform the
equivalent check. Concretely: if `--upstream-root` were ever pointed at a
different commit of `narunraman/STEER` (a newer or locally modified
checkout), the corpus would be silently rebuilt from that different data
while `pins.json`/every case file would still claim
`d66673c8277b9112fc5e39751524ccda6d852446` — and nothing anywhere would
notice or fail.

---

## Finding 3 — unauthenticated replay labeled `match`

**Classification: CONFIRMED.**

`ReplayReport.status` (`src/aeread_families/steer/replay.py:340-344`):

```python
@property
def status(self) -> str:
    if self.comparison is not None and not self.comparison.matches:
        return "mismatch"
    return "match"
```

`replay_and_verify`'s own docstring (`replay.py:358-363`) states the intent
correctly: when `original` is not supplied, `comparison` is `None` — "an
explicit, typed 'not comparable' rather than a fabricated match." The
`.status` property contradicts that stated intent: when `comparison is None`
(i.e., *no comparison against a live run was ever performed*), it still
returns `"match"` rather than a distinct "not compared"/"unverified" value.
This is the "status reported without the comparison that would justify it"
shape named in this triage's own instructions.

The test suite encodes this as expected behavior rather than catching it:
`tests/test_steer_replay.py:388-409`
(`test_replay_and_verify_with_no_original_is_still_scored_but_not_compared`)
runs `replay_and_verify(..., original=None...)` and asserts
`report.status == "match"  # no comparison means nothing to disagree with`.

Concretely: a caller (this family's own sibling `tau3_retail.parity` treats
an analogous `report.status == "match"` as a genuine pass/fail parity gate —
`src/aeread_families/tau3_retail/parity.py:139`) that checks
`report.status == "match"` to decide "this replay was verified against a live
run" would get a false positive on a bare, uncompared re-score.

---

## Finding 4 — circular golden oracles

**Classification: CONFIRMED.**

Goldens 1/2 in `tests/test_steer_goldens.py` (`_run_golden`,
`test_steer_goldens.py:99-114` and its two callers at lines 122-138 and
146-166) construct the *submitted* answer from `row["correct_option_id"]`
(read from the flattened cache), then score it by calling
`plugin.build_scorer(family_case).score(result.outcome)`. `build_scorer`
(`environment.py:359-377`) recovers `correct_option_id` by re-reading the
*same* cached row (`_load_cached_row`, `environment.py:388-402`) from the
*same* file the test itself read. So golden 1/2 verify "does the pipeline
report `submitted == cached_value` when `submitted` was itself set to
`cached_value`?" — an internal-consistency/plumbing check, not a check that
`cached_value` is upstream's actual correct answer.

This isn't a theoretical concern: it's already been demonstrated in
practice. Per `docs/steer_review_disposition.md`'s finding M1 (fixed earlier
in this same review cycle), `steer_bridge_driver.py`'s `_op_flatten` had a
real classification bug (`.astype(bool)` on `pure_nash`'s `Answers.correct`
column read `NaN` as `True`) that mislabeled tens of thousands of rows.
Goldens 1-4 as written could not have caught that class of bug: they only
ever check the scorer's *self*-agreement with whatever `correct_option_id`
the (possibly-buggy) driver already wrote into the cache, never an
independent, hand-verified ground truth.

---

## Finding 5 — silent module skips

**Classification: CONFIRMED** (reproduced empirically).

Every one of the 6 steer test modules
(`test_steer_measurement.py:29-44`, `test_steer_goldens.py:31-44`,
`test_steer_cases.py:34-62`, `test_steer_environment.py:26-37`,
`test_steer_replay.py:48-59`, `test_steer_e2e.py:40-51`) module-level-skips
its entire contents (`pytest.skip(..., allow_module_level=True)`) if the
externally-cached, out-of-repo corpus at
`bridges/steer-data/transitivity/cases.jsonl` (default path, or
`AEREAD_STEER_DATA_ROOT`) is missing.

Reproduced: pointing `AEREAD_STEER_DATA_ROOT` at a nonexistent directory and
running the steer suite alone gives `6 skipped` at **exit code 5** (pytest's
"nothing ran" code — this alone would be caught by a naive CI check). But run
alongside any other passing test file in the same invocation, the picture
changes completely:

```
$ AEREAD_STEER_DATA_ROOT=/tmp/nonexistent_steer_cache_dir \
    pytest tests/test_steer_measurement.py tests/test_case_catalog.py -q
6 passed, 1 skipped
$ echo $?
0
```

i.e. in the normal case of running the steer suite as part of the wider
repo's test run (which is how it is actually exercised), a missing/misplaced
external cache directory causes **all** of steer's tests to silently
disappear from the run while the overall suite still reports green. Nothing
distinguishes "steer's tests ran and passed" from "steer's tests never ran at
all" except manually reading the skip count in the summary line. This is the
exact failure shape recorded in this project's own memory
(`feedback-skips-hide-unrun-claims.md`: "a green suite once hid that fidelity
tests never ran").

---

## Finding 6 — missing exclusion records

**Classification: CONFIRMED.**

`steer_bridge_driver.py`'s `_op_flatten` (`steer_bridge_driver.py:171-283`)
classifies every upstream `question_id` into exactly one of
`exactly_one_correct` / `zero_correct` / `multi_correct`
(`steer_bridge_driver.py:213-234`), but only ever returns **aggregate
per-element counts** (`"counts": {...}`, `steer_bridge_driver.py:277-282`)
plus exactly one arbitrary sample `question_id` for the `zero_correct`
reason only (`zero_correct_sample_question_id`, set once at
`steer_bridge_driver.py:220-222` and never analogously captured for
`multi_correct`). No per-question-id ledger of which specific rows were
excluded (or why) is ever produced anywhere in the pipeline.

Confirmed against the actual committed artifact,
`cases/steer/pins.json`: its top-level keys are exactly
`branch_by_element, counts_by_element, declared_elements,
file_sha256_by_element, head_n, upstream_commit, upstream_repo,
zero_correct_sample_by_element` — counts and one sample id per element, no
`excluded_question_ids` or equivalent. Concretely, per the current corpus:
`backward_induction` excludes 550 questions, `dsic_mechanism` excludes 1,765
(1,760 zero-correct + 5 multi-correct), `ir_mechanism` excludes 240,
`pure_nash` excludes roughly 12,550 (per `docs/steer_adapter_spec.md`'s
corrected Governing Facts table) — for every one of these, only a per-element
total is auditable; which exact upstream question survived vs. was dropped,
and under which of the two exclusion reasons, is not recorded for all but one
sample per element.

---

## Finding 7 — a vacuous Golden 5

**Classification: CONFIRMED.**

`test_golden_5_degenerate_reference_question_id_is_a_real_zero_correct_row`
(`tests/test_steer_goldens.py:266-271`) asserts only
`isinstance(sample, str) and sample` — it never independently checks that the
row actually has zero correct options (e.g. by loading the raw upstream
frame directly); it trusts the label the driver itself already assigned.

More importantly, the other two golden-5 tests
(`test_golden_5_degenerate_reference_was_excluded_at_gate_1_never_written_as_a_case`,
`test_golden_5_degenerate_reference_is_absent_from_the_cached_admitted_rows`,
`tests/test_steer_goldens.py:274-290`) check that this same `sample`
`question_id` is absent from the committed case files and from the cached
admitted rows. This cannot ever fail, by construction: in
`steer_bridge_driver.py`'s `_op_flatten` loop
(`steer_bridge_driver.py:217-234`), the branch that records
`zero_correct_sample_question_id` ends in `continue`
(`steer_bridge_driver.py:220-224`) — the exact same iteration that samples a
question_id as "zero-correct" unconditionally skips appending that same
question_id to `admitted`. Since both the sample and the admitted-rows list
come from one run of one function, "the sampled id is absent from admitted"
is a tautology enforced by Python control flow, not an independently
verifiable property of the *classification* being correct. If the
classifier's zero-correct/exactly-one-correct boundary were wrong in either
direction (as it in fact was for `pure_nash`, per finding 4's M1 reference),
Golden 5 would still pass unchanged — it cannot distinguish "the exclusion
logic is right" from "the exclusion logic is self-consistent."

---

## Finding 8 — unsealed score evidence

**Classification: CONFIRMED.**

`ScriptedSteerHarness.__call__` (`src/aeread_families/steer/harness.py:47-66`)
appends exactly one sealed evidence event, `"steer_answer_submitted"`,
recording only the raw served response text
(`harness.py:58-65`). No score is ever appended to the `EvidenceStore`
anywhere in this family's own harness/e2e code path.

Confirmed in `tests/test_steer_e2e.py:117-158`
(`test_scripted_harness_seals_evidence_for_a_valid_submission` and its
neighbors): the scorer is built and run (`plugin.build_scorer(family_case)`,
`scorer.score(result.outcome)`, lines 142-143) **after**
`evidence.seal()` is called (line 156), and `seal.event_count == 1` (line
157) — i.e. the seal that this family's own milestone-3 "sealed evidence"
requirement produces certifies only "this raw text was served," never "this
outcome was scored as X." The `ScoreEnvelope` is computed purely for the
test's own local assertions and never enters the durable evidence record.

This is the correct pattern *done right* elsewhere in the same codebase:
`finalize_family_execution`
(`src/aeread/shared_runner/family_evaluation.py:245-253`) appends a
`"score_recorded"` event carrying the `ScoreEnvelope` **before** calling
`evidence.seal()`. Steer's own harness has no equivalent step, so — even
independent of finding 1's callable-shape mismatch — nothing in
`src/aeread_families/steer/` today produces a sealed, score-inclusive
evidence bundle for a completed episode.

---

## Summary

| # | Finding | Classification |
|---|---|---|
| 1 | Production finalization calls scorer as callable; `SteerScorer` only has `.score()` | CONFIRMED |
| 2 | False upstream pinning (commit never verified against a real checkout) | CONFIRMED |
| 3 | Unauthenticated replay labeled `match` | CONFIRMED |
| 4 | Circular golden oracles (goldens 1-4) | CONFIRMED |
| 5 | Silent module skips (all 6 steer test modules) | CONFIRMED |
| 6 | Missing exclusion records (counts only, no per-question ledger) | CONFIRMED |
| 7 | Vacuous Golden 5 (tautological by construction) | CONFIRMED |
| 8 | Unsealed score evidence | CONFIRMED |

**Confirmed: 8. Refuted: 0. Out of scope (shared kernel): 0.**

No entry was appended to `runner_defect_ledger.md`: every confirmed finding's
fix is local to `src/aeread_families/steer/` (or its tests); finding 1's
defect is a contract mismatch exposed *by* a shared-kernel caller, but the
fix itself belongs to this family's own `SteerScorer`, matching the
already-working convention `housing.py`/`smoke.py` use in the same codebase.

**Worst:** the silent module-level test skip (finding 5) — reproduced with
exit code 0 and zero steer tests executed whenever the external bridge cache
is absent, meaning the family's "tests currently pass" claim can already be
vacuously true today on any machine or CI runner without that out-of-repo
directory, with nothing in the pytest exit code to reveal it in a
multi-module run.
