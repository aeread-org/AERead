# steer adapter — independent review (Claude, second reviewer)

Scope: diff vs `origin/main` on branch `zeyu/steer-adapter`
(`docs/steer_adapter_spec.md`, `src/aeread_families/steer/*.py`,
`tests/test_steer_*.py`, `tools/steer_bridge/*`, `cases/steer/*`).
Reviewed read-only; full `test_steer_*` suite run locally (138 passed, 0
skipped — the pinned upstream checkout, bridge venv, and flattened cache are
all present on this machine).

Focus per assignment: QC Gate-2 golden realness/state-protection proof,
verifier-declaration correctness vs. `docs/verifier_taxonomy.md`, replay
honesty, and Gate-1 corpus admission (digests/dedup/no silent resampling).

---

## CRITICAL

### C1. `source_sha256` "runtime integrity check" never recomputes the hash — it only compares two stored copies of the same label, so a tampered/corrupted cache goes undetected exactly where the design says it must not

**Where:** `src/aeread_families/steer/environment.py:166-178` (`initial_state`)
and `:333-351` (`build_scorer`); the same pattern is used in both places:

```python
row = self._load_cached_row(family_case["element"], family_case["question_id"])
if row["source_sha256"] != family_case["source_sha256"]:
    raise ValueError(...)
```

**Claim being made:** `docs/steer_adapter_spec.md` lines 22-24: "real text is
cached at `bridges/steer-data/` ... and read from there at runtime, **verified
by `source_sha256` each time**." Line 92-93: "`source_sha256` ... is both the
Gate-1 content digest **and the runtime integrity check against the local
cache**." `environment.py`'s own docstrings repeat this ("re-verifies
`source_sha256` against the payload's declared value every time it does",
lines 124-125 and 338-340).

**Why it's false:** `row["source_sha256"]` is not recomputed from
`row["question_text"]`/`row["options"]`/`row["correct_option_id"]` at read
time — it is simply another field sitting in the same cached JSONL line,
written once by `steer_bridge_driver.py:237-245` at Gate-1 import time and
never touched again. `family_case["source_sha256"]` is the same string,
copied into the committed case payload by the same importer run
(`cases.py:140`). The "check" therefore only proves that the cache file and
the case file agree about *what they think* the digest is; it never proves
the digest actually matches the content sitting right next to it in the same
row.

**Reproduction (ran locally):** copied `bridges/steer-data/transitivity/cases.jsonl`
to a scratch directory, replaced only `question_text` in the first row with
different text while leaving `source_sha256` untouched, and called
`SteerPlugin.initial_state` against the real, unmodified, committed case file:

```
original question_text: You like mojitos more than margaritas, ...
initial_state succeeded despite tampering!
served question_text: TAMPERED QUESTION TEXT THAT DIFFERS FROM SOURCE_SHA256
```

No exception raised. The exact same code path (`build_scorer`) that recovers
`correct_option_id` for scoring has an identical, equally-inert guard, so a
tampered/corrupted `correct_option_id` in the cache would silently change
which answer is scored as gold, with the family's stated "verified" integrity
claim producing zero detection.

**Failure scenario:** the cache directory (`bridges/steer-data/`) is
explicitly, deliberately kept *outside version control* (the whole point of
the license-avoidance design). Any partial regeneration (e.g. a bridge bug,
an interrupted re-import that updates `cases/steer/*.json` but not the
sibling cache, a manual hot-fix to one cached row, or disk corruption) that
changes cached text/answer while leaving the `source_sha256` field
byte-identical will run and score silently against wrong content — precisely
the scenario `source_sha256` was introduced to catch, since there is no other
guard (no license means no git history/diff review of the actual content
either).

**Fix direction (not required by review, just for context):** recompute
`sha256(canonical_json({"question_text":..., "options":[...], "correct_option_id":...}))`
from the cached row's own fields at `initial_state`/`build_scorer` time and
compare *that* to `family_case["source_sha256"]`, mirroring exactly what
`steer_bridge_driver.py` does at import time.

---

## MAJOR

### M1. `_op_flatten`'s boolean coercion of the `Answers.correct` column silently turns missing (`NaN`) values into `True`, corrupting the typed zero/multi-correct exclusion bookkeeping for `pure_nash` (currently harmless to the admitted set only by luck, verified empirically)

**Where:** `src/aeread_families/steer/steer_bridge_driver.py:180-183`:

```python
correct_column = _correct_column(answers)
truthy = answers[correct_column].astype(bool)
correct_rows = answers[truthy]
```

**The bug:** for `pure_nash`, the `correct` column (an `object`-dtype Series
mixing genuine Python `bool` values with float `NaN` placeholders) is coerced
with `.astype(bool)`. Pandas propagates Python's own `bool(float('nan')) is
True` element-wise on object columns, so every `NaN` row is silently counted
as "this option is correct." Verified directly against the pinned, cached
`pure_nash/answers.pkl` under the project's own pinned bridge venv
(pandas 3.0.5):

```
nan count: 60000
bool True count (real):  6047
bool False count (real): 11051
astype(bool) True total: 66047   # 6047 real + 60000 NaN misread as True
```

Grouped by `question_id`, this inflates `multi_correct` from what a
"NaN excluded / not counted" reading would classify as **12,550 zero-correct,
0 multi-correct** questions into the committed **550 zero-correct, 12,000
multi-correct** — i.e. the recorded "Governing Facts" narrative
(`docs/steer_adapter_spec.md`'s table, line 44: `pure_nash | ... | 6,047 |
550 | 12,000 |`, and line 51: "`pure_nash`'s multi-correct rate (64.5%) is
**largely real** (many questions legitimately admit more than one
equilibrium ...)") is not a verified fact about the corpus — it is, to a
large extent, an artifact of this coercion bug. The regression test
`tests/test_steer_cases.py::test_admission_counts_reproduce_the_governing_facts_table`
locks in these numbers as "expected," so it would actually **fail** if the
`NaN`-handling bug were fixed, i.e. the "regression guard for the
schema-drift finding" is currently guarding a bug, not a fact.

**Why this doesn't (yet) corrupt the admitted pilot corpus — checked, not
assumed:** I recomputed the classification treating `NaN` as *not* correct
(the semantically defensible reading) and compared it question-by-question
against the shipped code's output:

```
exactly-one sets equal: True
in buggy but not fixed: 0
in fixed but not buggy: 0
gold_option_id mismatches among common exactly-one qids: 0
```

For this specific pinned snapshot, no `NaN` row happens to coexist with a
question that also carries a real, single marked-`True` option, so the set
of admitted (`exactly_one_correct`) `pure_nash` questions and their gold
answers are bit-identical either way — the bug currently only relabels which
*exclusion reason* (`zero_correct` vs. `multi_correct`) 12,000 already-excluded
questions get, not which questions are admitted.

**Failure scenario this creates going forward:** the bug is in the shared
`_op_flatten` path, not something specific to a known-safe element. If a
future declared element (or a refreshed/rebuilt cache under a different
pandas version, or upstream revising the pinned data before the pin is
re-verified) has a `NaN`-bearing `correct`/`correct_answer` column where a
`NaN` row *does* coexist with the question's own genuine single `True` row,
this coercion would push that question from `exactly_one_correct` into
`multi_correct`, **silently excluding an otherwise-valid, single-answer
question from the corpus** — a real instance of the "no silent resampling /
no silent exclusion" property this review was asked to check, currently
un-guarded by any test (no test in `test_steer_cases.py` exercises `NaN`
handling in the `correct` column at all).

---

## MINOR

### N1. `ledger_entries/steer.md` is cited as the schema-drift provenance log by both `docs/steer_adapter_spec.md` (line 35, "the importer must probe for either name per element, never assume one (logged: `ledger_entries/steer.md`)") and `docs/steer_adapter_status.md` (line 167, "also logged in `ledger_entries/steer.md` from an earlier milestone") — the file/directory does not exist anywhere in this repository or its git history

```
$ git log --all --oneline -- "ledger_entries/steer.md"    # empty
$ find . -iname "ledger_entries*"                          # empty
```

A reviewer or future maintainer following this citation to audit the
schema-drift finding (`correct` vs `correct_answer`, `pure_nash` carrying
both) has nothing to read. `docs/steer_adapter_status.md`'s own "Open item"
section already flags a related but different missing file
(`docs/benchmark_qc.md`); this second dangling reference is not flagged
anywhere.

### N2. `cases/steer/README.md` is stale and contradicts the rest of this diff: it says scoring isn't implemented yet

`cases/steer/README.md:21`: "Scoring is not implemented yet -- see
`docs/steer_adapter_spec.md` section 2." This diff adds
`src/aeread_families/steer/measurement.py`, wires `SteerPlugin.build_scorer`,
and adds five QC Gate-2 goldens that score real episodes — scoring is
implemented. A reader who opens the committed corpus README (the file
closest to the actual case data) would be actively misled about the state of
the family. (Same file also describes the cache as "keyed by
`source_sha256`"; in fact `write_cache`/`_load_cached_row`
(`src/aeread_families/steer/cases.py:261-271`,
`src/aeread_families/steer/environment.py:363-378`) key it by one
`<element>/cases.jsonl` scanned linearly for a matching `question_id`, not by
`source_sha256`.)

---

## SUGGESTIONS

### S1. `_correct_column`'s fixed priority ("correct" before "correct_answer") is a hard-coded tie-break, not a semantically-verified choice, for the one element that carries both

`src/aeread_families/steer/steer_bridge_driver.py:156-168`. For `pure_nash`
(the only declared element with both columns), preferring `correct` over
`correct_answer` happens to reproduce the committed Governing Facts numbers
(verified: `correct_answer` alone gives `{6047 → 12000, 0 → 550... }`
different numbers entirely — `{exactly_one_correct: 12000, zero_correct: 0,
multi_correct: 6597}`, which does *not* match the table). Nothing in the code
or a test documents *why* `correct` (not `correct_answer`) is the
semantically intended column for `pure_nash` beyond "it reproduces last
session's snapshot" — a future ninth declared element with both columns
present would silently get the same hard-coded priority with no test able to
catch a wrong-but-internally-consistent count unless someone manually extends
`EXPECTED_COUNTS`/`EXPECTED_FILE_SHA256` for it first.

### S2. Golden 3's "no protected state changed" claim is verified only through the narrow `outcome()` projection, not the full `final_state`

`tests/test_steer_goldens.py:174-200` (`test_golden_3_invalid_unauthorized_earns_no_credit_and_changes_no_state`)
asserts `result.outcome["selected_option_id"] is None`, but `outcome()`
(`src/aeread_families/steer/environment.py:323-331`) only ever exposes
`termination_reason`/`selected_option_id`/`failure_code` — it structurally
cannot see whether `question_text`/`options` (the other two fields of
`state`) were mutated by the illegal-action path. Code inspection confirms
`step()` (`environment.py:286-308`) never touches them, so the claim is true,
but the golden itself doesn't independently demonstrate it against
`result.final_state`; the docstring's own scoping to "the episode's own
`selected_option_id`" (not a general "no state changed" claim) is honest, but
a reviewer skimming the test name ("...changes no state") could reasonably
expect a broader assertion than what's actually checked.

### S3. Hard-coded personal absolute path as the default upstream/cache root

`src/aeread_families/steer/cases.py:295-310`
(`default_upstream_root`/`default_cache_root`) fall back to
`/Users/sunzeyu/Documents/econ benchmark/upstream-steer` and
`/Users/sunzeyu/Documents/econ benchmark/bridges/steer-data` when the
corresponding env vars are unset. Fully overridable, so not a functional bug,
but anyone else running the importer without setting
`AEREAD_STEER_UPSTREAM_ROOT`/`AEREAD_STEER_DATA_ROOT` gets a confusing
`FileNotFoundError` against a path that only exists on this machine rather
than a clear "set this env var" message (contrast with
`discover_bridge_python`'s explicit, actionable
`SteerBridgeUnavailableError`).

---

## What checked out clean

- **All five QC Gate-2 goldens are real**, not fixtures invented for the
  occasion: goldens 1-4 each drive one scripted trajectory through the real
  `run_episode` scheduler and the real `environment.py`/`measurement.py`
  wiring (no hand-rolled shortcut); golden 5 is honestly labeled as a
  corpus-admission regression test rather than a live scoring run, and its
  fixture (`pins.json`'s `zero_correct_sample_by_element.dsic_mechanism ==
  "6_0"`) is real upstream data, confirmed non-null and confirmed absent from
  both the committed case files and the cached admitted rows.
- **Verifier declaration matches `docs/verifier_taxonomy.md` correctly**:
  `canonical_reference` / `canonical_point` / `deterministic` is an
  appropriate, non-judge-dependent label for an exact index-equality MCQA
  check (confirmed against `aeread/shared_runner/measurement.py`'s own
  `_REFERENCE_KINDS`/`_EVALUATION_CLASSES` contract enforcement); there is no
  judge/rater component anywhere in this family, so "is anything
  judge-dependent labeled deterministic" does not arise. `reference_values`
  (`gold_option_id`) is presented as a reference value, not dressed up as an
  independent confirmation signal.
- **Replay genuinely re-executes**, it does not just re-read stored state:
  `replay_episode` (`src/aeread_families/steer/replay.py:180-209`) drives the
  real `run_episode` scheduler with a `RecordedResponseSource` that replays
  only the *raw recorded responses*; state, terminal, outcome, and score are
  all independently recomputed by the scheduler/scorer, then compared
  byte-exactly (`canonical_json_bytes(original.final_state) ==
  canonical_json_bytes(replayed.final_state)`) against the original run. The
  one honestly-disclosed replay limitation (a genuinely offline replay with
  no `original` in memory cannot detect a tampered *recorded response*,
  since Mode A has no independent tool/upstream computation to cross-check
  against) is stated plainly in both `replay.py`'s docstrings and
  `docs/steer_adapter_status.md`'s "Known limits" section, not hidden.
- **Gate-1 digests**: 32/32 file-level sha256 checks against the pinned
  git-LFS `oid` reproduce locally; `content_sha256`/`corpus_manifest.json`
  hashing is stable under re-hash; no duplicate `question_id` exists in any
  of the 8 declared elements' real `questions.pkl` frames (checked directly),
  so the dedup-by-first-occurrence logic in `_op_flatten` is not currently
  exercised against a real collision; head-N selection is a deterministic,
  frame-order slice with no randomness anywhere in the admission path.
